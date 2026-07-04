"""Event segmentation: group shots by temporal proximity of their source media."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from roughcut.models import Shot

logger = logging.getLogger(__name__)

# Default gap threshold: if two consecutive files are > 30 min apart, new event
DEFAULT_EVENT_GAP_SEC = 30 * 60


@dataclass
class EventSummary:
    """Summary statistics for a single event group."""

    event_id: int
    shot_count: int = 0
    total_duration: float = 0.0
    avg_quality: float = 0.0
    time_range: str = ""
    emotion_intensity: float = 0.0  # Based on face + motion scores
    rank_score: float = 0.0  # Overall event ranking score


def _parse_creation_time(time_str: str) -> datetime | None:
    """Parse creation_time from ffprobe metadata."""
    if not time_str:
        return None
    # Common formats from ffprobe / Apple QuickTime
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    return None


def assign_events(
    shots: list[Shot],
    gap_threshold_sec: float = DEFAULT_EVENT_GAP_SEC,
) -> list[Shot]:
    """Assign event_id to each shot based on source creation time continuity.

    Shots from the same source file share an event. Events are split when
    the time gap between consecutive sources exceeds gap_threshold_sec.

    Args:
        shots: All shots (will be modified in-place).
        gap_threshold_sec: Max gap in seconds before starting a new event.

    Returns:
        The same list with event_id assigned.
    """
    if not shots:
        return shots

    # Collect unique sources, sorted by creation time
    source_times: dict[str, datetime | None] = {}
    for shot in shots:
        key = str(shot.source.path)
        if key not in source_times:
            source_times[key] = _parse_creation_time(shot.source.creation_time)

    # Sort sources by creation time (None last)
    sorted_sources = sorted(
        source_times.items(),
        key=lambda x: (x[1] is None, x[1] or datetime.min),
    )

    # Assign event IDs based on time gaps
    source_to_event: dict[str, int] = {}
    current_event = 0
    prev_time: datetime | None = None

    for source_key, creation_time in sorted_sources:
        if creation_time is not None and prev_time is not None:
            gap = (creation_time - prev_time).total_seconds()
            if gap > gap_threshold_sec:
                current_event += 1
        elif prev_time is None and creation_time is not None:
            pass  # First source with valid time
        elif creation_time is None and prev_time is not None:
            current_event += 1  # Unknown time = new event

        source_to_event[source_key] = current_event
        if creation_time is not None:
            prev_time = creation_time

    # Assign to shots
    for shot in shots:
        key = str(shot.source.path)
        shot.event_id = source_to_event.get(key, 0)

    event_count = current_event + 1
    logger.info("Assigned %d events across %d shots", event_count, len(shots))
    return shots


def summarize_events(shots: list[Shot]) -> list[EventSummary]:
    """Generate per-event summary statistics."""
    events: dict[int, list[Shot]] = {}
    for shot in shots:
        events.setdefault(shot.event_id, []).append(shot)

    summaries = []
    for event_id in sorted(events.keys()):
        event_shots = events[event_id]
        total_dur = sum(s.duration_sec for s in event_shots)
        avg_q = sum(s.quality.overall for s in event_shots) / len(event_shots)

        # Emotion intensity: real emotion proxy (smile/audio-driven, with a
        # face+motion fallback baked into QualityScores.emotion)
        emotion = sum(s.quality.emotion for s in event_shots) / len(event_shots)

        # Time range from source creation times
        times = [
            _parse_creation_time(s.source.creation_time)
            for s in event_shots
            if s.source.creation_time
        ]
        times = [t for t in times if t is not None]
        if times:
            time_range = f"{min(times).strftime('%H:%M')} - {max(times).strftime('%H:%M')}"
        else:
            time_range = "unknown"

        summaries.append(EventSummary(
            event_id=event_id,
            shot_count=len(event_shots),
            total_duration=total_dur,
            avg_quality=avg_q,
            time_range=time_range,
            emotion_intensity=emotion,
        ))

    return summaries


def rank_events(summaries: list[EventSummary]) -> list[EventSummary]:
    """Rank events by quality, emotion intensity, and shot variety.

    Higher rank_score = more suitable for inclusion.
    """
    if not summaries:
        return summaries

    # Normalize across events
    max_quality = max(s.avg_quality for s in summaries) or 1.0
    max_emotion = max(s.emotion_intensity for s in summaries) or 1.0
    max_shots = max(s.shot_count for s in summaries) or 1

    for s in summaries:
        norm_q = s.avg_quality / max_quality
        norm_e = s.emotion_intensity / max_emotion
        # Shot variety: more shots = more flexibility for arc construction
        norm_variety = min(s.shot_count / max_shots, 1.0)
        s.rank_score = norm_q * 0.4 + norm_e * 0.35 + norm_variety * 0.25

    summaries.sort(key=lambda s: s.rank_score, reverse=True)
    logger.info("Event ranking: %s", [(s.event_id, f"{s.rank_score:.2f}") for s in summaries])
    return summaries


def get_event_shots(shots: list[Shot], event_id: int) -> list[Shot]:
    """Return all shots belonging to a specific event."""
    return [s for s in shots if s.event_id == event_id]


def sort_events_chronological(summaries: list[EventSummary]) -> list[EventSummary]:
    """Sort events by time_range (earliest first) for chronological narrative."""
    def _time_key(es: EventSummary) -> str:
        if es.time_range == "unknown":
            return "99:99"
        return es.time_range.split(" - ")[0]

    return sorted(summaries, key=_time_key)


def sort_events_by_energy(summaries: list[EventSummary]) -> list[EventSummary]:
    """Sort events by emotion intensity (low→high) for energy-first narrative."""
    return sorted(summaries, key=lambda s: s.emotion_intensity)


def order_events_for_narrative(
    summaries: list[EventSummary],
    mode: str = "chronological",
) -> list[EventSummary]:
    """Order events based on narrative mode.

    Args:
        summaries: Ranked event summaries.
        mode: "chronological" (time order), "energy_first" (low→high energy),
              or "hybrid" (chronological with energy boost at middle).

    Returns:
        Ordered event summaries.
    """
    if mode == "energy_first":
        return sort_events_by_energy(summaries)

    if mode == "hybrid":
        # Chronological order, but move highest-energy event to ~60% position
        chrono = sort_events_chronological(summaries)
        if len(chrono) >= 3:
            # Find highest energy event
            max_idx = max(range(len(chrono)), key=lambda i: chrono[i].emotion_intensity)
            peak = chrono.pop(max_idx)
            insert_pos = int(len(chrono) * 0.6)
            chrono.insert(insert_pos, peak)
        return chrono

    # Default: chronological
    return sort_events_chronological(summaries)


def build_event_arc(event_shots: list[Shot]) -> dict[str, list[Shot]]:
    """Organize shots within an event into an arc structure.

    Returns dict with keys: establishing, action, reaction, detail.
    Each shot is placed into its best-fitting role bucket.
    """
    arc: dict[str, list[Shot]] = {
        "establishing": [],
        "action": [],
        "reaction": [],
        "detail": [],
    }
    for shot in event_shots:
        role = shot.shot_role or "detail"
        if role in arc:
            arc[role].append(shot)
        else:
            arc["detail"].append(shot)

    # Sort each bucket by quality (best first)
    for role in arc:
        arc[role].sort(key=lambda s: s.quality.overall, reverse=True)

    return arc
