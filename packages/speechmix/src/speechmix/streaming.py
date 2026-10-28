"""Disk-backed programme mastering with bounded signal-processing windows.

The in-memory programme.master stays the parity reference. Scratch vectors are
ordinary files, not full-length resident arrays. Audio is always re-read from
its original source for each global loudness-search attempt.
"""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from . import chain, programme
from .meter import IntegratedMeter


def scratch_bytes(frames):
    """Conservative maximum private scratch bytes: five float64 gain vectors.

    Excludes caller source/output spools and filesystem allocation overhead.
    """
    if int(frames) < 0:
        raise ValueError("negative mastering frame count")
    return 40 * int(frames)


class _Vector:
    def __init__(self, path, frames):
        self.path = Path(path)
        self.frames = frames
        self.handle = self.path.open("w+b")

    def put(self, start, values):
        self.handle.seek(start * 8)
        self.handle.write(np.asarray(values, dtype=np.float64).tobytes())

    def get(self, start, stop):
        self.handle.flush()
        lo, hi = max(0, start), min(self.frames, stop)
        self.handle.seek(lo * 8)
        data = np.frombuffer(self.handle.read((hi - lo) * 8), dtype=np.float64)
        if data.size != hi - lo:
            raise ValueError("incomplete mastering scratch vector")
        return np.pad(data, (lo - start, stop - hi), mode="edge")

    def close(self):
        self.handle.close()
        self.path.unlink(missing_ok=True)


