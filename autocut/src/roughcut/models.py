"""Core data models for the roughcut pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class MediaType(str, Enum):
    VIDEO = "video"
    PHOTO = "photo"
    MUSIC = "music"


class TransitionType(str, Enum):
    CUT = "cut"
    FADE_IN = "fade_in"
    FADE_OUT = "fade_out"
    CROSS_DISSOLVE = "cross_dissolve"


@dataclass
class MediaItem:
    """A single media file with metadata."""

    path: Path
    media_type: MediaType
    file_hash: str = ""
    file_size: int = 0
    # Video/photo metadata
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    fps: float = 0.0
    creation_time: str = ""
    # Optional
    gps_lat: float | None = None
    gps_lon: float | None = None
    # Proxy path for DNG
    proxy_path: Path | None = None

    @property
    def is_video(self) -> bool:
        return self.media_type == MediaType.VIDEO

    @property
    def is_photo(self) -> bool:
        return self.media_type == MediaType.PHOTO

    @property
    def is_music(self) -> bool:
        return self.media_type == MediaType.MUSIC


@dataclass
class QualityScores:
    """Quality assessment scores for a shot."""

    sharpness: float = 0.0       # 0-1, higher = sharper
    exposure: float = 0.0        # 0-1, higher = better exposed
    stability: float = 0.0       # 0-1, higher = more stable
    face_score: float = 0.0      # 0-1, higher = more/better faces
    motion_intensity: float = 0.0  # 0-1, higher = more dynamic

    @property
    def overall(self) -> float:
        return (
            self.sharpness * 0.2
            + self.exposure * 0.2
            + self.stability * 0.2
            + self.face_score * 0.2
            + self.motion_intensity * 0.2
        )


@dataclass
class Shot:
    """A segment within a video after shot boundary detection."""

    source: MediaItem
    start_sec: float
    end_sec: float
    quality: QualityScores = field(default_factory=QualityScores)
    shot_index: int = 0
    event_id: int = -1      # Assigned by event segmentation
    shot_role: str = ""      # Assigned by shot_role classifier
    highlight_score: float = 0.0    # 0-1, higher = more memorable moment
    highlight_reason: str = ""       # Why this is a highlight

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class MusicSection:
    """A structural section of a music track (verse, chorus, etc.)."""

    label: str           # "verse", "chorus", "bridge", "intro", "outro"
    start: float         # seconds
    end: float           # seconds
    avg_energy: float = 0.0  # 0-1 normalized energy level

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class BeatInfo:
    """Beat/rhythm information from music analysis."""

    beat_times: list[float] = field(default_factory=list)      # seconds
    downbeat_times: list[float] = field(default_factory=list)  # seconds
    tempo: float = 0.0  # BPM
    high_energy_ranges: list[tuple[float, float]] = field(default_factory=list)
    sections: list[MusicSection] = field(default_factory=list)
    energy_curve: list[tuple[float, float]] = field(default_factory=list)  # (time, energy) pairs

    def section_at(self, time: float) -> MusicSection | None:
        """Return the music section at a given time."""
        for s in self.sections:
            if s.start <= time < s.end:
                return s
        return None

    def energy_at(self, time: float) -> float:
        """Return interpolated energy at a given time."""
        if not self.energy_curve:
            return 0.5
        # Find surrounding points
        for i in range(len(self.energy_curve) - 1):
            t0, e0 = self.energy_curve[i]
            t1, e1 = self.energy_curve[i + 1]
            if t0 <= time <= t1:
                ratio = (time - t0) / (t1 - t0) if t1 != t0 else 0.0
                return e0 + ratio * (e1 - e0)
        # Outside range — return nearest
        if time <= self.energy_curve[0][0]:
            return self.energy_curve[0][1]
        return self.energy_curve[-1][1]


@dataclass
class TimelineClip:
    """A clip placed on the timeline."""

    shot: Shot
    timeline_start: float  # seconds on output timeline
    timeline_end: float
    in_point: float        # source in point (seconds)
    out_point: float       # source out point (seconds)
    transition_in: TransitionType = TransitionType.CUT
    transition_out: TransitionType = TransitionType.CUT
    transition_duration: float = 0.0  # seconds
    chapter: str = ""
    selection_reason: str = ""
    total_score: float = 0.0

    @property
    def timeline_duration(self) -> float:
        return self.timeline_end - self.timeline_start


@dataclass
class Chapter:
    """A chapter/section in the story template."""

    name: str
    ratio: float  # fraction of total duration (0-1)
    description: str = ""


@dataclass
class ClipDurationConfig:
    min: float = 1.5
    max: float = 6.0


@dataclass
class MusicConfig:
    mode: str = "single"
    file: str = ""


@dataclass
class RhythmConfig:
    snap_to_beat: bool = True
    tolerance_ms: int = 120


@dataclass
class OutputConfig:
    resolution: str = "1920x1080"
    fps: int = 30
    draft_bitrate_mbps: int = 12

    @property
    def width(self) -> int:
        return int(self.resolution.split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split("x")[1])


@dataclass
class DiversityConfig:
    """Controls for anti-repetition and diversity."""

    max_consecutive_same_source: int = 2      # Max clips from same source file in a row
    max_consecutive_same_event: int = 3       # Max clips from same event in a row
    max_consecutive_same_role: int = 2        # Max clips with same shot role in a row
    min_event_coverage: float = 0.3           # Min fraction of events that must be used (0-1)
    same_source_penalty: float = 0.15         # Score penalty for reusing same source
    same_angle_penalty: float = 0.10          # Score penalty for similar motion/role pattern
    chapter_repeat_penalty: float = 0.20      # Penalty for same source within a chapter


@dataclass
class ProjectConfig:
    """Project configuration loaded from YAML."""

    project_type: str = "growth"
    target_duration_sec: int = 240
    video_photo_ratio: list[int] = field(default_factory=lambda: [7, 3])
    clip_duration_sec: ClipDurationConfig = field(default_factory=ClipDurationConfig)
    max_same_event_streak_sec: int = 20
    music: MusicConfig = field(default_factory=MusicConfig)
    rhythm: RhythmConfig = field(default_factory=RhythmConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    diversity: DiversityConfig = field(default_factory=DiversityConfig)
    seed: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ProjectConfig:
        config = cls()
        config.project_type = data.get("project_type", config.project_type)
        config.target_duration_sec = data.get(
            "target_duration_sec", config.target_duration_sec
        )
        config.video_photo_ratio = data.get(
            "video_photo_ratio", config.video_photo_ratio
        )
        if "clip_duration_sec" in data:
            cd = data["clip_duration_sec"]
            config.clip_duration_sec = ClipDurationConfig(
                min=cd.get("min", 1.5), max=cd.get("max", 6.0)
            )
        config.max_same_event_streak_sec = data.get(
            "max_same_event_streak_sec", config.max_same_event_streak_sec
        )
        if "music" in data:
            m = data["music"]
            config.music = MusicConfig(
                mode=m.get("mode", "single"), file=m.get("file", "")
            )
        if "rhythm" in data:
            r = data["rhythm"]
            config.rhythm = RhythmConfig(
                snap_to_beat=r.get("snap_to_beat", True),
                tolerance_ms=r.get("tolerance_ms", 120),
            )
        if "output" in data:
            o = data["output"]
            config.output = OutputConfig(
                resolution=o.get("resolution", "1920x1080"),
                fps=o.get("fps", 30),
                draft_bitrate_mbps=o.get("draft_bitrate_mbps", 12),
            )
        if "diversity" in data:
            d = data["diversity"]
            config.diversity = DiversityConfig(
                max_consecutive_same_source=d.get("max_consecutive_same_source", 2),
                max_consecutive_same_event=d.get("max_consecutive_same_event", 3),
                max_consecutive_same_role=d.get("max_consecutive_same_role", 2),
                min_event_coverage=d.get("min_event_coverage", 0.3),
                same_source_penalty=d.get("same_source_penalty", 0.15),
                same_angle_penalty=d.get("same_angle_penalty", 0.10),
                chapter_repeat_penalty=d.get("chapter_repeat_penalty", 0.20),
            )
        config.seed = data.get("seed")
        return config
