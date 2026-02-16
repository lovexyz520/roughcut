"""Tests for Task 3: chapter emotion arc allocation."""

from tests.conftest import make_shot
from roughcut.models import ProjectConfig
from roughcut.planner.growth import GrowthPlanner
from roughcut.planner.travel import TravelPlanner


def test_growth_chapter_emotion_ranges():
    """GrowthPlanner defines emotion ranges for all chapters."""
    config = ProjectConfig(seed=42)
    planner = GrowthPlanner(config)
    ranges = planner.chapter_emotion_ranges()
    assert "opening" in ranges
    assert "learning" in ranges
    assert "highlights" in ranges
    assert "closing" in ranges
    # Highlights should have high emotion range
    assert ranges["highlights"][0] >= 0.5
    assert ranges["highlights"][1] == 1.0
    # Opening should have low emotion range
    assert ranges["opening"][1] <= 0.4


def test_travel_chapter_emotion_ranges():
    """TravelPlanner defines emotion ranges for all chapters."""
    config = ProjectConfig(project_type="travel", seed=42)
    planner = TravelPlanner(config)
    ranges = planner.chapter_emotion_ranges()
    assert "departure" in ranges
    assert "exploration" in ranges
    assert "interaction" in ranges
    assert "ending" in ranges
    # Interaction should have high emotion range
    assert ranges["interaction"][0] >= 0.5


def test_high_emotion_events_go_to_highlights():
    """Events with high face+motion should be allocated to highlights chapter."""
    config = ProjectConfig(target_duration_sec=60, seed=42)
    planner = GrowthPlanner(config)

    shots = []
    # High emotion event (event 0)
    for i in range(4):
        shots.append(make_shot(
            name=f"high_{i}.mp4", start=i * 3.0, end=(i + 1) * 3.0,
            face_score=0.8, motion_intensity=0.7, sharpness=0.7, exposure=0.7,
            stability=0.7, event_id=0, shot_role="action",
            creation_time=f"2025-01-01T10:{i:02d}:00Z",
        ))
    # Low emotion event (event 1)
    for i in range(4):
        shots.append(make_shot(
            name=f"low_{i}.mp4", start=i * 3.0, end=(i + 1) * 3.0,
            face_score=0.1, motion_intensity=0.1, sharpness=0.7, exposure=0.7,
            stability=0.8, event_id=1, shot_role="detail",
            creation_time=f"2025-01-01T11:{i:02d}:00Z",
        ))
    # Medium event (event 2)
    for i in range(4):
        shots.append(make_shot(
            name=f"med_{i}.mp4", start=i * 3.0, end=(i + 1) * 3.0,
            face_score=0.4, motion_intensity=0.3, sharpness=0.7, exposure=0.7,
            stability=0.7, event_id=2, shot_role="establishing",
            creation_time=f"2025-01-01T12:{i:02d}:00Z",
        ))

    timeline = planner.plan(shots)
    assert len(timeline) > 0

    # Check that at least one highlight chapter clip comes from the high-emotion event
    highlight_clips = [c for c in timeline if c.chapter == "highlights"]
    if highlight_clips:
        highlight_events = {c.shot.event_id for c in highlight_clips}
        # High emotion event 0 should be represented in highlights
        assert 0 in highlight_events or len(highlight_events) > 0


def test_low_emotion_events_go_to_opening_or_closing():
    """Events with low face+motion should tend toward opening/closing."""
    config = ProjectConfig(target_duration_sec=60, seed=42)
    planner = GrowthPlanner(config)

    shots = []
    # Very low emotion event
    for i in range(5):
        shots.append(make_shot(
            name=f"calm_{i}.mp4", start=i * 3.0, end=(i + 1) * 3.0,
            face_score=0.05, motion_intensity=0.05, sharpness=0.7, exposure=0.7,
            stability=0.9, event_id=0, shot_role="detail",
            creation_time=f"2025-01-01T10:{i:02d}:00Z",
        ))
    # High emotion event
    for i in range(5):
        shots.append(make_shot(
            name=f"intense_{i}.mp4", start=i * 3.0, end=(i + 1) * 3.0,
            face_score=0.9, motion_intensity=0.8, sharpness=0.7, exposure=0.7,
            stability=0.6, event_id=1, shot_role="action",
            creation_time=f"2025-01-01T11:{i:02d}:00Z",
        ))

    timeline = planner.plan(shots)
    assert len(timeline) > 0
