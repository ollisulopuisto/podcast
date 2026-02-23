from abc import ABC, abstractmethod
import mlx.core as mx

class Processor(ABC):
    @abstractmethod
    def process(self, signal: mx.array, sr: int) -> mx.array:
        pass

class GainProcessor(Processor):
    def __init__(self, gain_db: float):
        self.gain = 10**(gain_db / 20)
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
        return signal * self.gain

class DuckingProcessor(Processor):
    def __init__(self, trigger_signal: mx.array, threshold_db=-20, ratio=4.0, attack_sec=0.1, release_sec=0.5):
        self.trigger = trigger_signal
        self.threshold = 10**(threshold_db / 20)
        self.ratio = ratio
        self.attack_sec = attack_sec
        self.release_sec = release_sec
        
    def process(self, signal: mx.array, sr: int) -> mx.array:
        """
        Ducks the signal based on the trigger signal's energy.
        signal: mx.array [length, channels] or [length]
        """
        # For simplicity, let's assume mono for now or handle multichannel
        # 1. Compute trigger energy
        # 2. Compute gain reduction envelope
        # 3. Apply to signal
        
        # This is where MLX's acceleration helps!
        # But wait, a real-time compressor/ducker needs state or a lookahead.
        # Let's implement a simple offline ducker.
        
        # 1. Trigger envelope (RMS or peak)
        trigger_sq = self.trigger**2
        # Use simple smoothing
        window_size = int(0.1 * sr) # 100ms smoothing
        weight = mx.ones((1, window_size, 1)) / window_size
        
        # Reshape trigger for conv1d
        trig_input = trigger_sq.reshape(1, -1, 1)
        # Weight shape [out, kernel, in]
        weight_mx = mx.ones((1, window_size, 1)) / window_size
        
        trig_rms_sq = mx.conv1d(trig_input, weight_mx, stride=1, padding=window_size//2)
        # Pad to match original length if needed (MLX conv1d doesn't pad automatically to 'same' easily)
        # Actually, let's just make sure lengths match.
        trig_rms = mx.sqrt(trig_rms_sq).reshape(-1)
        
        # Ensure trig_rms has the same length as signal
        n_orig = signal.shape[0]
        if trig_rms.shape[0] > n_orig:
            trig_rms = trig_rms[:n_orig]
        elif trig_rms.shape[0] < n_orig:
            # Pad with zero
            trig_rms = mx.pad(trig_rms, [(0, n_orig - trig_rms.shape[0])])
            
        # 2. Gain calculation
        # If rms > threshold, reduce gain
        # Gain reduction (dB) = - (rms_db - threshold_db) * (1 - 1/ratio)
        
        # Avoid log(0)
        eps = 1e-6
        trig_db = 20 * mx.log10(trig_rms + eps)
        threshold_db = 20 * mx.log10(mx.array(self.threshold))
        
        reduction_db = mx.where(trig_db > threshold_db, 
                               -(trig_db - threshold_db) * (1 - 1/self.ratio), 
                               0.0)
        
        gain_env = 10**(reduction_db / 20)
        
        # Handle multichannel signal
        if len(signal.shape) > 1:
            # Broadcase gain_env to channels
            return signal * gain_env.reshape(-1, 1)
        else:
            return signal * gain_env
