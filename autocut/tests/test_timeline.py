"""Tests for timeline assembly and report generation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from roughcut.editor.timeline import Timeline, build_timeline
from roughcut.models import BeatInfo, MusicSection
from roughcut.report.writer import (
    _compute_rhythm_stats,
    _infer_rejection_reason,
    write_all_reports,
    write_report_json,
    write_selected_csv,
    write_rejected_csv,
)
from tests.conftest import make_shot, make_timeline_clip


class TestTimeline:
    """Test Timeline class."""

    def test_empty_timeline(self):
        tl = Timeline()
        assert tl.duration == 0.0
        assert len(tl.clips) == 0

    def test_duration(self):
        clips = [
            make_timeline_clip(timeline_start=0, timeline_end=5),
            make_timeline_clip(timeline_start=5, timeline_end=12),
        ]
        tl = Timeline(clips)
        assert tl.duration == 12.0

    def test_validate_gap(self):
        clips = [
            make_timeline_clip(timeline_start=0, timeline_end=5),
            make_timeline_clip(timeline_start=6, timeline_end=10),
        ]
        tl = Timeline(clips)
        issues = tl.validate()
        assert len(issues) == 1
        assert "Gap" in issues[0]

    def test_validate_no_issues(self):
        clips = [
            make_timeline_clip(timeline_start=0, timeline_end=5),
            make_timeline_clip(timeline_start=5, timeline_end=10),
        ]
        tl = Timeline(clips)
        issues = tl.validate()
        assert len(issues) == 0

    def test_get_chapters(self):
        clips = [
            make_timeline_clip(timeline_start=0, timeline_end=5, chapter="intro"),
            make_timeline_clip(timeline_start=5, timeline_end=10, chapter="intro"),
            make_timeline_clip(timeline_start=10, timeline_end=15, chapter="main"),
        ]
        tl = Timeline(clips)
        chapters = tl.get_chapters()
        assert "intro" in chapters
        assert "main" in chapters
        assert len(chapters["intro"]) == 2
        assert len(chapters["main"]) == 1

    def test_summary(self):
        clips = [make_timeline_clip(timeline_start=0, timeline_end=5)]
        tl = Timeline(clips)
        s = tl.summary()
        assert s["total_clips"] == 1
        assert s["total_duration"] == 5.0


class TestReportWriter:
    """Test report generation functions."""

    def test_write_report_json(self, tmp_path):
        shots = [make_shot(name=f"v{i}.mp4", event_id=i) for i in range(3)]
        clips = [
            make_timeline_clip(
                shot=shots[0], timeline_start=0, timeline_end=5, chapter="intro"
            )
        ]
        tl = Timeline(clips)

        out = tmp_path / "report.json"
        write_report_json(tl, shots, out)

        assert out.exists()
        data = json.loads(out.read_text("utf-8"))
        assert "summary" in data
        assert "story_structure" in data
        assert "chapters" in data["story_structure"]
        assert "grammar_violations" in data
        assert "selected_clips" in data
        assert "rejected_count" in data
        assert data["rejected_count"] == 2  # 3 shots - 1 selected

    def test_write_selected_csv(self, tmp_path):
        clips = [make_timeline_clip(timeline_start=0, timeline_end=5)]
        tl = Timeline(clips)

        out = tmp_path / "selected.csv"
        write_selected_csv(tl, out)

        assert out.exists()
        lines = out.read_text("utf-8").strip().split("\n")
        assert len(lines) == 2  # header + 1 row

    def test_write_rejected_csv(self, tmp_path):
        shots = [make_shot(name=f"v{i}.mp4", event_id=i) for i in range(3)]
        clips = [make_timeline_clip(shot=shots[0])]
        tl = Timeline(clips)

        out = tmp_path / "rejected.csv"
        write_rejected_csv(shots, tl, out)

        assert out.exists()
        lines = out.read_text("utf-8").strip().split("\n")
        assert len(lines) == 3  # header + 2 rejected

    def test_infer_rejection_reason_low_quality(self):
        shot = make_shot(sharpness=0.1, exposure=0.2, stability=0.2)
        reason = _infer_rejection_reason(shot)
        assert "blurry" in reason
        assert "poor_exposure" in reason

    def test_infer_rejection_reason_outranked(self):
        shot = make_shot(sharpness=0.8, exposure=0.8, stability=0.8)
        reason = _infer_rejection_reason(shot)
        assert reason == "outranked_by_better_candidates"

    def test_rhythm_stats_no_beat_info(self):
        clips = [make_timeline_clip()]
        tl = Timeline(clips)
        stats = _compute_rhythm_stats(tl, None)
        assert stats["beat_aligned_cuts"] == 0

    def test_rhythm_stats_with_beats(self):
        clips = [
            make_timeline_clip(timeline_start=0.0, timeline_end=5.0),
            make_timeline_clip(timeline_start=5.0, timeline_end=10.0),
        ]
        tl = Timeline(clips)
        beat_info = BeatInfo(
            beat_times=[0.0, 0.5, 1.0, 5.0, 5.5],
            sections=[MusicSection("verse", 0.0, 10.0, avg_energy=0.5)],
        )
        stats = _compute_rhythm_stats(tl, beat_info)
        assert stats["beat_aligned_cuts"] >= 1
        assert stats["total_cuts"] == 2

    def test_write_all_reports(self, tmp_path):
        shots = [make_shot(name=f"v{i}.mp4", event_id=i) for i in range(3)]
        clips = [make_timeline_clip(shot=shots[0])]
        tl = Timeline(clips)

        write_all_reports(tl, shots, tmp_path)

        assert (tmp_path / "report" / "report.json").exists()
        assert (tmp_path / "report" / "selected_clips.csv").exists()
        assert (tmp_path / "report" / "rejected_clips.csv").exists()
        assert (tmp_path / "report" / "story_notes.md").exists()
        assert (tmp_path / "report" / "comparison_v3_v4.json").exists()

        comparison = json.loads(
            (tmp_path / "report" / "comparison_v3_v4.json").read_text("utf-8")
        )
        assert "v3_proxy" in comparison
        assert "v4" in comparison
        assert "delta" in comparison
