"""Facial expression analysis: real smile detection (not just face presence).

Uses OpenCV's bundled Haar cascades — no external model download or new
dependency. A face is validated by eye detection before its lower region is
searched for a smile, which sharply reduces the false positives the raw smile
cascade is notorious for.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Module-level cascade singletons (building these per-frame was a real hotspot).
_FACE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
_EYE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
_SMILE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")


def measure_smile(frame: np.ndarray) -> float:
    """Return a smile/expression intensity score (0-1) for a single frame.

    Approach:
    - Find frontal faces.
    - For each face, require at least one eye (rejects non-face detections).
    - Search the lower half of the face for a smile.
    - Weight by face size so a big, close smiling face scores higher than a
      tiny distant one.
    """
    if frame is None or frame.size == 0:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    frame_area = float(frame.shape[0] * frame.shape[1])

    faces = _FACE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    if len(faces) == 0:
        return 0.0

    best = 0.0
    for (x, y, w, h) in faces:
        face_gray = gray[y:y + h, x:x + w]
        if face_gray.size == 0:
            continue

        # Validate the face with eye detection (upper 60%).
        eyes = _EYE.detectMultiScale(
            face_gray[: int(h * 0.6), :], scaleFactor=1.1, minNeighbors=6, minSize=(15, 15)
        )
        if len(eyes) == 0:
            continue  # Likely a false face; skip to avoid smile false positives.

        # Search the lower half of the face for a smile.
        mouth_region = face_gray[int(h * 0.55):, :]
        if mouth_region.size == 0:
            continue
        smiles = _SMILE.detectMultiScale(
            mouth_region, scaleFactor=1.7, minNeighbors=22, minSize=(int(w * 0.25), int(h * 0.12))
        )
        if len(smiles) == 0:
            continue

        # Smile strength: relative width of the widest smile within the face.
        widest = max(sw for (_sx, _sy, sw, _sh) in smiles)
        strength = min(1.0, widest / max(w * 0.9, 1.0))
        # Scale by how prominent the face is in the frame (sqrt to soften).
        face_prominence = min(1.0, np.sqrt((w * h) / frame_area) * 3.0)
        score = strength * (0.6 + 0.4 * face_prominence)
        best = max(best, score)

    return min(1.0, best)


def measure_smile_multi(frames: list[np.ndarray]) -> float:
    """Peak smile across sampled frames.

    A shot where someone breaks into a smile partway through should score on the
    smiling frame, not on a bland middle frame — so we take the max, not the mean.
    """
    if not frames:
        return 0.0
    return max((measure_smile(f) for f in frames), default=0.0)
