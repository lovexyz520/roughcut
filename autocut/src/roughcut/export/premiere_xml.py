"""FCP7 XML export for Adobe Premiere import."""

from __future__ import annotations

import logging
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from roughcut.constants import FCP7_NTSC, FCP7_TIMEBASE
from roughcut.editor.timeline import Timeline
from roughcut.models import TimelineClip, TransitionType

logger = logging.getLogger(__name__)


def _seconds_to_frames(seconds: float, timebase: int = FCP7_TIMEBASE) -> int:
    return int(round(seconds * timebase))


def _add_rate(parent: ET.Element, timebase: int = FCP7_TIMEBASE) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if FCP7_NTSC else "FALSE"


def _path_to_url(p: Path) -> str:
    """Convert a Path to a file:// URL that Premiere accepts."""
    abs_path = p.resolve()
    return abs_path.as_uri()


def _build_file_element(
    parent: ET.Element, clip: TimelineClip, file_id: str
) -> ET.Element:
    """Create a full <file> element for a media source."""
    file_el = ET.SubElement(parent, "file", id=file_id)
    source = clip.shot.source
    path = source.proxy_path or source.path

    ET.SubElement(file_el, "name").text = path.name
    ET.SubElement(file_el, "pathurl").text = _path_to_url(path)
    _add_rate(file_el)

    duration = source.duration_sec if source.duration_sec > 0 else clip.out_point
    ET.SubElement(file_el, "duration").text = str(_seconds_to_frames(duration))

    # Timecode
    timecode = ET.SubElement(file_el, "timecode")
    _add_rate(timecode)
    ET.SubElement(timecode, "string").text = "00:00:00:00"
    ET.SubElement(timecode, "frame").text = "0"
    ET.SubElement(timecode, "displayformat").text = "NDF"

    # Media description
    media = ET.SubElement(file_el, "media")
    video = ET.SubElement(media, "video")
    vs = ET.SubElement(video, "samplecharacteristics")
    _add_rate(vs)
    ET.SubElement(vs, "width").text = str(source.width or 1920)
    ET.SubElement(vs, "height").text = str(source.height or 1080)
    ET.SubElement(vs, "anamorphic").text = "FALSE"
    ET.SubElement(vs, "pixelaspectratio").text = "Square"
    ET.SubElement(vs, "fielddominance").text = "none"

    return file_el


def _build_clipitem(
    track: ET.Element,
    clip: TimelineClip,
    index: int,
    file_ids: dict[str, str],
    masterclip_ids: dict[str, str],
) -> None:
    """Build a <clipitem> element on a track."""
    clip_id = f"clipitem-{index + 1}"
    clipitem = ET.SubElement(track, "clipitem", id=clip_id)

    source_key = str(clip.shot.source.path)

    # Masterclip ID (Premiere uses this to group clips from same source)
    if source_key not in masterclip_ids:
        masterclip_ids[source_key] = f"masterclip-{len(masterclip_ids) + 1}"
    ET.SubElement(clipitem, "masterclipid").text = masterclip_ids[source_key]

    ET.SubElement(clipitem, "name").text = clip.shot.source.path.stem
    ET.SubElement(clipitem, "enabled").text = "TRUE"
    _add_rate(clipitem)

    ET.SubElement(clipitem, "start").text = str(
        _seconds_to_frames(clip.timeline_start)
    )
    ET.SubElement(clipitem, "end").text = str(
        _seconds_to_frames(clip.timeline_end)
    )
    ET.SubElement(clipitem, "in").text = str(
        _seconds_to_frames(clip.in_point)
    )
    ET.SubElement(clipitem, "out").text = str(
        _seconds_to_frames(clip.out_point)
    )

    # File reference (first occurrence gets full definition, rest just ref by id)
    if source_key not in file_ids:
        file_id = f"file-{len(file_ids) + 1}"
        file_ids[source_key] = file_id
        _build_file_element(clipitem, clip, file_id)
    else:
        ET.SubElement(clipitem, "file", id=file_ids[source_key])

    # Transitions
    if clip.transition_in != TransitionType.CUT:
        _add_transition_effect(clipitem, clip.transition_duration, start=True)
    if clip.transition_out != TransitionType.CUT:
        _add_transition_effect(clipitem, clip.transition_duration, start=False)


def _add_transition_effect(
    parent: ET.Element, duration: float, start: bool
) -> None:
    """Add a cross-dissolve transition effect."""
    dur_frames = _seconds_to_frames(duration)
    transitionitem = ET.SubElement(parent, "transitionitem")
    _add_rate(transitionitem)
    ET.SubElement(transitionitem, "start").text = str(0 if start else -1)
    ET.SubElement(transitionitem, "end").text = str(dur_frames)
    ET.SubElement(transitionitem, "alignment").text = "start" if start else "end"

    effect = ET.SubElement(transitionitem, "effect")
    ET.SubElement(effect, "name").text = "Cross Dissolve"
    ET.SubElement(effect, "effectid").text = "CrossDissolve"
    ET.SubElement(effect, "effecttype").text = "transition"
    ET.SubElement(effect, "mediatype").text = "video"


