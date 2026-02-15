"""Music beat, section, and energy analysis using librosa."""

from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

from roughcut.models import BeatInfo, MusicSection

logger = logging.getLogger(__name__)


def analyze_beats(music_path: Path) -> BeatInfo:
    """Analyze a music file for beats, sections, and energy curve.

    Args:
        music_path: Path to the music file.

    Returns:
        BeatInfo with beats, sections, energy curve, and high-energy ranges.
    """
    logger.info("Analyzing beats for: %s", music_path.name)

    y, sr = librosa.load(str(music_path), sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # Tempo and beat detection
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    # Estimate downbeats (every 4th beat as heuristic)
    downbeat_times = beat_times[::4] if beat_times else []

    # RMS energy (used by multiple analyses)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    # Energy curve (downsampled to ~1 point per second)
    energy_curve = _compute_energy_curve(rms, rms_times)

    # High-energy ranges
    high_energy_ranges = _detect_high_energy_segments(rms, rms_times, duration)

    # Section detection
    sections = _detect_sections(y, sr, rms, rms_times, duration)

    # Handle tempo being an array
    tempo_val = float(tempo) if np.isscalar(tempo) else float(tempo[0])

    info = BeatInfo(
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        tempo=tempo_val,
        high_energy_ranges=high_energy_ranges,
        sections=sections,
        energy_curve=energy_curve,
    )

    logger.info(
        "Found %d beats, tempo=%.1f BPM, %d sections, %d high-energy segments",
        len(beat_times),
        info.tempo,
        len(sections),
        len(high_energy_ranges),
    )
    for sec in sections:
        logger.info(
            "  Section: %s [%.1f-%.1f] energy=%.2f",
            sec.label, sec.start, sec.end, sec.avg_energy,
        )
    return info


def _compute_energy_curve(
    rms: np.ndarray, rms_times: np.ndarray
) -> list[tuple[float, float]]:
    """Downsample RMS energy to ~1 point per second, normalized 0-1."""
    if len(rms) == 0:
        return [(0.0, 0.5)]

    # Normalize RMS to 0-1
    rms_max = rms.max()
    if rms_max > 0:
        rms_norm = rms / rms_max
    else:
        rms_norm = rms

    # Downsample: pick every ~1 second
    hop_sec = rms_times[1] - rms_times[0] if len(rms_times) > 1 else 0.023
    step = max(1, int(1.0 / hop_sec))

    curve = []
    for i in range(0, len(rms_norm), step):
        # Average over the window
        window = rms_norm[i : i + step]
        curve.append((float(rms_times[i]), float(window.mean())))

    return curve


def _detect_high_energy_segments(
    rms: np.ndarray,
    rms_times: np.ndarray,
    duration: float,
    threshold_percentile: float = 75,
) -> list[tuple[float, float]]:
    """Find time ranges with above-threshold energy."""
    threshold = np.percentile(rms, threshold_percentile)
    is_high = rms > threshold
    ranges: list[tuple[float, float]] = []
    start = None

    for i, high in enumerate(is_high):
        if high and start is None:
            start = rms_times[i]
        elif not high and start is not None:
            end = rms_times[i]
            if end - start >= 2.0:
                ranges.append((float(start), float(end)))
            start = None

    if start is not None:
        end = min(float(rms_times[-1]), duration)
        if end - start >= 2.0:
            ranges.append((float(start), float(end)))

    return ranges


def _detect_sections(
    y: np.ndarray,
    sr: int,
    rms: np.ndarray,
    rms_times: np.ndarray,
    duration: float,
) -> list[MusicSection]:
    """Detect music sections using structural segmentation.

    Uses self-similarity matrix + spectral clustering to find boundaries,
    then labels sections by energy profile (chorus=high, verse=low, etc.).
    """
    # Compute features for structural analysis
    try:
        # Chroma + MFCC for structural similarity
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=512)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=512)

        # Stack features
        features = np.vstack([
            librosa.util.normalize(chroma),
            librosa.util.normalize(mfcc),
        ])

        # Self-similarity via recurrence matrix
        rec = librosa.segment.recurrence_matrix(
            features, width=3, mode="affinity", sym=True
        )

        # Laplacian segmentation to find boundaries
        # k=number of sections to find; estimate based on duration
        n_sections = max(4, min(8, int(duration / 20)))
        bound_frames = librosa.segment.agglomerative(features, k=n_sections)
        bound_times = librosa.frames_to_time(bound_frames, sr=sr, hop_length=512)
        bound_times = np.unique(bound_times)

        # Filter: merge very short sections (< 6 seconds for stability)
        bound_times = _merge_short_boundaries(bound_times, duration, min_sec=6.0)

    except Exception as e:
        logger.warning("Section detection failed, using energy-based fallback: %s", e)
        bound_times = _energy_based_boundaries(rms, rms_times, duration)

    # Build sections with labels based on energy
    sections = _label_sections(bound_times, duration, rms, rms_times)
    return sections


