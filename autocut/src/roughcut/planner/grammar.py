"""Human editing grammar engine: post-processing rules for natural flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from roughcut.models import TimelineClip, TransitionType

logger = logging.getLogger(__name__)


@dataclass
class GrammarReport:
    """Summary of grammar violations found and fixed."""

    consecutive_same_role: int = 0
    missing_breath_points: int = 0
    chapter_transitions_fixed: int = 0
    total_violations: int = 0


def apply_grammar(
    clips: list[TimelineClip],
    all_shots: list | None = None,
) -> GrammarReport:
    """Apply human editing grammar rules to a planned timeline.

    Rules:
    1. No more than 2 consecutive clips with the same shot role/angle.
    2. Insert reaction/detail buffer between consecutive high-dynamic clips.
    3. Add breath points within events (avoid relentless fast cuts).
    4. Semantic transitions at chapter boundaries.

    Modifies clips in-place (reordering and transition adjustments).

    Returns:
        GrammarReport with violation counts.
    """
    report = GrammarReport()

    if len(clips) < 3:
        return report

    # Rule 1: Detect consecutive same-role violations (3+)
    report.consecutive_same_role = _fix_consecutive_roles(clips)

    # Rule 2: Insert buffer between consecutive high-action clips
    report.missing_breath_points = _add_action_buffers(clips)

    # Rule 4: Semantic chapter transitions
    report.chapter_transitions_fixed = _fix_chapter_transitions(clips)

    report.total_violations = (
        report.consecutive_same_role
        + report.missing_breath_points
        + report.chapter_transitions_fixed
    )

    logger.info(
        "Grammar check: %d violations (same_role=%d, breath=%d, transitions=%d)",
        report.total_violations,
        report.consecutive_same_role,
        report.missing_breath_points,
        report.chapter_transitions_fixed,
    )

    return report


def _fix_consecutive_roles(clips: list[TimelineClip]) -> int:
    """Rule 1: Break runs of 3+ clips with the same shot role by swapping."""
    violations = 0
    i = 0
    while i < len(clips) - 2:
        role_a = clips[i].shot.shot_role
        role_b = clips[i + 1].shot.shot_role
        role_c = clips[i + 2].shot.shot_role

        if role_a and role_a == role_b == role_c:
            violations += 1
            # Try to swap clips[i+2] with the next different-role clip
            swapped = False
            for j in range(i + 3, min(i + 6, len(clips))):
                if clips[j].shot.shot_role != role_a and clips[j].chapter == clips[i + 2].chapter:
                    # Swap positions but keep timeline times
                    _swap_clip_content(clips[i + 2], clips[j])
                    swapped = True
                    break
            if not swapped:
                i += 3  # Can't fix, skip ahead
                continue
        i += 1

    return violations


def _add_action_buffers(clips: list[TimelineClip]) -> int:
    """Rule 2 & 3: Detect consecutive high-action clips without breathing room.

    Instead of inserting new clips (which would require unused shots),
    we adjust selection_reason to flag violations for the report.
    """
    violations = 0
    consecutive_high_action = 0

    for i, clip in enumerate(clips):
        motion = clip.shot.quality.motion_intensity
        role = clip.shot.shot_role or ""

        if motion > 0.6 or role == "action":
            consecutive_high_action += 1
            if consecutive_high_action >= 3:
                violations += 1
                clip.selection_reason += " [grammar:needs_breath]"
                consecutive_high_action = 0  # Reset after flagging
        else:
            consecutive_high_action = 0

    return violations


def _fix_chapter_transitions(clips: list[TimelineClip]) -> int:
    """Rule 4: Ensure chapter boundaries have proper closing/opening.

    - Chapter end: prefer fade_out (closing feel)
    - Chapter start: prefer fade_in (opening feel)
    - Cross dissolve for smooth same-event transitions across chapters
    """
    fixed = 0
    for i in range(1, len(clips)):
        prev = clips[i - 1]
        curr = clips[i]

        if prev.chapter != curr.chapter:
            # Already has transitions? Skip
            if prev.transition_out != TransitionType.CUT:
                continue

            # Same event across chapters → cross dissolve
            if prev.shot.event_id == curr.shot.event_id:
                prev.transition_out = TransitionType.CROSS_DISSOLVE
                curr.transition_in = TransitionType.CROSS_DISSOLVE
                prev.transition_duration = 0.5
                curr.transition_duration = 0.5
            else:
                # Different events → fade out/in
                prev.transition_out = TransitionType.FADE_OUT
                curr.transition_in = TransitionType.FADE_IN
                prev.transition_duration = 0.5
                curr.transition_duration = 0.5
            fixed += 1

    return fixed


def _swap_clip_content(a: TimelineClip, b: TimelineClip) -> None:
    """Swap the shot content of two clips while keeping their timeline positions."""
    a.shot, b.shot = b.shot, a.shot
    a.in_point, b.in_point = b.in_point, a.in_point
    a.out_point, b.out_point = b.out_point, a.out_point
    a.total_score, b.total_score = b.total_score, a.total_score
    a.selection_reason, b.selection_reason = b.selection_reason, a.selection_reason


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
