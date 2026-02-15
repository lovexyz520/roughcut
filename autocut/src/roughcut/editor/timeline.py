"""Timeline assembly with transitions."""

from __future__ import annotations

import logging

from roughcut.models import TimelineClip, TransitionType

logger = logging.getLogger(__name__)


class Timeline:
    """Manages the assembled video timeline."""

    def __init__(self, clips: list[TimelineClip] | None = None):
        self.clips: list[TimelineClip] = clips or []

    @property
    def duration(self) -> float:
        if not self.clips:
            return 0.0
        return max(c.timeline_end for c in self.clips)

    @property
    def video_clips(self) -> list[TimelineClip]:
        return [c for c in self.clips if c.shot.source.is_video]

    @property
    def photo_clips(self) -> list[TimelineClip]:
        return [c for c in self.clips if c.shot.source.is_photo]

    def add_clip(self, clip: TimelineClip) -> None:
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.timeline_start)

    def get_chapters(self) -> dict[str, list[TimelineClip]]:
        """Group clips by chapter."""
        chapters: dict[str, list[TimelineClip]] = {}
        for clip in self.clips:
            chapters.setdefault(clip.chapter, []).append(clip)
        return chapters

    def validate(self) -> list[str]:
        """Check for timeline issues (gaps, overlaps)."""
        issues = []
        for i in range(1, len(self.clips)):
            prev = self.clips[i - 1]
            curr = self.clips[i]
            gap = curr.timeline_start - prev.timeline_end
            if gap > 0.1:
                issues.append(
                    f"Gap of {gap:.2f}s between clip {i-1} and {i}"
                )
            if gap < -0.1:
                issues.append(
                    f"Overlap of {-gap:.2f}s between clip {i-1} and {i}"
                )
        return issues

    def summary(self) -> dict:
        chapters = self.get_chapters()
        return {
            "total_clips": len(self.clips),
            "total_duration": self.duration,
            "video_clips": len(self.video_clips),
            "photo_clips": len(self.photo_clips),
            "chapters": {
                name: {
                    "clips": len(clips),
                    "duration": sum(c.timeline_duration for c in clips),
                }
                for name, clips in chapters.items()
            },
        }


def build_timeline(clips: list[TimelineClip]) -> Timeline:
    """Build and validate a timeline from planned clips."""
    tl = Timeline(clips)
    issues = tl.validate()
    for issue in issues:
        logger.warning("Timeline issue: %s", issue)
    logger.info("Timeline built: %s", tl.summary())
    return tl
