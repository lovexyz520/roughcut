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
    order_events_for_narrative,
    rank_events,
    summarize_events,
)
from roughcut.planner.preference import UserProfile

logger = logging.getLogger(__name__)


class TemplatePlanner(ABC):
    """Abstract base class for story template planners."""

    def __init__(
        self,
        config: ProjectConfig,
        beat_info: BeatInfo | None = None,
        user_profile: UserProfile | None = None,
    ):
        self.config = config
        self.beat_info = beat_info
        self.user_profile = user_profile
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

    def chapter_emotion_ranges(self) -> dict[str, tuple[float, float]]:
        """Return emotion range (min, max) for each chapter.

        Override in subclasses for template-specific emotion arcs.
        Default: all chapters accept full range.
        """
        return {c.name: (0.0, 1.0) for c in self.chapters()}

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
                    highlight_bonus += 0.25  # Task 2: chorus highlight boost
                else:
                    # Slight penalty for reserved highlights outside chorus
                    source_key = f"{shot.source.path}:{shot.start_sec}"
                    if hasattr(self, '_chorus_reserved_keys') and source_key in self._chorus_reserved_keys:
                        highlight_bonus -= 0.10

        # Penalties
        penalties = 0.0
        if q.exposure < 0.3:
            penalties += 0.2  # Too dark/bright
        if q.sharpness < 0.2:
            penalties += 0.15  # Too blurry
        if q.stability < 0.3:
            penalties += 0.1  # Too shaky

        # User preference bias
        pref_adj = 0.0
        if self.user_profile:
            pref_adj = self.user_profile.score_adjustment(shot)

        return max(0.0, total + highlight_bonus + pref_adj - penalties)

    def story_fit(self, shot: Shot, chapter: Chapter) -> float:
        """Evaluate how well a shot fits a chapter. Override in subclasses."""
        return 0.5

    # Section → preferred roles mapping (explicit intent mapping)
    SECTION_ROLE_MAP: dict[str, list[str]] = {
        "intro": ["establishing", "detail"],
        "verse": ["establishing", "detail", "reaction"],
        "chorus": ["action", "reaction"],
        "bridge": ["reaction", "detail"],
        "outro": ["detail", "establishing", "reaction"],
    }

    # Mismatch penalty when role is not in preferred list
    SECTION_MISMATCH_PENALTY = 0.15

    def section_fit(self, shot: Shot, timeline_position: float) -> float:
        """Score how well a shot matches the current music section's mood.

        Section-level mapping (V4):
        - intro  → establishing, detail (scene setting)
        - verse  → establishing, detail, reaction (exploration)
        - chorus → action, reaction (highlights)
        - bridge → reaction, detail (transition)
        - outro  → detail, establishing, reaction (closure)

        Mismatched roles receive a penalty.
        """
        if not self.beat_info or not self.beat_info.sections:
            return 0.5

        section = self.beat_info.section_at(timeline_position)
        if section is None:
            return 0.5

        q = shot.quality
        role = shot.shot_role or ""
        highlight = shot.highlight_score
        preferred = self.SECTION_ROLE_MAP.get(section.label, [])

        if section.label == "chorus":
            score = q.motion_intensity * 0.3 + highlight * 0.4 + (1.0 - q.stability) * 0.1
            if role == "action":
                score += 0.35
            elif role == "reaction" and highlight >= 0.5:
                score += 0.2
            # Extra chorus highlight bonus
            if highlight >= 0.6:
                score += 0.15
        elif section.label == "verse":
            score = q.stability * 0.3 + q.sharpness * 0.2 + q.exposure * 0.1
            if role in ("establishing", "detail"):
                score += 0.3
            elif role == "reaction":
                score += 0.15
            # Verse motion penalty: too dynamic shots feel wrong in verse
            if q.motion_intensity > 0.7:
                score -= 0.1
        elif section.label == "intro":
            score = q.stability * 0.3 + q.exposure * 0.2
            if role == "establishing":
                score += 0.4
            elif role == "detail":
                score += 0.3
        elif section.label == "outro":
            score = q.stability * 0.3 + q.exposure * 0.2
            if shot.source.is_photo:
                score += 0.3
            if role in ("detail", "establishing"):
                score += 0.25
        elif section.label == "bridge":
            score = q.stability * 0.2 + q.sharpness * 0.2
            if role == "reaction":
                score += 0.3
            elif role == "detail":
                score += 0.2
        else:
            return 0.5

        # Apply mismatch penalty when role conflicts with section intent
        if role and preferred and role not in preferred:
            score -= self.SECTION_MISMATCH_PENALTY

        return max(0.0, min(1.0, score))

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

    def energy_clip_duration(self, position: float) -> float:
        """Compute max clip duration based on music energy at position.

        Formula: clip_max = base_max * (1.2 - factor * energy)
        - energy=0 → clip_max ≈ base_max * 1.2 (verse: longer, breathing)
        - energy=1 → clip_max ≈ base_max * 0.6 (chorus: shorter, punchy)

        Always clamped to [clip_min, base_max * 1.2].
        """
        base_max = self.config.clip_duration_sec.max
        clip_min = self.config.clip_duration_sec.min
        factor = self.config.rhythm.energy_clip_factor
        energy = self.music_energy_at(position)
        clip_max = base_max * (1.2 - factor * energy)
        return max(clip_min, min(clip_max, base_max * 1.2))

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

        # --- Chorus highlight reservation ---
        chorus_reserved, chorus_event_usage = self._reserve_chorus_highlights(shots)
        logger.info(
            "Chorus reservation: %d shots reserved across %d chorus sections",
            sum(len(v) for v in chorus_reserved.values()),
            len(chorus_reserved),
        )

        # Event ranking and narrative ordering
        event_summaries = summarize_events(shots)
        ranked_events = rank_events(event_summaries)
        ranked_events = order_events_for_narrative(
            ranked_events, self.config.narrative_mode
        )
        logger.info("Narrative mode: %s", self.config.narrative_mode)
        all_event_ids = {s.event_id for s in shots if s.event_id >= 0}
        used_event_ids: set[int] = set()
        global_source_usage: dict[str, int] = {}

        # Build per-event shot pools
        event_shots_map: dict[int, list[Shot]] = {}
        for s in shots:
            event_shots_map.setdefault(s.event_id, []).append(s)

        # Allocate events to chapters using emotion-aware matching
        chapter_events: dict[str, list[int]] = {c.name: [] for c in chapters}
        events_per_chapter = max(1, len(ranked_events) // len(chapters))
        emotion_ranges = self.chapter_emotion_ranges()

        # Compute emotion value per event
        event_emotions: dict[int, float] = {}
        for es in ranked_events:
            event_emotions[es.event_id] = es.emotion_intensity

        # Distribute events: match emotion to chapter range
        assigned_events: set[int] = set()
        for chapter in chapters:
            emo_min, emo_max = emotion_ranges.get(chapter.name, (0.0, 1.0))
            # Find events that fit this chapter's emotion range
            fitting = [
                es for es in ranked_events
                if es.event_id not in assigned_events
                and emo_min <= event_emotions.get(es.event_id, 0.5) <= emo_max
            ]
            # If not enough fitting, also consider near-range events
            if len(fitting) < events_per_chapter:
                near = [
                    es for es in ranked_events
                    if es.event_id not in assigned_events
                    and es not in fitting
                ]
                # Sort by distance to range midpoint
                mid = (emo_min + emo_max) / 2
                near.sort(key=lambda es: abs(event_emotions.get(es.event_id, 0.5) - mid))
                fitting.extend(near)

            for es in fitting[:events_per_chapter]:
                chapter_events[chapter.name].append(es.event_id)
                assigned_events.add(es.event_id)

        # Remaining unassigned events go to chapter with best emotion fit
        for es in ranked_events:
            if es.event_id not in assigned_events:
                emo = event_emotions.get(es.event_id, 0.5)
                best_ch = min(
                    chapters,
                    key=lambda c: abs(
                        emo - sum(emotion_ranges.get(c.name, (0.0, 1.0))) / 2
                    ),
                )
                chapter_events[best_ch.name].append(es.event_id)
                assigned_events.add(es.event_id)

        logger.info("Event allocation: %s", {k: v for k, v in chapter_events.items()})

        # --- Fill each chapter using event-first selection ---
        for chapter in chapters:
            chapter_duration = target * chapter.ratio
            chapter_start = current_time
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
            arc_phase_budget = {
                "establishing": 0.15,  # First 15% of chapter
                "action": 0.40,        # Next 40%
                "reaction": 0.30,      # Next 30%
                "detail": 0.15,        # Last 15%
            }

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

            # Track role coverage for this chapter
            ch_role_counts: dict[str, int] = {}
            min_role_types = 2  # Minimum distinct roles per chapter

            for score, shot, arc_role in ch_candidates:
                if current_time >= chapter_end:
                    break

                source_key = f"{shot.source.path}:{shot.start_sec}"
                if source_key in used_sources:
                    continue

                remaining = chapter_end - current_time
                energy_max = self.energy_clip_duration(current_time)

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
                elapsed = current_time - chapter_start
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

                # Arc phase preference: boost shots matching current phase
                ch_progress = (current_time - chapter_start) / max(chapter_duration, 0.1)
                desired_role = self._arc_role_for_progress(ch_progress, arc_order, arc_phase_budget)
                if arc_role == desired_role:
                    adjusted_score += 0.08
                elif arc_role in arc_order and arc_order.index(arc_role) <= arc_order.index(desired_role):
                    adjusted_score += 0.03  # Earlier phase still acceptable

                # Role diversity boost: favor underrepresented roles
                if len(ch_role_counts) < min_role_types and arc_role not in ch_role_counts:
                    adjusted_score += 0.10  # Encourage diversity early

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

                # Use highlight window if available (prefer best sub-segment)
                if shot.best_start_sec is not None and shot.best_end_sec is not None:
                    in_point = shot.best_start_sec
                    out_point = min(shot.best_start_sec + clip_dur, shot.best_end_sec, shot.end_sec)
                else:
                    in_point = shot.start_sec
                    out_point = min(shot.start_sec + clip_dur, shot.end_sec)
                actual_dur = out_point - in_point
                if actual_dur < self.config.clip_duration_sec.min:
                    # Fall back to shot start if window too short
                    in_point = shot.start_sec
                    out_point = min(shot.start_sec + clip_dur, shot.end_sec)
                    actual_dur = out_point - in_point

                reason = f"event={shot.event_id} arc={arc_role} score={adjusted_score:.3f}"
                if shot.best_start_sec is not None and shot.best_start_sec != shot.start_sec:
                    reason += f" window={shot.best_start_sec:.1f}-{shot.best_end_sec:.1f}"
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
                ch_role_counts[shot_role] = ch_role_counts.get(shot_role, 0) + 1

                if is_video:
                    ch_video_used += actual_dur
                    video_used += actual_dur
                else:
                    ch_photo_used += actual_dur
                    photo_used += actual_dur

        # --- Duration backfill: try to reach at least 95% of target ---
        actual_total = current_time
        min_target = target * 0.95
        if actual_total < min_target:
            logger.info(
                "Duration backfill: %.1fs < %.1fs (95%% target), attempting to fill gap",
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

        # --- Trim pass: remove lowest-score clips if over 105% of target ---
        max_target = target * 1.05
        actual_total = current_time
        if actual_total > max_target and len(timeline) > 2:
            logger.info(
                "Trim pass: %.1fs > %.1fs (105%% target), removing lowest-score clips",
                actual_total, max_target,
            )
            # Chapter minimum retention: protect essential chapters
            chapter_min_ratio = {
                "opening": 0.60, "highlights": 0.70, "closing": 0.50,
                "departure": 0.60, "interaction": 0.70, "ending": 0.50,
                "learning": 0.50, "exploration": 0.50,
            }
            # Compute current chapter durations
            ch_durations: dict[str, float] = {}
            ch_budgets: dict[str, float] = {}
            for ch in chapters:
                ch_clips = [c for c in timeline if c.chapter == ch.name]
                ch_durations[ch.name] = sum(c.timeline_duration for c in ch_clips)
                ch_budgets[ch.name] = target * ch.ratio

            while actual_total > max_target and len(timeline) > 2:
                # Find lowest-score clip that won't violate chapter minimum
                candidates = []
                for i, clip in enumerate(timeline):
                    ch = clip.chapter
                    min_r = chapter_min_ratio.get(ch, 0.40)
                    ch_dur = ch_durations.get(ch, 0)
                    ch_budget = ch_budgets.get(ch, 0)
                    if ch_dur - clip.timeline_duration >= ch_budget * min_r:
                        candidates.append((clip.total_score, i))
                if not candidates:
                    break
                candidates.sort()
                _, remove_idx = candidates[0]
                removed = timeline.pop(remove_idx)
                ch_durations[removed.chapter] -= removed.timeline_duration
                actual_total -= removed.timeline_duration

            # Recalculate timeline positions after trim
            pos = 0.0
            for tc in timeline:
                dur = tc.timeline_end - tc.timeline_start
                tc.timeline_start = pos
                tc.timeline_end = pos + dur
                pos += dur
            current_time = pos
            actual_total = current_time
            logger.info("After trim: %.1fs (target=%ds)", actual_total, target)

        # Enforce chapter-end closure: last clip in each chapter should be reaction/detail
        self._enforce_chapter_endings(timeline, chapters)

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

    @staticmethod
    def _arc_role_for_progress(
        progress: float,
        arc_order: list[str],
        phase_budget: dict[str, float],
    ) -> str:
        """Determine the desired arc role given chapter progress (0-1)."""
        cumulative = 0.0
        for role in arc_order:
            cumulative += phase_budget.get(role, 0.25)
            if progress <= cumulative:
                return role
        return arc_order[-1]

    def _enforce_chapter_endings(
        self, timeline: list[TimelineClip], chapters: list[Chapter]
    ) -> None:
        """Ensure the last clip in each chapter is reaction or detail (closure feel).

        If the last clip is action/establishing, swap it with the nearest
        reaction/detail clip within the same chapter.
        """
        closure_roles = {"reaction", "detail"}
        chapter_groups: dict[str, list[int]] = {}
        for i, clip in enumerate(timeline):
            chapter_groups.setdefault(clip.chapter, []).append(i)

        for ch_name, indices in chapter_groups.items():
            if not indices:
                continue
            last_idx = indices[-1]
            last_role = timeline[last_idx].shot.shot_role or ""
            if last_role in closure_roles:
                continue  # Already good

            # Find nearest reaction/detail in this chapter to swap
            for j in reversed(indices[:-1]):
                swap_role = timeline[j].shot.shot_role or ""
                if swap_role in closure_roles:
                    # Swap shot content
                    a, b = timeline[last_idx], timeline[j]
                    a.shot, b.shot = b.shot, a.shot
                    a.in_point, b.in_point = b.in_point, a.in_point
                    a.out_point, b.out_point = b.out_point, a.out_point
                    a.total_score, b.total_score = b.total_score, a.total_score
                    a.selection_reason, b.selection_reason = b.selection_reason, a.selection_reason
                    break

    def _add_transitions(
        self, timeline: list[TimelineClip], chapters: list[Chapter]
    ) -> None:
        """Add fade transitions at chapter boundaries and cinematic edges."""
        if not timeline:
            return

        if len(timeline) >= 2:
            # Chapter boundary transitions
            for i in range(1, len(timeline)):
                prev_chapter = timeline[i - 1].chapter
                curr_chapter = timeline[i].chapter
                if prev_chapter != curr_chapter:
                    timeline[i - 1].transition_out = TransitionType.FADE_OUT
                    timeline[i].transition_in = TransitionType.FADE_IN
                    timeline[i - 1].transition_duration = 0.5
                    timeline[i].transition_duration = 0.5

        # Cinematic edges: fade from black at start, fade to black at end
        # Applied last so they always win over chapter boundaries
        timeline[0].transition_in = TransitionType.FADE_FROM_BLACK
        timeline[0].transition_duration = max(timeline[0].transition_duration, 1.0)
        timeline[-1].transition_out = TransitionType.FADE_TO_BLACK
        timeline[-1].transition_duration = max(timeline[-1].transition_duration, 1.5)

    def _reserve_chorus_highlights(
        self, shots: list[Shot]
    ) -> tuple[dict[int, list[Shot]], dict[int, set[int]]]:
        """Reserve top highlight shots for chorus sections.

        Returns:
            chorus_reserved: {chorus_index: [reserved shots]}
            chorus_event_usage: {chorus_index: {event_ids used}}
        """
        self._chorus_reserved_keys: set[str] = set()

        if not self.beat_info or not self.beat_info.sections:
            return {}, {}

        # Find chorus sections
        chorus_sections = [
            (i, s) for i, s in enumerate(self.beat_info.sections)
            if s.label == "chorus"
        ]
        if not chorus_sections:
            return {}, {}

        # Sort all shots by highlight score (descending)
        highlight_pool = sorted(
            [s for s in shots if s.highlight_score >= 0.3],
            key=lambda s: s.highlight_score,
            reverse=True,
        )

        chorus_reserved: dict[int, list[Shot]] = {}
        chorus_event_usage: dict[int, set[int]] = {}
        used_events_across_chorus: dict[int, set[int]] = {}  # chorus_idx -> events used
        global_reserved: set[str] = set()

        for ci, (chorus_idx, section) in enumerate(chorus_sections):
            reserved: list[Shot] = []
            events_used: set[int] = set()
            # Collect events used by all previous chorus sections
            prev_events: set[int] = set()
            for prev_ci in range(ci):
                prev_events.update(used_events_across_chorus.get(prev_ci, set()))

            # Pick top highlights, preferring different events from previous chorus
            max_reserve = max(2, int(section.duration / 3))  # ~1 highlight per 3s
            for shot in highlight_pool:
                if len(reserved) >= max_reserve:
                    break
                source_key = f"{shot.source.path}:{shot.start_sec}"
                if source_key in global_reserved:
                    continue
                # Cross-chorus diversity: prefer events not used in prior chorus
                if shot.event_id in prev_events and len(highlight_pool) > max_reserve * 2:
                    continue
                reserved.append(shot)
                events_used.add(shot.event_id)
                global_reserved.add(source_key)

            # Fallback: if not enough due to event constraints, relax
            if len(reserved) < max_reserve:
                for shot in highlight_pool:
                    if len(reserved) >= max_reserve:
                        break
                    source_key = f"{shot.source.path}:{shot.start_sec}"
                    if source_key in global_reserved:
                        continue
                    reserved.append(shot)
                    events_used.add(shot.event_id)
                    global_reserved.add(source_key)
                if len(reserved) < max_reserve:
                    logger.warning(
                        "Chorus %d: only %d/%d highlights reserved (insufficient events)",
                        chorus_idx, len(reserved), max_reserve,
                    )

            chorus_reserved[chorus_idx] = reserved
            chorus_event_usage[chorus_idx] = events_used
            used_events_across_chorus[ci] = events_used

        self._chorus_reserved_keys = global_reserved
        return chorus_reserved, chorus_event_usage
