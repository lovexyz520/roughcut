"""Travel (family trip) video template planner."""

from __future__ import annotations

from roughcut.models import Chapter, Shot
from roughcut.planner.base import TemplatePlanner


class TravelPlanner(TemplatePlanner):
    """Template for family travel videos.

    Chapters:
    1. Departure (15%): Transport, preparation, gathering
    2. Exploration (50%): Landmarks, activities, moving shots
    3. Interaction (25%): Group photos, play, dining
    4. Ending (10%): Sunset/nightscape, return journey
    """

    def chapters(self) -> list[Chapter]:
        return [
            Chapter("departure", 0.15, "Transport, preparation, gathering"),
            Chapter("exploration", 0.50, "Landmarks, activities, scenic shots"),
            Chapter("interaction", 0.25, "Group photos, play, dining"),
            Chapter("ending", 0.10, "Sunset, night scenes, return"),
        ]

    def chapter_emotion_ranges(self) -> dict[str, tuple[float, float]]:
        return {
            "departure": (0.1, 0.4),
            "exploration": (0.3, 0.7),
            "interaction": (0.5, 1.0),
            "ending": (0.0, 0.35),
        }

    def score_weights(self) -> dict[str, float]:
        return {
            "quality": 0.25,
            "face": 0.10,
            "motion": 0.15,    # More weight on dynamic shots
            "story_fit": 0.15,
            "rhythm_fit": 0.15,
            "section_fit": 0.20,  # Travel benefits more from section alignment
        }

    def story_fit(self, shot: Shot, chapter: Chapter) -> float:
        """Evaluate story fit for travel video chapters."""
        q = shot.quality

        if chapter.name == "departure":
            # Prefer establishing shots, moderate motion
            return (q.stability * 0.3 + q.motion_intensity * 0.3 + q.exposure * 0.2 + q.face_score * 0.2)

        if chapter.name == "exploration":
            # Prefer wide/dynamic shots, sharp scenic imagery
            score = (q.sharpness * 0.3 + q.motion_intensity * 0.3 + q.exposure * 0.2 + q.stability * 0.2)
            # Bonus for landscape-oriented shots (wider than tall)
            if shot.source.width > shot.source.height:
                score += 0.1
            return min(score, 1.0)

        if chapter.name == "interaction":
            # Prefer face-heavy, stable shots
            return (q.face_score * 0.5 + q.stability * 0.3 + q.sharpness * 0.2)

        if chapter.name == "ending":
            # Prefer calm, well-exposed shots; photos welcome
            if shot.source.is_photo:
                return 0.7
            return (q.exposure * 0.4 + q.stability * 0.3 + q.sharpness * 0.3)

        return 0.5
