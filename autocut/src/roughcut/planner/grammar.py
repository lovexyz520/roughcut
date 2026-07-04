"""Human editing grammar engine 2.0: post-processing rules for natural flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from roughcut.analyze.camera_motion import motion_conflict
from roughcut.analyze.color import color_distance
from roughcut.models import TimelineClip, TransitionType

logger = logging.getLogger(__name__)


@dataclass
class GrammarViolation:
    """A single grammar violation with context."""
    rule: str           # e.g. "consecutive_same_role", "needs_breath", "cross_event_jump"
    clip_index: int
    description: str


@dataclass
class GrammarReport:
    """Summary of grammar violations found and fixed."""

    consecutive_same_role: int = 0
    missing_breath_points: int = 0
    chapter_transitions_fixed: int = 0
    cross_event_jump_violations: int = 0
    semantic_transitions_added: int = 0
    emotion_gradient_score: float = 0.0  # 0-1 how well emotion flows
    total_violations: int = 0
    violations_before: int = 0
    violations_after: int = 0
    details: list[GrammarViolation] = field(default_factory=list)


def apply_grammar(
    clips: list[TimelineClip],
    all_shots: list | None = None,
) -> GrammarReport:
    """Apply human editing grammar rules to a planned timeline.

    Rules:
    1. No more than 2 consecutive clips with the same shot role/angle.
    2. Insert reaction/detail buffer between consecutive high-dynamic clips.
    3. Limit cross-event jump frequency (max 1 per 4s average).
    4. Semantic transitions at chapter boundaries.

    Modifies clips in-place (reordering and transition adjustments).

    Returns:
        GrammarReport with violation counts and details.
    """
    report = GrammarReport()

    if len(clips) < 3:
        return report

    # Count violations before fixing
    report.violations_before = count_grammar_violations(clips)

    # Rule 1: Detect consecutive same-role violations (3+)
    report.consecutive_same_role = _fix_consecutive_roles(clips, report.details)

    # Rule 2: Insert buffer between consecutive high-action clips
    report.missing_breath_points = _add_action_buffers(clips, report.details)

    # Rule 3: Cross-event jump rate limiting
    report.cross_event_jump_violations = _check_cross_event_jumps(clips, report.details)

    # Rule 4: Semantic chapter transitions
    report.chapter_transitions_fixed = _fix_chapter_transitions(clips, report.details)

    # Rule 5: Semantic transitions (time jumps, emotion contrast, media type switch)
    report.semantic_transitions_added = _apply_semantic_transitions(clips, report.details)

    report.total_violations = (
        report.consecutive_same_role
        + report.missing_breath_points
        + report.cross_event_jump_violations
        + report.chapter_transitions_fixed
        + report.semantic_transitions_added
    )

    # Compute emotion gradient score
    report.emotion_gradient_score = _compute_emotion_gradient(clips)

    # Count violations after fixing
    report.violations_after = count_grammar_violations(clips)

    logger.info(
        "Grammar check: %d violations (same_role=%d, breath=%d, cross_event=%d, transitions=%d) "
        "| before=%d, after=%d",
        report.total_violations,
        report.consecutive_same_role,
        report.missing_breath_points,
        report.cross_event_jump_violations,
        report.chapter_transitions_fixed,
        report.violations_before,
        report.violations_after,
    )

    return report


def _fix_consecutive_roles(
    clips: list[TimelineClip], details: list[GrammarViolation]
) -> int:
    """Rule 1: Break runs of 3+ clips with the same shot role by swapping."""
    violations = 0
    i = 0
    while i < len(clips) - 2:
        role_a = clips[i].shot.shot_role
        role_b = clips[i + 1].shot.shot_role
        role_c = clips[i + 2].shot.shot_role

        if role_a and role_a == role_b == role_c:
            violations += 1
            details.append(GrammarViolation(
                rule="consecutive_same_role",
                clip_index=i,
                description=f"3+ consecutive '{role_a}' at clips {i}-{i+2}",
            ))
            # Try to swap clips[i+2] with the next different-role clip
            swapped = False
            for j in range(i + 3, min(i + 8, len(clips))):
                if clips[j].shot.shot_role != role_a and clips[j].chapter == clips[i + 2].chapter:
                    _swap_clip_content(clips[i + 2], clips[j])
                    swapped = True
                    break
            if not swapped:
                i += 3
                continue
        i += 1

    return violations


def _add_action_buffers(
    clips: list[TimelineClip], details: list[GrammarViolation]
) -> int:
    """Rule 2: Detect consecutive high-action clips without breathing room."""
    violations = 0
    consecutive_high_action = 0

    for i, clip in enumerate(clips):
        motion = clip.shot.quality.motion_intensity
        role = clip.shot.shot_role or ""

        if motion > 0.6 or role == "action":
            consecutive_high_action += 1
            if consecutive_high_action >= 3:
                violations += 1
                details.append(GrammarViolation(
                    rule="needs_breath",
                    clip_index=i,
                    description=f"3+ consecutive high-action clips ending at {i}",
                ))
                clip.selection_reason += " [grammar:needs_breath]"
                consecutive_high_action = 0
        else:
            consecutive_high_action = 0

    return violations


def _check_cross_event_jumps(
    clips: list[TimelineClip], details: list[GrammarViolation]
) -> int:
    """Rule 3: Flag excessive cross-event jumping (> 1 jump per 4s average)."""
    violations = 0
    if len(clips) < 2:
        return violations

    # Track jumps per chapter
    chapter_jumps: dict[str, list[int]] = {}
    for i in range(1, len(clips)):
        if clips[i].shot.event_id != clips[i - 1].shot.event_id:
            ch = clips[i].chapter
            chapter_jumps.setdefault(ch, []).append(i)

    for ch, jump_indices in chapter_jumps.items():
        # Get chapter duration
        ch_clips = [c for c in clips if c.chapter == ch]
        if not ch_clips:
            continue
        ch_dur = ch_clips[-1].timeline_end - ch_clips[0].timeline_start
        if ch_dur <= 0:
            continue

        jump_rate = len(jump_indices) / ch_dur  # jumps per second
        if jump_rate > 0.25:  # More than 1 jump per 4 seconds
            violations += 1
            details.append(GrammarViolation(
                rule="cross_event_jump_rate",
                clip_index=jump_indices[0],
                description=f"Chapter '{ch}': {len(jump_indices)} event jumps in {ch_dur:.1f}s "
                            f"(rate={jump_rate:.2f}/s, max=0.25/s)",
            ))

    return violations


def _fix_chapter_transitions(
    clips: list[TimelineClip], details: list[GrammarViolation]
) -> int:
    """Rule 4: Ensure chapter boundaries have proper closing/opening."""
    fixed = 0
    for i in range(1, len(clips)):
        prev = clips[i - 1]
        curr = clips[i]

        if prev.chapter != curr.chapter:
            if prev.transition_out != TransitionType.CUT:
                continue

            if prev.shot.event_id == curr.shot.event_id:
                prev.transition_out = TransitionType.CROSS_DISSOLVE
                curr.transition_in = TransitionType.CROSS_DISSOLVE
                prev.transition_duration = 0.5
                curr.transition_duration = 0.5
            else:
                prev.transition_out = TransitionType.FADE_OUT
                curr.transition_in = TransitionType.FADE_IN
                prev.transition_duration = 0.5
                curr.transition_duration = 0.5

            fixed += 1
            details.append(GrammarViolation(
                rule="chapter_transition",
                clip_index=i,
                description=f"Added transition between '{prev.chapter}' and '{curr.chapter}'",
            ))

    return fixed


def _apply_semantic_transitions(
    clips: list[TimelineClip], details: list[GrammarViolation]
) -> int:
    """Rule 5: Apply context-aware transitions between adjacent clips.

    Rules:
    - Same event, time jump >30s → cross dissolve (time passing feel)
    - Emotion contrast >0.5 → fade to/from black (emotion reset)
    - Photo↔video media switch → cross dissolve (smooth handoff)
    - Never override existing chapter boundary transitions.
    """
    added = 0
    for i in range(1, len(clips)):
        prev = clips[i - 1]
        curr = clips[i]

        # Skip if already has a non-CUT transition (e.g., chapter boundary)
        if prev.transition_out != TransitionType.CUT:
            continue
        if curr.transition_in != TransitionType.CUT:
            continue
        # Skip if different chapters (handled by chapter transitions)
        if prev.chapter != curr.chapter:
            continue

        # Rule 5a: same event, time jump >30s → cross dissolve
        if (prev.shot.event_id == curr.shot.event_id
                and prev.shot.event_id >= 0):
            time_gap = abs(curr.shot.start_sec - prev.shot.end_sec)
            if time_gap > 30.0:
                prev.transition_out = TransitionType.CROSS_DISSOLVE
                curr.transition_in = TransitionType.CROSS_DISSOLVE
                prev.transition_duration = 0.5
                curr.transition_duration = 0.5
                added += 1
                details.append(GrammarViolation(
                    rule="semantic_time_jump",
                    clip_index=i,
                    description=f"Time jump {time_gap:.0f}s in event {prev.shot.event_id}",
                ))
                continue

        # Rule 5b: emotion contrast >0.5 → fade (real smile/audio-driven emotion)
        prev_emo = prev.shot.quality.emotion
        curr_emo = curr.shot.quality.emotion
        if abs(curr_emo - prev_emo) > 0.5:
            prev.transition_out = TransitionType.FADE_OUT
            curr.transition_in = TransitionType.FADE_IN
            prev.transition_duration = 0.4
            curr.transition_duration = 0.4
            added += 1
            details.append(GrammarViolation(
                rule="semantic_emotion_contrast",
                clip_index=i,
                description=f"Emotion contrast {abs(curr_emo - prev_emo):.2f}",
            ))
            continue

        # Rule 5c: photo↔video media switch → cross dissolve
        prev_photo = prev.shot.source.is_photo
        curr_photo = curr.shot.source.is_photo
        if prev_photo != curr_photo:
            prev.transition_out = TransitionType.CROSS_DISSOLVE
            curr.transition_in = TransitionType.CROSS_DISSOLVE
            prev.transition_duration = 0.4
            curr.transition_duration = 0.4
            added += 1
            details.append(GrammarViolation(
                rule="semantic_media_switch",
                clip_index=i,
                description=f"Media switch: {'photo→video' if prev_photo else 'video→photo'}",
            ))
            continue

        # Rule 5d: clashing camera moves or a big color-temp jump → cross dissolve
        # to soften an otherwise jarring hard cut.
        clash = motion_conflict(prev.shot.camera_motion, curr.shot.camera_motion)
        color_jump = color_distance(prev.shot.color_temp, curr.shot.color_temp) > 0.4
        if clash or color_jump:
            prev.transition_out = TransitionType.CROSS_DISSOLVE
            curr.transition_in = TransitionType.CROSS_DISSOLVE
            prev.transition_duration = 0.35
            curr.transition_duration = 0.35
            added += 1
            reason = "camera_motion_clash" if clash else "color_jump"
            details.append(GrammarViolation(
                rule=f"semantic_{reason}",
                clip_index=i,
                description=(
                    f"{prev.shot.camera_motion}→{curr.shot.camera_motion}" if clash
                    else f"color Δ={color_distance(prev.shot.color_temp, curr.shot.color_temp):.2f}"
                ),
            ))

    return added


def _swap_clip_content(a: TimelineClip, b: TimelineClip) -> None:
    """Swap the shot content of two clips while keeping their timeline positions."""
    a.shot, b.shot = b.shot, a.shot
    a.in_point, b.in_point = b.in_point, a.in_point
    a.out_point, b.out_point = b.out_point, a.out_point
    a.total_score, b.total_score = b.total_score, a.total_score
    a.selection_reason, b.selection_reason = b.selection_reason, a.selection_reason


def _compute_emotion_gradient(clips: list[TimelineClip]) -> float:
    """Quantify how smoothly the emotion arc flows (0=chaotic, 1=smooth).

    Measures the average clip-to-clip emotion change. Smaller jumps = smoother.
    A perfect score means gentle transitions between emotion levels.
    """
    if len(clips) < 2:
        return 1.0

    emotions = [c.shot.quality.emotion for c in clips]
    jumps = [abs(emotions[i + 1] - emotions[i]) for i in range(len(emotions) - 1)]
    avg_jump = sum(jumps) / len(jumps)
    # Score: 0 jump = 1.0, 0.5+ jump = 0.0
    return max(0.0, min(1.0, 1.0 - avg_jump * 2.0))


def count_grammar_violations(clips: list[TimelineClip]) -> int:
    """Count grammar violations without fixing them (for reporting)."""
    violations = 0

    # Count consecutive same-role runs of 3+
    for i in range(len(clips) - 2):
        role = clips[i].shot.shot_role
        if role and role == clips[i + 1].shot.shot_role == clips[i + 2].shot.shot_role:
            violations += 1

    # Count consecutive high-action runs of 3+
    consecutive = 0
    for clip in clips:
        if clip.shot.quality.motion_intensity > 0.6 or clip.shot.shot_role == "action":
            consecutive += 1
            if consecutive >= 3:
                violations += 1
                consecutive = 0
        else:
            consecutive = 0

    return violations
