"""Tests for core data models."""

from __future__ import annotations

import pytest

from roughcut.models import (
    BeatInfo,
    DiversityConfig,
    MediaItem,
    MediaType,
    MusicSection,
    OutputConfig,
    ProjectConfig,
    QualityScores,
    Shot,
    TimelineClip,
)
from tests.conftest import make_shot


class TestQualityScores:
    def test_overall_equal_weights(self):
        q = QualityScores(sharpness=1.0, exposure=1.0, stability=1.0,
                          face_score=1.0, motion_intensity=1.0)
        assert q.overall == pytest.approx(1.0)

    def test_overall_zero(self):
        q = QualityScores()
        assert q.overall == 0.0


class TestBeatInfo:
    def test_section_at(self):
        bi = BeatInfo(sections=[
            MusicSection("verse", 0.0, 10.0),
            MusicSection("chorus", 10.0, 20.0),
        ])
        assert bi.section_at(5.0).label == "verse"
        assert bi.section_at(15.0).label == "chorus"
        assert bi.section_at(25.0) is None

    def test_energy_at_interpolation(self):
        bi = BeatInfo(energy_curve=[
            (0.0, 0.0),
            (10.0, 1.0),
        ])
        assert bi.energy_at(5.0) == pytest.approx(0.5)
        assert bi.energy_at(0.0) == pytest.approx(0.0)
        assert bi.energy_at(10.0) == pytest.approx(1.0)

    def test_energy_at_outside_range(self):
        bi = BeatInfo(energy_curve=[(5.0, 0.3), (10.0, 0.7)])
        assert bi.energy_at(0.0) == pytest.approx(0.3)  # Before range
        assert bi.energy_at(20.0) == pytest.approx(0.7)  # After range


class TestProjectConfig:
    def test_from_dict_defaults(self):
        config = ProjectConfig.from_dict({})
        assert config.project_type == "growth"
        assert config.target_duration_sec == 240

    def test_from_dict_full(self):
        data = {
            "project_type": "travel",
            "target_duration_sec": 180,
            "video_photo_ratio": [8, 2],
            "clip_duration_sec": {"min": 2.0, "max": 8.0},
            "diversity": {
                "max_consecutive_same_source": 3,
                "min_event_coverage": 0.5,
                "same_source_penalty": 0.2,
            },
        }
        config = ProjectConfig.from_dict(data)
        assert config.project_type == "travel"
        assert config.target_duration_sec == 180
        assert config.video_photo_ratio == [8, 2]
        assert config.clip_duration_sec.min == 2.0
        assert config.clip_duration_sec.max == 8.0
        assert config.diversity.max_consecutive_same_source == 3
        assert config.diversity.min_event_coverage == 0.5

    def test_output_config_properties(self):
        o = OutputConfig(resolution="1280x720")
        assert o.width == 1280
        assert o.height == 720
