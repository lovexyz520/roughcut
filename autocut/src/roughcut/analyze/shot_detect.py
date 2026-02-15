"""Shot boundary detection using OpenCV histogram comparison."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from roughcut.constants import HISTOGRAM_DIFF_THRESHOLD, MIN_SHOT_DURATION_SEC
from roughcut.models import MediaItem, Shot

logger = logging.getLogger(__name__)


def compute_histogram(frame: np.ndarray) -> np.ndarray:
    """Compute a normalized HSV histogram for a frame."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def detect_shots(
    item: MediaItem,
    threshold: float = HISTOGRAM_DIFF_THRESHOLD,
    min_duration: float = MIN_SHOT_DURATION_SEC,
    sample_interval: int = 3,
) -> list[Shot]:
    """Detect shot boundaries in a video using histogram differences.

    Args:
        item: The video MediaItem to analyze.
        threshold: Histogram difference threshold for cut detection.
        min_duration: Minimum shot duration in seconds.
        sample_interval: Process every Nth frame for speed.

    Returns:
        List of Shot objects.
    """
    if not item.is_video:
        logger.warning("Not a video file: %s", item.path)
        return []

    cap = cv2.VideoCapture(str(item.path))
    if not cap.isOpened():
        logger.error("Cannot open video: %s", item.path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    boundaries: list[float] = [0.0]  # Start of first shot
    prev_hist = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            hist = compute_histogram(frame)
            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                timestamp = frame_idx / fps
                if diff > threshold:
                    # Check minimum duration from last boundary
                    if timestamp - boundaries[-1] >= min_duration:
                        boundaries.append(timestamp)
            prev_hist = hist

        frame_idx += 1

    cap.release()

    # Add end of video
    boundaries.append(duration)

    # Create Shot objects
    shots = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        if end - start >= min_duration:
            shots.append(
                Shot(source=item, start_sec=start, end_sec=end, shot_index=i)
            )

    logger.info("Detected %d shots in %s", len(shots), item.path.name)
    return shots


def detect_shots_for_photo(item: MediaItem, default_duration: float = 4.0) -> Shot:
    """Create a single Shot for a photo item."""
    return Shot(source=item, start_sec=0.0, end_sec=default_duration, shot_index=0)
