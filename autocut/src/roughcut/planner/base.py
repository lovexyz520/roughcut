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
from roughcut.planner.events import (
    build_event_arc,
    get_event_shots,
    rank_events,
    summarize_events,
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

        # Highlight bonus: boost in chorus sections or chapter end zones
        highlight_bonus = 0.0
        if shot.highlight_score >= 0.5:
            highlight_bonus = shot.highlight_score * 0.1
            # Extra boost during chorus
            if self.beat_info and self.beat_info.sections:
                section = self.beat_info.section_at(timeline_position)
                if section and section.label == "chorus":
                    highlight_bonus += 0.05

        # Penalties
        penalties = 0.0
        if q.exposure < 0.3:
            penalties += 0.2  # Too dark/bright
        if q.sharpness < 0.2:
            penalties += 0.15  # Too blurry
        if q.stability < 0.3:
            penalties += 0.1  # Too shaky

        return max(0.0, total + highlight_bonus - penalties)

    def story_fit(self, shot: Shot, chapter: Chapter) -> float:
        """Evaluate how well a shot fits a chapter. Override in subclasses."""
        return 0.5

    def section_fit(self, shot: Shot, timeline_position: float) -> float:
        """Score how well a shot matches the current music section's mood.

        Section-level mapping (V3):
        - intro  → establishing, detail (scene setting)
        - verse  → learning/exploration, calm shots
        - chorus → highlights, action, high-energy moments
        - bridge → reaction, transition moments
        - outro  → closing, detail, establishing (farewell)
        """
        if not self.beat_info or not self.beat_info.sections:
            return 0.5

        section = self.beat_info.section_at(timeline_position)
        if section is None:
            return 0.5

        q = shot.quality
        role = shot.shot_role or ""
        highlight = shot.highlight_score

        if section.label == "chorus":
            # Prefer highlights, high motion, action shots
            score = q.motion_intensity * 0.3 + highlight * 0.3 + (1.0 - q.stability) * 0.1
            if role == "action":
                score += 0.3
            elif role == "reaction" and highlight >= 0.5:
                score += 0.2
            return min(1.0, score)

        elif section.label == "verse":
            # Prefer calm, learning, establishing/detail
            score = q.stability * 0.3 + q.sharpness * 0.2 + q.exposure * 0.1
            if role in ("establishing", "detail"):
                score += 0.3
            elif role == "reaction":
                score += 0.15
            return min(1.0, score)

        elif section.label == "intro":
            # Scene setting: establishing + detail
            score = q.stability * 0.3 + q.exposure * 0.2
            if role == "establishing":
                score += 0.4
            elif role == "detail":
                score += 0.3
            return min(1.0, score)

        elif section.label == "outro":
            # Closing feel: calm, stable, photos welcome
            score = q.stability * 0.3 + q.exposure * 0.2
            if shot.source.is_photo:
                score += 0.3
            if role in ("detail", "establishing"):
                score += 0.25
            return min(1.0, score)

        elif section.label == "bridge":
            # Transition: reaction, moderate energy
            score = q.stability * 0.2 + q.sharpness * 0.2
            if role == "reaction":
                score += 0.3
            elif role == "detail":
                score += 0.2
            return min(1.0, score)

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
        """Event-first planning: select events, then pick shots within each event.

        Algorithm:
        1. Rank events by quality, emotion, and variety.
        2. Allocate events to chapters based on fit.
        3. For each chapter, pick shots from allocated events using event arc.
        4. Respect diversity constraints and video/photo ratio.

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

        # Target ratio
        v_ratio = self.config.video_photo_ratio[0]
        p_ratio = self.config.video_photo_ratio[1]
        total_ratio = v_ratio + p_ratio
        video_used = 0.0
        photo_used = 0.0

        # Event ranking
        event_summaries = summarize_events(shots)
        ranked_events = rank_events(event_summaries)
        all_event_ids = {s.event_id for s in shots if s.event_id >= 0}
        used_event_ids: set[int] = set()
        global_source_usage: dict[str, int] = {}

        # Build per-event shot pools
        event_shots_map: dict[int, list[Shot]] = {}
        for s in shots:
            event_shots_map.setdefault(s.event_id, []).append(s)

        # Allocate events to chapters proportionally
        chapter_events: dict[str, list[int]] = {c.name: [] for c in chapters}
        events_per_chapter = max(1, len(ranked_events) // len(chapters))

        # Distribute top-ranked events across chapters
        assigned_events: set[int] = set()
        for ci, chapter in enumerate(chapters):
            for ei, es in enumerate(ranked_events):
                if es.event_id in assigned_events:
                    continue
                chapter_events[chapter.name].append(es.event_id)
                assigned_events.add(es.event_id)
                if len(chapter_events[chapter.name]) >= events_per_chapter:
                    break

        # Remaining unassigned events go to chapters with most duration budget
        for es in ranked_events:
            if es.event_id not in assigned_events:
                # Find chapter with most remaining capacity
                best_ch = max(chapters, key=lambda c: c.ratio)
                chapter_events[best_ch.name].append(es.event_id)
                assigned_events.add(es.event_id)

        logger.info("Event allocation: %s", {k: v for k, v in chapter_events.items()})

        # --- Fill each chapter using event-first selection ---
        for chapter in chapters:
            chapter_duration = target * chapter.ratio
            chapter_end = current_time + chapter_duration
            ch_events = chapter_events[chapter.name]

            # Build scored candidate pool from chapter's events
            ch_video_budget = chapter_duration * v_ratio / total_ratio
            ch_photo_budget = chapter_duration * p_ratio / total_ratio
            ch_video_used = 0.0
            ch_photo_used = 0.0
            chapter_source_files: set[str] = set()

            last_source_path = ""
            last_event_id = -1
            last_role = ""
            consecutive_same_source = 0
            consecutive_same_event = 0
            consecutive_same_role = 0
            same_event_streak = 0.0
            cross_event_count = 0  # Track cross-event jumps

            # Iterate through chapter's events, picking shots in arc order
            # (establishing → action → reaction → detail)
            arc_order = ["establishing", "action", "reaction", "detail"]

            # Score all candidates from this chapter's events
            ch_candidates: list[tuple[float, Shot, str]] = []  # (score, shot, arc_role)
            for eid in ch_events:
                e_shots = event_shots_map.get(eid, [])
                arc = build_event_arc(e_shots)
                for role_name in arc_order:
                    for shot in arc[role_name]:
                        score = self.compute_score(shot, chapter, current_time)
                        ch_candidates.append((score, shot, role_name))

            # Also add shots from non-assigned events (lower priority)
            for eid, e_shots in event_shots_map.items():
                if eid in ch_events:
                    continue
                for shot in e_shots:
                    score = self.compute_score(shot, chapter, current_time) * 0.7  # lower priority
                    arc_role = shot.shot_role or "detail"
                    ch_candidates.append((score, shot, arc_role))

            # Sort by score
            ch_candidates.sort(key=lambda x: x[0], reverse=True)

            for score, shot, arc_role in ch_candidates:
                if current_time >= chapter_end:
                    break

                source_key = f"{shot.source.path}:{shot.start_sec}"
                if source_key in used_sources:
                    continue

                remaining = chapter_end - current_time
                energy = self.music_energy_at(current_time)
                energy_max = self.config.clip_duration_sec.max
                if energy > 0.7:
                    energy_max *= 0.6
                elif energy > 0.5:
                    energy_max *= 0.8

                clip_dur = min(shot.duration_sec, energy_max, remaining)
                clip_dur = max(clip_dur, self.config.clip_duration_sec.min)
                if clip_dur > remaining:
                    continue

                source_path = str(shot.source.path)
                shot_role = shot.shot_role or "unknown"

                # --- Diversity checks ---
                if source_path == last_source_path:
                    consecutive_same_source += 1
                    if consecutive_same_source >= div.max_consecutive_same_source:
                        continue
                else:
                    consecutive_same_source = 0

                if source_path == last_source_path:
                    same_event_streak += clip_dur
                    if same_event_streak > self.config.max_same_event_streak_sec:
                        continue
                else:
                    same_event_streak = clip_dur

                if shot.event_id == last_event_id:
                    consecutive_same_event += 1
                    if consecutive_same_event >= div.max_consecutive_same_event:
                        continue
                else:
                    consecutive_same_event = 0
                    if last_event_id >= 0:
                        cross_event_count += 1

                if shot_role == last_role:
                    consecutive_same_role += 1
                    if consecutive_same_role >= div.max_consecutive_same_role:
                        continue
                else:
                    consecutive_same_role = 0

                # Cross-event jump rate limit (max 1 jump per 4 seconds average)
                elapsed = current_time - (current_time - chapter_duration * chapter.ratio) if timeline else 0
                if cross_event_count > 0 and elapsed > 0:
                    jump_rate = cross_event_count / max(elapsed, 1.0)
                    if jump_rate > 0.25 and shot.event_id != last_event_id:
                        continue  # Too many event jumps

                # --- Score adjustments ---
                adjusted_score = score
                src_uses = global_source_usage.get(source_path, 0)
                if src_uses > 0:
                    adjusted_score -= div.same_source_penalty * src_uses
                if source_path in chapter_source_files:
                    adjusted_score -= div.chapter_repeat_penalty
                if shot_role == last_role:
                    adjusted_score -= div.same_angle_penalty

                # Boost for event's chapter assignment
                if shot.event_id in ch_events:
                    adjusted_score += 0.05

                if adjusted_score < 0.05:
                    continue

                if self.is_high_energy(current_time) and shot.source.is_video:
                    if shot.quality.motion_intensity < 0.3:
                        continue

                # Video/photo ratio enforcement
                is_video = shot.source.is_video
                if is_video and ch_video_used >= ch_video_budget * 1.2:
                    continue
                if not is_video and ch_photo_used >= ch_photo_budget * 1.2:
                    continue

                # Snap to beat
                snapped_start = self.snap_to_beat(current_time)
                if snapped_start > current_time:
                    current_time = snapped_start

                in_point = shot.start_sec
                out_point = min(shot.start_sec + clip_dur, shot.end_sec)
                actual_dur = out_point - in_point

                reason = f"event={shot.event_id} arc={arc_role} score={adjusted_score:.3f}"
                clip = TimelineClip(
                    shot=shot,
                    timeline_start=current_time,
                    timeline_end=current_time + actual_dur,
                    in_point=in_point,
                    out_point=out_point,
                    chapter=chapter.name,
                    selection_reason=reason,
                    total_score=adjusted_score,
                )
                timeline.append(clip)
                used_sources.add(source_key)
                current_time = clip.timeline_end
                last_event_id = shot.event_id
                last_source_path = source_path
                last_role = shot_role
                used_event_ids.add(shot.event_id)
                global_source_usage[source_path] = src_uses + 1
                chapter_source_files.add(source_path)

                if is_video:
                    ch_video_used += actual_dur
                    video_used += actual_dur
                else:
                    ch_photo_used += actual_dur
                    photo_used += actual_dur

        # --- Duration backfill: try to reach at least 85% of target ---
        actual_total = current_time
        min_target = target * 0.85
        if actual_total < min_target:
            logger.info(
                "Duration backfill: %.1fs < %.1fs (85%% target), attempting to fill gap",
                actual_total, min_target,
            )
            # Pass 1: reuse video shots with relaxed diversity (allow used sources)
            all_candidates = sorted(
                [(self.compute_score(s, chapters[-1], current_time), s) for s in shots],
                key=lambda x: x[0], reverse=True,
            )
            for score, shot in all_candidates:
                if current_time >= min_target:
                    break
                source_key = f"{shot.source.path}:{shot.start_sec}"
                if source_key in used_sources:
                    continue
                remaining = min_target - current_time
                clip_dur = min(shot.duration_sec, self.config.clip_duration_sec.max, remaining)
                clip_dur = max(clip_dur, self.config.clip_duration_sec.min)
                if clip_dur > remaining:
                    continue
                in_point = shot.start_sec
                out_point = min(shot.start_sec + clip_dur, shot.end_sec)
                actual_dur = out_point - in_point
                clip = TimelineClip(
                    shot=shot,
                    timeline_start=current_time,
                    timeline_end=current_time + actual_dur,
                    in_point=in_point,
                    out_point=out_point,
                    chapter=chapters[-1].name,
                    selection_reason=f"backfill score={score:.3f}",
                    total_score=score,
                )
                timeline.append(clip)
                used_sources.add(source_key)
                current_time = clip.timeline_end

            # Pass 2: extend photo clips if still short
            if current_time < min_target:
                for tc in timeline:
                    if current_time >= min_target:
                        break
                    if tc.shot.source.is_photo:
                        extend = min(2.0, min_target - current_time)
                        tc.timeline_end += extend
                        current_time += extend
                # Recalculate timeline positions after extension
                pos = 0.0
                for tc in timeline:
                    dur = tc.timeline_end - tc.timeline_start
                    tc.timeline_start = pos
                    tc.timeline_end = pos + dur
                    pos += dur
                current_time = pos

            actual_total = current_time
            logger.info("After backfill: %.1fs (target=%ds)", actual_total, target)

        # Add transitions between chapters
        self._add_transitions(timeline, chapters)

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
