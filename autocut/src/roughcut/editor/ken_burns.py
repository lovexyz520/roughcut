"""Ken Burns effect (pan/zoom) for photos."""

from __future__ import annotations

import random
from dataclasses import dataclass

from roughcut.constants import KEN_BURNS_PAN_RANGE, KEN_BURNS_ZOOM_RANGE


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
