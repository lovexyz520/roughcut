"""Color analysis: per-shot color temperature and continuity distance.

Abrupt warm/cool jumps between adjacent clips break the "look" of a cut and hurt
the cinematic feel. We measure a simple warm/cool temperature per shot and let
the grammar engine penalize large jumps between neighbours.
"""

from __future__ import annotations

import cv2
import numpy as np


def measure_color_temp(frame: np.ndarray) -> float:
    """Return color temperature 0-1 (0 = cool/blue, 0.5 = neutral, 1 = warm/orange).

    Based on the balance of the red vs blue channels (OpenCV frames are BGR).
    """
    if frame is None or frame.size == 0:
        return 0.5
    # Sample downscaled for speed; ignore near-black pixels (noise/rumble).
    small = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    b = float(np.mean(small[..., 0]))
    r = float(np.mean(small[..., 2]))
    denom = r + b
    if denom <= 1e-6:
        return 0.5
    warm = r / denom  # 0.5 neutral, >0.5 warm, <0.5 cool
    # Gently expand around neutral so typical footage spreads across the range.
    return float(np.clip(0.5 + (warm - 0.5) * 1.6, 0.0, 1.0))


def measure_color_temp_multi(frames: list[np.ndarray]) -> float:
    """Median color temperature across sampled frames."""
    if not frames:
        return 0.5
    return float(np.median([measure_color_temp(f) for f in frames]))


def color_distance(temp_a: float, temp_b: float) -> float:
    """Absolute color-temperature distance between two shots (0-1)."""
    return abs(temp_a - temp_b)
