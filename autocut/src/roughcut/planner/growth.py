"""Growth (child development) video template planner."""

from __future__ import annotations

from roughcut.models import Chapter, Shot
from roughcut.planner.base import TemplatePlanner


class GrowthPlanner(TemplatePlanner):
    """Template for child growth/development videos.

    Chapters:
    1. Opening (10%): Warm intro, name/date feel
    2. Learning (45%): Practice, focus, classes
    3. Highlights (30%): Smiles, achievements, parent-child interaction
    4. Closing (15%): Ending moments, photo review
    """

    def chapters(self) -> list[Chapter]:
        return [
            Chapter("opening", 0.10, "Warm intro and context setting"),
            Chapter("learning", 0.45, "Learning process, practice, focused moments"),
            Chapter("highlights", 0.30, "Smiles, achievements, interactions"),
            Chapter("closing", 0.15, "Ending moments and photo review"),
        ]

    def chapter_emotion_ranges(self) -> dict[str, tuple[float, float]]:
        return {
            "opening": (0.0, 0.35),
            "learning": (0.25, 0.65),
            "highlights": (0.55, 1.0),
            "closing": (0.1, 0.4),
        }

    def score_weights(self) -> dict[str, float]:
        return {
            "quality": 0.20,
            "face": 0.25,    # Face/emotion is most important
            "motion": 0.10,
            "story_fit": 0.15,
            "rhythm_fit": 0.15,
            "section_fit": 0.15,
        }

    def story_fit(self, shot: Shot, chapter: Chapter) -> float:
        """Evaluate story fit for growth video chapters."""
        q = shot.quality

        if chapter.name == "opening":
            # Prefer stable, well-exposed shots with faces
            return (q.stability * 0.4 + q.face_score * 0.4 + q.exposure * 0.2)

        if chapter.name == "learning":
            # Prefer focused/stable shots, moderate motion
            return (q.stability * 0.3 + q.sharpness * 0.3 + q.motion_intensity * 0.2 + q.face_score * 0.2)

        if chapter.name == "highlights":
            # Prefer high face score and dynamic moments
            return (q.face_score * 0.5 + q.motion_intensity * 0.3 + q.sharpness * 0.2)

        if chapter.name == "closing":
            # Prefer calm, stable shots; photos are good here
            if shot.source.is_photo:
                return 0.8
            return (q.stability * 0.4 + q.exposure * 0.3 + q.face_score * 0.3)

        return 0.5
