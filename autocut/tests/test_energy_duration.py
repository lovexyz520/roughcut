"""Tests for Task 1: energy-based continuous clip duration mapping."""

from roughcut.models import BeatInfo, MusicSection, ProjectConfig, RhythmConfig
from roughcut.planner.growth import GrowthPlanner


def _make_planner(energy_curve, factor=0.6):
    config = ProjectConfig(seed=42)
    config.rhythm = RhythmConfig(energy_clip_factor=factor)
    beat_info = BeatInfo(
        energy_curve=energy_curve,
        sections=[MusicSection("verse", 0.0, 60.0, avg_energy=0.5)],
    )
    return GrowthPlanner(config, beat_info)


def test_energy_zero_gives_max_times_1_2():
    """energy=0 → clip_max ≈ base_max * 1.2"""
    planner = _make_planner([(0.0, 0.0), (60.0, 0.0)])
    result = planner.energy_clip_duration(30.0)
    expected = planner.config.clip_duration_sec.max * 1.2
    assert abs(result - expected) < 0.01


def test_energy_one_gives_max_times_0_6():
    """energy=1 → clip_max ≈ base_max * (1.2 - 0.6) = base_max * 0.6"""
    planner = _make_planner([(0.0, 1.0), (60.0, 1.0)])
    result = planner.energy_clip_duration(30.0)
    expected = planner.config.clip_duration_sec.max * 0.6
    assert abs(result - expected) < 0.01


def test_clip_min_floor_protection():
    """Result never drops below clip_min even with extreme energy."""
    config = ProjectConfig(seed=42)
    config.rhythm = RhythmConfig(energy_clip_factor=2.0)  # Extreme factor
    beat_info = BeatInfo(
        energy_curve=[(0.0, 1.0), (60.0, 1.0)],
        sections=[MusicSection("chorus", 0.0, 60.0, avg_energy=1.0)],
    )
    planner = GrowthPlanner(config, beat_info)
    result = planner.energy_clip_duration(30.0)
    assert result >= config.clip_duration_sec.min


def test_mid_energy_interpolation():
    """energy=0.5 → clip_max between min and max*1.2."""
    planner = _make_planner([(0.0, 0.5), (60.0, 0.5)])
    result = planner.energy_clip_duration(30.0)
    base_max = planner.config.clip_duration_sec.max
    expected = base_max * (1.2 - 0.6 * 0.5)  # base_max * 0.9
    assert abs(result - expected) < 0.01


def test_no_beat_info_uses_base_max():
    """Without beat info, energy defaults to 0.5."""
    config = ProjectConfig(seed=42)
    planner = GrowthPlanner(config, beat_info=None)
    result = planner.energy_clip_duration(10.0)
    base_max = config.clip_duration_sec.max
    expected = base_max * (1.2 - 0.6 * 0.5)  # base_max * 0.9
    assert abs(result - expected) < 0.01


def test_custom_factor():
    """Custom energy_clip_factor works correctly."""
    planner = _make_planner([(0.0, 1.0), (60.0, 1.0)], factor=0.4)
    result = planner.energy_clip_duration(30.0)
    base_max = planner.config.clip_duration_sec.max
    expected = base_max * (1.2 - 0.4 * 1.0)  # base_max * 0.8
    assert abs(result - expected) < 0.01
