"""
Module containing various audio processors.

This module defines an abstract `Processor` base class and several concrete
implementations for applying effects like gain, EQ, compression, limiting,
ducking, and external VST/AU plugins.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import mlx.core as mx
import numpy as np
from scipy import signal as sp_signal

from speechmix import chain

from . import shared


class Processor(ABC):
    """
    Abstract base class for all audio processors.
    """

    @abstractmethod
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        """
        Applies processing to an audio signal.

        Args:
            signal (mx.array): The input audio signal.
            sr (int): The sample rate.
            progress_callback (callable, optional): Callback for progress updates.

        Returns:
            mx.array: The processed audio signal.
        """


class GainProcessor(Processor):
    """
    Applies static gain to an audio signal.

    Attributes:
        gain (float): Linear gain multiplier.
    """

    def __init__(self, gain_db: float):
        """
        Initializes the GainProcessor.

        Args:
            gain_db (float): The gain to apply in decibels (dB).
        """
        self.gain = 10 ** (gain_db / 20)

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        return signal * self.gain


class HighPassProcessor(Processor):
    """
    Applies a high-pass Butterworth filter.

    Attributes:
        cut_freq (float): The cutoff frequency in Hz.
    """

    def __init__(self, cut_freq=100.0):
        """
        Initializes the HighPassProcessor.

        Args:
            cut_freq (float, optional): Cutoff frequency. Defaults to 100.0.
        """
        self.cut_freq = cut_freq

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        sig_np = np.array(signal)
        sos = sp_signal.butter(4, self.cut_freq, "hp", fs=sr, output="sos")
        axis = 0 if len(sig_np.shape) > 1 else -1
        filtered_np = sp_signal.sosfilt(sos, sig_np, axis=axis)
        return mx.array(filtered_np.astype(np.float32))


class DuckingProcessor(Processor):
    """
    Applies sidechain ducking based on a trigger signal.

    Attributes:
        trigger (mx.array): The signal used to control gain reduction.
        threshold (float): Linear threshold for ducking.
        ratio (float): Ducking ratio.
        window_sec (float): Analysis window size in seconds.
    """

    def __init__(
        self, trigger_signal: mx.array, threshold_db=-20, ratio=4.0, window_sec=0.1
    ):
        """
        Initializes the DuckingProcessor.

        Args:
            trigger_signal (mx.array): The sidechain signal.
            threshold_db (float, optional): Threshold in dB. Defaults to -20.
            ratio (float, optional): Compression ratio. Defaults to 4.0.
            window_sec (float, optional): RMS window. Defaults to 0.1.
        """
        self.trigger = trigger_signal
        self.threshold = 10 ** (threshold_db / 20)
        self.ratio = ratio
        self.window_sec = window_sec

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        trigger_sq = self.trigger**2
        window_size = max(1, int(self.window_sec * sr))

        # Fast moving average using cumsum
        pad_size = window_size // 2
        trig_padded = mx.pad(trigger_sq, [(pad_size, pad_size)])
        cs = mx.cumsum(trig_padded)
        trig_rms_sq = (cs[window_size:] - cs[:-window_size]) / window_size

        trig_rms = mx.sqrt(trig_rms_sq)
        n_orig = signal.shape[0]
        if trig_rms.shape[0] > n_orig:
            trig_rms = trig_rms[:n_orig]
        elif trig_rms.shape[0] < n_orig:
            trig_rms = mx.pad(trig_rms, [(0, n_orig - trig_rms.shape[0])])

        eps = 1e-6
        trig_db = 20 * mx.log10(trig_rms + eps)
        threshold_db_val = 20 * mx.log10(mx.array(self.threshold))
        reduction_db = mx.where(
            trig_db > threshold_db_val,
            -(trig_db - threshold_db_val) * (1 - 1 / self.ratio),
            0.0,
        )
        gain_env = 10 ** (reduction_db / 20)
        return (
            signal * gain_env[:, None] if len(signal.shape) > 1 else signal * gain_env
        )


class CompressorProcessor(Processor):
    """
    Standard dynamic range compressor, implemented via the DuckingProcessor.
    """

    def __init__(self, threshold_db=-20, ratio=4.0, window_sec=0.1):
        """
        Initializes the CompressorProcessor.

        Args:
            threshold_db (float, optional): Threshold in dB. Defaults to -20.
            ratio (float, optional): Compression ratio. Defaults to 4.0.
            window_sec (float, optional): RMS window size in seconds. Defaults to 0.1.
        """
        self.threshold = threshold_db
        self.ratio = ratio
        self.window_sec = window_sec

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        ducker = DuckingProcessor(
            trigger_signal=signal,
            threshold_db=self.threshold,
            ratio=self.ratio,
            window_sec=self.window_sec,
        )
        return ducker.process(signal, sr, progress_callback=progress_callback)


class SpectralCarverProcessor(Processor):
    """
    Applies dynamic spectral carving (dynamic EQ) to reduce masking.

    Attenuates frequencies in the target signal that overlap strongly with the trigger signal.
    """

    def __init__(self, trigger_signal: mx.array, strength: float = 0.5):
        """
        Initializes the SpectralCarverProcessor.

        Args:
            trigger_signal (mx.array): The reference signal driving the EQ reduction.
            strength (float, optional): Intensity of the carving effect (0.0 to 1.0). Defaults to 0.5.
        """
        self.trigger = trigger_signal
        self.strength = strength

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        n_fft = 2048
        hop_length = 512
        n_orig = signal.shape[0]
        n_ch = signal.shape[1] if len(signal.shape) > 1 else 1

        trigger = self.trigger
        if trigger.shape[0] < n_orig:
            trigger = mx.pad(trigger, [(0, n_orig - trigger.shape[0])])
        elif trigger.shape[0] > n_orig:
            trigger = trigger[:n_orig]

        # Larger blocks for better GPU utilization, e.g. 10 minutes
        block_samples = 10 * 60 * sr
        window = mx.array(np.hanning(n_fft).astype(np.float32))

        out_signal = mx.zeros(signal.shape)
        norm_signal = mx.zeros((n_orig,))

        num_blocks = (n_orig // block_samples) + 1
        for b in range(num_blocks):
            b_start = b * block_samples
            b_end = min(b_start + block_samples, n_orig)
            if b_start >= n_orig:
                break

            # For overlap-add, we need a bit of buffer at the end of the segment
            # to handle the last window's tail
            seg_end = min(b_end + n_fft, n_orig)
            s_seg = signal[b_start:seg_end]
            t_seg = trigger[b_start:seg_end]

            if s_seg.shape[0] < n_fft:
                break

            num_windows = (s_seg.shape[0] - n_fft) // hop_length + 1
            if num_windows <= 0:
                continue

            if progress_callback:
                progress_callback(b / num_blocks)

            # Extract windows (using broadcasting/indexing)
            win_indices = (
                mx.arange(n_fft)[None, :]
                + (mx.arange(num_windows) * hop_length)[:, None]
            )
            s_win = s_seg[win_indices]  # (num_windows, n_fft, [ch])
            t_win = t_seg[win_indices]  # (num_windows, n_fft)

            # Apply analysis window
            s_win = s_win * (window[None, :, None] if n_ch > 1 else window[None, :])
            t_win = t_win * window[None, :]

            # FFT
            s_fft = mx.fft.fft(s_win, axis=1)
            t_fft = mx.fft.fft(t_win, axis=1)

            # Carving mask
            t_mag = mx.abs(t_fft)
            t_max = mx.max(t_mag, axis=1, keepdims=True) + 1e-6
            mask = mx.clip(1.0 - (self.strength * (t_mag / t_max)), 0.1, 1.0)

            # Apply mask & IFFT
            carved_fft = s_fft * (mask[:, :, None] if n_ch > 1 else mask)
            carved_win = mx.fft.ifft(carved_fft, axis=1).real

            # Fast Overlap-Add in MLX using .at[...].add(...)
            flat_indices = (win_indices + b_start).reshape(-1)

            if n_ch > 1:
                # For multi-channel, we need to handle the channel axis
                # carved_win shape (num_windows, n_fft, n_ch)
                # out_signal shape (n_orig, n_ch)
                for ch in range(n_ch):
                    out_signal_ch = out_signal[:, ch]
                    out_signal_ch = out_signal_ch.at[flat_indices].add(
                        carved_win[:, :, ch].reshape(-1)
                    )
                    out_signal[:, ch] = out_signal_ch
            else:
                out_signal = out_signal.at[flat_indices].add(carved_win.reshape(-1))

            # Normalize with window contribution
            # window contribution is sum of window weights at each sample
            # Since we only applied window once (at analysis), we add 'window' to norm
            norm_updates = mx.broadcast_to(
                window[None, :], (num_windows, n_fft)
            ).reshape(-1)
            norm_signal = norm_signal.at[flat_indices].add(norm_updates)

        # Avoid division by zero
        norm_signal = mx.maximum(norm_signal, 1e-6)
        if n_ch > 1:
            return out_signal / norm_signal[:, None]
        return out_signal / norm_signal


class ExternalPluginProcessor(Processor):
    """Ulkoinen VST3 tai AU, jaetun ketjun kautta.

    Tämä oli oma toteutuksensa `chain.load_plugin`ista: `pedalboard`
    suoraan, säätimet `setattr`illa ja `print` virheeksi. Se ei kaatanut
    mitään, ja siinä oli kolme hiljaista vikaa joita kirjastossa ei ole.

    **Tila puuttui kokonaan.** Kaikki mikä vaikuttaa lopputulokseen ei ole
    parametri: dxRevivella mallin valinta elää liitännäisen omassa tilassa
    eikä ole yksikään sen neljästä parametrista. Ilman tilaa täällä ajettiin
    aina sitä mallia jonka liitännäinen sattuu ottamaan oletuksena — eri
    malli, eri lopputulos, eikä mitään tapaa kertoa kummasta oli kyse.

    **Nollaus puuttui.** `plugin.process(sig, sr)` ilman `reset=True` jättää
    liitännäisen tilan elämään kutsusta toiseen, jolloin peräkkäin
    käsitellyt raidat kuulostavat eriltä sen mukaan mikä niitä edelsi.

    **Pituutta ei tarkistettu.** Viiveellinen liitännäinen palauttaa
    lyhyemmän tuloksen — dxRevivella mitattuna 4641 näytettä — ja se siirtää
    kaiken sen jälkeisen. `chain.apply_plugin` kieltäytyy siitä.

    Lataus tapahtuu **rakennettaessa** eikä ensimmäisellä käsittelyllä.
    Kaksi syytä: väärä polku kerrotaan ennen kuin minuuttien ajo alkaa, ja
    pedalboard vaatii latauksen samasta säikeestä joka liitännäistä käyttää
    — laiska lataus `process`in sisällä oli sama vika joka kaatoi mlx-työn
    `ThreadPoolExecutor`issa.
    """

    def __init__(
        self,
        plugin_path: str,
        parameters: dict | None = None,
        state: str | None = None,
    ):
        """
        Args:
            plugin_path (str): File path to the external plugin.
            parameters (dict, optional): Parameters to set, in the plug-in's
                own units.
            state (str, optional): The plug-in's own opaque state as base64,
                as left by its own window. See `speechmix.editor`.
        """
        self.plugin_path = plugin_path
        self.parameters = parameters or {}
        self.state = state
        self.plugin = chain.load_plugin(plugin_path, self.parameters, state)

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        sig_np = np.array(signal)
        mono = sig_np.ndim == 1
        # Kirjasto puhuu kanavia riveinä, (kanavat, näytteet).
        block = sig_np[None, :] if mono else sig_np.T
        done = chain.apply_plugin(self.plugin, block, sr)
        return mx.array(done[0] if mono else done.T)


@dataclass
class SpeechSettings:
    """Mitä jaettu ketju lukee. Oletukset ovat kirjaston omat.

    `chain.process` on ankkatyypitetty: se lukee näitä kuutta nimeä eikä
    tiedä mistä ne tulevat. Numerot **eivät** ole tässä kirjoitettuina auki
    -- ne on viritetty yhdessä kynnysviitteen, suhteiden ja aikojen kanssa,
    ja irrallaan niistä ne ovat vain numeroita, jotka voivat erota
    autoraffkatin numeroista ilman että mikään kertoo eroa.
    """

    high_pass_hz: float = shared.HIGH_PASS_HZ
    peak_threshold_db: float = shared.PEAK_THRESHOLD_DB
    leveler_threshold_db: float = shared.LEVELER_THRESHOLD_DB
    declick: bool = True
    declick_sensitivity: float = 0.5
    # Tasonkuljettaja: hidas tason tasaus **ennen** kompressoreita, se vaihe
    # joka käsityönä tehdyssä miksauksessa on ensin. Se tarvitsee puhemaskin,
    # ja `domain/room.py` rakentaa sellaisen automixerin omista raidoista —
    # tämä oli `False` niin kauan kuin sitä ei ollut. Ilman maskia
    # `chain.process` ohittaa vaiheen joka tapauksessa eikä arvaa signaalista:
    # mitattuna tasoheuristiikka kutsui 74 % lohkoista puheeksi kun 53 % oli
    # omaa, ja kuljettaja nosti toisen puhujan vuotoa.
    rider: bool = True


class SpeechChainProcessor(Processor):
    """Koko puheketju kerralla, jaetusta kirjastosta.

    Tämä korvaa kuusi automixerin omaa vaihetta -- naksunpoiston,
    ylipäästön, normalisoinnin ja kaksi kattamatonta kompressoria (tai
    monikaistatilan) -- yhdellä kutsulla, ja tuo mukanaan neljä vaihetta
    joita automixerillä ei ollut lainkaan: sihinänpoiston, kolmannen
    kompressorivaiheen, rinnakkaiskompression ja true peak -rajoittimen.

    `SPEECHMIX-INVENTORY.md` mittasi mitä vaihtui. Tässä kontissa mitattuna
    samalla aineistolla: naksunpoisto muutti **0 näytettä** kaikilla
    herkkyyksillä, yksittäinen kompressorivaihe veti **29,26 dB** ilman
    kattoa, ja monikaistatila liikutti kaistojen tasapainoa **10,72 dB**.

    Kynnykset siirtyvät tavoitteen mukana kirjastossa (`offset = target -
    THRESHOLD_REFERENCE_LUFS`), joten automixerin oma -23 LUFS:n viite
    antaa vaiheille -15 / -21 / -25 ilman että yhtäkään lukua kirjoitetaan
    tänne. -15 on tarkalleen se kynnys jolla automixerin nopea vaihe jo oli.
    """

    def __init__(self, target_lufs: float, settings: SpeechSettings | None = None,
                 speaking=None):
        """
        Args:
            target_lufs (float): Taso johon raita normalisoidaan; myös se
                mistä kynnysten siirtymä lasketaan.
            settings (SpeechSettings, optional): Ketjun asetukset.
            speaking (optional): Tasonkuljettajan maski lohkoittain — milloin
                **tämän raidan oma puhuja** on äänessä. `domain/room.py`
                rakentaa sen puheruudukosta. ``None`` ohittaa vaiheen; se on
                oikea vastaus silloin kun ruudukkoa ei ole, koska signaalista
                pääteltynä puolet «puheesta» olisi toisen mikin vuotoa.
        """
        self.target_lufs = target_lufs
        self.settings = settings or SpeechSettings()
        self.speaking = speaking

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        audio = shared.as_channels(signal)
        stage = None
        if progress_callback is not None:

            def stage(_name, fraction):
                progress_callback(fraction)

        out, _ = shared.process(
            audio,
            sr,
            self.settings,
            gain_db=0.0,
            speech=True,
            target_lufs=self.target_lufs,
            stage=stage,
            speaking=self.speaking,
        )
        return shared.from_channels(out, signal)


class MicDuckProcessor(Processor):
    """Mikin sulkeminen kun sen omistaja on hiljaa, näytteisiin poltettuna.

    Älä sekoita tätä `DuckingProcessor`iin. Se sivuketjuttaa **musiikkipedin**
    summatusta puheesta; tämä sulkee **mikrofonin** toisen puhujan puheen alla.
    Molempia halutaan, ja vain jälkimmäinen on kirjastossa.

    Käyrä tulee `speechmix.envelopes.duck_envelopes`ista, eli se on sama
    laskenta jonka autoraffkat kirjoittaa Final Cutin äänenvoimakkuuden
    keyframeiksi. Ero on emissiossa: automixer vie valmiin wavin, jossa ei ole
    mitään mihin automaatio kirjoitettaisiin, joten se kertoo käyrän
    näytteisiin. Sama päätös, ja siksi sama tulos.

    Tämä ajetaan ketjun **jälkeen**: tasopäätökset jotka tulevat ketjun
    jälkeen voivat olla automaatiota, sitä ennen tulevat on poltettava sisään.
    Vaimennus on jälkeen, tasonkuljettaja ennen.
    """

    def __init__(self, gain: np.ndarray):
        """
        Args:
            gain (np.ndarray): Kerroin näytettä kohden, `Room.duck_gain`ista.
                Yhden alkion taulukko tarkoittaa «ei vaimennusta»: se
                levittyy, eikä koko ohjelman mittaista ykköstaulukkoa
                kannata varata.
        """
        self.gain = np.asarray(gain, dtype=np.float32)

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        if self.gain.size <= 1:
            return signal * float(self.gain[0]) if self.gain.size else signal
        n = signal.shape[0]
        gain = self.gain[:n]
        if gain.size < n:
            # Käyrä loppuu ennen raitaa vain jos näytemäärä on muuttunut
            # matkalla. Ykkösiä perään: vaimennuksen puuttuminen on
            # korjattavissa, väärään kohtaan osunut ei.
            gain = np.pad(gain, (0, n - gain.size), constant_values=1.0)
        curve = mx.array(gain)
        return signal * (curve[:, None] if len(signal.shape) > 1 else curve)


class CeilingProcessor(Processor):
    """Masterin katto, true peakina.

    Korvaa `LimiterProcessor`in, joka laski näytehuipuista: näytteiden
    **väliin** jäävä huippu on se joka leikkaa D/A-muuntimessa ja
    lossy-koodauksessa, eikä se näy näytteitä katsomalla. Mitattuna tässä
    kontissa vanha -1,0 dBFS:n rajoitin jätti todellisen huipun -0,93
    dBTP:hen, ja sen vahvistuskäyrän suurin näytteestä toiseen -askel oli
    8 dB -- pehmentämätön käyrä on itsessään särölähde.

    `peak_guard` on perässä varmistuksena, jonka ei pitäisi koskaan laueta.
    """

    def __init__(self, ceiling_db: float = shared.CEILING_DB):
        """
        Args:
            ceiling_db (float, optional): Katto dBTP. Oletus kirjastosta.
        """
        self.ceiling_db = ceiling_db

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        audio = shared.as_channels(signal)
        limited, _ = shared.limiter(audio, sr, ceiling_db=self.ceiling_db)
        guarded, _ = shared.peak_guard(limited, ceiling_db=self.ceiling_db)
        return shared.from_channels(guarded, signal)
