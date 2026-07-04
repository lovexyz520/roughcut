"""Shot role classification: establishing, action, reaction, detail."""

from __future__ import annotations

import logging
from enum import Enum

from roughcut.models import Shot

logger = logging.getLogger(__name__)


class ShotRole(str, Enum):
    ESTABLISHING = "establishing"  # Wide/landscape, context-setting
    ACTION = "action"              # Dynamic motion, activity
    REACTION = "reaction"          # Face-heavy, emotional response
    DETAIL = "detail"              # Close-up, static, focused object


def classify_shot_role(shot: Shot) -> ShotRole:
    """Classify a shot's narrative role based on quality metrics.

    Heuristics:
    - establishing: wide aspect, low face, moderate quality
    - action: high motion intensity
    - reaction: high face score, low-moderate motion
    - detail: low motion, low face, high sharpness (close-up of object)
    """
    q = shot.quality
    source = shot.source

    # Aspect ratio hint: wider = more likely establishing
    is_wide = source.width > source.height if source.width and source.height else True

    # Score each role
    scores = {
        ShotRole.ESTABLISHING: 0.0,
        ShotRole.ACTION: 0.0,
        ShotRole.REACTION: 0.0,
        ShotRole.DETAIL: 0.0,
    }

    # Establishing: wide, low face, decent exposure
    if is_wide:
        scores[ShotRole.ESTABLISHING] += 0.3
    if q.face_score < 0.2:
        scores[ShotRole.ESTABLISHING] += 0.3
    scores[ShotRole.ESTABLISHING] += q.exposure * 0.2
    scores[ShotRole.ESTABLISHING] += (1.0 - q.motion_intensity) * 0.2

    # Action: high motion, and dynamic camera moves (pan/shake) reinforce it
    scores[ShotRole.ACTION] += q.motion_intensity * 0.5
    if q.motion_intensity > 0.4:
        scores[ShotRole.ACTION] += 0.2
    scores[ShotRole.ACTION] += (1.0 - q.stability) * 0.15  # Unstable = action
    if shot.camera_motion in ("pan", "tilt", "shake"):
        scores[ShotRole.ACTION] += 0.15

    # Reaction: face-heavy (real smile counts double), lower motion, static camera
    scores[ShotRole.REACTION] += q.face_score * 0.45
    scores[ShotRole.REACTION] += q.smile_score * 0.25
    if q.face_score > 0.3:
        scores[ShotRole.REACTION] += 0.15
    scores[ShotRole.REACTION] += (1.0 - q.motion_intensity) * 0.15

    # Detail: sharp, static, no face
    scores[ShotRole.DETAIL] += q.sharpness * 0.3
    scores[ShotRole.DETAIL] += (1.0 - q.motion_intensity) * 0.3
    scores[ShotRole.DETAIL] += (1.0 - q.face_score) * 0.2
    scores[ShotRole.DETAIL] += q.stability * 0.2
    if shot.camera_motion == "zoom":
        scores[ShotRole.DETAIL] += 0.1  # slow push-in reads as a detail beat

    # Photos are often detail or establishing
    if source.is_photo:
        scores[ShotRole.DETAIL] += 0.15
        scores[ShotRole.ESTABLISHING] += 0.1

    return max(scores, key=scores.get)


def assign_roles(shots: list[Shot]) -> dict[str, ShotRole]:
    """Classify all shots and return a mapping of shot key -> role.

    Also logs role distribution.
    """
    role_map: dict[str, ShotRole] = {}
    counts: dict[ShotRole, int] = {r: 0 for r in ShotRole}

    for shot in shots:
        key = f"{shot.source.path}:{shot.start_sec}"
        role = classify_shot_role(shot)
        role_map[key] = role
        counts[role] += 1

    logger.info(
        "Shot roles: %s",
        ", ".join(f"{r.value}={c}" for r, c in counts.items()),
    )
    return role_map
