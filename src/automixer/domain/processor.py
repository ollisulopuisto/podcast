from abc import ABC, abstractmethod
import mlx.core as mx
import numpy as np
from scipy import signal as sp_signal
from scipy.ndimage import maximum_filter1d

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
        sos = sp_signal.butter(10, self.cut_freq, 'hp', fs=sr, output='sos')
        if len(sig_np.shape) > 1:
            filtered_np = sp_signal.sosfilt(sos, sig_np, axis=0)
        else:
            filtered_np = sp_signal.sosfilt(sos, sig_np)
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
        if trig_rms.shape[0] > n_orig:
            trig_rms = trig_rms[:n_orig]
        elif trig_rms.shape[0] < n_orig:
            trig_rms = mx.pad(trig_rms, [(0, n_orig - trig_rms.shape[0])])
            
        eps = 1e-6
        trig_db = 20 * mx.log10(trig_rms + eps)
        threshold_db = 20 * mx.log10(mx.array(self.threshold))
        
        reduction_db = mx.where(trig_db > threshold_db, 
                               -(trig_db - threshold_db) * (1 - 1/self.ratio), 
                               0.0)
        
        gain_env = 10**(reduction_db / 20)
        if len(signal.shape) > 1:
            return signal * gain_env[:, None]
        else:
            return signal * gain_env

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
        
        if len(signal.shape) > 1:
            env_np = np.array(mx.max(mx.abs(signal), axis=-1))
        else:
            env_np = np.array(mx.abs(signal))
            
        # Sliding window max for lookahead
        peak_env = maximum_filter1d(env_np, size=lookahead_samples, origin=-(lookahead_samples // 2))
        
        target_gain = np.where(peak_env > self.threshold, self.threshold / (peak_env + 1e-6), 1.0)
        
        smoothed_gain = np.ones_like(target_gain)
        alpha_rel = np.exp(-1.0 / (self.release_sec * sr))
        
        current_gain = 1.0
        for i in range(len(target_gain)):
            target = target_gain[i]
            if target < current_gain: 
                current_gain = target
            else:
                current_gain = current_gain * alpha_rel + target * (1 - alpha_rel)
            smoothed_gain[i] = current_gain
            
        final_gain = mx.array(smoothed_gain)
        if len(signal.shape) > 1:
            return signal * final_gain[:, None]
        else:
            return signal * final_gain

class SpectralCarverProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, strength: float = 0.5):
        self.trigger = trigger_signal
        self.strength = strength 
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        n_fft = 2048
        hop_length = 512
        n_orig = signal.shape[0]
        trigger = self.trigger
        if trigger.shape[0] < n_orig:
            trigger = mx.pad(trigger, [(0, n_orig - trigger.shape[0])])
        elif trigger.shape[0] > n_orig:
            trigger = trigger[:n_orig]
            
        window = mx.array(np.hanning(n_fft).astype(np.float32))
        sig_np = np.array(signal)
        trig_np = np.array(trigger)
        out_np = np.zeros_like(sig_np)
        norm_np = np.zeros_like(sig_np)
        
        starts = list(range(0, n_orig - n_fft, hop_length))
        total_steps = len(starts)
        
        for i, start in enumerate(starts):
            if progress_callback and i % 50 == 0:
                progress_callback(i / total_steps)
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