def _merge_short_boundaries(
    bounds: np.ndarray, duration: float, min_sec: float = 4.0
) -> np.ndarray:
    """Merge boundaries that are too close together."""
    if len(bounds) < 2:
        return bounds

    merged = [0.0]
    for t in bounds:
        if t - merged[-1] >= min_sec:
            merged.append(float(t))

    # Ensure we don't have too many sections (cap at ~8)
    if len(merged) > 9:
        # Keep evenly spaced subset
        indices = np.linspace(0, len(merged) - 1, 9, dtype=int)
        merged = [merged[i] for i in indices]

    return np.array(merged)


def _energy_based_boundaries(
    rms: np.ndarray, rms_times: np.ndarray, duration: float
) -> np.ndarray:
    """Fallback: split song into sections by energy changes."""
    if len(rms) < 10:
        return np.array([0.0, duration])

    # Smooth energy and find significant changes
    window = min(50, len(rms) // 4)
    if window < 3:
        return np.array([0.0, duration])

    smoothed = np.convolve(rms, np.ones(window) / window, mode="same")
    diff = np.abs(np.diff(smoothed))

    # Find peaks in energy difference (section boundaries)
    threshold = np.percentile(diff, 85)
    peaks = np.where(diff > threshold)[0]

    if len(peaks) == 0:
        return np.array([0.0, duration])

    # Cluster nearby peaks
    boundaries = [0.0]
    last = -100
    for p in peaks:
        t = float(rms_times[p])
        if t - boundaries[-1] >= 8.0:  # Min 8 seconds between boundaries
            boundaries.append(t)
            last = p

    return np.array(boundaries)


def _label_sections(
    bound_times: np.ndarray,
    duration: float,
    rms: np.ndarray,
    rms_times: np.ndarray,
) -> list[MusicSection]:
    """Label sections based on their energy profile."""
    sections: list[MusicSection] = []

    # Build section time ranges
    all_bounds = list(bound_times) + [duration]
    all_bounds = sorted(set(all_bounds))
    if all_bounds[0] > 0.5:
        all_bounds.insert(0, 0.0)

    # Compute average energy per section
    rms_max = rms.max() if rms.max() > 0 else 1.0
    rms_norm = rms / rms_max

    for i in range(len(all_bounds) - 1):
        start = all_bounds[i]
        end = all_bounds[i + 1]
        if end - start < 1.0:
            continue

        # Average energy in this range
        mask = (rms_times >= start) & (rms_times < end)
        avg_energy = float(rms_norm[mask].mean()) if mask.any() else 0.5

        sections.append(MusicSection(
            label="",  # Will be labeled below
            start=start,
            end=end,
            avg_energy=avg_energy,
        ))

    if not sections:
        return [MusicSection(label="verse", start=0.0, end=duration, avg_energy=0.5)]

    # Label by energy: intro/outro at edges, chorus=high energy, verse=low
    _assign_labels(sections)
    return sections


def _assign_labels(sections: list[MusicSection]) -> None:
    """Assign structural labels based on position and energy."""
    if not sections:
        return

    energies = [s.avg_energy for s in sections]
    median_energy = float(np.median(energies))

    for i, sec in enumerate(sections):
        # First section: intro if short enough
        if i == 0 and sec.duration < 15.0:
            sec.label = "intro"
        # Last section: outro if short enough
        elif i == len(sections) - 1 and sec.duration < 15.0:
            sec.label = "outro"
        # High energy = chorus
        elif sec.avg_energy > median_energy * 1.15:
            sec.label = "chorus"
        # Low energy = verse
        elif sec.avg_energy < median_energy * 0.85:
            sec.label = "verse"
        else:
            sec.label = "bridge"

    # Avoid consecutive same labels — alternate verse/bridge
    for i in range(1, len(sections)):
        if sections[i].label == sections[i - 1].label and sections[i].label in ("verse", "bridge"):
            sections[i].label = "bridge" if sections[i - 1].label == "verse" else "verse"
