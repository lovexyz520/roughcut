"""Draft MP4 output using FFmpeg."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from roughcut.editor.ken_burns import random_ken_burns
from roughcut.editor.timeline import Timeline
from roughcut.models import OutputConfig, TimelineClip, TransitionType

logger = logging.getLogger(__name__)


def _resolve_path(p: Path) -> str:
    """Resolve to absolute path string for FFmpeg."""
    return str(p.resolve())


def build_clip_command(
    clip: TimelineClip, output_config: OutputConfig, temp_dir: Path, idx: int
) -> Path | None:
    """Render a single clip to a temp file. Returns None on failure."""
    out_path = temp_dir / f"clip_{idx:04d}.mp4"
    w, h = output_config.width, output_config.height
    fps = output_config.fps

    if clip.shot.source.is_photo:
        # Photo: DNG must use proxy; other formats use proxy if available
        if clip.shot.source.path.suffix.lower() == ".dng":
            if not clip.shot.source.proxy_path:
                logger.warning("Skipping DNG without proxy: %s", clip.shot.source.path.name)
                return None
            source_path = clip.shot.source.proxy_path
        else:
            source_path = clip.shot.source.proxy_path or clip.shot.source.path
        abs_path = _resolve_path(source_path)

        # Photo -> video with Ken Burns zoompan
        kb = random_ken_burns(clip.timeline_duration)
        kb_filter = kb.ffmpeg_filter(w, h)

        bitrate = f"{output_config.draft_bitrate_mbps}M"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", abs_path,
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,{kb_filter}",
            "-c:v", "libx264", "-preset", "fast",
            "-b:v", bitrate,
            "-pix_fmt", "yuv420p",
            "-t", str(clip.timeline_duration),
            "-r", str(fps),
            str(out_path),
        ]
    else:
        # Video: trim and scale
        duration = clip.out_point - clip.in_point
        abs_path = _resolve_path(clip.shot.source.path)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        bitrate = f"{output_config.draft_bitrate_mbps}M"

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip.in_point),
            "-i", abs_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast",
            "-b:v", bitrate,
            "-an",
            "-r", str(fps),
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]

    logger.debug("Rendering clip %d: %s", idx, " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        logger.error("FFmpeg failed for clip %d: %s", idx, result.stderr.decode(errors="replace")[:500])
        return None

    # Verify output has content
    if not out_path.exists() or out_path.stat().st_size < 1000:
        logger.error("Clip %d output is empty or too small", idx)
        return None

    return out_path


def render_draft(
    timeline: Timeline,
    output_path: Path,
    output_config: OutputConfig,
    music_path: Path | None = None,
) -> Path:
    """Render the full timeline to a draft MP4.

    Args:
        timeline: The assembled timeline.
        output_path: Where to save the output file.
        output_config: Resolution, FPS, bitrate settings.
        music_path: Optional background music file.

    Returns:
        Path to the rendered draft.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="roughcut_") as temp_dir:
        temp = Path(temp_dir)
        clip_files: list[Path] = []

        # Render each clip
        for i, clip in enumerate(timeline.clips):
            logger.info("Rendering clip %d/%d: %s", i + 1, len(timeline.clips), clip.shot.source.path.name)
            clip_file = build_clip_command(clip, output_config, temp, i)
            if clip_file is not None:
                clip_files.append(clip_file)
            else:
                logger.warning("Skipped clip %d/%d", i + 1, len(timeline.clips))

        if not clip_files:
            logger.error("No clips rendered, cannot create draft")
            return output_path

        logger.info("Successfully rendered %d/%d clips", len(clip_files), len(timeline.clips))

        # Create concat file
        concat_file = temp / "concat.txt"
        with open(concat_file, "w") as f:
            for cf in clip_files:
                f.write(f"file '{cf}'\n")

        # Concat all clips — re-encode to ensure uniform format
        concat_output = temp / "concat.mp4"
        bitrate = f"{output_config.draft_bitrate_mbps}M"
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast",
            "-b:v", bitrate,
            "-pix_fmt", "yuv420p",
            "-r", str(output_config.fps),
            "-movflags", "+faststart",
            str(concat_output),
        ]
        logger.info("Concatenating %d clips...", len(clip_files))
        result = subprocess.run(concat_cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            logger.error("Concat failed: %s", result.stderr.decode(errors="replace")[:500])
            return output_path

        # Add music if provided
        if music_path and music_path.exists():
            music_abs = _resolve_path(music_path)
            logger.info("Adding music track: %s", music_path.name)
            final_cmd = [
                "ffmpeg", "-y",
                "-i", str(concat_output),
                "-i", music_abs,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                "-map", "0:v:0", "-map", "1:a:0",
                str(output_path),
            ]
        else:
            final_cmd = [
                "ffmpeg", "-y",
                "-i", str(concat_output),
                "-c", "copy",
                str(output_path),
            ]

        result = subprocess.run(final_cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            logger.error("Final render failed: %s", result.stderr.decode(errors="replace")[:500])
        else:
            logger.info("Draft rendered: %s", output_path)

    return output_path
