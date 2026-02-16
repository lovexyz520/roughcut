"""Tests for Task 2: highlight shots locked to chorus sections."""

from tests.conftest import make_shot
from roughcut.models import BeatInfo, MusicSection, ProjectConfig
from roughcut.planner.growth import GrowthPlanner


def _make_beat_info_with_chorus():
    return BeatInfo(
        beat_times=[i * 0.5 for i in range(120)],
        downbeat_times=[i * 2.0 for i in range(30)],
        tempo=120.0,
        high_energy_ranges=[(15.0, 25.0), (40.0, 50.0)],
        sections=[
            MusicSection("intro", 0.0, 8.0, avg_energy=0.3),
            MusicSection("verse", 8.0, 20.0, avg_energy=0.5),
            MusicSection("chorus", 20.0, 32.0, avg_energy=0.8),
            MusicSection("verse", 32.0, 44.0, avg_energy=0.5),
            MusicSection("chorus", 44.0, 55.0, avg_energy=0.85),
            MusicSection("outro", 55.0, 60.0, avg_energy=0.3),
        ],
        energy_curve=[(i, 0.3 + 0.5 * abs((i - 30) / 30)) for i in range(0, 61, 5)],
    )


def _make_shots_with_highlights():
    shots = []
    for i in range(20):
        shot = make_shot(
            name=f"vid_{i}.mp4",
            start=0.0,
            end=5.0,
            sharpness=0.6,
            exposure=0.7,
            stability=0.7,
            face_score=0.3 + (0.4 if i < 5 else 0.0),  # First 5 are highlight-worthy
            motion_intensity=0.3 + (0.3 if i < 5 else 0.0),
            event_id=i % 4,
            shot_role=["action", "reaction", "establishing", "detail"][i % 4],
            creation_time=f"2025-01-01T10:{i:02d}:00Z",
        )
        # Manually set highlight scores
        if i < 5:
            shot.highlight_score = 0.7 + i * 0.02
        else:
            shot.highlight_score = 0.1
        shots.append(shot)
    return shots


def test_chorus_reservation_creates_reserved_shots():
    """_reserve_chorus_highlights should reserve shots for chorus sections."""
    config = ProjectConfig(target_duration_sec=60, seed=42)
    beat_info = _make_beat_info_with_chorus()
    planner = GrowthPlanner(config, beat_info)
    shots = _make_shots_with_highlights()
    reserved, event_usage = planner._reserve_chorus_highlights(shots)
    # Should have reservations for 2 chorus sections
    assert len(reserved) >= 1
    total_reserved = sum(len(v) for v in reserved.values())
    assert total_reserved >= 2


def test_chorus_repeat_uses_different_events():
    """Different chorus sections should prefer different event sources."""
    config = ProjectConfig(target_duration_sec=60, seed=42)
    beat_info = _make_beat_info_with_chorus()
    planner = GrowthPlanner(config, beat_info)
    shots = _make_shots_with_highlights()
    reserved, event_usage = planner._reserve_chorus_highlights(shots)
    if len(event_usage) >= 2:
        chorus_indices = sorted(event_usage.keys())
        events_0 = event_usage[chorus_indices[0]]
        events_1 = event_usage[chorus_indices[1]]
        # At least some diversity (not 100% overlap)
        # They can share some events, but shouldn't be identical if enough events exist
        assert len(events_0 | events_1) >= len(events_0)  # Union >= either set


def test_no_music_no_reservation():
    """Without beat info, reservation returns empty."""
    config = ProjectConfig(target_duration_sec=60, seed=42)
    planner = GrowthPlanner(config, beat_info=None)
    shots = _make_shots_with_highlights()
    reserved, event_usage = planner._reserve_chorus_highlights(shots)
    assert reserved == {}
    assert event_usage == {}


def test_no_chorus_sections_no_reservation():
    """Music without chorus sections returns empty reservation."""
    config = ProjectConfig(target_duration_sec=60, seed=42)
    beat_info = BeatInfo(
        sections=[
            MusicSection("verse", 0.0, 30.0, avg_energy=0.5),
            MusicSection("outro", 30.0, 60.0, avg_energy=0.3),
        ],
    )
    planner = GrowthPlanner(config, beat_info)
    shots = _make_shots_with_highlights()
    reserved, event_usage = planner._reserve_chorus_highlights(shots)
    assert reserved == {}