def master_stream(read, write, frames, channels, rate, target_lufs, *,
                  ceiling_db=programme.PROGRAM_PEAK_DB,
                  budget_lu=programme.PROGRAM_LIMIT_BUDGET_LU,
                  block_frames=524288, check=None, scratch_dir=None, progress=None):
    """Master re-readable channels-first audio, writing only the selected pass.

    ``read(start, stop)`` returns exactly that range. ``write(block)`` receives
    ordered float64 blocks once global target search finishes. ``check()`` may
    raise to cancel; all private scratch files are cleaned on every exit.
    ``progress(fraction)`` reports monotonic estimated work and ends at 1.0.
    Caller owns its output sink and atomic rollback. RAM is bounded by block
    size plus meter statistics; scratch disk grows with programme length.
    """
    frames, channels, rate = int(frames), int(channels), int(rate)
    block_frames = int(block_frames)
    if frames < 0 or channels < 1 or rate < 1 or block_frames < 1:
        raise ValueError("invalid streaming mastering dimensions")

    ticks = 0
    estimate = max(1, 20 * (programme.MASTER_ROUNDS + 3) * (
        (frames + block_frames - 1) // block_frames +
        (frames + chain._TRUE_PEAK_CHUNK - 1) // chain._TRUE_PEAK_CHUNK))

    def checkpoint():
        nonlocal ticks
        if check is not None:
            check()
        ticks += 1
        if progress is not None:
            progress(min(0.99, ticks / estimate))

    def blocks():
        return range(0, frames, block_frames)

    def source(start, stop):
        checkpoint()
        data = np.asarray(read(start, stop), dtype=np.float64)
        if data.shape != (channels, stop - start):
            raise ValueError("mastering reader returned an unexpected block shape")
        return data

    def measured(meter):
        if frames < rate:
            return None
        value = meter.value()
        return (value if value is not None and np.isfinite(value) and value >= -70
                else None)

    with TemporaryDirectory(prefix="speechmix-master-", dir=scratch_dir) as folder:
        if shutil.disk_usage(folder).free < scratch_bytes(frames):
            raise OSError("insufficient scratch space for streaming mastering")
        vectors = []

        def vector(name):
            item = _Vector(Path(folder) / name, frames)
            vectors.append(item)
            return item

        def peak_needed(destination, boost, stage=None):
            ceiling = 10.0 ** (ceiling_db / 20.0)
            limited = False
            # Match the reference CPU true-peak chunk origin and halo exactly.
            for start in range(0, frames, chain._TRUE_PEAK_CHUNK):
                checkpoint()
                stop = min(frames, start + chain._TRUE_PEAK_CHUNK)
                lo = max(0, start - chain._TRUE_PEAK_PAD)
                hi = min(frames, stop + chain._TRUE_PEAK_PAD)
                audio = source(lo, hi) * boost
                if stage is not None:
                    audio *= stage.get(lo, hi)
                dense = np.abs(signal.resample_poly(
                    audio, chain.LIMITER_OVERSAMPLE, 1, axis=-1)).max(axis=0)
                peak = dense.reshape(-1, chain.LIMITER_OVERSAMPLE).max(axis=1)
                needed = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
                piece = needed[start - lo:stop - lo]
                limited = limited or bool(np.any(piece < 1.0))
                destination.put(start, piece)
            return limited

        def filtered(src, dst, size, origin, function):
            # Read a complete halo, so each interior result has the same
            # neighborhood as the reference; nearest padding only at file ends.
            halo = size + 1
            for start in blocks():
                checkpoint()
                stop = min(frames, start + block_frames)
                data = src.get(start - halo, stop + halo)
                result = function(data, size=size, origin=origin, mode="nearest")
                dst.put(start, result[halo:halo + stop - start])

        def run(boost_db, emit=False):
            linear = float(10 ** (boost_db / 20))
            needed = vector("needed")
            future = vector("future")
            held = vector("held")
            stage = vector("stage")
            ahead = vector("ahead")
            try:
                stage_limited = peak_needed(needed, linear)
                if not stage_limited:
                    # Both reference gain stages are exactly unity when the
                    # oversampled source is already below the ceiling.
                    meter = IntegratedMeter(rate)
                    for start in blocks():
                        checkpoint()
                        stop = min(frames, start + block_frames)
                        output = source(start, stop) * linear
                        meter.add(output)
                        if emit:
                            checkpoint()
                            write(output)
                    return measured(meter), 0.0
                # The reference peak stage operates on dB requirements.
                for start in blocks():
                    stop = min(frames, start + block_frames)
                    needed.put(start, 20.0 * np.log10(needed.get(start, stop)))
                width = max(1, int(chain.PEAK_STAGE_MS * rate / 1000))
                filtered(needed, future, width, -(width // 2), minimum_filter1d)
                minimum = np.inf
                step = chain.PEAK_STAGE_RELEASE_DB_S / rate
                for start in blocks():
                    checkpoint()
                    stop = min(frames, start + block_frames)
                    ramp = np.arange(start, stop) * step
                    values = np.minimum.accumulate(future.get(start, stop) - ramp)
                    values = np.minimum(values, minimum)
                    minimum = values[-1]
                    held.put(start, ramp + values)
                filtered(held, stage, width, (width - 1) // 2, uniform_filter1d)
                for start in blocks():
                    checkpoint()
                    stop = min(frames, start + block_frames)
                    stage.put(start, 10.0 ** (np.minimum(stage.get(start, stop), 0) / 20))
                limiter_limited = peak_needed(needed, linear, stage)
                window = max(1, int(chain.LIMITER_LOOKAHEAD_MS * rate / 1000))
                filtered(needed, ahead, 2 * window + 1, 0, minimum_filter1d)
                coefficient = float(np.exp(-1 / max(
                    1.0, chain.LIMITER_RELEASE_MS * rate / 1000)))
                b, a = [1 - coefficient], [1.0, -coefficient]
                state = None
                played, plain = IntegratedMeter(rate), IntegratedMeter(rate)
                for start in blocks():
                    checkpoint()
                    stop = min(frames, start + block_frames)
                    required = ahead.get(start, stop)
                    if limiter_limited:
                        if state is None:
                            state = signal.lfilter_zi(b, a) * required[0]
                        smooth, state = signal.lfilter(b, a, required, zi=state)
                        gain = stage.get(start, stop) * np.minimum(smooth, required)
                    else:
                        gain = stage.get(start, stop)
                    lifted = source(start, stop) * linear
                    output = lifted * gain
                    played.add(output)
                    plain.add(lifted)
                    if emit:
                        checkpoint()
                        write(output)
                after, before = measured(played), measured(plain)
                cost = 0.0 if after is None or before is None else before - after
                return after, cost
            finally:
                for item in [needed, future, held, stage, ahead]:
                    item.close()
                    vectors.remove(item)

        try:
            meter = IntegratedMeter(rate)
            for start in blocks():
                meter.add(source(start, min(frames, start + block_frames)))
            after = measured(meter)
            boost, cost, capped = 0.0, 0.0, False
            if after is None:
                after, cost = run(0.0, emit=True)
                if progress is not None:
                    progress(1.0)
                return programme.MasterResult(0.0, after, cost, False)
            for _ in range(programme.MASTER_ROUNDS):
                if after is None or (abs(target_lufs - after) <=
                                     programme.MASTER_TOLERANCE_LU and boost):
                    break
                boost = max(-programme.MAX_PROGRAM_BOOST, min(
                    programme.MAX_PROGRAM_BOOST, boost + target_lufs - after))
                after, cost = run(boost)
                if budget_lu and cost > budget_lu:
                    boost -= cost - budget_lu
                    after, cost = run(boost)
                    capped = True
                    break
            after, cost = run(boost, emit=True)
            reached = (not capped and after is not None and
                       abs(target_lufs - after) <= programme.MASTER_TOLERANCE_LU)
            if progress is not None:
                progress(1.0)
            return programme.MasterResult(round(boost, 2), after, round(cost, 2), reached)
        finally:
            for item in vectors:
                item.close()
