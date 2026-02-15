"""Highlight detection and windowing: identify memorable moments and best sub-segments."""

from __future__ import annotations

import logging

import cv2
import numpy as np

from roughcut.models import Shot

logger = logging.getLogger(__name__)

# Thresholds for highlight detection
SMILE_THRESHOLD = 0.6       # face_score threshold for "smile/interaction"
ACTION_COMPLETE_THRESHOLD = 0.5  # motion that peaks then drops
GAZE_THRESHOLD = 0.7        # face_score + stability combo

# Windowing parameters
WINDOW_MIN_SEC = 0.8
WINDOW_MAX_SEC = 2.5
WINDOW_STEP_SEC = 0.5


def compute_highlight_scores(shots: list[Shot]) -> None:
    """Compute highlight_score and highlight_reason for each shot in-place.

    Highlight signals (heuristic):
    - High face score + moderate motion = interaction/smile
    - High face score + high stability = looking at camera
    - High motion + high sharpness = action completion moment
    - Photo with high face score = posed moment
    """
    if not shots:
        return

    for shot in shots:
        q = shot.quality
        score = 0.0
        reasons: list[str] = []

        # Smile / interaction detection
        if q.face_score >= SMILE_THRESHOLD:
            smile_signal = q.face_score * 0.6 + q.motion_intensity * 0.2 + q.exposure * 0.2
            if smile_signal > score:
                score = smile_signal
                reasons.append("interaction")

        # Gaze / looking at camera
        if q.face_score >= 0.5 and q.stability >= GAZE_THRESHOLD:
            gaze_signal = q.face_score * 0.5 + q.stability * 0.3 + q.sharpness * 0.2
            if gaze_signal > score:
                score = gaze_signal
                reasons.append("gaze")

        # Action completion (high motion + sharp = captured a moment)
        if q.motion_intensity >= ACTION_COMPLETE_THRESHOLD and q.sharpness >= 0.5:
            action_signal = q.motion_intensity * 0.4 + q.sharpness * 0.3 + q.exposure * 0.3
            if action_signal > score:
                score = action_signal
                reasons.append("action_moment")

        # Photo with face = posed moment
        if shot.source.is_photo and q.face_score >= 0.3:
            photo_signal = q.face_score * 0.5 + q.sharpness * 0.3 + q.exposure * 0.2
            if photo_signal > score:
                score = photo_signal
                reasons.append("posed_photo")

        shot.highlight_score = min(score, 1.0)
        shot.highlight_reason = ", ".join(reasons) if reasons else ""

    # Log summary
    highlights = [s for s in shots if s.highlight_score >= 0.5]
    logger.info(
        "Highlight detection: %d/%d shots marked as highlights (score >= 0.5)",
        len(highlights), len(shots),
    )
    for s in sorted(highlights, key=lambda x: x.highlight_score, reverse=True)[:5]:
        logger.info(
            "  Top highlight: %s @ %.1fs, score=%.2f, reason=%s",
            s.source.path.name, s.start_sec, s.highlight_score, s.highlight_reason,
        )


def _score_frame_quality(frame: np.ndarray) -> float:
    """Quick per-frame quality score: sharpness + exposure + face presence."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Sharpness (Laplacian variance)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    sharpness = min(lap_var / 500.0, 1.0)

    # Exposure (ideal around 128)
    mean_val = float(np.mean(gray))
    if mean_val < 40:
        exposure = mean_val / 40.0
    elif mean_val > 220:
        exposure = (255 - mean_val) / 35.0
    else:
        exposure = 1.0 - abs(mean_val - 128) / 128.0 * 0.3

    # Face presence (quick Haar cascade)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(30, 30))
    face_score = min(len(faces) * 0.3, 1.0)

    return sharpness * 0.35 + exposure * 0.25 + face_score * 0.4


def compute_highlight_windows(shots: list[Shot]) -> None:
    """For each video shot, find the best sub-window using frame-level scoring.

    Sets shot.best_start_sec, shot.best_end_sec, shot.window_score in-place.
    Photos are skipped (they use their full extent).
    Short shots (< WINDOW_MIN_SEC * 2) use their full extent.
    """
    if not shots:
        return

    windowed_count = 0
    for shot in shots:
        # Skip photos
        if shot.source.is_photo:
            shot.best_start_sec = shot.start_sec
            shot.best_end_sec = shot.end_sec
            shot.window_score = shot.highlight_score
            continue

        dur = shot.duration_sec
        # Short shots: use full extent
        if dur < WINDOW_MIN_SEC * 2:
            shot.best_start_sec = shot.start_sec
            shot.best_end_sec = shot.end_sec
            shot.window_score = shot.quality.overall
            continue

        # Determine window size: clip between WINDOW_MIN and min(WINDOW_MAX, dur)
        window_size = min(WINDOW_MAX_SEC, dur * 0.6)
        window_size = max(window_size, WINDOW_MIN_SEC)

        # Sample frames at window centers and score
        cap = cv2.VideoCapture(str(shot.source.path))
        if not cap.isOpened():
            shot.best_start_sec = shot.start_sec
            shot.best_end_sec = shot.end_sec
            shot.window_score = shot.quality.overall
            continue

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        best_score = -1.0
        best_offset = 0.0

        # Slide the window across the shot
        offset = 0.0
        while offset + window_size <= dur + 0.01:
            abs_time = shot.start_sec + offset + window_size / 2.0
            frame_num = int(abs_time * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if ret:
                score = _score_frame_quality(frame)
                if score > best_score:
                    best_score = score
                    best_offset = offset
            offset += WINDOW_STEP_SEC

        cap.release()

        if best_score >= 0:
            shot.best_start_sec = shot.start_sec + best_offset
            shot.best_end_sec = min(
                shot.best_start_sec + window_size, shot.end_sec
            )
            shot.window_score = best_score
            windowed_count += 1
        else:
            shot.best_start_sec = shot.start_sec
            shot.best_end_sec = shot.end_sec
            shot.window_score = shot.quality.overall

    logger.info(
        "Highlight windowing: %d/%d shots got sub-window selection",
        windowed_count, len(shots),
    )
