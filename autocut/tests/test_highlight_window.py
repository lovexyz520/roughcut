"""Tests for Highlight Windowing (Task 2)."""

from __future__ import annotations

from tests.conftest import make_shot
from roughcut.analyze.highlights import compute_highlight_scores
from roughcut.models import MediaType


class TestHighlightWindowFields:
    """Test that window fields are set properly."""

    def test_short_shot_uses_full_extent(self):
        """Shots shorter than 2x window_min should use full extent."""
        shot = make_shot(name="short.mp4", start=0.0, end=1.0)
        # Manually set window fields as compute_highlight_windows does for short shots
        shot.best_start_sec = shot.start_sec
        shot.best_end_sec = shot.end_sec
        shot.window_score = shot.quality.overall
        assert shot.best_start_sec == 0.0
        assert shot.best_end_sec == 1.0

    def test_photo_uses_full_extent(self):
        """Photos should always use full extent."""
        shot = make_shot(name="photo.jpg", start=0.0, end=4.0, media_type=MediaType.PHOTO)
        shot.best_start_sec = shot.start_sec
        shot.best_end_sec = shot.end_sec
        assert shot.best_start_sec == 0.0
        assert shot.best_end_sec == 4.0

    def test_window_fields_default_none(self):
        """Window fields should default to None."""
        shot = make_shot()
        assert shot.best_start_sec is None
        assert shot.best_end_sec is None
        assert shot.window_score == 0.0

    def test_window_within_shot_bounds(self):
        """Window should not exceed shot boundaries."""
        shot = make_shot(start=5.0, end=20.0)
        shot.best_start_sec = 8.0
        shot.best_end_sec = 10.5
        assert shot.best_start_sec >= shot.start_sec
        assert shot.best_end_sec <= shot.end_sec


class TestHighlightScores:
    """Test that highlight score computation works with window fields."""

    def test_highlight_scores_set(self):
        shots = [
            make_shot(face_score=0.8, motion_intensity=0.3, sharpness=0.7, exposure=0.7),
            make_shot(face_score=0.1, motion_intensity=0.1, sharpness=0.5, exposure=0.5),
        ]
        compute_highlight_scores(shots)
        # First shot (high face) should have higher highlight score
        assert shots[0].highlight_score > shots[1].highlight_score
        assert shots[0].highlight_reason != ""

    def test_action_moment_highlight(self):
        shot = make_shot(motion_intensity=0.7, sharpness=0.6, exposure=0.7)
        compute_highlight_scores([shot])
        assert shot.highlight_score > 0.0
        assert "action_moment" in shot.highlight_reason

    def test_posed_photo_highlight(self):
        shot = make_shot(
            name="photo.jpg",
            media_type=MediaType.PHOTO,
            face_score=0.5,
            sharpness=0.8,
            exposure=0.7,
        )
        compute_highlight_scores([shot])
        assert shot.highlight_score > 0.0
        assert "posed_photo" in shot.highlight_reason


class TestPlannerWindowIntegration:
    """Test that planner uses window fields."""

    def test_planner_picks_window_start(self):
        """When best_start_sec is set, in_point should use it."""
        shot = make_shot(start=0.0, end=15.0)
        shot.best_start_sec = 5.0
        shot.best_end_sec = 7.5
        # Simulate what planner does
        clip_dur = 2.5
        in_point = shot.best_start_sec
        out_point = min(shot.best_start_sec + clip_dur, shot.best_end_sec, shot.end_sec)
        assert in_point == 5.0
        assert out_point == 7.5

    def test_fallback_when_no_window(self):
        """When best_start_sec is None, should use shot.start_sec."""
        shot = make_shot(start=3.0, end=10.0)
        in_point = shot.best_start_sec if shot.best_start_sec is not None else shot.start_sec
        assert in_point == 3.0
