"""Source-audio analysis: extract highlight signals from a clip's *own* audio.

The music track was already analysed for beats; here we mine the raw audio that
came with each video shot. Laughter, an excited "wow!", clapping and speech are
among the strongest indicators of a memorable moment, and until now they were
completely ignored.

Extraction goes through ffmpeg (already a hard dependency) as raw float PCM over
a pipe — no temp files. Feature extraction uses numpy/librosa (already present).
"""

from __future__ import annotations

import logging
import subprocess

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# RMS reference: ~ -20 dBFS full-scale conversational level maps to ~1.0.
_RMS_REF = 0.15


def _extract_pcm(video_path: str, start_sec: float, end_sec: float) -> np.ndarray | None:
    """Extract a mono float32 PCM segment via ffmpeg. Returns None on failure/no audio."""
    dur = max(0.0, end_sec - start_sec)
    if dur <= 0.05:
        return None
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-ss", f"{start_sec:.3f}", "-t", f"{dur:.3f}",
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "f32le", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("Audio extraction failed for %s: %s", video_path, e)
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None  # No audio stream, or ffmpeg error.
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if samples.size < SAMPLE_RATE // 10:  # < 0.1s of audio
        return None
    return samples


def analyze_source_audio(
    video_path: str, start_sec: float, end_sec: float
) -> tuple[float, float]:
    """Return (audio_energy, laughter_score), each 0-1.

    - audio_energy: overall loudness of the shot's own audio (RMS-based).
    - laughter_score: heuristic for laughter/excitement — loud, mid-band,
      rapidly modulated audio. Not a trained classifier, but a strong-enough
      proxy to surface the clips where people are audibly delighted.
    """
    samples = _extract_pcm(video_path, start_sec, end_sec)
    if samples is None:
        return 0.0, 0.0

    # --- Loudness ---
    rms = float(np.sqrt(np.mean(samples ** 2)))
    audio_energy = float(np.clip(rms / _RMS_REF, 0.0, 1.0))
    if audio_energy < 0.05:  # essentially silence
        return audio_energy, 0.0

    # --- Laughter / excitement heuristic ---
    # 1) Amplitude modulation: laughter comes in rapid bursts (~4-8 Hz).
    frame = int(SAMPLE_RATE * 0.03)  # 30 ms
    hop = int(SAMPLE_RATE * 0.015)   # 15 ms
    if samples.size < frame * 4:
        return audio_energy, 0.0
    envelope = np.array([
        np.sqrt(np.mean(samples[i:i + frame] ** 2))
        for i in range(0, samples.size - frame, hop)
    ])
    if envelope.size < 4 or envelope.max() <= 1e-6:
        return audio_energy, 0.0
    env_norm = envelope / envelope.max()
    # Modulation depth: how much the envelope swings (bursty vs steady).
    modulation = float(np.clip(np.std(env_norm) * 2.5, 0.0, 1.0))

    # 2) Burst rate: count envelope peaks per second (laughter is fast).
    mean_env = float(np.mean(env_norm))
    crossings = np.sum((env_norm[:-1] < mean_env) & (env_norm[1:] >= mean_env))
    seg_dur = envelope.size * hop / SAMPLE_RATE
    burst_rate = crossings / max(seg_dur, 1e-3)  # peaks per second
    burst_score = float(np.clip((burst_rate - 1.5) / 6.0, 0.0, 1.0))  # 1.5-7.5 Hz band

    # 3) Mid-band brightness: voice/laughter energy sits above rumble.
    centroid = _spectral_centroid(samples)
    band_score = float(np.clip((centroid - 400.0) / 2600.0, 0.0, 1.0))  # 400-3000 Hz

    laughter = audio_energy * (0.45 * modulation + 0.35 * burst_score + 0.20 * band_score)
    return audio_energy, float(np.clip(laughter, 0.0, 1.0))


def _spectral_centroid(samples: np.ndarray) -> float:
    """Rough spectral centroid in Hz (numpy-only, robust to short segments)."""
    windowed = samples * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / SAMPLE_RATE)
    total = spectrum.sum()
    if total <= 1e-9:
        return 0.0
    return float(np.sum(freqs * spectrum) / total)
