"""Composition / aesthetic scoring.

"Visual feel" comes largely from framing, which the old quality metrics never
measured (a tack-sharp, well-exposed but dead-centre or beheaded shot scored the
same as a beautifully framed one). This module rewards rule-of-thirds subject
placement, proper headroom for faces, and a level horizon.
"""

from __future__ import annotations

import cv2
import numpy as np

from roughcut.analyze.expression import _FACE

# Rule-of-thirds lines (normalized).
_THIRDS = (1.0 / 3.0, 2.0 / 3.0)


def _thirds_proximity(cx: float, cy: float) -> float:
    """Reward a subject centroid (normalized 0-1) near a thirds intersection."""
    dx = min(abs(cx - t) for t in _THIRDS)
    dy = min(abs(cy - t) for t in _THIRDS)
    # Distance to nearest thirds *line* on each axis; 0 = on a line.
    dist = np.hypot(dx, dy)
    return float(np.clip(1.0 - dist / 0.35, 0.0, 1.0))


def _headroom_score(face_top: float, face_bottom: float) -> float:
    """Reward comfortable headroom: eyes/face in the upper-middle band."""
    face_mid = (face_top + face_bottom) / 2.0
    # Ideal face midpoint sits around 0.38 of frame height.
    return float(np.clip(1.0 - abs(face_mid - 0.38) / 0.45, 0.0, 1.0))


def _horizon_level(gray: np.ndarray) -> float:
    """Reward a level horizon: strong lines close to horizontal score high."""
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(80, gray.shape[1] // 8))
    if lines is None:
        return 0.6  # neutral: no dominant lines to judge
    tilts = []
    for rho_theta in lines[:20]:
        theta = float(rho_theta[0][1])
        # Near-horizontal lines have theta ~ pi/2.
        deviation = abs(theta - np.pi / 2)
        if deviation < np.radians(25):  # only consider roughly-horizontal lines
            tilts.append(deviation)
    if not tilts:
        return 0.6
    avg_tilt = float(np.mean(tilts))
    return float(np.clip(1.0 - avg_tilt / np.radians(12), 0.0, 1.0))


def measure_composition(frame: np.ndarray) -> float:
    """Return a composition score (0-1) for a single frame."""
    if frame is None or frame.size == 0:
        return 0.0
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    faces = _FACE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    if len(faces) > 0:
        # Use the largest face as the subject.
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        cx = (fx + fw / 2.0) / w
        cy = (fy + fh / 2.0) / h
        thirds = _thirds_proximity(cx, cy)
        headroom = _headroom_score(fy / h, (fy + fh) / h)
        horizon = _horizon_level(gray)
        return float(np.clip(0.45 * thirds + 0.35 * headroom + 0.20 * horizon, 0.0, 1.0))

    # No face: use gradient-saliency centroid as the "subject".
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    total = mag.sum()
    if total <= 1e-6:
        return 0.3  # flat, featureless frame
    ys, xs = np.mgrid[0:h, 0:w]
    cx = float((mag * xs).sum() / total) / w
    cy = float((mag * ys).sum() / total) / h
    thirds = _thirds_proximity(cx, cy)
    horizon = _horizon_level(gray)
    return float(np.clip(0.65 * thirds + 0.35 * horizon, 0.0, 1.0))


def measure_composition_multi(frames: list[np.ndarray]) -> float:
    """Median composition across sampled frames (robust to a stray bad frame)."""
    if not frames:
        return 0.0
    scores = [measure_composition(f) for f in frames]
    return float(np.median(scores)) if scores else 0.0
