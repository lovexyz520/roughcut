"""Quality scoring for video shots and photos."""

from __future__ import annotations

import logging

import cv2
import numpy as np

from roughcut.analyze.audio_energy import analyze_source_audio
from roughcut.analyze.camera_motion import classify_camera_motion
from roughcut.analyze.color import measure_color_temp_multi
from roughcut.analyze.composition import measure_composition, measure_composition_multi
from roughcut.analyze.dedup import compute_phash
from roughcut.analyze.expression import measure_smile, measure_smile_multi
from roughcut.models import MediaItem, QualityScores, Shot, SignalsConfig

logger = logging.getLogger(__name__)


def measure_sharpness(frame: np.ndarray) -> float:
    """Measure sharpness using Laplacian variance (0-1 normalized)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Normalize: typical range 0-2000, cap at 1
    return min(lap_var / 500.0, 1.0)


def measure_exposure(frame: np.ndarray) -> float:
    """Measure exposure quality from histogram distribution (0-1)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_val = np.mean(gray)
    # Ideal: mean around 120. Penalize too dark (<40) or too bright (>220)
    if mean_val < 40:
        return mean_val / 40.0
    if mean_val > 220:
        return (255 - mean_val) / 35.0
    # Good range
    return 1.0 - abs(mean_val - 128) / 128.0 * 0.3


def measure_stability(frames: list[np.ndarray]) -> float:
    """Measure stability via optical flow jitter between consecutive frames (0-1)."""
    if len(frames) < 2:
        return 1.0

    total_motion = 0.0
    pairs = 0

    for i in range(min(len(frames) - 1, 5)):
        gray1 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frames[i + 1], cv2.COLOR_BGR2GRAY)

        # Use sparse optical flow on corner points
        corners = cv2.goodFeaturesToTrack(gray1, maxCorners=50, qualityLevel=0.3, minDistance=7)
        if corners is None or len(corners) < 5:
            continue

        next_pts, status, _ = cv2.calcOpticalFlowPyrLK(gray1, gray2, corners, None)
        if next_pts is None:
            continue

        good_old = corners[status.flatten() == 1]
        good_new = next_pts[status.flatten() == 1]
        if len(good_old) == 0:
            continue

        motion = np.sqrt(np.sum((good_new - good_old) ** 2, axis=1)).mean()
        total_motion += motion
        pairs += 1

    if pairs == 0:
        return 0.5

    avg_motion = total_motion / pairs
    # High motion = unstable. Normalize: 0 motion = 1.0, 20+ pixels = 0.0
    return max(0.0, 1.0 - avg_motion / 20.0)


def detect_faces(frame: np.ndarray) -> float:
    """Detect faces and return a score (0-1)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
    )

    if len(faces) == 0:
        return 0.0

    # Score based on number and size of faces relative to frame
    frame_area = frame.shape[0] * frame.shape[1]
    total_face_area = sum(w * h for (_, _, w, h) in faces)
    face_ratio = total_face_area / frame_area

    # More faces and bigger = higher score, cap at 1
    return min(face_ratio * 10.0 + len(faces) * 0.1, 1.0)


def measure_motion_intensity(frames: list[np.ndarray]) -> float:
    """Measure motion intensity via frame differencing (0-1)."""
    if len(frames) < 2:
        return 0.0

    total_diff = 0.0
    pairs = 0

    for i in range(min(len(frames) - 1, 5)):
        gray1 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frames[i + 1], cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray1, gray2)
        total_diff += np.mean(diff)
        pairs += 1

    if pairs == 0:
        return 0.0

    avg_diff = total_diff / pairs
    # Normalize: 0 = static, 40+ = very dynamic
    return min(avg_diff / 40.0, 1.0)


def sample_frames(
    video_path: str, start_sec: float, end_sec: float, max_frames: int = 8
) -> list[np.ndarray]:
    """Sample evenly spaced frames from a video segment."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)
    total = end_frame - start_frame

    if total <= 0:
        cap.release()
        return []

    step = max(1, total // max_frames)
    frames = []

    for i in range(start_frame, end_frame, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
        if len(frames) >= max_frames:
            break

    cap.release()
    return frames


def _top_half_mean(values: list[float]) -> float:
    """Mean of the better half of the values (rewards the shot's best moment
    without letting a single stray frame dominate)."""
    if not values:
        return 0.0
    ordered = sorted(values, reverse=True)
    half = ordered[: max(1, len(ordered) // 2)]
    return float(np.mean(half))


def score_shot(shot: Shot, signals: SignalsConfig | None = None) -> QualityScores:
    """Compute quality scores for a video shot and populate its V2.2 signals.

    Point metrics are aggregated across *all* sampled frames instead of trusting
    a single middle frame — a shot where someone turns and smiles at second 3 no
    longer gets judged by a bland frame at second 1.5. Also populates the shot's
    camera_motion, color_temp and phash fields in place (returned as part of the
    shots list by the worker).
    """
    if shot.source.is_photo:
        return score_photo(shot, signals)

    signals = signals or SignalsConfig()
    frames = sample_frames(
        str(shot.source.path), shot.start_sec, shot.end_sec
    )
    if not frames:
        logger.warning("No frames sampled for shot in %s", shot.source.path.name)
        return QualityScores()

    mid_frame = frames[len(frames) // 2]

    # Aggregate point metrics across frames.
    sharp = _top_half_mean([measure_sharpness(f) for f in frames])
    expo = float(np.median([measure_exposure(f) for f in frames]))
    face = max(detect_faces(f) for f in frames)  # peak: catch the moment

    q = QualityScores(
        sharpness=sharp,
        exposure=expo,
        stability=measure_stability(frames),
        face_score=face,
        motion_intensity=measure_motion_intensity(frames),
    )

    # --- V2.2 semantic signals ---
    if signals.expression and face > 0.0:
        q.smile_score = measure_smile_multi(frames)
    if signals.composition:
        q.composition = measure_composition_multi(frames)
    if signals.source_audio:
        q.audio_energy, q.laughter_score = analyze_source_audio(
            str(shot.source.path), shot.start_sec, shot.end_sec
        )
    if signals.camera_motion:
        shot.camera_motion = classify_camera_motion(frames)
    if signals.color_continuity:
        shot.color_temp = measure_color_temp_multi(frames)
    if signals.dedup:
        shot.phash = compute_phash(mid_frame)

    return q


def score_photo(shot: Shot, signals: SignalsConfig | None = None) -> QualityScores:
    """Compute quality scores for a photo and populate its V2.2 signals."""
    signals = signals or SignalsConfig()
    path = shot.source.proxy_path or shot.source.path
    frame = cv2.imread(str(path))
    if frame is None:
        logger.warning("Cannot read photo: %s", path)
        return QualityScores()

    q = QualityScores(
        sharpness=measure_sharpness(frame),
        exposure=measure_exposure(frame),
        stability=1.0,  # Photos are perfectly stable
        face_score=detect_faces(frame),
        motion_intensity=0.0,
    )
    if signals.expression and q.face_score > 0.0:
        q.smile_score = measure_smile(frame)
    if signals.composition:
        q.composition = measure_composition(frame)
    # Photos have no source audio and no camera motion.
    if signals.color_continuity:
        from roughcut.analyze.color import measure_color_temp
        shot.color_temp = measure_color_temp(frame)
    if signals.dedup:
        shot.phash = compute_phash(frame)

    return q
