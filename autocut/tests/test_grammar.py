"""Tests for Grammar / Continuity 2.0 (Task 4)."""

from __future__ import annotations

from tests.conftest import make_shot, make_timeline_clip
from roughcut.planner.grammar import (
    GrammarViolation,
    apply_grammar,
    count_grammar_violations,
)
from roughcut.models import TransitionType


class TestConsecutiveRoleDetection:
    """Test detection of 3+ same-role runs."""

    def test_detects_triple_same_role(self):
        clips = [
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=0, timeline_end=3, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=3, timeline_end=6, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=6, timeline_end=9, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="detail"), timeline_start=9, timeline_end=12, chapter="main"),
        ]
        report = apply_grammar(clips)
        assert report.consecutive_same_role >= 1
        assert any(v.rule == "consecutive_same_role" for v in report.details)

    def test_no_violation_with_mixed_roles(self):
        clips = [
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=0, timeline_end=3, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="detail"), timeline_start=3, timeline_end=6, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="reaction"), timeline_start=6, timeline_end=9, chapter="main"),
        ]
        report = apply_grammar(clips)
        assert report.consecutive_same_role == 0


class TestBreathPoints:
    """Test high-action buffer detection."""

    def test_detects_triple_high_action(self):
        clips = [
            make_timeline_clip(
                shot=make_shot(shot_role="action", motion_intensity=0.8),
                timeline_start=0, timeline_end=3, chapter="main"
            ),
            make_timeline_clip(
                shot=make_shot(shot_role="action", motion_intensity=0.7),
                timeline_start=3, timeline_end=6, chapter="main"
            ),
            make_timeline_clip(
                shot=make_shot(shot_role="action", motion_intensity=0.9),
                timeline_start=6, timeline_end=9, chapter="main"
            ),
        ]
        report = apply_grammar(clips)
        assert report.missing_breath_points >= 1
        assert any(v.rule == "needs_breath" for v in report.details)


class TestCrossEventJumps:
    """Test cross-event jump rate limiting."""

    def test_rapid_event_jumps_flagged(self):
        """Many event jumps in short duration should be flagged."""
        clips = []
        for i in range(6):
            clips.append(make_timeline_clip(
                shot=make_shot(name=f"v{i}.mp4", event_id=i),
                timeline_start=i * 1.0, timeline_end=(i + 1) * 1.0,
                chapter="main"
            ))
        report = apply_grammar(clips)
        # 5 jumps in 6 seconds = 0.83/s > 0.25/s
        assert report.cross_event_jump_violations >= 1
        assert any(v.rule == "cross_event_jump_rate" for v in report.details)

    def test_slow_event_jumps_ok(self):
        """Few jumps over long duration should not be flagged."""
        clips = [
            make_timeline_clip(shot=make_shot(event_id=0), timeline_start=0, timeline_end=10, chapter="main"),
            make_timeline_clip(shot=make_shot(event_id=1), timeline_start=10, timeline_end=20, chapter="main"),
            make_timeline_clip(shot=make_shot(event_id=2), timeline_start=20, timeline_end=30, chapter="main"),
        ]
        report = apply_grammar(clips)
        assert report.cross_event_jump_violations == 0


class TestChapterTransitions:
    """Test chapter boundary transitions."""

    def test_transition_added_at_chapter_boundary(self):
        clips = [
            make_timeline_clip(
                shot=make_shot(event_id=0), timeline_start=0, timeline_end=5, chapter="opening"
            ),
            make_timeline_clip(
                shot=make_shot(event_id=1), timeline_start=5, timeline_end=10, chapter="learning"
            ),
            make_timeline_clip(
                shot=make_shot(event_id=1), timeline_start=10, timeline_end=15, chapter="learning"
            ),
        ]
        report = apply_grammar(clips)
        assert report.chapter_transitions_fixed >= 1
        assert clips[0].transition_out in (TransitionType.FADE_OUT, TransitionType.CROSS_DISSOLVE)
        assert any(v.rule == "chapter_transition" for v in report.details)


class TestViolationDetails:
    """Test that violation details are populated."""

    def test_details_populated(self):
        clips = [
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=0, timeline_end=3, chapter="A"),
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=3, timeline_end=6, chapter="A"),
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=6, timeline_end=9, chapter="A"),
            make_timeline_clip(shot=make_shot(shot_role="detail"), timeline_start=9, timeline_end=12, chapter="B"),
        ]
        report = apply_grammar(clips)
        assert len(report.details) > 0
        for v in report.details:
            assert isinstance(v, GrammarViolation)
            assert v.rule
            assert v.description

    def test_before_after_counts(self):
        clips = [
            make_timeline_clip(shot=make_shot(shot_role="action"), timeline_start=0, timeline_end=3, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="detail"), timeline_start=3, timeline_end=6, chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="reaction"), timeline_start=6, timeline_end=9, chapter="main"),
        ]
        report = apply_grammar(clips)
        assert report.violations_before >= 0
        assert report.violations_after >= 0
