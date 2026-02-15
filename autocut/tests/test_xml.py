"""Tests for FCP7 XML structure (Task 7.3)."""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roughcut.editor.timeline import Timeline
from roughcut.export.premiere_xml import export_fcp7_xml
from roughcut.models import MediaType
from tests.conftest import make_shot, make_timeline_clip


def _build_test_timeline(n_clips: int = 5) -> tuple[Timeline, list]:
    """Build a simple timeline with n_clips for testing XML export."""
    clips = []
    all_shots = []
    for i in range(n_clips):
        shot = make_shot(
            name=f"video_{i}.mp4",
            start=0.0,
            end=5.0,
            event_id=i % 3,
            shot_role=["establishing", "action", "reaction"][i % 3],
        )
        all_shots.append(shot)
        clip = make_timeline_clip(
            shot=shot,
            timeline_start=i * 5.0,
            timeline_end=(i + 1) * 5.0,
            chapter=["opening", "main", "closing"][i % 3],
        )
        clips.append(clip)

    # Add extra unselected shots for alt track testing
    for i in range(3):
        all_shots.append(make_shot(
            name=f"alt_{i}.mp4",
            start=0.0,
            end=5.0,
            event_id=i,
        ))

    return Timeline(clips), all_shots


class TestXMLStructure:
    """Test that exported XML has required FCP7 nodes."""

    @pytest.fixture(autouse=True)
    def setup_timeline(self, tmp_path):
        self.timeline, self.all_shots = _build_test_timeline()
        self.xml_path = tmp_path / "test_sequence.xml"
        export_fcp7_xml(
            self.timeline,
            self.xml_path,
            all_shots=self.all_shots,
        )
        self.tree = ET.parse(str(self.xml_path))
        self.root = self.tree.getroot()

    def test_root_is_xmeml(self):
        assert self.root.tag == "xmeml"
        assert self.root.attrib.get("version") == "5"

    def test_has_sequence(self):
        seq = self.root.find("sequence")
        assert seq is not None

    def test_sequence_has_name(self):
        name = self.root.find("sequence/name")
        assert name is not None
        assert name.text == "Roughcut Sequence"

    def test_sequence_has_duration(self):
        duration = self.root.find("sequence/duration")
        assert duration is not None
        assert int(duration.text) > 0

    def test_sequence_has_rate(self):
        rate = self.root.find("sequence/rate")
        assert rate is not None
        timebase = rate.find("timebase")
        assert timebase is not None
        assert int(timebase.text) == 30

    def test_has_video_track(self):
        tracks = self.root.findall(".//media/video/track")
        assert len(tracks) >= 1, "Should have at least one video track"

    def test_clipitems_exist(self):
        # Only count V1 track (first track)
        tracks = self.root.findall(".//media/video/track")
        v1_clips = tracks[0].findall("clipitem")
        assert len(v1_clips) == 5, f"Expected 5 clips on V1, got {len(v1_clips)}"

    def test_clipitem_has_required_fields(self):
        clipitem = self.root.find(".//media/video/track/clipitem")
        assert clipitem is not None
        for field in ("name", "enabled", "start", "end", "in", "out"):
            el = clipitem.find(field)
            assert el is not None, f"Missing <{field}> in clipitem"

    def test_clipitem_has_file_reference(self):
        clipitem = self.root.find(".//media/video/track/clipitem")
        file_el = clipitem.find("file")
        assert file_el is not None
        assert "id" in file_el.attrib

    def test_first_file_has_pathurl(self):
        """First file element should have full definition with pathurl."""
        file_el = self.root.find(".//media/video/track/clipitem/file/pathurl")
        assert file_el is not None
        assert file_el.text.startswith("file:")

    def test_has_timecode(self):
        tc = self.root.find("sequence/timecode")
        assert tc is not None
        assert tc.find("string") is not None
        assert tc.find("frame") is not None

    def test_has_chapter_markers(self):
        """Chapter markers should appear on the sequence."""
        markers = self.root.findall("sequence/marker")
        chapter_markers = [
            m for m in markers
            if m.find("name") is not None and "Chapter" in m.find("name").text
        ]
        assert len(chapter_markers) >= 1, "Should have chapter markers"

    def test_has_event_markers(self):
        """Event markers should appear on the sequence."""
        markers = self.root.findall("sequence/marker")
        event_markers = [
            m for m in markers
            if m.find("name") is not None and "Event" in m.find("name").text
        ]
        assert len(event_markers) >= 1, "Should have event markers"

    def test_marker_has_required_fields(self):
        marker = self.root.find("sequence/marker")
        assert marker is not None
        for field in ("name", "in", "out"):
            assert marker.find(field) is not None, f"Marker missing <{field}>"

    def test_has_alt_track(self):
        """Should have a second video track (V2) for alt candidates."""
        tracks = self.root.findall(".//media/video/track")
        assert len(tracks) >= 2, "Should have V1 + alt track"

    def test_alt_track_clips_disabled(self):
        """Alt track clips should be disabled by default."""
        tracks = self.root.findall(".//media/video/track")
        if len(tracks) < 2:
            pytest.skip("No alt track")
        alt_track = tracks[1]
        for clipitem in alt_track.findall("clipitem"):
            enabled = clipitem.find("enabled")
            assert enabled is not None
            assert enabled.text == "FALSE"


class TestXMLWithMusic:
    """Test XML export with music track."""

    def test_music_track(self, tmp_path):
        timeline, all_shots = _build_test_timeline(3)

        # Create a fake music file
        music_path = tmp_path / "music.mp3"
        music_path.write_bytes(b"fake mp3 data")

        xml_path = tmp_path / "test_music.xml"
        export_fcp7_xml(timeline, xml_path, music_path=music_path)

        tree = ET.parse(str(xml_path))
        root = tree.getroot()

        audio = root.find(".//media/audio")
        assert audio is not None
        audio_clip = root.find(".//media/audio/track/clipitem")
        assert audio_clip is not None
        name = audio_clip.find("name")
        assert name is not None
        assert name.text == "music"
