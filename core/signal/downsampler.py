import numpy as np


def downsample(data: np.ndarray, max_points: int = 2000) -> tuple[np.ndarray, int]:
    """Return (downsampled_array, rate). Rate=1 means no downsampling."""
    rate = max(1, len(data) // max_points)
    return data[::rate], rate