def _add_markers(
    sequence: ET.Element,
    timeline: Timeline,
) -> None:
    """Add three-layer markers to the sequence.

    Layer 1 (Blue): Chapter markers
    Layer 2 (Green): Event markers
    Layer 3 (Red): Highlight markers with why_selected
    """
    # Chapter markers
    chapters_seen: set[str] = set()
    for clip in timeline.clips:
        if clip.chapter and clip.chapter not in chapters_seen:
            chapters_seen.add(clip.chapter)
            marker = ET.SubElement(sequence, "marker")
            ET.SubElement(marker, "name").text = f"Chapter: {clip.chapter}"
            ET.SubElement(marker, "comment").text = f"Chapter start: {clip.chapter}"
            ET.SubElement(marker, "in").text = str(_seconds_to_frames(clip.timeline_start))
            ET.SubElement(marker, "out").text = "-1"
            ET.SubElement(marker, "color").text = "Blue"

    # Event markers (mark first clip of each event)
    events_seen: set[int] = set()
    for clip in timeline.clips:
        eid = clip.shot.event_id
        if eid >= 0 and eid not in events_seen:
            events_seen.add(eid)
            marker = ET.SubElement(sequence, "marker")
            ET.SubElement(marker, "name").text = f"Event {eid}"
            ET.SubElement(marker, "comment").text = f"Event {eid} start"
            ET.SubElement(marker, "in").text = str(_seconds_to_frames(clip.timeline_start))
            ET.SubElement(marker, "out").text = "-1"
            ET.SubElement(marker, "color").text = "Green"

    # Highlight markers (mark clips with high highlight score)
    for clip in timeline.clips:
        if clip.shot.highlight_score >= 0.5:
            marker = ET.SubElement(sequence, "marker")
            reason = clip.shot.highlight_reason or "highlight"
            ET.SubElement(marker, "name").text = f"Highlight: {reason}"
            comment = (
                f"{clip.shot.source.path.name} | "
                f"score={clip.total_score:.3f} | "
                f"{clip.selection_reason}"
            )
            ET.SubElement(marker, "comment").text = comment
            ET.SubElement(marker, "in").text = str(_seconds_to_frames(clip.timeline_start))
            ET.SubElement(marker, "out").text = "-1"
            ET.SubElement(marker, "color").text = "Red"


def _build_alt_track(
    video: ET.Element,
    timeline: Timeline,
    all_shots: list | None,
    file_ids: dict[str, str],
    masterclip_ids: dict[str, str],
) -> None:
    """Build an alternative shots track (V2) with runner-up candidates."""
    if not all_shots:
        return

    from roughcut.models import Shot

    # Build set of selected source keys
    selected_keys = {f"{c.shot.source.path}:{c.shot.start_sec}" for c in timeline.clips}

    # For each selected clip, find best unused alternative from same event
    alt_track = ET.SubElement(video, "track")
    alt_idx = len(timeline.clips)

    for clip in timeline.clips:
        # Find best alternative shot from same event that wasn't selected
        best_alt: Shot | None = None
        best_quality = -1.0
        for shot in all_shots:
            key = f"{shot.source.path}:{shot.start_sec}"
            if key in selected_keys:
                continue
            if shot.event_id == clip.shot.event_id and shot.event_id >= 0:
                if shot.quality.overall > best_quality:
                    best_quality = shot.quality.overall
                    best_alt = shot

        if best_alt is None:
            continue

        # Build a disabled clipitem on the alt track
        from roughcut.models import TimelineClip, TransitionType
        alt_clip = TimelineClip(
            shot=best_alt,
            timeline_start=clip.timeline_start,
            timeline_end=clip.timeline_end,
            in_point=best_alt.start_sec,
            out_point=min(best_alt.start_sec + clip.timeline_duration, best_alt.end_sec),
            chapter=clip.chapter,
            selection_reason="alt_candidate",
            total_score=best_quality,
        )

        clip_id = f"clipitem-alt-{alt_idx + 1}"
        clipitem = ET.SubElement(alt_track, "clipitem", id=clip_id)

        source_key = str(best_alt.source.path)
        if source_key not in masterclip_ids:
            masterclip_ids[source_key] = f"masterclip-{len(masterclip_ids) + 1}"
        ET.SubElement(clipitem, "masterclipid").text = masterclip_ids[source_key]

        ET.SubElement(clipitem, "name").text = f"[ALT] {best_alt.source.path.stem}"
        ET.SubElement(clipitem, "enabled").text = "FALSE"  # Disabled by default
        _add_rate(clipitem)

        ET.SubElement(clipitem, "start").text = str(_seconds_to_frames(alt_clip.timeline_start))
        ET.SubElement(clipitem, "end").text = str(_seconds_to_frames(alt_clip.timeline_end))
        ET.SubElement(clipitem, "in").text = str(_seconds_to_frames(alt_clip.in_point))
        ET.SubElement(clipitem, "out").text = str(_seconds_to_frames(alt_clip.out_point))

        if source_key not in file_ids:
            file_id = f"file-{len(file_ids) + 1}"
            file_ids[source_key] = file_id
            _build_file_element(clipitem, alt_clip, file_id)
        else:
            ET.SubElement(clipitem, "file", id=file_ids[source_key])

        alt_idx += 1


