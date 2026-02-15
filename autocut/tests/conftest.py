"""Shared test fixtures for roughcut tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.models import (
    BeatInfo,
    Chapter,
    DiversityConfig,
    MediaItem,
    MediaType,
    MusicSection,
    OutputConfig,
    ProjectConfig,
    QualityScores,
    Shot,
    TimelineClip,
    TransitionType,
)


def make_media(
    name: str = "clip.mp4",
    media_type: MediaType = MediaType.VIDEO,
    width: int = 1920,
    height: int = 1080,
    duration_sec: float = 10.0,
    creation_time: str = "",
) -> MediaItem:
    return MediaItem(
        path=Path(f"/fake/{name}"),
        media_type=media_type,
        width=width,
        height=height,
        duration_sec=duration_sec,
        creation_time=creation_time,
    )


def make_shot(
    name: str = "clip.mp4",
    start: float = 0.0,
    end: float = 5.0,
    sharpness: float = 0.7,
    exposure: float = 0.7,
    stability: float = 0.7,
    face_score: float = 0.3,
    motion_intensity: float = 0.3,
    event_id: int = 0,
    shot_role: str = "",
    media_type: MediaType = MediaType.VIDEO,
    creation_time: str = "",
    width: int = 1920,
    height: int = 1080,
) -> Shot:
    media = make_media(
        name=name,
        media_type=media_type,
        duration_sec=end,
        creation_time=creation_time,
        width=width,
        height=height,
    )
    return Shot(
        source=media,
        start_sec=start,
        end_sec=end,
        quality=QualityScores(
            sharpness=sharpness,
            exposure=exposure,
            stability=stability,
            face_score=face_score,
            motion_intensity=motion_intensity,
        ),
        event_id=event_id,
        shot_role=shot_role,
    )


def make_timeline_clip(
    shot: Shot | None = None,
    timeline_start: float = 0.0,
    timeline_end: float = 5.0,
    chapter: str = "main",
) -> TimelineClip:
    if shot is None:
        shot = make_shot()
    return TimelineClip(
        shot=shot,
        timeline_start=timeline_start,
        timeline_end=timeline_end,
        in_point=shot.start_sec,
        out_point=shot.start_sec + (timeline_end - timeline_start),
        chapter=chapter,
        selection_reason="test",
        total_score=0.5,
    )


@pytest.fixture
def default_config() -> ProjectConfig:
    return ProjectConfig(
        project_type="growth",
        target_duration_sec=60,
        video_photo_ratio=[7, 3],
        seed=42,
    )


@pytest.fixture
def travel_config() -> ProjectConfig:
    return ProjectConfig(
        project_type="travel",
        target_duration_sec=60,
        video_photo_ratio=[8, 2],
        seed=42,
    )


@pytest.fixture
def sample_shots() -> list[Shot]:
    """Create a diverse set of shots for testing planners."""
    shots = []
    # 5 different source files, 3 shots each, different events
    for i in range(5):
        event_id = i // 2  # events: 0, 0, 1, 1, 2
        for j in range(3):
            shots.append(make_shot(
                name=f"video_{i}.mp4",
                start=j * 5.0,
                end=(j + 1) * 5.0,
                sharpness=0.5 + (i % 3) * 0.15,
                exposure=0.6 + (j % 2) * 0.2,
                stability=0.7,
                face_score=0.2 + (i % 2) * 0.4,
                motion_intensity=0.2 + (j % 3) * 0.2,
                event_id=event_id,
                shot_role=["establishing", "action", "reaction", "detail"][j % 4],
                creation_time=f"2025-01-01T{10+i}:{j*20:02d}:00Z",
            ))
    # Add a few photo shots
    for i in range(3):
        shots.append(make_shot(
            name=f"photo_{i}.jpg",
            start=0.0,
            end=4.0,
            sharpness=0.8,
            exposure=0.7,
            stability=1.0,
            face_score=0.1 * i,
            motion_intensity=0.0,
            event_id=i,
            shot_role="detail",
            media_type=MediaType.PHOTO,
            creation_time=f"2025-01-01T{12+i}:00:00Z",
        ))
    return shots


@pytest.fixture
def sample_beat_info() -> BeatInfo:
    """Create sample beat info for testing rhythm alignment."""
    return BeatInfo(
        beat_times=[i * 0.5 for i in range(120)],  # beat every 0.5s for 60s
        downbeat_times=[i * 2.0 for i in range(30)],
        tempo=120.0,
        high_energy_ranges=[(15.0, 25.0), (40.0, 50.0)],
        sections=[
            MusicSection("intro", 0.0, 10.0, avg_energy=0.3),
            MusicSection("verse", 10.0, 25.0, avg_energy=0.5),
            MusicSection("chorus", 25.0, 40.0, avg_energy=0.8),
            MusicSection("verse", 40.0, 50.0, avg_energy=0.5),
            MusicSection("outro", 50.0, 60.0, avg_energy=0.3),
        ],
        energy_curve=[(i, 0.3 + 0.5 * (i / 60)) for i in range(0, 61, 5)],
    )
