import numpy as np
import mlx.core as mx

class SpotAnalyzer:
    def __init__(self, sr, skip_first_percent=50, window_sec=0.5, hop_sec=0.1, threshold_db=-45):
        self.sr = sr
        self.skip_first_percent = skip_first_percent
        self.window_size = int(window_sec * sr)
        self.hop_size = int(hop_sec * sr)
        self.threshold = 10**(threshold_db / 20)
        
    def find_spots(self, audio):
        """
        Finds silences in the audio signal.
        audio: numpy array or mlx array
        returns: list of timestamps in seconds
        """
        # Convert to mlx array if it's numpy
        if isinstance(audio, np.ndarray):
            audio_mx = mx.array(audio)
        else:
            audio_mx = audio
            
        n_samples = audio_mx.shape[0]
        skip_samples = int(n_samples * (self.skip_first_percent / 100))
        
        # Analyze from the skip point
        analysis_audio = audio_mx[skip_samples:]
        
        # Simple RMS calculation using MLX
        # We can implement a sliding window RMS by squaring, then a uniform filter (convolution)
        squared = analysis_audio**2
        
        # Reshape audio for conv1d: [batch, length, channels]
        input_mx = squared.reshape(1, -1, 1)
        # Weight shape for conv1d in MLX: [out_channels, kernel_size, in_channels]
        weight_mx = mx.ones((1, self.window_size, 1)) / self.window_size
        
        # RMS squared via convolution
        rms_sq = mx.conv1d(input_mx, weight_mx, stride=self.hop_size)
        rms = mx.sqrt(rms_sq).reshape(-1)
        
        # Find indices below threshold using NumPy for convenience
        condition = rms < self.threshold
        silent_indices_np = np.where(np.array(condition))[0]
        
        # Convert indices to timestamps
        skip_sec = skip_samples / self.sr
        hop_sec = self.hop_size / self.sr
        
        spots = []
        if len(silent_indices_np) > 0:
            # Group consecutive indices into clusters
            diffs = np.diff(silent_indices_np)
            # Split where diff > 1 (not consecutive)
            splits = np.where(diffs > 1)[0] + 1
            clusters = np.split(silent_indices_np, splits)
            
            for cluster in clusters:
                # Use the middle of the cluster as the spot
                mid_idx = cluster[len(cluster) // 2]
                timestamp = skip_sec + (mid_idx * hop_sec)
                spots.append(float(timestamp))
                    
        return spots
