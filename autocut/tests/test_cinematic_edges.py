"""Tests for Task 4: cinematic edges (fade from/to black)."""

from tests.conftest import make_shot
from roughcut.models import ProjectConfig, TransitionType
from roughcut.planner.growth import GrowthPlanner
from roughcut.export.premiere_xml import _transition_effect_name


def test_first_clip_has_fade_from_black():
    """First clip should have FADE_FROM_BLACK transition_in."""
    config = ProjectConfig(target_duration_sec=30, seed=42)
    planner = GrowthPlanner(config)
    shots = [
        make_shot(name=f"v{i}.mp4", start=0.0, end=5.0, event_id=i % 2,
                  shot_role=["establishing", "action", "reaction", "detail"][i % 4],
                  creation_time=f"2025-01-01T10:{i:02d}:00Z")
        for i in range(10)
    ]
    timeline = planner.plan(shots)
    assert len(timeline) > 0
    assert timeline[0].transition_in == TransitionType.FADE_FROM_BLACK
    assert timeline[0].transition_duration >= 1.0


def test_last_clip_has_fade_to_black():
    """Last clip should have FADE_TO_BLACK transition_out."""
    config = ProjectConfig(target_duration_sec=30, seed=42)
    planner = GrowthPlanner(config)
    shots = [
        make_shot(name=f"v{i}.mp4", start=0.0, end=5.0, event_id=i % 2,
                  shot_role=["establishing", "action", "reaction", "detail"][i % 4],
                  creation_time=f"2025-01-01T10:{i:02d}:00Z")
        for i in range(10)
    ]
    timeline = planner.plan(shots)
    assert len(timeline) > 0
    assert timeline[-1].transition_out == TransitionType.FADE_TO_BLACK
    assert timeline[-1].transition_duration >= 1.5


def test_fade_types_have_correct_xml_effect():
    """FADE_FROM_BLACK and FADE_TO_BLACK map to DipToColorDissolve."""
    name, eid = _transition_effect_name(TransitionType.FADE_FROM_BLACK)
    assert eid == "DipToColorDissolve"
    name, eid = _transition_effect_name(TransitionType.FADE_TO_BLACK)
    assert eid == "DipToColorDissolve"


def test_cross_dissolve_maps_correctly():
    """CROSS_DISSOLVE maps to CrossDissolve."""
    name, eid = _transition_effect_name(TransitionType.CROSS_DISSOLVE)
    assert eid == "CrossDissolve"
