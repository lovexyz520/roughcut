"""Base template class for story-driven clip selection."""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod

from roughcut.models import (
    BeatInfo,
    Chapter,
    ProjectConfig,
    QualityScores,
    Shot,
    TimelineClip,
    TransitionType,
)

logger = logging.getLogger(__name__)


class TemplatePlanner(ABC):
    """Abstract base class for story template planners."""

    def __init__(self, config: ProjectConfig, beat_info: BeatInfo | None = None):
        self.config = config
        self.beat_info = beat_info
        if config.seed is not None:
            random.seed(config.seed)

    @abstractmethod
    def chapters(self) -> list[Chapter]:
        """Return the chapter structure for this template."""
        ...

    @abstractmethod
    def score_weights(self) -> dict[str, float]:
        """Return scoring weights: quality, face, motion, story_fit, rhythm_fit."""
        ...

    def compute_score(
        self,
        shot: Shot,
        chapter: Chapter,
        timeline_position: float,
    ) -> float:
        """Compute total score for a shot in a given chapter context.

        total = w1*quality + w2*face + w3*motion + w4*story_fit
                + w5*rhythm_fit + w6*section_fit - penalties
        """
        w = self.score_weights()
        q = shot.quality

        quality_score = (q.sharpness + q.exposure + q.stability) / 3.0
        story_fit = self.story_fit(shot, chapter)
        rhythm_fit = self.rhythm_fit(timeline_position)
        sec_fit = self.section_fit(shot, timeline_position)

        total = (
            w.get("quality", 0.25) * quality_score
            + w.get("face", 0.15) * q.face_score
            + w.get("motion", 0.10) * q.motion_intensity
            + w.get("story_fit", 0.20) * story_fit
            + w.get("rhythm_fit", 0.15) * rhythm_fit
            + w.get("section_fit", 0.15) * sec_fit
        )

        # Penalties
        penalties = 0.0
        if q.exposure < 0.3:
            penalties += 0.2  # Too dark/bright
        if q.sharpness < 0.2:
            penalties += 0.15  # Too blurry
        if q.stability < 0.3:
            penalties += 0.1  # Too shaky

        return max(0.0, total - penalties)

    def story_fit(self, shot: Shot, chapter: Chapter) -> float:
        """Evaluate how well a shot fits a chapter. Override in subclasses."""
        return 0.5

    def section_fit(self, shot: Shot, timeline_position: float) -> float:
        """Score how well a shot matches the current music section's mood.

        chorus -> prefer dynamic/action shots
        verse  -> prefer calm/establishing/detail shots
        bridge -> neutral
        """
        if not self.beat_info or not self.beat_info.sections:
            return 0.5

        section = self.beat_info.section_at(timeline_position)
        if section is None:
            return 0.5

        q = shot.quality
        role = shot.shot_role or ""

        if section.label == "chorus":
            # Prefer high motion, action shots
            score = q.motion_intensity * 0.5 + (1.0 - q.stability) * 0.2
            if role == "action":
                score += 0.3
            elif role == "reaction":
                score += 0.1
            return min(1.0, score)

        elif section.label == "verse":
            # Prefer calm, establishing, detail shots
            score = q.stability * 0.3 + q.sharpness * 0.2
            if role in ("establishing", "detail"):
                score += 0.3
            elif role == "reaction":
                score += 0.2
            return min(1.0, score)

        elif section.label in ("intro", "outro"):
            # Prefer establishing shots for intro, calm for outro
            if section.label == "intro" and role == "establishing":
                return 0.8
            if section.label == "outro" and role in ("detail", "establishing"):
                return 0.8
            return 0.5

        # bridge — neutral
        return 0.5

    def rhythm_fit(self, timeline_position: float) -> float:
        """Score how well a position aligns with music beats."""
        if not self.beat_info or not self.beat_info.beat_times:
            return 0.5

        beats = self.beat_info.beat_times
        tolerance = self.config.rhythm.tolerance_ms / 1000.0

        # Find closest beat
        min_dist = float("inf")
        for bt in beats:
            dist = abs(timeline_position - bt)
            if dist < min_dist:
                min_dist = dist

        if min_dist <= tolerance:
            return 1.0
        elif min_dist <= tolerance * 3:
            return 0.7
        return 0.3

    def music_energy_at(self, position: float) -> float:
        """Get the music energy level at a timeline position (0-1)."""
        if not self.beat_info:
            return 0.5
        return self.beat_info.energy_at(position)

    def snap_to_beat(self, position: float) -> float:
        """Snap a timeline position to the nearest beat if within tolerance."""
        if not self.config.rhythm.snap_to_beat:
            return position
        if not self.beat_info or not self.beat_info.beat_times:
            return position

        tolerance = self.config.rhythm.tolerance_ms / 1000.0
        closest = min(
            self.beat_info.beat_times,
            key=lambda bt: abs(bt - position),
            default=position,
        )
        if abs(closest - position) <= tolerance:
            return closest
        return position

    def is_high_energy(self, position: float) -> bool:
        """Check if a timeline position falls in a high-energy music segment."""
        if not self.beat_info:
            return False
        for start, end in self.beat_info.high_energy_ranges:
            if start <= position <= end:
                return True
        return False

    def plan(self, shots: list[Shot]) -> list[TimelineClip]:
        """Select and arrange shots into a timeline.

        Args:
            shots: All available shots (already scored).

        Returns:
            Ordered list of TimelineClips.
        """
        target = self.config.target_duration_sec
        chapters = self.chapters()
        div = self.config.diversity
        timeline: list[TimelineClip] = []
        current_time = 0.0
        used_sources: set[str] = set()

        # Separate video and photo shots
        video_shots = [s for s in shots if s.source.is_video]
        photo_shots = [s for s in shots if s.source.is_photo]

        # Target ratio — compute budgets
        v_ratio = self.config.video_photo_ratio[0]
        p_ratio = self.config.video_photo_ratio[1]
        total_ratio = v_ratio + p_ratio
        video_budget = target * v_ratio / total_ratio
        photo_budget = target * p_ratio / total_ratio

        # Track accumulated durations per type
        video_used = 0.0
        photo_used = 0.0

        # Event coverage tracking
        all_event_ids = {s.event_id for s in shots if s.event_id >= 0}
        used_event_ids: set[int] = set()
        global_source_usage: dict[str, int] = {}  # source_path -> times used

        for chapter in chapters:
            chapter_duration = target * chapter.ratio
            chapter_end = current_time + chapter_duration

            # Chapter-level budgets proportional to global ratio
            ch_video_budget = chapter_duration * v_ratio / total_ratio
            ch_photo_budget = chapter_duration * p_ratio / total_ratio
            ch_video_used = 0.0
            ch_photo_used = 0.0

            # Per-chapter tracking
            chapter_source_files: set[str] = set()  # source paths used in this chapter

            # Score video and photo shots separately for this chapter
            scored_video = sorted(
                [(self.compute_score(s, chapter, current_time), s) for s in video_shots],
                key=lambda x: x[0], reverse=True,
            )
            scored_photo = sorted(
                [(self.compute_score(s, chapter, current_time), s) for s in photo_shots],
                key=lambda x: x[0], reverse=True,
            )

            # Interleave: pick from whichever pool is more under-budget
            vi, pi = 0, 0
            same_event_streak = 0.0
            last_source_path = ""
            last_event_id = -1
            consecutive_same_event = 0
            consecutive_same_source = 0
            last_role = ""
            consecutive_same_role = 0
            chapter_roles: dict[str, int] = {}  # role -> count

            while current_time < chapter_end:
                # Decide which pool to pick from based on ratio fulfillment
                video_fill = ch_video_used / ch_video_budget if ch_video_budget > 0 else 1.0
                photo_fill = ch_photo_used / ch_photo_budget if ch_photo_budget > 0 else 1.0

                # Event coverage boost: if we're underusing events, prefer unused ones
                coverage = len(used_event_ids) / len(all_event_ids) if all_event_ids else 1.0
                needs_coverage = coverage < div.min_event_coverage

                # Try the under-filled pool first, fall back to the other
                if video_fill <= photo_fill:
                    pools = [(scored_video, vi, "video"), (scored_photo, pi, "photo")]
                else:
                    pools = [(scored_photo, pi, "photo"), (scored_video, vi, "video")]

                placed = False
                for pool, idx_ref, pool_type in pools:
                    # Find next usable shot in this pool
                    start_idx = vi if pool_type == "video" else pi
                    for j in range(start_idx, len(pool)):
                        score, shot = pool[j]

                        source_key = f"{shot.source.path}:{shot.start_sec}"
                        if source_key in used_sources:
                            continue

                        remaining = chapter_end - current_time
                        # Adjust max clip duration by music energy:
                        # high energy → shorter clips (more cuts), low → longer
                        energy = self.music_energy_at(current_time)
                        energy_max = self.config.clip_duration_sec.max
                        if energy > 0.7:
                            energy_max *= 0.6  # Faster cuts in high energy
                        elif energy > 0.5:
                            energy_max *= 0.8

                        clip_dur = min(
                            shot.duration_sec,
                            energy_max,
                            remaining,
                        )
                        clip_dur = max(clip_dur, self.config.clip_duration_sec.min)
                        if clip_dur > remaining:
                            continue

                        # === Diversity checks (using config) ===
                        source_path = str(shot.source.path)

                        # Same-source consecutive limit
                        if source_path == last_source_path:
                            consecutive_same_source += 1
                            if consecutive_same_source >= div.max_consecutive_same_source:
                                continue
                        else:
                            consecutive_same_source = 0

                        # Same-source streak (time-based)
                        if source_path == last_source_path:
                            same_event_streak += clip_dur
                            if same_event_streak > self.config.max_same_event_streak_sec:
                                continue
                        else:
                            same_event_streak = clip_dur

                        # Event continuity limit
                        if shot.event_id == last_event_id:
                            consecutive_same_event += 1
                            if consecutive_same_event >= div.max_consecutive_same_event:
                                continue
                        else:
                            consecutive_same_event = 0

                        # Role diversity limit
                        shot_role = shot.shot_role or "unknown"
                        if shot_role == last_role:
                            consecutive_same_role += 1
                            if consecutive_same_role >= div.max_consecutive_same_role:
                                continue
                        else:
                            consecutive_same_role = 0

                        # === Diversity score adjustments ===
                        adjusted_score = score

                        # Penalty: same source file used again globally
                        src_uses = global_source_usage.get(source_path, 0)
                        if src_uses > 0:
                            adjusted_score -= div.same_source_penalty * src_uses

                        # Penalty: same source file used in this chapter
                        if source_path in chapter_source_files:
                            adjusted_score -= div.chapter_repeat_penalty

                        # Penalty: same role as last clip (angle similarity)
                        if shot_role == last_role:
                            adjusted_score -= div.same_angle_penalty

                        # Boost: unused event (coverage enforcement)
                        if needs_coverage and shot.event_id not in used_event_ids:
                            adjusted_score += 0.15  # Bonus for new event

                        # Skip if adjusted score too low
                        if adjusted_score < 0.05:
                            continue

                        # Prefer dynamic shots during high-energy music
                        if self.is_high_energy(current_time) and shot.source.is_video:
                            if shot.quality.motion_intensity < 0.3:
                                continue

                        # Snap to beat
                        snapped_start = self.snap_to_beat(current_time)
                        if snapped_start > current_time:
                            current_time = snapped_start

                        in_point = shot.start_sec
                        out_point = min(shot.start_sec + clip_dur, shot.end_sec)
                        actual_dur = out_point - in_point

                        clip = TimelineClip(
                            shot=shot,
                            timeline_start=current_time,
                            timeline_end=current_time + actual_dur,
                            in_point=in_point,
                            out_point=out_point,
                            chapter=chapter.name,
                            selection_reason=f"score={adjusted_score:.3f}",
                            total_score=adjusted_score,
                        )
                        timeline.append(clip)
                        used_sources.add(source_key)
                        current_time = clip.timeline_end
                        last_event_id = shot.event_id
                        last_source_path = source_path
                        last_role = shot_role
                        chapter_roles[shot_role] = chapter_roles.get(shot_role, 0) + 1
                        used_event_ids.add(shot.event_id)
                        global_source_usage[source_path] = src_uses + 1
                        chapter_source_files.add(source_path)

                        # Track ratio
                        if pool_type == "video":
                            ch_video_used += actual_dur
                            video_used += actual_dur
                            vi = j + 1
                        else:
                            ch_photo_used += actual_dur
                            photo_used += actual_dur
                            pi = j + 1

                        placed = True
                        break

                    if placed:
                        break

                if not placed:
                    # No more usable shots for this chapter
                    break

        # Add transitions between chapters
        self._add_transitions(timeline, chapters)

        actual_total = current_time
        event_coverage = len(used_event_ids) / len(all_event_ids) if all_event_ids else 0
        logger.info(
            "Planned %d clips, total duration=%.1fs (target=%ds), "
            "video=%.1fs (%.0f%%), photo=%.1fs (%.0f%%)",
            len(timeline), actual_total, target,
            video_used, video_used / actual_total * 100 if actual_total else 0,
            photo_used, photo_used / actual_total * 100 if actual_total else 0,
        )
        logger.info(
            "Diversity: %d/%d events covered (%.0f%%), %d unique sources",
            len(used_event_ids), len(all_event_ids),
            event_coverage * 100,
            len(global_source_usage),
        )
        return timeline

    def _add_transitions(
        self, timeline: list[TimelineClip], chapters: list[Chapter]
    ) -> None:
        """Add fade transitions at chapter boundaries."""
        if len(timeline) < 2:
            return

        chapter_names = [c.name for c in chapters]
        for i in range(1, len(timeline)):
            prev_chapter = timeline[i - 1].chapter
            curr_chapter = timeline[i].chapter
            if prev_chapter != curr_chapter:
                timeline[i - 1].transition_out = TransitionType.FADE_OUT
                timeline[i].transition_in = TransitionType.FADE_IN
                timeline[i - 1].transition_duration = 0.5
                timeline[i].transition_duration = 0.5
