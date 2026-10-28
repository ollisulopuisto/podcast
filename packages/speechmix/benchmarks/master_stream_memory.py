import json
import os
import sys
import tempfile
import threading
import time

import numpy as np
import psutil

from speechmix import programme

minutes = int(sys.argv[1])
rate = 48000
frames = minutes * 60 * rate
# Generated random-access stereo fixture: no full input/output allocation.
t = np.arange(rate, dtype=np.float64) / rate
wave = 0.06 * np.sin(2 * np.pi * 137 * t) + 0.01 * np.sin(2 * np.pi * 911 * t)
wave[::4000] = 0.99


def read(a, b):
    v = wave[np.arange(a, b) % rate]
    return np.stack([v, v * 0.6])


# Warm JIT before baseline; the input fixture remains bounded.
warm = []
programme.master_stream(read, warm.append, rate, 2, rate, -16, block_frames=65536)
del warm
p = psutil.Process()
base = p.memory_info().rss
peak = base
disk_peak = 0
stop = threading.Event()
samples = []
with tempfile.TemporaryDirectory() as scratch:

    def monitor():
        global peak, disk_peak
        while not stop.wait(0.05):
            rss = p.memory_info().rss
            peak = max(peak, rss)
            size = sum(
                f.stat().st_size
                for root, dirs, files in os.walk(scratch)
                for n in files
                if (f := __import__("pathlib").Path(root) / n).exists()
            )
            disk_peak = max(disk_peak, size)

    thread = threading.Thread(target=monitor)
    thread.start()
    count = 0
    energy = np.zeros(2)
    maximum = 0

    def write(block):
        global count, energy, maximum
        count += block.shape[1]
        energy += np.sum(block * block, axis=1)
        maximum = max(maximum, float(abs(block).max()))

    t = time.perf_counter()
    try:
        result = programme.master_stream(
            read, write, frames, 2, rate, -16, block_frames=262144, scratch_dir=scratch
        )
    finally:
        stop.set()
        thread.join()
    print(
        json.dumps(
            {
                "minutes": minutes,
                "rate": rate,
                "channels": 2,
                "frames": frames,
                "written_frames": count,
                "baseline_rss": base,
                "peak_rss": peak,
                "incremental_peak_rss": peak - base,
                "scratch_peak_bytes": disk_peak,
                "scratch_left": os.listdir(scratch),
                "elapsed": time.perf_counter() - t,
                "boost_db": result.boost_db,
                "lufs": result.lufs,
                "cost_lu": result.cost_lu,
                "reached": result.reached,
                "sample_peak": maximum,
                "channel_rms": np.sqrt(energy / frames).tolist(),
            }
        ),
        flush=True,
    )
