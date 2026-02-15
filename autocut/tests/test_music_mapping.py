"""Tests for Music Intent Mapping (Task 5)."""

from __future__ import annotations

import pytest

from tests.conftest import make_shot
from roughcut.models import BeatInfo, MusicSection, ProjectConfig
from roughcut.planner.base import TemplatePlanner
from roughcut.planner.growth import GrowthPlanner


class TestSectionRoleMap:
    """Test that the explicit section→role mapping is defined."""

    def test_all_sections_mapped(self):
        expected = {"intro", "verse", "chorus", "bridge", "outro"}
        assert expected.issubset(set(TemplatePlanner.SECTION_ROLE_MAP.keys()))

    def test_chorus_prefers_action(self):
        assert "action" in TemplatePlanner.SECTION_ROLE_MAP["chorus"]

    def test_intro_prefers_establishing(self):
        assert "establishing" in TemplatePlanner.SECTION_ROLE_MAP["intro"]

    def test_outro_prefers_detail(self):
        assert "detail" in TemplatePlanner.SECTION_ROLE_MAP["outro"]


class TestSectionFitScoring:
    """Test section_fit scoring with mismatch penalty."""

    @pytest.fixture
    def planner(self, sample_beat_info):
        config = ProjectConfig(seed=42)
        return GrowthPlanner(config, sample_beat_info)

    def test_chorus_action_high_score(self, planner):
        """Action shot in chorus should score high."""
        shot = make_shot(shot_role="action", motion_intensity=0.8, sharpness=0.6)
        score = planner.section_fit(shot, 30.0)  # chorus starts at 25.0
        assert score > 0.5

    def test_chorus_detail_penalized(self, planner):
        """Detail shot in chorus should be penalized (not in preferred list)."""
        shot = make_shot(shot_role="detail", motion_intensity=0.1, stability=0.9)
        score_chorus = planner.section_fit(shot, 30.0)

        # Same shot in verse (detail is preferred there)
        score_verse = planner.section_fit(shot, 12.0)  # verse starts at 10.0
        assert score_verse > score_chorus

    def test_intro_establishing_high(self, planner):
        """Establishing shot in intro should score high."""
        shot = make_shot(shot_role="establishing", stability=0.9, exposure=0.8)
        score = planner.section_fit(shot, 2.0)  # intro 0-10s
        assert score > 0.5

    def test_no_beat_info_returns_default(self):
        """Without beat info, section_fit should return 0.5."""
        config = ProjectConfig(seed=42)
        planner = GrowthPlanner(config, None)
        shot = make_shot(shot_role="action")
        score = planner.section_fit(shot, 10.0)
        assert score == 0.5


class TestMismatchPenalty:
    """Test that mismatch penalty is applied correctly."""

    def test_mismatch_penalty_constant(self):
        assert TemplatePlanner.SECTION_MISMATCH_PENALTY > 0
        assert TemplatePlanner.SECTION_MISMATCH_PENALTY <= 0.3

    def test_matched_role_no_penalty(self, sample_beat_info):
        config = ProjectConfig(seed=42)
        planner = GrowthPlanner(config, sample_beat_info)

        shot = make_shot(shot_role="action", motion_intensity=0.7)
        score = planner.section_fit(shot, 30.0)  # chorus → action is matched
        # Score should be decent (no penalty applied)
        assert score >= 0.3

    def test_unmatched_role_lower_score(self, sample_beat_info):
        config = ProjectConfig(seed=42)
        planner = GrowthPlanner(config, sample_beat_info)

        # Establishing in chorus = mismatch
        shot = make_shot(shot_role="establishing", stability=0.9, exposure=0.8, motion_intensity=0.1)
        score = planner.section_fit(shot, 30.0)  # chorus
        assert score < 0.7  # Should be penalized
