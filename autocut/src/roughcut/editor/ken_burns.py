"""Ken Burns effect (pan/zoom) for photos."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import cv2
import numpy as np

from roughcut.analyze.expression import _FACE
from roughcut.constants import KEN_BURNS_PAN_RANGE, KEN_BURNS_ZOOM_RANGE

logger = logging.getLogger(__name__)


@dataclass
class KenBurnsParams:
    """Parameters for a Ken Burns pan/zoom animation."""

    start_zoom: float   # e.g. 1.0
    end_zoom: float     # e.g. 1.15
    start_x: float      # pan offset fraction (-0.05 to 0.05)
    start_y: float
    end_x: float
    end_y: float
    duration: float

    def ffmpeg_filter(self, width: int, height: int) -> str:
        """Generate an FFmpeg zoompan filter string."""
        fps = 30
        total_frames = int(self.duration * fps)
        # zoompan filter: zoom from start_zoom to end_zoom, pan from start to end
        z_start = self.start_zoom
        z_end = self.end_zoom
        # x/y are pixel offsets; compute from fraction
        x_start = int(width * (0.5 + self.start_x) - width / (2 * z_start))
        y_start = int(height * (0.5 + self.start_y) - height / (2 * z_start))
        x_end = int(width * (0.5 + self.end_x) - width / (2 * z_end))
        y_end = int(height * (0.5 + self.end_y) - height / (2 * z_end))

        return (
            f"zoompan=z='if(eq(on,1),{z_start},{z_start}+(({z_end}-{z_start})/{total_frames})*on)'"
            f":x='if(eq(on,1),{x_start},{x_start}+(({x_end}-{x_start})/{total_frames})*on)'"
            f":y='if(eq(on,1),{y_start},{y_start}+(({y_end}-{y_start})/{total_frames})*on)'"
            f":d={total_frames}:s={width}x{height}:fps={fps}"
        )


def random_ken_burns(duration: float, seed: int | None = None) -> KenBurnsParams:
    """Generate random Ken Burns parameters.

    Creates a gentle zoom-in or zoom-out with slight pan.
    """
    if seed is not None:
        random.seed(seed)

    zoom_min, zoom_max = KEN_BURNS_ZOOM_RANGE
    pan_range = KEN_BURNS_PAN_RANGE

    # Randomly choose zoom direction
    if random.random() > 0.5:
        start_zoom = zoom_min
        end_zoom = zoom_min + random.uniform(0.05, zoom_max - zoom_min)
    else:
        start_zoom = zoom_min + random.uniform(0.05, zoom_max - zoom_min)
        end_zoom = zoom_min

    return KenBurnsParams(
        start_zoom=start_zoom,
        end_zoom=end_zoom,
        start_x=random.uniform(-pan_range, pan_range),
        start_y=random.uniform(-pan_range, pan_range),
        end_x=random.uniform(-pan_range, pan_range),
        end_y=random.uniform(-pan_range, pan_range),
        duration=duration,
    )


def _subject_offset(image_path: str) -> tuple[float, float] | None:
    """Return the subject's normalized offset from centre (fraction), or None.

    Uses the largest face if present, otherwise the gradient-saliency centroid.
    """
    img = cv2.imread(str(image_path))
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    faces = _FACE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    if len(faces) > 0:
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        cx = (fx + fw / 2.0) / w - 0.5
        cy = (fy + fh / 2.0) / h - 0.5
        return cx, cy

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    total = mag.sum()
    if total <= 1e-6:
        return None
    ys, xs = np.mgrid[0:h, 0:w]
    cx = float((mag * xs).sum() / total) / w - 0.5
    cy = float((mag * ys).sum() / total) / h - 0.5
    return cx, cy


def subject_aware_ken_burns(
    image_path: str, duration: float, seed: int | None = None
) -> KenBurnsParams:
    """Ken Burns that gently pushes in toward the photo's subject.

    Falls back to :func:`random_ken_burns` when no subject can be located, so
    behaviour is unchanged for images where detection fails.
    """
    offset = _subject_offset(image_path)
    if offset is None:
        return random_ken_burns(duration, seed)

    if seed is not None:
        random.seed(seed)
    zoom_min, zoom_max = KEN_BURNS_ZOOM_RANGE
    pan_range = KEN_BURNS_PAN_RANGE

    ox, oy = offset
    # Clamp the target into the safe pan range and end on the subject.
    end_x = max(-pan_range, min(pan_range, ox))
    end_y = max(-pan_range, min(pan_range, oy))
    # Start slightly wider and off the subject, push in toward it.
    start_zoom = zoom_min
    end_zoom = zoom_min + max(0.06, (zoom_max - zoom_min) * 0.8)

    return KenBurnsParams(
        start_zoom=start_zoom,
        end_zoom=end_zoom,
        start_x=-end_x * 0.5,
        start_y=-end_y * 0.5,
        end_x=end_x,
        end_y=end_y,
        duration=duration,
    )
