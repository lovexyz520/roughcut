"""Tests for event segmentation (Task 1)."""

from __future__ import annotations

import pytest

from roughcut.planner.events import assign_events, summarize_events
from tests.conftest import make_shot


class TestAssignEvents:
    """Test event assignment based on creation time continuity."""

    def test_empty_shots(self):
        result = assign_events([])
        assert result == []

    def test_same_event_close_times(self):
        """Shots with close creation times should share an event."""
        shots = [
            make_shot(name="a.mp4", creation_time="2025-01-01T10:00:00Z"),
            make_shot(name="b.mp4", creation_time="2025-01-01T10:05:00Z"),
            make_shot(name="c.mp4", creation_time="2025-01-01T10:10:00Z"),
        ]
        assign_events(shots)
        assert shots[0].event_id == shots[1].event_id == shots[2].event_id

    def test_different_events_large_gap(self):
        """Shots separated by > 30 min gap should be different events."""
        shots = [
            make_shot(name="a.mp4", creation_time="2025-01-01T10:00:00Z"),
            make_shot(name="b.mp4", creation_time="2025-01-01T11:00:00Z"),
        ]
        assign_events(shots)
        assert shots[0].event_id != shots[1].event_id

    def test_custom_gap_threshold(self):
        """Custom gap threshold should be respected."""
        shots = [
            make_shot(name="a.mp4", creation_time="2025-01-01T10:00:00Z"),
            make_shot(name="b.mp4", creation_time="2025-01-01T10:10:00Z"),
        ]
        # 5 min threshold → should split at 10 min gap
        assign_events(shots, gap_threshold_sec=300)
        assert shots[0].event_id != shots[1].event_id

    def test_same_source_same_event(self):
        """Multiple shots from the same source file should have the same event."""
        shots = [
            make_shot(name="a.mp4", start=0, end=5, creation_time="2025-01-01T10:00:00Z"),
            make_shot(name="a.mp4", start=5, end=10, creation_time="2025-01-01T10:00:00Z"),
        ]
        assign_events(shots)
        assert shots[0].event_id == shots[1].event_id

    def test_no_creation_time_new_event(self):
        """Shots without creation time should become separate events."""
        shots = [
            make_shot(name="a.mp4", creation_time="2025-01-01T10:00:00Z"),
            make_shot(name="b.mp4", creation_time=""),
        ]
        assign_events(shots)
        assert shots[0].event_id != shots[1].event_id

    def test_multiple_events(self):
        """Three distinct events should produce 3 unique event IDs."""
        shots = [
            make_shot(name="a.mp4", creation_time="2025-01-01T08:00:00Z"),
            make_shot(name="b.mp4", creation_time="2025-01-01T08:10:00Z"),
            make_shot(name="c.mp4", creation_time="2025-01-01T10:00:00Z"),
            make_shot(name="d.mp4", creation_time="2025-01-01T14:00:00Z"),
        ]
        assign_events(shots)
        event_ids = {s.event_id for s in shots}
        assert len(event_ids) == 3


class TestSummarizeEvents:
    """Test event summary statistics."""

    def test_summarize_basic(self):
        shots = [
            make_shot(name="a.mp4", start=0, end=5, event_id=0),
            make_shot(name="b.mp4", start=0, end=3, event_id=0),
            make_shot(name="c.mp4", start=0, end=7, event_id=1),
        ]
        summaries = summarize_events(shots)
        assert len(summaries) == 2
        assert summaries[0].event_id == 0
        assert summaries[0].shot_count == 2
        assert summaries[0].total_duration == pytest.approx(8.0)
        assert summaries[1].event_id == 1
        assert summaries[1].shot_count == 1

    def test_summarize_empty(self):
        summaries = summarize_events([])
        assert summaries == []
