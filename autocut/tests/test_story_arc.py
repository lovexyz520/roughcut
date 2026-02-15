"""Tests for Story Arc Planner (Task 3): arc ordering, role coverage, chapter endings."""

from __future__ import annotations

import pytest

from tests.conftest import make_shot, make_timeline_clip
from roughcut.models import ProjectConfig, TimelineClip
from roughcut.planner.base import TemplatePlanner
from roughcut.planner.growth import GrowthPlanner


class TestArcRoleForProgress:
    """Test the arc phase selection logic."""

    def test_beginning_is_establishing(self):
        arc_order = ["establishing", "action", "reaction", "detail"]
        budget = {"establishing": 0.15, "action": 0.40, "reaction": 0.30, "detail": 0.15}
        assert TemplatePlanner._arc_role_for_progress(0.0, arc_order, budget) == "establishing"
        assert TemplatePlanner._arc_role_for_progress(0.10, arc_order, budget) == "establishing"

    def test_middle_is_action(self):
        arc_order = ["establishing", "action", "reaction", "detail"]
        budget = {"establishing": 0.15, "action": 0.40, "reaction": 0.30, "detail": 0.15}
        assert TemplatePlanner._arc_role_for_progress(0.30, arc_order, budget) == "action"
        assert TemplatePlanner._arc_role_for_progress(0.50, arc_order, budget) == "action"

    def test_later_is_reaction(self):
        arc_order = ["establishing", "action", "reaction", "detail"]
        budget = {"establishing": 0.15, "action": 0.40, "reaction": 0.30, "detail": 0.15}
        assert TemplatePlanner._arc_role_for_progress(0.60, arc_order, budget) == "reaction"

    def test_end_is_detail(self):
        arc_order = ["establishing", "action", "reaction", "detail"]
        budget = {"establishing": 0.15, "action": 0.40, "reaction": 0.30, "detail": 0.15}
        assert TemplatePlanner._arc_role_for_progress(0.95, arc_order, budget) == "detail"
        assert TemplatePlanner._arc_role_for_progress(1.0, arc_order, budget) == "detail"


class TestChapterEndings:
    """Test that chapter endings are forced to reaction/detail."""

    def test_enforce_chapter_endings_swaps_action(self):
        """Last clip in chapter should become reaction/detail."""
        config = ProjectConfig(seed=42)
        planner = GrowthPlanner(config)

        clips = [
            make_timeline_clip(
                shot=make_shot(name="v1.mp4", shot_role="establishing"),
                timeline_start=0, timeline_end=3, chapter="opening"
            ),
            make_timeline_clip(
                shot=make_shot(name="v2.mp4", shot_role="reaction"),
                timeline_start=3, timeline_end=6, chapter="opening"
            ),
            make_timeline_clip(
                shot=make_shot(name="v3.mp4", shot_role="action"),
                timeline_start=6, timeline_end=9, chapter="opening"
            ),
        ]

        chapters = planner.chapters()
        planner._enforce_chapter_endings(clips, chapters)

        # Last clip in "opening" should now be reaction (swapped with clip at index 1)
        last_opening = clips[2]
        assert last_opening.shot.shot_role in ("reaction", "detail")

    def test_already_closure_role_unchanged(self):
        """If last clip is already reaction/detail, no swap needed."""
        config = ProjectConfig(seed=42)
        planner = GrowthPlanner(config)

        clips = [
            make_timeline_clip(
                shot=make_shot(name="v1.mp4", shot_role="action"),
                timeline_start=0, timeline_end=3, chapter="opening"
            ),
            make_timeline_clip(
                shot=make_shot(name="v2.mp4", shot_role="detail"),
                timeline_start=3, timeline_end=6, chapter="opening"
            ),
        ]

        chapters = planner.chapters()
        planner._enforce_chapter_endings(clips, chapters)

        assert clips[1].shot.shot_role == "detail"


class TestRoleCoverage:
    """Test that planner produces diverse roles."""

    def test_planner_produces_multiple_roles(self, sample_shots, default_config):
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)

        if not clips:
            pytest.skip("No clips planned (insufficient material)")

        # Check role diversity across all clips
        roles = {c.shot.shot_role for c in clips if c.shot.shot_role}
        assert len(roles) >= 2, f"Expected at least 2 distinct roles, got {roles}"

    def test_planner_produces_clips_with_chapters(self, sample_shots, default_config):
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)

        if not clips:
            pytest.skip("No clips planned")

        chapters = {c.chapter for c in clips}
        assert len(chapters) >= 2, f"Expected at least 2 chapters, got {chapters}"
