"""Tests for V3→V4 comparison report (Task 7)."""

from __future__ import annotations

import json

import pytest

from tests.conftest import make_shot, make_timeline_clip
from roughcut.editor.timeline import Timeline
from roughcut.models import BeatInfo, MusicSection
from roughcut.report.writer import _compute_story_metrics, write_comparison_v3_v4


class TestStoryMetrics:
    """Test the V4 story metrics computation."""

    def test_empty_clips_zero_metrics(self):
        metrics = _compute_story_metrics([], [], target_duration_sec=60, audio_present=False)
        assert metrics["duration_achievement_rate"] == 0.0
        assert metrics["event_coverage_rate"] == 0.0
        assert metrics["chapter_role_coverage_rate"] == 0.0
        assert metrics["chorus_highlight_lift"] == 0.0

    def test_duration_achievement(self):
        clips = [
            make_timeline_clip(timeline_start=0, timeline_end=30, chapter="main"),
        ]
        metrics = _compute_story_metrics(clips, [], target_duration_sec=60, audio_present=True)
        assert metrics["duration_achievement_rate"] == pytest.approx(0.5, abs=0.01)

    def test_event_coverage(self):
        shots = [make_shot(event_id=i) for i in range(5)]
        clips = [
            make_timeline_clip(shot=make_shot(event_id=0), chapter="a"),
            make_timeline_clip(shot=make_shot(event_id=2), chapter="b"),
        ]
        metrics = _compute_story_metrics(clips, shots, target_duration_sec=60, audio_present=False)
        assert metrics["event_coverage_rate"] == pytest.approx(0.4, abs=0.01)

    def test_repeated_shot_rate(self):
        shot_a = make_shot(name="same.mp4", event_id=0)
        shot_b = make_shot(name="same.mp4", event_id=0)
        clips = [
            make_timeline_clip(shot=shot_a, timeline_start=0, timeline_end=3, chapter="main"),
            make_timeline_clip(shot=shot_b, timeline_start=3, timeline_end=6, chapter="main"),
        ]
        metrics = _compute_story_metrics(clips, [], target_duration_sec=60, audio_present=False)
        assert metrics["repeated_shot_rate"] == 1.0  # Both from same source

    def test_chapter_role_coverage_rate(self):
        clips = [
            make_timeline_clip(shot=make_shot(shot_role="action"), chapter="opening"),
            make_timeline_clip(shot=make_shot(shot_role="detail"), chapter="opening"),
            make_timeline_clip(shot=make_shot(shot_role="action"), chapter="closing"),
        ]
        metrics = _compute_story_metrics(clips, [], target_duration_sec=60, audio_present=False)
        # opening has 2 roles (good), closing has 1 role (bad)
        assert metrics["chapter_role_coverage_rate"] == pytest.approx(0.5, abs=0.01)

    def test_highlight_hit_rate(self):
        shot_high = make_shot()
        shot_high.highlight_score = 0.8
        shot_low = make_shot()
        shot_low.highlight_score = 0.2
        clips = [
            make_timeline_clip(shot=shot_high, chapter="main"),
            make_timeline_clip(shot=shot_low, chapter="main"),
        ]
        metrics = _compute_story_metrics(clips, [], target_duration_sec=60, audio_present=False)
        assert metrics["highlight_hit_rate"] == pytest.approx(0.5, abs=0.01)

    def test_all_seven_metrics_present(self):
        clips = [make_timeline_clip(chapter="main")]
        metrics = _compute_story_metrics(clips, [], target_duration_sec=60, audio_present=True)
        expected_keys = {
            "duration_achievement_rate",
            "event_coverage_rate",
            "repeated_shot_rate",
            "highlight_hit_rate",
            "audio_presence_rate",
            "grammar_violations",
            "chapter_role_coverage_rate",
            "chorus_highlight_lift",
        }
        assert expected_keys.issubset(set(metrics.keys()))


class TestComparisonReport:
    """Test the comparison_v3_v4.json output."""

    def test_comparison_file_written(self, tmp_path):
        clips = [
            make_timeline_clip(shot=make_shot(shot_role="action", event_id=0), chapter="main"),
            make_timeline_clip(shot=make_shot(shot_role="detail", event_id=1), chapter="main"),
        ]
        shots = [make_shot(event_id=i) for i in range(3)]
        timeline = Timeline(clips)
        pre_grammar = clips[:1]

        output = tmp_path / "comparison_v3_v4.json"
        write_comparison_v3_v4(
            timeline=timeline,
            all_shots=shots,
            output_path=output,
            pre_grammar_clips=pre_grammar,
            target_duration_sec=60,
        )

        assert output.exists()
        data = json.loads(output.read_text())
        assert "v3_proxy" in data
        assert "v4" in data
        assert "delta" in data
        assert "chapter_role_coverage_rate" in data["delta"]
        assert "chorus_highlight_lift" in data["delta"]

    def test_delta_has_all_metrics(self, tmp_path):
        clips = [make_timeline_clip(chapter="main")]
        timeline = Timeline(clips)
        output = tmp_path / "comparison_v3_v4.json"
        write_comparison_v3_v4(
            timeline=timeline,
            all_shots=[],
            output_path=output,
            pre_grammar_clips=[],
            target_duration_sec=60,
        )
        data = json.loads(output.read_text())
        expected_delta_keys = {
            "duration_achievement_rate",
            "event_coverage_rate",
            "repeated_shot_rate",
            "highlight_hit_rate",
            "grammar_violations",
            "chapter_role_coverage_rate",
            "chorus_highlight_lift",
        }
        assert expected_delta_keys.issubset(set(data["delta"].keys()))
