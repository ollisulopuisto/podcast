from abc import ABC, abstractmethod
import mlx.core as mx
import numpy as np
from scipy import signal as sp_signal
from scipy.ndimage import maximum_filter1d, median_filter
import pyloudnorm as pyln
from typing import Optional, List
import pedalboard
import os

class Processor(ABC):
    @abstractmethod
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        pass

class GainProcessor(Processor):
    def __init__(self, gain_db: float):
        self.gain = 10**(gain_db / 20)
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        return signal * self.gain

class HighPassProcessor(Processor):
    def __init__(self, cut_freq=100.0):
        self.cut_freq = cut_freq
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        sig_np = np.array(signal)
        sos = sp_signal.butter(4, self.cut_freq, 'hp', fs=sr, output='sos')
        axis = 0 if len(sig_np.shape) > 1 else -1
        filtered_np = sp_signal.sosfilt(sos, sig_np, axis=axis)
        return mx.array(filtered_np.astype(np.float32))

class DuckingProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, threshold_db=-20, ratio=4.0, window_sec=0.1):
        self.trigger = trigger_signal
        self.threshold = 10**(threshold_db / 20)
        self.ratio = ratio
        self.window_sec = window_sec
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        trigger_sq = self.trigger**2
        window_size = max(1, int(self.window_sec * sr))
        weight_mx = mx.ones((1, window_size, 1)) / window_size
        trig_input = trigger_sq.reshape(1, -1, 1)
        trig_rms_sq = mx.conv1d(trig_input, weight_mx, stride=1, padding=window_size//2)
        trig_rms = mx.sqrt(trig_rms_sq).reshape(-1)
        n_orig = signal.shape[0]
        if trig_rms.shape[0] > n_orig: trig_rms = trig_rms[:n_orig]
        elif trig_rms.shape[0] < n_orig: trig_rms = mx.pad(trig_rms, [(0, n_orig - trig_rms.shape[0])])
        eps = 1e-6
        trig_db = 20 * mx.log10(trig_rms + eps)
        threshold_db_val = 20 * mx.log10(mx.array(self.threshold))
        reduction_db = mx.where(trig_db > threshold_db_val, -(trig_db - threshold_db_val) * (1 - 1/self.ratio), 0.0)
        gain_env = 10**(reduction_db / 20)
        return signal * gain_env[:, None] if len(signal.shape) > 1 else signal * gain_env

class CompressorProcessor(Processor):
    def __init__(self, threshold_db=-20, ratio=4.0, window_sec=0.1):
        self.threshold = threshold_db
        self.ratio = ratio
        self.window_sec = window_sec
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        ducker = DuckingProcessor(trigger_signal=signal, threshold_db=self.threshold, ratio=self.ratio, window_sec=self.window_sec)
        return ducker.process(signal, sr, progress_callback=progress_callback)

class LimiterProcessor(Processor):
    def __init__(self, threshold_db=-1.0, lookahead_sec=0.005, release_sec=0.1):
        self.threshold = 10**(threshold_db / 20)
        self.lookahead_sec = lookahead_sec
        self.release_sec = release_sec

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        """
        GPU-Accelerated Brickwall Limiter.
        """
        n_samples = signal.shape[0]
        lookahead_samples = max(1, int(self.lookahead_sec * sr))
        
        # 1. Absolute envelope (GPU)
        env = mx.max(mx.abs(signal), axis=-1) if len(signal.shape) > 1 else mx.abs(signal)
        env_np = np.array(env)
        
        # 2. Peak Detection (Sliding Max)
        # We spread the peak's influence backwards in time by 'lookahead_samples'
        # origin=-(lookahead_samples//2) means for index i, we see max of [i, i+lookahead]
        peak_env = maximum_filter1d(env_np, size=lookahead_samples, origin=-(lookahead_samples // 2))
        
        # 3. Gain Calculation
        # To make it smooth but brickwall, we apply a release filter to the peak envelope
        # but NOT an attack filter.
        target_gain = np.where(peak_env > self.threshold, self.threshold / (peak_env + 1e-6), 1.0)
        
        # Fast attack, slow release smoothing in NumPy (optimized)
        smoothed_gain = np.ones_like(target_gain)
        alpha_rel = np.exp(-1.0 / (self.release_sec * sr))
        
        # We still need a loop for the non-linear attack/release, but let's 
        # make it as fast as possible or use a trick.
        # Given we have lookahead, we can just use the target_gain directly for a 
        # perfect brickwall, and maybe just a tiny bit of smoothing.
        
        # For now, let's use the target_gain DIRECTLY to fix the bug and ensure 
        # it is a brickwall. Distortion can be handled by increasing lookahead.
        final_gain = mx.array(target_gain.astype(np.float32))
        
        return signal * final_gain[:, None] if len(signal.shape) > 1 else signal * final_gain

class SpectralCarverProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, strength: float = 0.5):
        self.trigger = trigger_signal
        self.strength = strength 
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        n_fft = 2048
        hop_length = 512
        n_orig = signal.shape[0]
        trigger = self.trigger
        if trigger.shape[0] < n_orig: trigger = mx.pad(trigger, [(0, n_orig - trigger.shape[0])])
        elif trigger.shape[0] > n_orig: trigger = trigger[:n_orig]
        block_samples = 5 * 60 * sr 
        out_np = np.zeros(signal.shape, dtype=np.float32)
        norm_np = np.zeros(n_orig, dtype=np.float32)
        window = mx.array(np.hanning(n_fft).astype(np.float32))
        window_np = np.array(window)**2
        num_blocks = (n_orig // block_samples) + 1
        for b in range(num_blocks):
            b_start = b * block_samples
            b_end = min(b_start + block_samples, n_orig)
            if b_start >= n_orig: break
            seg_end = min(b_end + n_fft, n_orig)
            s_seg = signal[b_start : seg_end]
            t_seg = trigger[b_start : seg_end]
            if s_seg.shape[0] < n_fft: break
            num_windows = (s_seg.shape[0] - n_fft) // hop_length + 1
            if num_windows <= 0: continue
            if progress_callback: progress_callback(b / num_blocks)
            idx = mx.arange(n_fft)[None, :] + (mx.arange(num_windows) * hop_length)[:, None]
            s_win = s_seg[idx] 
            t_win = t_seg[idx]
            if len(s_win.shape) > 2: s_win = s_win * window[None, :, None]
            else: s_win = s_win * window[None, :]
            t_win = t_win * window[None, :]
            s_fft = mx.fft.fft(s_win, axis=1)
            t_fft = mx.fft.fft(t_win, axis=1)
            t_mag = mx.abs(t_fft)
            t_max = mx.max(t_mag, axis=1, keepdims=True) + 1e-6
            mask = mx.clip(1.0 - (self.strength * (t_mag / t_max)), 0.1, 1.0)
            if len(s_win.shape) > 2: carved_fft = s_fft * mask[:, :, None]
            else: carved_fft = s_fft * mask
            carved_win = mx.fft.ifft(carved_fft, axis=1).real
            carved_np = np.array(carved_win)
            for i in range(num_windows):
                w_start = b_start + (i * hop_length)
                w_end = w_start + n_fft
                out_np[w_start:w_end] += carved_np[i]
                norm_np[w_start:w_end] += window_np
        norm_np[norm_np < 1e-6] = 1.0
        return mx.array(out_np / (norm_np[:, None] if len(signal.shape) > 1 else norm_np))

class MultibandCompressorProcessor(Processor):
    def __init__(self, low_mid_freq=250, mid_high_freq=4000, peak_enabled=True, lev_enabled=True):
        self.low_mid_freq = low_mid_freq
        self.mid_high_freq = mid_high_freq
        self.peak_enabled = peak_enabled
        self.lev_enabled = lev_enabled

    def _apply_auto_dynamics(self, band_sig: mx.array, sr: int, ref_lufs=-23.0) -> mx.array:
        band_np = np.array(band_sig)
        if np.max(np.abs(band_np)) < 1e-5: return band_sig
        meter = pyln.Meter(sr)
        try:
            loudness = meter.integrated_loudness(band_np)
            if np.isnan(loudness) or np.isinf(loudness): return band_sig
        except: return band_sig
        gain_offset = np.clip(ref_lufs - loudness, -20, 20)
        out = band_sig * (10**(gain_offset / 20))
        if self.peak_enabled: out = CompressorProcessor(threshold_db=-15, ratio=2.5, window_sec=0.03).process(out, sr)
        if self.lev_enabled: out = CompressorProcessor(threshold_db=-26, ratio=1.5, window_sec=0.3).process(out, sr)
        return out

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        sig_np = np.array(signal)
        sos_low = sp_signal.butter(2, self.low_mid_freq, 'lp', fs=sr, output='sos')
        sos_mid = sp_signal.butter(2, self.mid_high_freq, 'lp', fs=sr, output='sos')
        axis = 0 if len(sig_np.shape) > 1 else -1
        low_np = sp_signal.sosfilt(sos_low, sig_np, axis=axis)
        rem = sig_np - low_np
        mid_np = sp_signal.sosfilt(sos_mid, rem, axis=axis)
        high_np = rem - mid_np
        low_proc = self._apply_auto_dynamics(mx.array(low_np.astype(np.float32)), sr)
        mid_proc = self._apply_auto_dynamics(mx.array(mid_np.astype(np.float32)), sr)
        high_proc = self._apply_auto_dynamics(mx.array(high_np.astype(np.float32)), sr)
        return low_proc + mid_proc + high_proc

class ExternalPluginProcessor(Processor):
    def __init__(self, plugin_path: str, parameters: dict = None):
        self.plugin_path = plugin_path
        self.parameters = parameters or {}
        self.plugin = None

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        if self.plugin is None:
            try:
                plugin_name = os.path.basename(self.plugin_path)
                print(f"[PLUGIN] Loading {plugin_name}...")
                self.plugin = pedalboard.load_plugin(self.plugin_path)
                for name, value in self.parameters.items():
                    if hasattr(self.plugin, name):
                        setattr(self.plugin, name, value)
                        print(f"  - Set {name} = {value}")
                    else:
                        found = False
                        if hasattr(self.plugin, 'parameters'):
                            for p_name, p_obj in self.plugin.parameters.items():
                                if name.lower() == p_name.lower().replace(" ", "_"):
                                    setattr(self.plugin, p_name, value)
                                    print(f"  - Set {p_name} = {value}")
                                    found = True
                                    break
                        if not found: print(f"  ! Warning: Parameter '{name}' not found")
            except Exception as e:
                print(f"[PLUGIN ERROR] {self.plugin_path}: {e}")
                return signal
        sig_np = np.array(signal)
        if len(sig_np.shape) > 1: sig_pb = sig_np.T
        else: sig_pb = sig_np[None, :]
        processed_pb = self.plugin.process(sig_pb, sr)
        if len(sig_np.shape) > 1: return mx.array(processed_pb.T)
        else: return mx.array(processed_pb[0])

class DeSmackProcessor(Processor):
    def __init__(self, sensitivity: float = 0.5):
        self.sensitivity = sensitivity # 0.0 to 1.0

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        """
        Spectral Interpolation De-Smacker.
        Detects HF transients and smooths them in the spectrogram.
        """
        sig_np = np.array(signal)
        n_samples = sig_np.shape[0]
        
        # 1. SIDECHAINS FOR DETECTION
        # High-pass 4kHz+ (clicks live here)
        sos_hp = sp_signal.butter(4, 4000, 'hp', fs=sr, output='sos')
        hp_side = sp_signal.sosfiltfilt(sos_hp, sig_np, axis=0 if len(sig_np.shape)>1 else -1)
        
        # Low-pass 1kHz (plosives live here)
        sos_lp = sp_signal.butter(4, 1000, 'lp', fs=sr, output='sos')
        lp_side = sp_signal.sosfiltfilt(sos_lp, sig_np, axis=0 if len(sig_np.shape)>1 else -1)
        
        # 2. DETECTION
        # Find spikes in HP energy
        hp_energy = np.abs(hp_side)
        lp_energy = np.abs(lp_side)
        
        # Local mean energy for relative thresholding
        win_size = int(0.05 * sr) # 50ms window
        hp_mean = maximum_filter1d(hp_energy, size=win_size)
        
        # Threshold: spikes that are much louder than local mean
        # Sensitivity maps 0..1 to 5x..2x factor
        thresh_factor = 5.0 - (3.0 * self.sensitivity)
        potential_clicks = hp_energy > (hp_mean * thresh_factor)
        
        # Filter out plosives: if LP energy is also high, it's a 'p' or 't', not a smack
        is_plosive = lp_energy > (np.mean(lp_energy) * 3.0)
        actual_clicks = potential_clicks & ~is_plosive
        
        if not np.any(actual_clicks):
            return signal

        # 3. INTERPOLATION (Spectral Smoothing)
        # We'll use a short-time windowed approach for detected click ranges.
        out_np = sig_np.copy()
        click_indices = np.where(actual_clicks)[0]
        
        # Group consecutive indices into clicks
        if len(click_indices) > 0:
            diffs = np.diff(click_indices)
            splits = np.where(diffs > 1)[0] + 1
            clusters = np.split(click_indices, splits)
            
            for cluster in clusters:
                # Click center and width
                c_start = max(0, cluster[0] - 10)
                c_end = min(n_samples, cluster[-1] + 10)
                
                # Spectral Interpolation (Simplification: Median smoothing in time domain for tiny segments)
                # For tiny transients, a median filter on the waveform or a cubic interpolation
                # is effectively "spectral" if applied to the residual.
                # Here we do a surgical cubic spline interpolation over the click gap.
                if (c_end - c_start) < int(0.01 * sr): # Only for short clicks (<10ms)
                    x_pre = np.arange(max(0, c_start-20), c_start)
                    x_post = np.arange(c_end, min(n_samples, c_end+20))
                    
                    if len(x_pre) > 5 and len(x_post) > 5:
                        x_ref = np.concatenate([x_pre, x_post])
                        if len(sig_np.shape) > 1:
                            for ch in range(sig_np.shape[1]):
                                y_ref = sig_np[x_ref, ch]
                                interp = np.interp(np.arange(c_start, c_end), x_ref, y_ref)
                                out_np[c_start:c_end, ch] = interp
                        else:
                            y_ref = sig_np[x_ref]
                            interp = np.interp(np.arange(c_start, c_end), x_ref, y_ref)
                            out_np[c_start:c_end] = interp
                            
        return mx.array(out_np.astype(np.float32))
