"""Camera-movement classification: static / pan / tilt / zoom / shake.

Knowing *how* the camera moves lets the editor avoid ugly joins (two opposing
pans back-to-back), reward intentional moves, and drive Ken Burns direction on
stills. Built on Farneback dense optical flow over downscaled frames.
"""

from __future__ import annotations

import cv2
import numpy as np

# Motion thresholds (in normalized flow units, fraction of frame width per frame).
_STATIC_MAG = 0.004
_DIRECTIONAL_CONSISTENCY = 0.6   # mean/|mean|+std ratio above this = coherent move
_ZOOM_DIVERGENCE = 0.010
_SHAKE_MAG = 0.010


def _downscale_gray(frame: np.ndarray, width: int = 160) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = width / max(w, 1)
    small = cv2.resize(frame, (width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def classify_camera_motion(frames: list[np.ndarray]) -> str:
    """Classify the dominant camera movement across a sequence of frames."""
    if len(frames) < 2:
        return "static"

    grays = [_downscale_gray(f) for f in frames if f is not None and f.size > 0]
    if len(grays) < 2:
        return "static"
    h, w = grays[0].shape[:2]

    mean_dx, mean_dy, div_acc, mags = [], [], [], []
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = w / 2.0, h / 2.0

    for a, b in zip(grays[:-1], grays[1:]):
        if a.shape != b.shape:
            continue
        flow = cv2.calcOpticalFlowFarneback(
            a, b, None, 0.5, 2, 15, 3, 5, 1.2, 0
        )
        fx, fy = flow[..., 0], flow[..., 1]
        mean_dx.append(float(np.mean(fx)) / w)
        mean_dy.append(float(np.mean(fy)) / w)
        mags.append(float(np.mean(np.hypot(fx, fy))) / w)
        # Radial divergence: outward flow relative to centre = zoom in.
        rx, ry = xs - cx, ys - cy
        norm = np.hypot(rx, ry) + 1e-6
        radial = (fx * rx + fy * ry) / norm
        div_acc.append(float(np.mean(radial)) / w)

    if not mags:
        return "static"

    avg_mag = float(np.mean(mags))
    if avg_mag < _STATIC_MAG:
        return "static"

    mdx, mdy = float(np.mean(mean_dx)), float(np.mean(mean_dy))
    divergence = abs(float(np.mean(div_acc)))

    # Directional coherence: how much of the motion is a single translation.
    trans_mag = np.hypot(mdx, mdy)
    coherence = trans_mag / (avg_mag + 1e-6)

    # Zoom: strong radial divergence and not dominated by translation.
    if divergence > _ZOOM_DIVERGENCE and divergence > trans_mag * 0.8:
        return "zoom"

    # Coherent translation → pan (horizontal) or tilt (vertical).
    if coherence > _DIRECTIONAL_CONSISTENCY:
        return "pan" if abs(mdx) >= abs(mdy) else "tilt"

    # Big but incoherent motion → handheld shake.
    if avg_mag > _SHAKE_MAG:
        return "shake"

    # Mild coherent-ish drift.
    return "pan" if abs(mdx) >= abs(mdy) else "tilt"


def motion_conflict(prev: str, curr: str) -> bool:
    """True if two adjacent camera motions clash (jarring to cut together).

    Opposing continuous moves (pan→pan, tilt→tilt, zoom→zoom) read worst when
    hard-cut back-to-back; a buffer or dissolve helps.
    """
    continuous = {"pan", "tilt", "zoom"}
    return prev in continuous and prev == curr
