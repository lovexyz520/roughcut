"""Tests for Shot Detect 2.0: multi-signal detection, force-split, garbage removal."""

from __future__ import annotations

import pytest

from roughcut.analyze.shot_detect import (
    _force_split_long_shots,
    _remove_garbage_segments,
)
from roughcut.models import ShotDetectConfig


class TestForceSplitLongShots:
    """Test the force-split logic for long segments."""

    def test_no_split_needed(self):
        boundaries = [0.0, 5.0, 10.0]
        result = _force_split_long_shots(boundaries, max_duration=8.0, min_duration=0.5)
        assert result == [0.0, 5.0, 10.0]

    def test_single_long_segment_split(self):
        """A 20s segment with max=8s should split into ~3 pieces."""
        boundaries = [0.0, 20.0]
        result = _force_split_long_shots(boundaries, max_duration=8.0, min_duration=0.5)
        # 20/8 ≈ 2.5 → rounds to 3 splits
        # Each piece ≈ 6.67s
        assert len(result) >= 4  # at least 3 segments (4 boundaries)
        assert result[0] == 0.0
        assert result[-1] == 20.0
        # All segments should be <= max_duration + small tolerance
        for i in range(len(result) - 1):
            seg_dur = result[i + 1] - result[i]
            assert seg_dur <= 8.5, f"Segment {i} too long: {seg_dur}s"

    def test_mixed_segments(self):
        """Mix of short and long segments."""
        boundaries = [0.0, 3.0, 25.0, 30.0]
        result = _force_split_long_shots(boundaries, max_duration=8.0, min_duration=0.5)
        assert result[0] == 0.0
        assert result[-1] == 30.0
        # 3.0-25.0 = 22s segment should be split
        assert len(result) > 4

    def test_exact_max_duration_not_split(self):
        boundaries = [0.0, 8.0]
        result = _force_split_long_shots(boundaries, max_duration=8.0, min_duration=0.5)
        assert result == [0.0, 8.0]

    def test_just_over_max_duration_splits(self):
        boundaries = [0.0, 8.1]
        result = _force_split_long_shots(boundaries, max_duration=8.0, min_duration=0.5)
        assert len(result) >= 3  # Should split into at least 2 segments


class TestRemoveGarbageSegments:
    """Test garbage segment removal."""

    def test_no_garbage(self):
        boundaries = [0.0, 2.0, 4.0, 6.0]
        result = _remove_garbage_segments(boundaries, min_duration=0.5)
        assert result == [0.0, 2.0, 4.0, 6.0]

    def test_short_segment_merged(self):
        """A 0.2s segment should be merged."""
        boundaries = [0.0, 2.0, 2.2, 5.0]
        result = _remove_garbage_segments(boundaries, min_duration=0.5)
        # 2.0-2.2 is too short, should be merged
        assert 2.2 not in result
        assert result[0] == 0.0
        assert result[-1] == 5.0

    def test_all_segments_valid(self):
        boundaries = [0.0, 1.0, 2.5, 5.0]
        result = _remove_garbage_segments(boundaries, min_duration=0.5)
        assert result == [0.0, 1.0, 2.5, 5.0]

    def test_single_segment(self):
        boundaries = [0.0, 10.0]
        result = _remove_garbage_segments(boundaries, min_duration=0.5)
        assert result == [0.0, 10.0]

    def test_empty_segment_at_end(self):
        boundaries = [0.0, 5.0, 5.1]
        result = _remove_garbage_segments(boundaries, min_duration=0.5)
        assert result[-1] == 5.1
        # The tiny segment should be absorbed


class TestShotDetectConfig:
    """Test ShotDetectConfig integration."""

    def test_default_values(self):
        cfg = ShotDetectConfig()
        assert cfg.min_duration == 0.5
        assert cfg.max_duration == 8.0
        assert cfg.histogram_threshold == 0.4
        assert cfg.optical_flow_threshold == 12.0
        assert cfg.luminance_threshold == 30.0
        assert cfg.sample_interval == 3

    def test_custom_values(self):
        cfg = ShotDetectConfig(
            min_duration=1.0,
            max_duration=6.0,
            histogram_threshold=0.3,
        )
        assert cfg.min_duration == 1.0
        assert cfg.max_duration == 6.0
        assert cfg.histogram_threshold == 0.3

    def test_config_from_dict(self):
        from roughcut.models import ProjectConfig
        data = {
            "shot_detect": {
                "min_duration": 0.8,
                "max_duration": 10.0,
                "histogram_threshold": 0.35,
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.shot_detect.min_duration == 0.8
        assert config.shot_detect.max_duration == 10.0
        assert config.shot_detect.histogram_threshold == 0.35
        # Defaults for unspecified
        assert config.shot_detect.optical_flow_threshold == 12.0
