"""Main pipeline orchestrating all stages: ingest -> analyze -> plan -> edit -> export -> report."""

from __future__ import annotations

import csv
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from roughcut.analyze.beat import analyze_beats
from roughcut.analyze.quality import score_shot
from roughcut.analyze.shot_detect import detect_shots, detect_shots_for_photo
from roughcut.analyze.shot_role import assign_roles
from roughcut.constants import DEFAULT_PHOTO_DURATION_SEC
from roughcut.editor.timeline import build_timeline
from roughcut.export.draft import render_draft
from roughcut.export.premiere_xml import export_fcp7_xml
from roughcut.ingest.scanner import run_ingest
from roughcut.models import MediaItem, MediaType, OutputConfig, ProjectConfig, Shot
from roughcut.planner.events import assign_events, summarize_events
from roughcut.planner.growth import GrowthPlanner
from roughcut.planner.travel import TravelPlanner
from roughcut.report.writer import write_all_reports

logger = logging.getLogger(__name__)


def load_config(profile_path: Path) -> ProjectConfig:
    """Load project configuration from a YAML file."""
    with open(profile_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ProjectConfig.from_dict(data)


def _analyze_video(video: MediaItem) -> list[Shot]:
    """Analyze a single video: detect shots and score each. Used by worker pool."""
    shots = detect_shots(video)
    for shot in shots:
        shot.quality = score_shot(shot)
    return shots


def _analyze_photo(photo: MediaItem) -> Shot:
    """Analyze a single photo. Used by worker pool."""
    shot = detect_shots_for_photo(photo, DEFAULT_PHOTO_DURATION_SEC)
    shot.quality = score_shot(shot)
    return shot


def _load_file_list(path: Path | None) -> set[str]:
    """Load a text file with one filename per line. Returns set of filenames."""
    if path is None or not path.exists():
        return set()
    names: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
    return names


def _apply_favorites_exclude(
    shots: list[Shot],
    favorites: set[str],
    excludes: set[str],
) -> list[Shot]:
    """Filter shots based on favorites and exclude lists.

    - exclude: remove shots whose source filename matches
    - favorites: boost quality scores so they rank higher
    """
    filtered = []
    for shot in shots:
        filename = shot.source.path.name
        if filename in excludes:
            logger.info("Excluded by exclude list: %s", filename)
            continue
        if filename in favorites:
            # Boost all quality scores to ensure selection
            shot.quality.sharpness = max(shot.quality.sharpness, 0.9)
            shot.quality.exposure = max(shot.quality.exposure, 0.9)
            shot.quality.stability = max(shot.quality.stability, 0.9)
            logger.info("Boosted by favorites: %s", filename)
        filtered.append(shot)
    return filtered


def _run_analysis(
    videos: list[MediaItem],
    photos: list[MediaItem],
    max_workers: int,
) -> list[Shot]:
    """Run shot detection and quality scoring on all media."""
    all_shots: list[Shot] = []

    if max_workers > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            video_futures = {
                pool.submit(_analyze_video, v): v for v in videos
            }
            photo_futures = {
                pool.submit(_analyze_photo, p): p for p in photos
            }

            for future in as_completed(video_futures):
                video = video_futures[future]
                try:
                    shots = future.result()
                    all_shots.extend(shots)
                    logger.info("Analyzed video: %s (%d shots)", video.path.name, len(shots))
                except Exception as e:
                    logger.error("Failed to analyze %s: %s", video.path.name, e)

            for future in as_completed(photo_futures):
                photo = photo_futures[future]
                try:
                    shot = future.result()
                    all_shots.append(shot)
                    logger.info("Analyzed photo: %s", photo.path.name)
                except Exception as e:
                    logger.error("Failed to analyze %s: %s", photo.path.name, e)
    else:
        for video in videos:
            logger.info("Analyzing video: %s", video.path.name)
            shots = _analyze_video(video)
            all_shots.extend(shots)

        for photo in photos:
            logger.info("Analyzing photo: %s", photo.path.name)
            shot = _analyze_photo(photo)
            all_shots.append(shot)

    return all_shots


def _resolve_music(
    config: ProjectConfig,
    input_dir: Path,
    music_files: list[MediaItem],
) -> Path | None:
    """Resolve the music file path."""
    music_path: Path | None = None
    if config.music.file:
        candidate = input_dir / config.music.file
        if candidate.exists():
            music_path = candidate
        else:
            candidate = Path(config.music.file)
            if candidate.exists():
                music_path = candidate
            else:
                logger.error(
                    "Music file specified but not found: '%s' "
                    "(tried '%s' and '%s')",
                    config.music.file,
                    input_dir / config.music.file,
                    config.music.file,
                )
                sys.exit(2)

    if not music_path and music_files:
        music_path = music_files[0].path
        logger.info("Auto-selected music: %s", music_path.name)

    return music_path


def run_pipeline(
    input_dir: Path,
    profile_path: Path,
    output_dir: Path,
    seed: int | None = None,
    dry_run: bool = False,
    fast_preview: bool = False,
    max_workers: int = 1,
    favorites_path: Path | None = None,
    exclude_path: Path | None = None,
) -> None:
    """Execute the full roughcut pipeline."""
    # Load config
    logger.info("Loading profile: %s", profile_path)
    config = load_config(profile_path)
    if seed is not None:
        config.seed = seed

    # Fast preview: override output to 720p
    if fast_preview:
        config.output = OutputConfig(
            resolution="1280x720",
            fps=config.output.fps,
            draft_bitrate_mbps=6,
        )
        logger.info("Fast preview mode: 1280x720, 6 Mbps")

    # Stage 1: Ingest
    logger.info("=== Stage 1: Ingest ===")
    items = run_ingest(input_dir, output_dir)

    videos = [i for i in items if i.media_type == MediaType.VIDEO]
    photos = [i for i in items if i.media_type == MediaType.PHOTO]
    music_files = [i for i in items if i.media_type == MediaType.MUSIC]

    logger.info("Found %d videos, %d photos, %d music files", len(videos), len(photos), len(music_files))

    if not videos and not photos:
        logger.error("No usable media found. Aborting.")
        sys.exit(1)

    music_path = _resolve_music(config, input_dir, music_files)

    # Stage 2: Analyze
    logger.info("=== Stage 2: Analyze (workers=%d) ===", max_workers)
    all_shots = _run_analysis(videos, photos, max_workers)
    logger.info("Total shots for selection: %d", len(all_shots))

    # Apply favorites/exclude
    favorites = _load_file_list(favorites_path)
    excludes = _load_file_list(exclude_path)
    if favorites:
        logger.info("Loaded %d favorites", len(favorites))
    if excludes:
        logger.info("Loaded %d excludes", len(excludes))
    if favorites or excludes:
        all_shots = _apply_favorites_exclude(all_shots, favorites, excludes)
        logger.info("After filtering: %d shots", len(all_shots))

    # Event segmentation
    logger.info("=== Event Segmentation ===")
    assign_events(all_shots)
    event_summaries = summarize_events(all_shots)
    for es in event_summaries:
        logger.info(
            "  Event %d: %d shots, %.1fs, avg_quality=%.2f, time=%s",
            es.event_id, es.shot_count, es.total_duration, es.avg_quality, es.time_range,
        )

    # Shot role classification
    logger.info("=== Shot Role Classification ===")
    role_map = assign_roles(all_shots)
    for shot in all_shots:
        key = f"{shot.source.path}:{shot.start_sec}"
        shot.shot_role = role_map.get(key, "unknown")

    # Beat analysis
    beat_info = None
    if music_path:
        logger.info("Analyzing music beats: %s", music_path.name)
        beat_info = analyze_beats(music_path)

    # Stage 3: Plan
    logger.info("=== Stage 3: Plan ===")
    if config.project_type == "travel":
        planner = TravelPlanner(config, beat_info)
    else:
        planner = GrowthPlanner(config, beat_info)

    planned_clips = planner.plan(all_shots)

    # Stage 4: Build timeline
    logger.info("=== Stage 4: Build Timeline ===")
    timeline = build_timeline(planned_clips)

    # Stage 5: Export
    logger.info("=== Stage 5: Export ===")

    if not dry_run:
        draft_path = output_dir / "draft" / "draft.mp4"
        if fast_preview:
            draft_path = output_dir / "draft" / "preview_720p.mp4"
        logger.info("Rendering draft: %s", draft_path)
        render_draft(timeline, draft_path, config.output, music_path)

    xml_path = output_dir / "premiere" / "sequence.xml"
    logger.info("Exporting Premiere XML: %s", xml_path)
    export_fcp7_xml(timeline, xml_path, music_path=music_path, all_shots=all_shots)

    # Stage 6: Report
    logger.info("=== Stage 6: Report ===")
    write_all_reports(timeline, all_shots, output_dir, beat_info)

    logger.info("=== Pipeline complete ===")
    logger.info("Output directory: %s", output_dir)
    if not dry_run:
        logger.info("Draft: %s", draft_path)
    logger.info("XML: %s", xml_path)
    logger.info("Report: %s", output_dir / "report" / "report.json")


def run_review(
    input_dir: Path,
    profile_path: Path,
    output_dir: Path,
    max_workers: int = 1,
) -> None:
    """Run analysis only and output candidate lists for manual review."""
    logger.info("Loading profile: %s", profile_path)
    config = load_config(profile_path)

    # Ingest
    logger.info("=== Stage 1: Ingest ===")
    items = run_ingest(input_dir, output_dir)

    videos = [i for i in items if i.media_type == MediaType.VIDEO]
    photos = [i for i in items if i.media_type == MediaType.PHOTO]

    if not videos and not photos:
        logger.error("No usable media found. Aborting.")
        sys.exit(1)

    # Analyze
    logger.info("=== Stage 2: Analyze (workers=%d) ===", max_workers)
    all_shots = _run_analysis(videos, photos, max_workers)
    logger.info("Total shots: %d", len(all_shots))

    # Event segmentation & roles
    assign_events(all_shots)
    role_map = assign_roles(all_shots)
    for shot in all_shots:
        key = f"{shot.source.path}:{shot.start_sec}"
        shot.shot_role = role_map.get(key, "unknown")

    # Write candidates.csv
    review_dir = output_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    candidates_path = review_dir / "candidates.csv"
    with open(candidates_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "filename", "media_type", "event_id", "shot_role",
            "start_sec", "end_sec", "duration",
            "sharpness", "exposure", "stability", "face_score",
            "motion_intensity", "overall_quality",
        ])
        for shot in sorted(all_shots, key=lambda s: s.quality.overall, reverse=True):
            q = shot.quality
            writer.writerow([
                shot.source.path.name,
                shot.source.media_type.value,
                shot.event_id,
                shot.shot_role,
                f"{shot.start_sec:.2f}",
                f"{shot.end_sec:.2f}",
                f"{shot.duration_sec:.2f}",
                f"{q.sharpness:.4f}",
                f"{q.exposure:.4f}",
                f"{q.stability:.4f}",
                f"{q.face_score:.4f}",
                f"{q.motion_intensity:.4f}",
                f"{q.overall:.4f}",
            ])

    logger.info("Candidates written: %s", candidates_path)

    # Write template files
    all_filenames = sorted({shot.source.path.name for shot in all_shots})

    fav_template = review_dir / "favorites_template.txt"
    with open(fav_template, "w", encoding="utf-8") as f:
        f.write("# Favorites: uncomment filenames to force-include them\n")
        f.write("# Copy this file to favorites.txt and pass with --favorites\n\n")
        for name in all_filenames:
            f.write(f"# {name}\n")

    exc_template = review_dir / "exclude_template.txt"
    with open(exc_template, "w", encoding="utf-8") as f:
        f.write("# Exclude: uncomment filenames to force-exclude them\n")
        f.write("# Copy this file to exclude.txt and pass with --exclude\n\n")
        for name in all_filenames:
            f.write(f"# {name}\n")

    logger.info("Templates written: %s, %s", fav_template, exc_template)