def export_fcp7_xml(
    timeline: Timeline,
    output_path: Path,
    sequence_name: str = "Roughcut Sequence",
    music_path: Path | None = None,
    all_shots: list | None = None,
) -> Path:
    """Export timeline as FCP7 XML compatible with Adobe Premiere.

    Args:
        timeline: The assembled timeline.
        output_path: Where to save the XML file.
        sequence_name: Name for the sequence.
        music_path: Optional music file to include as audio track.

    Returns:
        Path to the exported XML.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Root
    xmeml = ET.Element("xmeml", version="5")

    # Sequence
    sequence = ET.SubElement(xmeml, "sequence")
    ET.SubElement(sequence, "uuid").text = str(uuid.uuid4())
    ET.SubElement(sequence, "name").text = sequence_name
    ET.SubElement(sequence, "duration").text = str(
        _seconds_to_frames(timeline.duration)
    )
    _add_rate(sequence)

    # Sequence timecode
    tc = ET.SubElement(sequence, "timecode")
    _add_rate(tc)
    ET.SubElement(tc, "string").text = "00:00:00:00"
    ET.SubElement(tc, "frame").text = "0"
    ET.SubElement(tc, "displayformat").text = "NDF"

    # Media container
    media = ET.SubElement(sequence, "media")

    # === Video section ===
    video = ET.SubElement(media, "video")
    vformat = ET.SubElement(video, "format")
    sc = ET.SubElement(vformat, "samplecharacteristics")
    _add_rate(sc)
    ET.SubElement(sc, "width").text = "1920"
    ET.SubElement(sc, "height").text = "1080"
    ET.SubElement(sc, "anamorphic").text = "FALSE"
    ET.SubElement(sc, "pixelaspectratio").text = "Square"
    ET.SubElement(sc, "fielddominance").text = "none"

    # Video track (V1 — selected clips)
    track = ET.SubElement(video, "track")
    file_ids: dict[str, str] = {}
    masterclip_ids: dict[str, str] = {}

    for i, clip in enumerate(timeline.clips):
        _build_clipitem(track, clip, i, file_ids, masterclip_ids)

    # Video track (V2 — alt candidates, disabled)
    _build_alt_track(video, timeline, all_shots, file_ids, masterclip_ids)

    # Markers (chapters + events)
    _add_markers(sequence, timeline)

    # === Audio section (music) ===
    if music_path and music_path.exists():
        audio = ET.SubElement(media, "audio")

        # Audio format
        audio_fmt = ET.SubElement(audio, "format")
        asc = ET.SubElement(audio_fmt, "samplecharacteristics")
        ET.SubElement(asc, "depth").text = "16"
        ET.SubElement(asc, "samplerate").text = "48000"

        audio_track = ET.SubElement(audio, "track")
        audio_clip = ET.SubElement(audio_track, "clipitem", id="music-1")
        ET.SubElement(audio_clip, "masterclipid").text = "masterclip-music-1"
        ET.SubElement(audio_clip, "name").text = music_path.stem
        ET.SubElement(audio_clip, "enabled").text = "TRUE"
        _add_rate(audio_clip)
        ET.SubElement(audio_clip, "start").text = "0"
        ET.SubElement(audio_clip, "end").text = str(
            _seconds_to_frames(timeline.duration)
        )
        ET.SubElement(audio_clip, "in").text = "0"
        ET.SubElement(audio_clip, "out").text = str(
            _seconds_to_frames(timeline.duration)
        )

        music_file = ET.SubElement(audio_clip, "file", id="music-file-1")
        ET.SubElement(music_file, "name").text = music_path.name
        ET.SubElement(music_file, "pathurl").text = _path_to_url(music_path)
        _add_rate(music_file)

        music_tc = ET.SubElement(music_file, "timecode")
        _add_rate(music_tc)
        ET.SubElement(music_tc, "string").text = "00:00:00:00"
        ET.SubElement(music_tc, "frame").text = "0"
        ET.SubElement(music_tc, "displayformat").text = "NDF"

        music_media = ET.SubElement(music_file, "media")
        music_audio = ET.SubElement(music_media, "audio")
        music_asc = ET.SubElement(music_audio, "samplecharacteristics")
        ET.SubElement(music_asc, "depth").text = "16"
        ET.SubElement(music_asc, "samplerate").text = "48000"
        ET.SubElement(music_audio, "channelcount").text = "2"

    # Write XML
    tree = ET.ElementTree(xmeml)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)

    logger.info("Exported FCP7 XML: %s (%d clips)", output_path, len(timeline.clips))
    return output_path
