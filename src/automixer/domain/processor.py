from abc import ABC, abstractmethod
import mlx.core as mx
import numpy as np
from scipy import signal as sp_signal

class Processor(ABC):
    @abstractmethod
    def process(self, signal: mx.array, sr: int) -> mx.array:
        pass

class GainProcessor(Processor):
    def __init__(self, gain_db: float):
        self.gain = 10**(gain_db / 20)
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
        return signal * self.gain

class HighPassProcessor(Processor):
    def __init__(self, cut_freq=100.0):
        self.cut_freq = cut_freq
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
        sig_np = np.array(signal)
        sos = sp_signal.butter(10, self.cut_freq, 'hp', fs=sr, output='sos')
        filtered_np = sp_signal.sosfilt(sos, sig_np)
        return mx.array(filtered_np.astype(np.float32))

class DuckingProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, threshold_db=-20, ratio=4.0, attack_sec=0.1, release_sec=0.5):
        self.trigger = trigger_signal
        self.threshold = 10**(threshold_db / 20)
        self.ratio = ratio
        self.attack_sec = attack_sec
        self.release_sec = release_sec
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
        # Simple offline ducking logic using MLX
        trigger_sq = self.trigger**2
        window_size = int(0.1 * sr) 
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
        if len(signal.shape) > 1:
            return signal * gain_env.reshape(-1, 1)
        else:
            return signal * gain_env

class CompressorProcessor(Processor):
    def __init__(self, threshold_db=-20, ratio=4.0):
        self.threshold = threshold_db
        self.ratio = ratio
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
        ducker = DuckingProcessor(trigger_signal=signal, threshold_db=self.threshold, ratio=self.ratio)
        return ducker.process(signal, sr)

class SpectralCarverProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, strength: float = 0.5):
        self.trigger = trigger_signal
        self.strength = strength # 0.0 (none) to 1.0 (full carving)
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
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
            
        # 2. Windowed STFT - Simple implementation
        # For a truly transparent sound, we should use a proper STFT.
        # But for an offline processor, we'll do it in chunks.
        
        # MLX stft is not as high-level as librosa. 
        # Let's use a simpler approach: 
        # Divide into overlapping frames, apply Hanning window, FFT, modify, iFFT, overlap-add.
        
        frames_idx = mx.arange(0, n_orig - n_fft, hop_length)
        # Window function
        window = mx.array(np.hanning(n_fft).astype(np.float32))
        
        # We'll use numpy for the windowing/overlap-add logic for robustness, 
        # then MLX for the FFT calculations.
        
        sig_np = np.array(signal)
        trig_np = np.array(trigger)
        out_np = np.zeros_like(sig_np)
        norm_np = np.zeros_like(sig_np)
        
        # Process in windows
        for start in range(0, n_orig - n_fft, hop_length):
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
            # If t_mag is high, reduce s_mag.
            # Simple inverse scaling mask
            t_max = mx.max(t_mag) + 1e-6
            mask = 1.0 - (self.strength * (t_mag / t_max))
            mask = mx.clip(mask, 0.1, 1.0) # Don't kill frequencies completely
            
            # 5. Apply Mask to music FFT (preserve phase)
            carved_fft = s_fft * mask
            
            # 6. iFFT
            carved_frame = mx.fft.ifft(carved_fft).real
            
            # 7. Overlap-Add
            out_np[start:end] += np.array(carved_frame * window)
            norm_np[start:end] += np.array(window**2)
            
        # Avoid division by zero
        norm_np[norm_np < 1e-6] = 1.0
        return mx.array(out_np / norm_np)
