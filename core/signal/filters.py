import numpy as np


def threshold_filter(data: np.ndarray, low: float, high: float) -> np.ndarray:
    """Zero out samples whose absolute value is outside [low, high]."""
    x = np.asarray(data, dtype=np.float32)
    low, high = abs(low), abs(high)
    if low > high:
        low, high = high, low
    mask = (np.abs(x) >= low) & (np.abs(x) <= high)
    return x * mask
