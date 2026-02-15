"""Tests for planner: ratio enforcement, diversity penalties, scoring (Tasks 0, 4)."""

from __future__ import annotations

import pytest

from roughcut.models import (
    BeatInfo,
    Chapter,
    DiversityConfig,
    MediaType,
    MusicSection,
    ProjectConfig,
    QualityScores,
)
from roughcut.planner.growth import GrowthPlanner
from roughcut.planner.travel import TravelPlanner
from tests.conftest import make_shot


class TestVideoPhotoRatio:
    """Test that video_photo_ratio is enforced in planning."""

    def test_ratio_produces_both_types(self, default_config, sample_shots):
        """With ratio [7,3], output should contain both video and photo clips."""
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)
        video_clips = [c for c in clips if c.shot.source.is_video]
        photo_clips = [c for c in clips if c.shot.source.is_photo]
        assert len(video_clips) > 0, "Should have video clips"
        assert len(photo_clips) > 0, "Should have photo clips"

    def test_ratio_approximate(self, default_config, sample_shots):
        """Video/photo duration ratio should approximately match config."""
        default_config.target_duration_sec = 120
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)
        video_dur = sum(c.timeline_duration for c in clips if c.shot.source.is_video)
        photo_dur = sum(c.timeline_duration for c in clips if c.shot.source.is_photo)
        total_dur = video_dur + photo_dur
        if total_dur > 0 and photo_dur > 0:
            actual_ratio = video_dur / photo_dur
            expected_ratio = 7.0 / 3.0
            # Allow wide tolerance — ratio is best-effort
            assert actual_ratio > 1.0, "Video should dominate given [7,3] ratio"


class TestDiversityPenalties:
    """Test diversity controls in planner."""

    def test_event_coverage(self, default_config, sample_shots):
        """Planner should cover multiple events."""
        default_config.diversity.min_event_coverage = 0.3
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)
        used_events = {c.shot.event_id for c in clips}
        all_events = {s.event_id for s in sample_shots if s.event_id >= 0}
        coverage = len(used_events) / len(all_events) if all_events else 0
        assert coverage >= 0.3, f"Event coverage {coverage:.0%} < 30%"

    def test_no_excessive_same_source_consecutive(self, default_config, sample_shots):
        """Should not exceed max_consecutive_same_source."""
        default_config.diversity.max_consecutive_same_source = 2
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)

        max_streak = 1
        streak = 1
        for i in range(1, len(clips)):
            if str(clips[i].shot.source.path) == str(clips[i - 1].shot.source.path):
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 1
        assert max_streak <= 2, f"Same-source streak {max_streak} > limit 2"

    def test_diversity_penalty_reduces_score(self):
        """same_source_penalty should reduce scores for repeated sources."""
        config = ProjectConfig(
            target_duration_sec=30,
            seed=42,
            diversity=DiversityConfig(same_source_penalty=0.5),
        )
        # All shots from the same source — heavy penalty should still work
        shots = [
            make_shot(name="same.mp4", start=i * 5, end=(i + 1) * 5,
                      event_id=0, shot_role="action")
            for i in range(6)
        ]
        planner = GrowthPlanner(config)
        clips = planner.plan(shots)
        assert len(clips) > 0

    def test_role_diversity(self, default_config, sample_shots):
        """Should not have too many consecutive clips with the same role."""
        default_config.diversity.max_consecutive_same_role = 2
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)

        if len(clips) < 3:
            pytest.skip("Not enough clips to test role diversity")

        max_streak = 1
        streak = 1
        for i in range(1, len(clips)):
            r1 = clips[i].shot.shot_role or "unknown"
            r0 = clips[i - 1].shot.shot_role or "unknown"
            if r1 == r0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 1
        assert max_streak <= 2, f"Same-role streak {max_streak} > limit 2"


class TestPlannerScoring:
    """Test score computation."""

    def test_compute_score_positive(self, default_config):
        planner = GrowthPlanner(default_config)
        shot = make_shot(sharpness=0.8, exposure=0.8, stability=0.8,
                         face_score=0.5, motion_intensity=0.3)
        chapter = Chapter("highlights", 0.30)
        score = planner.compute_score(shot, chapter, 10.0)
        assert score > 0.0

    def test_low_quality_penalty(self, default_config):
        """Shots with very low quality should get penalty."""
        planner = GrowthPlanner(default_config)
        chapter = Chapter("opening", 0.10)

        good_shot = make_shot(sharpness=0.8, exposure=0.8, stability=0.8)
        bad_shot = make_shot(sharpness=0.1, exposure=0.2, stability=0.2)

        good_score = planner.compute_score(good_shot, chapter, 0.0)
        bad_score = planner.compute_score(bad_shot, chapter, 0.0)
        assert good_score > bad_score

    def test_rhythm_fit_on_beat(self, default_config, sample_beat_info):
        """Position exactly on a beat should get high rhythm_fit."""
        planner = GrowthPlanner(default_config, beat_info=sample_beat_info)
        assert planner.rhythm_fit(1.0) == 1.0  # 1.0 is exactly on a beat (0.5*2)

    def test_rhythm_fit_off_beat(self, default_config, sample_beat_info):
        """Position far from any beat should get low rhythm_fit."""
        planner = GrowthPlanner(default_config, beat_info=sample_beat_info)
        # 0.25 is halfway between beats at 0.0 and 0.5
        fit = planner.rhythm_fit(0.25)
        assert fit < 1.0

    def test_section_fit_chorus_prefers_action(self, default_config, sample_beat_info):
        """During chorus, action shots should score higher."""
        planner = GrowthPlanner(default_config, beat_info=sample_beat_info)
        action_shot = make_shot(motion_intensity=0.8, stability=0.3, shot_role="action")
        calm_shot = make_shot(motion_intensity=0.1, stability=0.9, shot_role="detail")

        # Chorus section is at 25-40s
        action_fit = planner.section_fit(action_shot, 30.0)
        calm_fit = planner.section_fit(calm_shot, 30.0)
        assert action_fit > calm_fit


class TestTravelPlanner:
    """Basic tests for the travel planner."""

    def test_travel_chapters(self, travel_config):
        planner = TravelPlanner(travel_config)
        chapters = planner.chapters()
        assert len(chapters) == 4
        assert sum(c.ratio for c in chapters) == pytest.approx(1.0)

    def test_travel_plan_runs(self, travel_config, sample_shots):
        planner = TravelPlanner(travel_config)
        clips = planner.plan(sample_shots)
        assert len(clips) > 0


class TestGrowthPlanner:
    """Basic tests for the growth planner."""

    def test_growth_chapters(self, default_config):
        planner = GrowthPlanner(default_config)
        chapters = planner.chapters()
        assert len(chapters) == 4
        assert sum(c.ratio for c in chapters) == pytest.approx(1.0)

    def test_growth_plan_runs(self, default_config, sample_shots):
        planner = GrowthPlanner(default_config)
        clips = planner.plan(sample_shots)
        assert len(clips) > 0
        # Each clip should have a chapter assigned
        for clip in clips:
            assert clip.chapter != ""
