from abc import ABC, abstractmethod
import mlx.core as mx
import numpy as np
from scipy import signal as sp_signal

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
        # Process multichannel
        if len(sig_np.shape) > 1:
            # Apply along length axis for each channel
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
        # Simple offline ducking logic using MLX
        trigger_sq = self.trigger**2
        window_size = max(1, int(self.window_sec * sr))
        weight_mx = mx.ones((1, window_size, 1)) / window_size
        trig_input = trigger_sq.reshape(1, -1, 1)
        
        trig_rms_sq = mx.conv1d(trig_input, weight_mx, stride=1, padding=window_size//2)
        trig_rms = mx.sqrt(trig_rms_sq).reshape(-1)
        
        # Ensure length matches
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
        # Apply gain env to mono or stereo signal
        if len(signal.shape) > 1:
            # Broadcast gain_env: [length] -> [length, channels]
            # Ducking env is the same for all channels to maintain stereo image
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

class SpectralCarverProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, strength: float = 0.5):
        self.trigger = trigger_signal
        self.strength = strength # 0.0 (none) to 1.0 (full carving)
        
    def process(self, signal: mx.array, sr: int, progress_callback=None) -> mx.array:
        """
        Carve frequencies in 'signal' (music) that are present in 'trigger' (speech).
        Using STFT/FFT for spectral subtraction approach.
        """
        n_fft = 2048
        hop_length = 512
        
        # 1. Ensure signals match length
        n_orig = signal.shape[0]
        trigger = self.trigger
        if trigger.shape[0] < n_orig:
            trigger = mx.pad(trigger, [(0, n_orig - trigger.shape[0])])
        elif trigger.shape[0] > n_orig:
            trigger = trigger[:n_orig]
            
        # Window function
        window = mx.array(np.hanning(n_fft).astype(np.float32))
        
        sig_np = np.array(signal)
        trig_np = np.array(trigger)
        out_np = np.zeros_like(sig_np)
        norm_np = np.zeros_like(sig_np)
        
        starts = list(range(0, n_orig - n_fft, hop_length))
        total_steps = len(starts)
        
        # Process in windows
        for i, start in enumerate(starts):
            if progress_callback and i % 50 == 0:
                progress_callback(i / total_steps)
                
            end = start + n_fft
            
            # 1. Extract frames
            s_frame = mx.array(sig_np[start:end]) * window
            t_frame = mx.array(trig_np[start:end]) * window
            
            # 2. FFT
            s_fft = mx.fft.fft(s_frame)
            t_fft = mx.fft.fft(t_frame)
            
            # 3. Magnitude spectra
            s_mag = mx.abs(s_fft)
            t_mag = mx.abs(t_fft)
            
            # 4. Create Mask
            t_max = mx.max(t_mag) + 1e-6
            mask = 1.0 - (self.strength * (t_mag / t_max))
            mask = mx.clip(mask, 0.1, 1.0)
            
            # 5. Apply Mask to music FFT
            if len(sig_np.shape) > 1:
                s_frame = mx.array(sig_np[start:end]) * window[:, None]
                s_fft = mx.fft.fft(s_frame, axis=0)
                carved_fft = s_fft * mask[:, None]
                carved_frame = mx.fft.ifft(carved_fft, axis=0).real
                out_np[start:end] += np.array(carved_frame * window[:, None])
                norm_np[start:end] += np.array(window[:, None]**2)
            else:
                s_frame = mx.array(sig_np[start:end]) * window
                s_fft = mx.fft.fft(s_frame)
                carved_fft = s_fft * mask
                carved_frame = mx.fft.ifft(carved_fft).real
                out_np[start:end] += np.array(carved_frame * window)
                norm_np[start:end] += np.array(window**2)
            
        norm_np[norm_np < 1e-6] = 1.0
        return mx.array(out_np / norm_np)
