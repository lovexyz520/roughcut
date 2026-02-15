"""Tests for shot role classification (Task 2)."""

from __future__ import annotations

from roughcut.analyze.shot_role import ShotRole, assign_roles, classify_shot_role
from roughcut.models import MediaType
from tests.conftest import make_shot


class TestClassifyShotRole:
    """Test heuristic role classification."""

    def test_high_motion_is_action(self):
        """High motion intensity should classify as action."""
        shot = make_shot(
            motion_intensity=0.9,
            stability=0.2,
            face_score=0.0,
            sharpness=0.5,
        )
        role = classify_shot_role(shot)
        assert role == ShotRole.ACTION

    def test_high_face_is_reaction(self):
        """High face score with low motion should be reaction."""
        shot = make_shot(
            face_score=0.9,
            motion_intensity=0.1,
            stability=0.8,
            sharpness=0.6,
        )
        role = classify_shot_role(shot)
        assert role == ShotRole.REACTION

    def test_sharp_static_no_face_is_detail(self):
        """Sharp, static, no face should be detail."""
        shot = make_shot(
            sharpness=0.9,
            stability=0.9,
            motion_intensity=0.05,
            face_score=0.0,
        )
        role = classify_shot_role(shot)
        assert role == ShotRole.DETAIL

    def test_wide_low_face_is_establishing(self):
        """Wide shot with low face score should tend toward establishing."""
        shot = make_shot(
            width=1920,
            height=1080,
            face_score=0.0,
            motion_intensity=0.1,
            exposure=0.8,
            stability=0.7,
            sharpness=0.3,  # Not too sharp to avoid detail
        )
        role = classify_shot_role(shot)
        assert role == ShotRole.ESTABLISHING

    def test_photo_prefers_detail_or_establishing(self):
        """Photos should bias toward detail or establishing."""
        shot = make_shot(
            media_type=MediaType.PHOTO,
            sharpness=0.7,
            stability=1.0,
            motion_intensity=0.0,
            face_score=0.0,
        )
        role = classify_shot_role(shot)
        assert role in (ShotRole.DETAIL, ShotRole.ESTABLISHING)


class TestAssignRoles:
    """Test batch role assignment."""

    def test_assign_returns_map(self):
        shots = [
            make_shot(name="a.mp4", start=0, end=5, motion_intensity=0.8),
            make_shot(name="b.mp4", start=0, end=5, face_score=0.9),
        ]
        role_map = assign_roles(shots)
        assert len(role_map) == 2
        # All values should be valid ShotRole members
        for key, role in role_map.items():
            assert isinstance(role, ShotRole)

    def test_assign_multiple_roles_present(self):
        """Given diverse shots, assignment should produce multiple distinct roles."""
        shots = [
            make_shot(name="a.mp4", motion_intensity=0.9, stability=0.2, face_score=0.0),
            make_shot(name="b.mp4", face_score=0.9, motion_intensity=0.1),
            make_shot(name="c.mp4", sharpness=0.9, stability=0.9, motion_intensity=0.0, face_score=0.0),
        ]
        role_map = assign_roles(shots)
        roles = set(role_map.values())
        assert len(roles) >= 2, f"Expected multiple roles, got {roles}"
