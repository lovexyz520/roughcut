"""Tests for Human Preference Learning (Task 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import make_shot
from roughcut.models import MediaType
from roughcut.planner.preference import (
    UserProfile,
    learn_preferences,
    load_user_profile,
    save_user_profile,
)


class TestUserProfile:
    """Test UserProfile score adjustments."""

    def test_neutral_profile_no_adjustment(self):
        profile = UserProfile()
        shot = make_shot()
        assert profile.score_adjustment(shot) == 0.0

    def test_face_bias_positive(self):
        profile = UserProfile(face_bias=0.3, sample_count=5)
        shot_high_face = make_shot(face_score=0.9)
        shot_low_face = make_shot(face_score=0.1)
        assert profile.score_adjustment(shot_high_face) > profile.score_adjustment(shot_low_face)

    def test_preferred_event_boost(self):
        profile = UserProfile(preferred_events=[2], sample_count=3)
        shot_preferred = make_shot(event_id=2)
        shot_other = make_shot(event_id=5)
        assert profile.score_adjustment(shot_preferred) > profile.score_adjustment(shot_other)

    def test_avoided_event_penalty(self):
        profile = UserProfile(avoided_events=[3], sample_count=3)
        shot_avoided = make_shot(event_id=3)
        shot_other = make_shot(event_id=1)
        assert profile.score_adjustment(shot_avoided) < profile.score_adjustment(shot_other)

    def test_role_bias(self):
        profile = UserProfile(role_bias={"action": 0.2, "detail": -0.1}, sample_count=5)
        shot_action = make_shot(shot_role="action")
        shot_detail = make_shot(shot_role="detail")
        assert profile.score_adjustment(shot_action) > profile.score_adjustment(shot_detail)


class TestLearnPreferences:
    """Test learning preferences from favorites/excludes."""

    def test_learn_from_favorites(self):
        all_shots = [
            make_shot(name=f"v{i}.mp4", face_score=0.3, event_id=i)
            for i in range(10)
        ]
        favorites = [
            make_shot(name="fav1.mp4", face_score=0.9, event_id=2),
            make_shot(name="fav2.mp4", face_score=0.8, event_id=5),
        ]
        profile = learn_preferences(all_shots, favorites, [])
        assert profile.sample_count == 2
        assert profile.face_bias > 0  # Favorites have higher face scores

    def test_learn_from_excludes(self):
        all_shots = [
            make_shot(name=f"v{i}.mp4", motion_intensity=0.5, event_id=i)
            for i in range(10)
        ]
        excluded = [
            make_shot(name="exc1.mp4", motion_intensity=0.9, event_id=3),
            make_shot(name="exc2.mp4", motion_intensity=0.8, event_id=7),
        ]
        profile = learn_preferences(all_shots, [], excluded)
        assert profile.sample_count == 2
        assert profile.motion_bias < 0  # Excluded had high motion, so bias negative

    def test_empty_input_neutral(self):
        profile = learn_preferences([], [], [])
        assert profile.sample_count == 0
        assert profile.face_bias == 0.0

    def test_event_preferences_tracked(self):
        all_shots = [make_shot(event_id=i) for i in range(5)]
        favorites = [make_shot(event_id=1), make_shot(event_id=3)]
        excluded = [make_shot(event_id=4)]
        profile = learn_preferences(all_shots, favorites, excluded)
        assert 1 in profile.preferred_events
        assert 3 in profile.preferred_events
        assert 4 in profile.avoided_events


class TestProfilePersistence:
    """Test save/load of user profiles."""

    def test_save_and_load(self, tmp_path):
        profile = UserProfile(
            face_bias=0.2,
            motion_bias=-0.1,
            role_bias={"action": 0.15},
            preferred_events=[1, 3],
            sample_count=5,
        )
        path = tmp_path / "user_profile.json"
        save_user_profile(profile, path)

        loaded = load_user_profile(path)
        assert loaded is not None
        assert loaded.face_bias == pytest.approx(0.2, abs=0.01)
        assert loaded.motion_bias == pytest.approx(-0.1, abs=0.01)
        assert loaded.sample_count == 5
        assert 1 in loaded.preferred_events

    def test_load_nonexistent_returns_none(self, tmp_path):
        result = load_user_profile(tmp_path / "nonexistent.json")
        assert result is None

    def test_to_dict_roundtrip(self):
        profile = UserProfile(
            face_bias=0.15,
            motion_bias=-0.05,
            stability_bias=0.1,
            sharpness_bias=0.0,
            role_bias={"action": 0.2},
            preferred_events=[2],
            avoided_events=[5],
            photo_bias=0.05,
            sample_count=10,
        )
        d = profile.to_dict()
        assert isinstance(d, dict)
        assert d["face_bias"] == 0.15
        assert d["sample_count"] == 10
