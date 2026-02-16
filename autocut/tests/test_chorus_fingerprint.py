"""Tests for Task 6: chorus repeat fingerprint and Task G: KPI summary."""

from roughcut.models import MusicSection


def test_repeat_index_default_zero():
    """MusicSection repeat_index defaults to 0."""
    sec = MusicSection("chorus", 10.0, 20.0, avg_energy=0.8)
    assert sec.repeat_index == 0


def test_repeat_index_can_be_set():
    """MusicSection repeat_index can be assigned."""
    sec = MusicSection("chorus", 10.0, 20.0, avg_energy=0.8, repeat_index=1)
    assert sec.repeat_index == 1


def test_kpi_summary_structure():
    """_compute_kpi_summary returns expected keys."""
    from tests.conftest import make_shot, make_timeline_clip
    from roughcut.editor.timeline import Timeline
    from roughcut.report.writer import _compute_kpi_summary

    shots = [make_shot(name=f"v{i}.mp4", event_id=i % 2) for i in range(5)]
    clips = [make_timeline_clip(s, i * 5.0, (i + 1) * 5.0) for i, s in enumerate(shots)]
    tl = Timeline(clips)
    kpi = _compute_kpi_summary(tl, shots, None)

    assert "total_clips" in kpi
    assert "total_duration_sec" in kpi
    assert "event_coverage" in kpi
    assert "highlight_rate" in kpi
    assert "beat_alignment_rate" in kpi
    assert "unique_sources" in kpi
    assert kpi["total_clips"] == 5


def test_kpi_event_coverage():
    """KPI event coverage reflects actual usage."""
    from tests.conftest import make_shot, make_timeline_clip
    from roughcut.editor.timeline import Timeline
    from roughcut.report.writer import _compute_kpi_summary

    # 3 events in pool, only use 2
    all_shots = [
        make_shot("v0.mp4", event_id=0),
        make_shot("v1.mp4", event_id=1),
        make_shot("v2.mp4", event_id=2),
    ]
    clips = [
        make_timeline_clip(all_shots[0], 0.0, 5.0),
        make_timeline_clip(all_shots[1], 5.0, 10.0),
    ]
    tl = Timeline(clips)
    kpi = _compute_kpi_summary(tl, all_shots, None)
    # 2 out of 3 events used
    assert abs(kpi["event_coverage"] - 2.0 / 3.0) < 0.01


def test_chapter_energy_structure():
    """_compute_chapter_energy returns per-chapter stats."""
    from tests.conftest import make_shot, make_timeline_clip
    from roughcut.editor.timeline import Timeline
    from roughcut.report.writer import _compute_chapter_energy

    shots = [make_shot(name=f"v{i}.mp4", face_score=0.5, motion_intensity=0.5) for i in range(3)]
    clips = [
        make_timeline_clip(shots[0], 0.0, 5.0, chapter="opening"),
        make_timeline_clip(shots[1], 5.0, 10.0, chapter="highlights"),
        make_timeline_clip(shots[2], 10.0, 15.0, chapter="highlights"),
    ]
    tl = Timeline(clips)
    energy = _compute_chapter_energy(tl)
    assert len(energy) == 2  # 2 chapters
    ch_names = {e["chapter"] for e in energy}
    assert "opening" in ch_names
    assert "highlights" in ch_names
    for entry in energy:
        assert "avg_emotion" in entry
        assert "peak_emotion" in entry
        assert "clip_count" in entry
        assert "highlight_count" in entry
