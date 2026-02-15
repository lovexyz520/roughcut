"""Human Preference Learning: lightweight user profile from favorites/exclude signals."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from roughcut.models import Shot

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """Lightweight user preference weights learned from favorites/exclude."""

    # Preference bias for each dimension (0 = neutral, positive = prefer more)
    face_bias: float = 0.0
    motion_bias: float = 0.0
    stability_bias: float = 0.0
    sharpness_bias: float = 0.0
    # Role preferences (positive = prefer, negative = avoid)
    role_bias: dict[str, float] = field(default_factory=dict)
    # Event preferences
    preferred_events: list[int] = field(default_factory=list)
    avoided_events: list[int] = field(default_factory=list)
    # Source type preference (video vs photo ratio shift)
    photo_bias: float = 0.0  # positive = prefer more photos
    # Number of samples used to build this profile
    sample_count: int = 0

    def score_adjustment(self, shot: Shot) -> float:
        """Compute a score adjustment for a shot based on user preferences."""
        if self.sample_count == 0:
            return 0.0

        adj = 0.0
        q = shot.quality

        # Quality dimension biases
        adj += self.face_bias * q.face_score
        adj += self.motion_bias * q.motion_intensity
        adj += self.stability_bias * q.stability
        adj += self.sharpness_bias * q.sharpness

        # Role bias
        role = shot.shot_role or ""
        if role in self.role_bias:
            adj += self.role_bias[role]

        # Event preference
        if shot.event_id in self.preferred_events:
            adj += 0.15
        if shot.event_id in self.avoided_events:
            adj -= 0.20

        # Photo preference
        if shot.source.is_photo:
            adj += self.photo_bias

        return adj

    def to_dict(self) -> dict:
        return {
            "face_bias": round(self.face_bias, 4),
            "motion_bias": round(self.motion_bias, 4),
            "stability_bias": round(self.stability_bias, 4),
            "sharpness_bias": round(self.sharpness_bias, 4),
            "role_bias": {k: round(v, 4) for k, v in self.role_bias.items()},
            "preferred_events": self.preferred_events,
            "avoided_events": self.avoided_events,
            "photo_bias": round(self.photo_bias, 4),
            "sample_count": self.sample_count,
        }


def learn_preferences(
    all_shots: list[Shot],
    favorite_shots: list[Shot],
    excluded_shots: list[Shot],
) -> UserProfile:
    """Build a user preference profile from favorites and excludes.

    Compares the quality distribution of favorite/excluded shots against
    the overall pool to derive preference biases.
    """
    profile = UserProfile()

    if not favorite_shots and not excluded_shots:
        return profile

    profile.sample_count = len(favorite_shots) + len(excluded_shots)

    # Compute pool averages
    if not all_shots:
        return profile

    pool_avg = _avg_qualities(all_shots)
    fav_avg = _avg_qualities(favorite_shots) if favorite_shots else pool_avg
    exc_avg = _avg_qualities(excluded_shots) if excluded_shots else pool_avg

    # Bias = (favorite_avg - pool_avg) - (exclude_avg - pool_avg)
    # Simplified: bias = favorite_avg - exclude_avg (relative preference)
    if favorite_shots and excluded_shots:
        profile.face_bias = (fav_avg["face"] - exc_avg["face"]) * 0.5
        profile.motion_bias = (fav_avg["motion"] - exc_avg["motion"]) * 0.5
        profile.stability_bias = (fav_avg["stability"] - exc_avg["stability"]) * 0.5
        profile.sharpness_bias = (fav_avg["sharpness"] - exc_avg["sharpness"]) * 0.5
    elif favorite_shots:
        profile.face_bias = (fav_avg["face"] - pool_avg["face"]) * 0.5
        profile.motion_bias = (fav_avg["motion"] - pool_avg["motion"]) * 0.5
        profile.stability_bias = (fav_avg["stability"] - pool_avg["stability"]) * 0.5
        profile.sharpness_bias = (fav_avg["sharpness"] - pool_avg["sharpness"]) * 0.5
    elif excluded_shots:
        profile.face_bias = (pool_avg["face"] - exc_avg["face"]) * 0.5
        profile.motion_bias = (pool_avg["motion"] - exc_avg["motion"]) * 0.5
        profile.stability_bias = (pool_avg["stability"] - exc_avg["stability"]) * 0.5
        profile.sharpness_bias = (pool_avg["sharpness"] - exc_avg["sharpness"]) * 0.5

    # Role bias from favorites
    if favorite_shots:
        fav_roles = _count_roles(favorite_shots)
        pool_roles = _count_roles(all_shots)
        for role, count in fav_roles.items():
            fav_rate = count / len(favorite_shots)
            pool_rate = pool_roles.get(role, 0) / len(all_shots)
            profile.role_bias[role] = (fav_rate - pool_rate) * 0.3

    # Event preferences
    fav_events = {s.event_id for s in favorite_shots if s.event_id >= 0}
    exc_events = {s.event_id for s in excluded_shots if s.event_id >= 0}
    profile.preferred_events = sorted(fav_events)
    profile.avoided_events = sorted(exc_events)

    # Photo bias
    fav_photo_rate = sum(1 for s in favorite_shots if s.source.is_photo) / max(len(favorite_shots), 1)
    pool_photo_rate = sum(1 for s in all_shots if s.source.is_photo) / max(len(all_shots), 1)
    profile.photo_bias = (fav_photo_rate - pool_photo_rate) * 0.3

    logger.info(
        "Learned preferences from %d samples (face=%.3f, motion=%.3f, stability=%.3f)",
        profile.sample_count, profile.face_bias, profile.motion_bias, profile.stability_bias,
    )
    return profile


def save_user_profile(profile: UserProfile, output_path: Path) -> Path:
    """Save user profile to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info("User profile saved: %s", output_path)
    return output_path


def load_user_profile(path: Path) -> UserProfile | None:
    """Load a previously saved user profile."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        profile = UserProfile(
            face_bias=data.get("face_bias", 0.0),
            motion_bias=data.get("motion_bias", 0.0),
            stability_bias=data.get("stability_bias", 0.0),
            sharpness_bias=data.get("sharpness_bias", 0.0),
            role_bias=data.get("role_bias", {}),
            preferred_events=data.get("preferred_events", []),
            avoided_events=data.get("avoided_events", []),
            photo_bias=data.get("photo_bias", 0.0),
            sample_count=data.get("sample_count", 0),
        )
        logger.info("Loaded user profile: %d samples", profile.sample_count)
        return profile
    except Exception as e:
        logger.warning("Failed to load user profile: %s", e)
        return None


def _avg_qualities(shots: list[Shot]) -> dict[str, float]:
    """Compute average quality metrics for a list of shots."""
    if not shots:
        return {"face": 0.0, "motion": 0.0, "stability": 0.0, "sharpness": 0.0}
    n = len(shots)
    return {
        "face": sum(s.quality.face_score for s in shots) / n,
        "motion": sum(s.quality.motion_intensity for s in shots) / n,
        "stability": sum(s.quality.stability for s in shots) / n,
        "sharpness": sum(s.quality.sharpness for s in shots) / n,
    }


def _count_roles(shots: list[Shot]) -> dict[str, int]:
    """Count shot role occurrences."""
    counts: dict[str, int] = {}
    for s in shots:
        role = s.shot_role or "unknown"
        counts[role] = counts.get(role, 0) + 1
    return counts
