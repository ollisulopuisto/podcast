from abc import ABC, abstractmethod
import mlx.core as mx
import numpy as np
from scipy import signal as sp_signal
from scipy.ndimage import maximum_filter1d
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
        n_samples = signal.shape[0]
        lookahead_samples = max(1, int(self.lookahead_sec * sr))
        env_np = np.array(mx.max(mx.abs(signal), axis=-1)) if len(signal.shape) > 1 else np.array(mx.abs(signal))
        peak_env = maximum_filter1d(env_np, size=lookahead_samples, origin=-(lookahead_samples // 2))
        target_gain = np.where(peak_env > self.threshold, self.threshold / (peak_env + 1e-6), 1.0)
        smoothed_gain = np.ones_like(target_gain)
        alpha_rel = np.exp(-1.0 / (self.release_sec * sr))
        current_gain = 1.0
        for i in range(len(target_gain)):
            target = target_gain[i]
            if target < current_gain: current_gain = target
            else: current_gain = current_gain * alpha_rel + target * (1 - alpha_rel)
            smoothed_gain[i] = current_gain
        final_gain = mx.array(smoothed_gain)
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
        window = mx.array(np.hanning(n_fft).astype(np.float32))
        sig_np = np.array(signal)
        trig_np = np.array(trigger)
        out_np = np.zeros_like(sig_np)
        norm_np = np.zeros_like(sig_np)
        starts = list(range(0, n_orig - n_fft, hop_length))
        total_steps = len(starts)
        for i, start in enumerate(starts):
            if progress_callback and i % 50 == 0: progress_callback(i / total_steps)
            end = start + n_fft
            if len(sig_np.shape) > 1:
                s_frame = mx.array(sig_np[start:end]) * window[:, None]
                t_frame = mx.array(trig_np[start:end]) * window
                s_fft = mx.fft.fft(s_frame, axis=0)
                t_fft = mx.fft.fft(t_frame)
                t_mag = mx.abs(t_fft)
                t_max = mx.max(t_mag) + 1e-6
                mask = mx.clip(1.0 - (self.strength * (t_mag / t_max)), 0.1, 1.0)
                carved_fft = s_fft * mask[:, None]
                carved_frame = mx.fft.ifft(carved_fft, axis=0).real
                out_np[start:end] += np.array(carved_frame * window[:, None])
                norm_np[start:end] += np.array(window[:, None]**2)
            else:
                s_frame = mx.array(sig_np[start:end]) * window
                t_frame = mx.array(trig_np[start:end]) * window
                s_fft = mx.fft.fft(s_frame)
                t_fft = mx.fft.fft(t_frame)
                t_mag = mx.abs(t_fft)
                t_max = mx.max(t_mag) + 1e-6
                mask = mx.clip(1.0 - (self.strength * (t_mag / t_max)), 0.1, 1.0)
                carved_fft = s_fft * mask
                carved_frame = mx.fft.ifft(carved_fft).real
                out_np[start:end] += np.array(carved_frame * window)
                norm_np[start:end] += np.array(window**2)
        norm_np[norm_np < 1e-6] = 1.0
        return mx.array(out_np / norm_np)

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
        gain_offset = ref_lufs - loudness
        gain_offset = np.clip(gain_offset, -20, 20)
        out = band_sig * (10**(gain_offset / 20))
        if self.peak_enabled:
            out = CompressorProcessor(threshold_db=-15, ratio=2.5, window_sec=0.03).process(out, sr)
        if self.lev_enabled:
            out = CompressorProcessor(threshold_db=-26, ratio=1.5, window_sec=0.3).process(out, sr)
        return out

    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        sig_np = np.array(signal)
        # 2nd order Butterworth for better stability
        sos_low = sp_signal.butter(2, self.low_mid_freq, 'lp', fs=sr, output='sos')
        sos_mid = sp_signal.butter(2, self.mid_high_freq, 'lp', fs=sr, output='sos')
        
        axis = 0 if len(sig_np.shape) > 1 else -1
        # Subtract low from signal, then subtract mid from the rest
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
                self.plugin = pedalboard.load_plugin(self.plugin_path)
                for name, value in self.parameters.items():
                    if hasattr(self.plugin, name): setattr(self.plugin, name, value)
            except Exception as e:
                print(f"Error loading plugin {self.plugin_path}: {e}")
                return signal
        sig_np = np.array(signal)
        if len(sig_np.shape) > 1: sig_pb = sig_np.T
        else: sig_pb = sig_np[None, :]
        processed_pb = self.plugin.process(sig_pb, sr)
        if len(sig_np.shape) > 1: return mx.array(processed_pb.T)
        else: return mx.array(processed_pb[0])
