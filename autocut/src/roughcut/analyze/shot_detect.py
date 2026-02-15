"""Shot boundary detection 2.0: multi-signal (histogram + optical flow + luminance)."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from roughcut.constants import (
    HISTOGRAM_DIFF_THRESHOLD,
    LUMINANCE_JUMP_THRESHOLD,
    MAX_SHOT_DURATION_SEC,
    MIN_SHOT_DURATION_SEC,
    OPTICAL_FLOW_THRESHOLD,
)
from roughcut.models import MediaItem, Shot, ShotDetectConfig

logger = logging.getLogger(__name__)


def compute_histogram(frame: np.ndarray) -> np.ndarray:
    """Compute a normalized HSV histogram for a frame."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def _compute_optical_flow_magnitude(
    gray_prev: np.ndarray, gray_curr: np.ndarray
) -> float:
    """Compute mean optical flow magnitude between two grayscale frames."""
    corners = cv2.goodFeaturesToTrack(gray_prev, maxCorners=80, qualityLevel=0.2, minDistance=7)
    if corners is None or len(corners) < 5:
        return 0.0

    next_pts, status, _ = cv2.calcOpticalFlowPyrLK(gray_prev, gray_curr, corners, None)
    if next_pts is None:
        return 0.0

    good_old = corners[status.flatten() == 1]
    good_new = next_pts[status.flatten() == 1]
    if len(good_old) == 0:
        return 0.0

    return float(np.sqrt(np.sum((good_new - good_old) ** 2, axis=1)).mean())


def _compute_luminance_jump(gray_prev: np.ndarray, gray_curr: np.ndarray) -> float:
    """Compute absolute mean luminance change between two frames."""
    return float(abs(np.mean(gray_curr.astype(float)) - np.mean(gray_prev.astype(float))))


def _detect_boundaries_multi_signal(
    item: MediaItem,
    hist_threshold: float,
    flow_threshold: float,
    lum_threshold: float,
    min_duration: float,
    sample_interval: int,
) -> list[float]:
    """Detect shot boundaries using histogram + optical flow + luminance signals.

    A boundary is triggered when at least 2 of 3 signals exceed their threshold,
    OR when the histogram signal alone exceeds 1.5x threshold (hard cut).
    """
    cap = cv2.VideoCapture(str(item.path))
    if not cap.isOpened():
        logger.error("Cannot open video: %s", item.path)
        return [0.0]

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    boundaries: list[float] = [0.0]
    prev_hist = None
    prev_gray = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            hist = compute_histogram(frame)

            if prev_hist is not None and prev_gray is not None:
                timestamp = frame_idx / fps

                # Check minimum duration from last boundary
                if timestamp - boundaries[-1] < min_duration:
                    prev_hist = hist
                    prev_gray = gray
                    frame_idx += 1
                    continue

                # Signal 1: histogram diff
                hist_diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                hist_triggered = hist_diff > hist_threshold

                # Signal 2: optical flow magnitude
                flow_mag = _compute_optical_flow_magnitude(prev_gray, gray)
                flow_triggered = flow_mag > flow_threshold

                # Signal 3: luminance jump
                lum_jump = _compute_luminance_jump(prev_gray, gray)
                lum_triggered = lum_jump > lum_threshold

                signals_triggered = sum([hist_triggered, flow_triggered, lum_triggered])

                # Decision: hard cut (histogram very high) OR 2+ signals agree
                if hist_diff > hist_threshold * 1.5 or signals_triggered >= 2:
                    boundaries.append(timestamp)

            prev_hist = hist
            prev_gray = gray

        frame_idx += 1

    cap.release()
    boundaries.append(duration)
    return boundaries


def _force_split_long_shots(
    boundaries: list[float], max_duration: float, min_duration: float
) -> list[float]:
    """Force-split any segment longer than max_duration into roughly equal pieces."""
    result: list[float] = [boundaries[0]]

    for i in range(1, len(boundaries)):
        seg_start = result[-1]
        seg_end = boundaries[i]
        seg_dur = seg_end - seg_start

        if seg_dur > max_duration:
            # Split into N pieces, each approximately max_duration
            n_splits = max(2, int(seg_dur / max_duration + 0.5))
            piece_dur = seg_dur / n_splits
            for j in range(1, n_splits):
                split_point = seg_start + j * piece_dur
                result.append(split_point)

        result.append(seg_end)

    return result


def _remove_garbage_segments(
    boundaries: list[float], min_duration: float
) -> list[float]:
    """Remove segments shorter than min_duration by merging with neighbors."""
    if len(boundaries) <= 2:
        return boundaries

    cleaned = [boundaries[0]]
    for i in range(1, len(boundaries)):
        if boundaries[i] - cleaned[-1] >= min_duration:
            cleaned.append(boundaries[i])
        elif i == len(boundaries) - 1:
            # Last boundary: merge with previous (extend last segment)
            cleaned[-1] = boundaries[i] if len(cleaned) == 1 else cleaned[-1]
            if cleaned[-1] != boundaries[i]:
                cleaned.append(boundaries[i])

    # Ensure we end with the video end
    if cleaned[-1] != boundaries[-1]:
        cleaned.append(boundaries[-1])

    return cleaned


def detect_shots(
    item: MediaItem,
    threshold: float = HISTOGRAM_DIFF_THRESHOLD,
    min_duration: float = MIN_SHOT_DURATION_SEC,
    max_duration: float = MAX_SHOT_DURATION_SEC,
    sample_interval: int = 3,
    config: ShotDetectConfig | None = None,
) -> list[Shot]:
    """Detect shot boundaries using multi-signal analysis.

    Signals: histogram diff, optical flow magnitude, luminance jump.
    Also force-splits long shots and removes garbage segments.

    Args:
        item: The video MediaItem to analyze.
        threshold: Histogram difference threshold (overridden by config).
        min_duration: Minimum shot duration in seconds (overridden by config).
        max_duration: Maximum shot duration before force-split (overridden by config).
        sample_interval: Process every Nth frame (overridden by config).
        config: Optional ShotDetectConfig for full control.

    Returns:
        List of Shot objects.
    """
    if not item.is_video:
        logger.warning("Not a video file: %s", item.path)
        return []

    # Use config if provided, otherwise use individual params
    hist_thresh = config.histogram_threshold if config else threshold
    flow_thresh = config.optical_flow_threshold if config else OPTICAL_FLOW_THRESHOLD
    lum_thresh = config.luminance_threshold if config else LUMINANCE_JUMP_THRESHOLD
    min_dur = config.min_duration if config else min_duration
    max_dur = config.max_duration if config else max_duration
    interval = config.sample_interval if config else sample_interval

    # Step 1: Multi-signal boundary detection
    boundaries = _detect_boundaries_multi_signal(
        item, hist_thresh, flow_thresh, lum_thresh, min_dur, interval
    )

    # Step 2: Force-split long segments
    boundaries = _force_split_long_shots(boundaries, max_dur, min_dur)

    # Step 3: Remove garbage segments (too short)
    boundaries = _remove_garbage_segments(boundaries, min_dur)

    # Create Shot objects
    shots = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        if end - start >= min_dur:
            shots.append(
                Shot(source=item, start_sec=start, end_sec=end, shot_index=i)
            )

    logger.info("Detected %d shots in %s", len(shots), item.path.name)
    return shots


def detect_shots_for_photo(item: MediaItem, default_duration: float = 4.0) -> Shot:
    """Create a single Shot for a photo item."""
    return Shot(source=item, start_sec=0.0, end_sec=default_duration, shot_index=0)
