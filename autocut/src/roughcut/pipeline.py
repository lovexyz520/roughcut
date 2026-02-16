"""Main pipeline orchestrating all stages: ingest -> analyze -> plan -> edit -> export -> report."""

from __future__ import annotations

import copy
import csv
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from roughcut.analyze.beat import analyze_beats
from roughcut.analyze.highlights import compute_highlight_scores, compute_highlight_windows
from roughcut.analyze.quality import score_shot
from roughcut.analyze.shot_detect import detect_shots, detect_shots_for_photo
from roughcut.analyze.shot_role import assign_roles
from roughcut.constants import DEFAULT_PHOTO_DURATION_SEC, ErrorCode
from roughcut.editor.timeline import build_timeline
from roughcut.export.draft import render_draft
from roughcut.export.premiere_xml import export_fcp7_xml
from roughcut.ingest.scanner import run_ingest
from roughcut.models import MediaItem, MediaType, OutputConfig, ProjectConfig, Shot, ShotDetectConfig
from roughcut.planner.events import assign_events, summarize_events
from roughcut.planner.grammar import apply_grammar
from roughcut.planner.growth import GrowthPlanner
from roughcut.planner.preference import (
    UserProfile,
    learn_preferences,
    load_user_profile,
    save_user_profile,
)
from roughcut.planner.travel import TravelPlanner
from roughcut.report.writer import write_all_reports

logger = logging.getLogger(__name__)


def load_config(profile_path: Path) -> ProjectConfig:
    """Load project configuration from a YAML file."""
    with open(profile_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ProjectConfig.from_dict(data)


def _analyze_video(
    video: MediaItem, shot_detect_config: ShotDetectConfig | None = None
) -> list[Shot]:
    """Analyze a single video: detect shots and score each. Used by worker pool."""
    shots = detect_shots(video, config=shot_detect_config)
    for shot in shots:
        shot.quality = score_shot(shot)
    return shots


def _analyze_photo(photo: MediaItem) -> Shot:
    """Analyze a single photo. Used by worker pool."""
    shot = detect_shots_for_photo(photo, DEFAULT_PHOTO_DURATION_SEC)
    shot.quality = score_shot(shot)
    return shot


def _load_file_list(path: Path | None) -> tuple[set[str], set[int]]:
    """Load a text file with filenames and event IDs.

    Lines starting with 'event:' are parsed as event IDs.
    Other lines are treated as filenames.

    Returns:
        Tuple of (filenames set, event_ids set).
    """
    if path is None or not path.exists():
        return set(), set()
    names: set[str] = set()
    event_ids: set[int] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("event:"):
                try:
                    eid = int(line.split(":")[1].strip().split()[0])
                    event_ids.add(eid)
                except (ValueError, IndexError):
                    logger.warning("Invalid event ID in list: %s", line)
            else:
                names.add(line)
    return names, event_ids


def _apply_favorites_exclude(
    shots: list[Shot],
    favorites: set[str],
    favorite_events: set[int],
    excludes: set[str],
    exclude_events: set[int],
) -> list[Shot]:
    """Filter shots based on favorites and exclude lists.

    Supports both filename and event_id level filtering.
    - exclude: remove shots whose source filename or event_id matches
    - favorites: boost quality scores so they rank higher
    """
    filtered = []
    for shot in shots:
        filename = shot.source.path.name

        # Exclude check (filename or event)
        if filename in excludes:
            logger.info("Excluded by filename: %s", filename)
            continue
        if shot.event_id in exclude_events:
            logger.info("Excluded by event %d: %s", shot.event_id, filename)
            continue

        # Favorites boost (filename or event)
        if filename in favorites or shot.event_id in favorite_events:
            shot.quality.sharpness = max(shot.quality.sharpness, 0.9)
            shot.quality.exposure = max(shot.quality.exposure, 0.9)
            shot.quality.stability = max(shot.quality.stability, 0.9)
            reason = "filename" if filename in favorites else f"event:{shot.event_id}"
            logger.info("Boosted by favorites (%s): %s", reason, filename)

        filtered.append(shot)
    return filtered


def _run_analysis(
    videos: list[MediaItem],
    photos: list[MediaItem],
    max_workers: int,
    shot_detect_config: ShotDetectConfig | None = None,
) -> list[Shot]:
    """Run shot detection and quality scoring on all media."""
    all_shots: list[Shot] = []

    if max_workers > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            video_futures = {
                pool.submit(_analyze_video, v, shot_detect_config): v for v in videos
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
            shots = _analyze_video(video, shot_detect_config)
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
                    "E_MUSIC_NOT_FOUND: Music file specified but not found: '%s' "
                    "(tried '%s' and '%s')",
                    config.music.file,
                    input_dir / config.music.file,
                    config.music.file,
                )
                sys.exit(ErrorCode.E_MUSIC_NOT_FOUND)

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
    items, skipped_dng = run_ingest(input_dir, output_dir)

    videos = [i for i in items if i.media_type == MediaType.VIDEO]
    photos = [i for i in items if i.media_type == MediaType.PHOTO]
    music_files = [i for i in items if i.media_type == MediaType.MUSIC]

    logger.info("Found %d videos, %d photos, %d music files", len(videos), len(photos), len(music_files))

    if not videos and not photos:
        logger.error("E_NO_USABLE_MEDIA: No usable media found. Aborting.")
        sys.exit(ErrorCode.E_NO_USABLE_MEDIA)

    # Filter out DNG photos without successful proxy
    usable_photos: list[MediaItem] = []
    for p in photos:
        if p.path.suffix.lower() == ".dng" and not p.proxy_path:
            logger.warning("E_PROXY_FAIL: DNG without proxy skipped: %s", p.path.name)
        else:
            usable_photos.append(p)
    photos = usable_photos

    music_path = _resolve_music(config, input_dir, music_files)

    # Stage 2: Analyze
    logger.info("=== Stage 2: Analyze (workers=%d) ===", max_workers)
    all_shots = _run_analysis(videos, photos, max_workers, config.shot_detect)
    logger.info("Total shots for selection: %d", len(all_shots))

    # Apply favorites/exclude
    shots_before_filter = list(all_shots)  # Keep copy for preference learning
    fav_names, fav_events = _load_file_list(favorites_path)
    exc_names, exc_events = _load_file_list(exclude_path)
    if fav_names or fav_events:
        logger.info("Loaded favorites: %d files, %d events", len(fav_names), len(fav_events))
    if exc_names or exc_events:
        logger.info("Loaded excludes: %d files, %d events", len(exc_names), len(exc_events))
    if fav_names or fav_events or exc_names or exc_events:
        all_shots = _apply_favorites_exclude(all_shots, fav_names, fav_events, exc_names, exc_events)
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

    # Highlight detection
    logger.info("=== Highlight Detection ===")
    compute_highlight_scores(all_shots)

    # Highlight windowing (find best sub-segments)
    logger.info("=== Highlight Windowing ===")
    compute_highlight_windows(all_shots)

    # Beat analysis
    beat_info = None
    if music_path:
        logger.info("Analyzing music beats: %s", music_path.name)
        beat_info = analyze_beats(music_path)

    # User preference learning
    user_profile: UserProfile | None = None
    profile_path = output_dir / "user_profile.json"
    existing_profile = load_user_profile(profile_path)
    if fav_names or fav_events or exc_names or exc_events:
        # Build preference samples from favorites/excludes
        fav_shots = [s for s in all_shots if s.source.path.name in fav_names or s.event_id in fav_events]
        exc_shots_list = [
            s for s in shots_before_filter
            if s.source.path.name in exc_names or s.event_id in exc_events
        ]
        user_profile = learn_preferences(all_shots, fav_shots, exc_shots_list)
        save_user_profile(user_profile, profile_path)
    elif existing_profile:
        user_profile = existing_profile
        logger.info("Using existing user profile (%d samples)", user_profile.sample_count)

    # Stage 3: Plan
    logger.info("=== Stage 3: Plan ===")
    if config.project_type == "travel":
        planner = TravelPlanner(config, beat_info, user_profile)
    else:
        planner = GrowthPlanner(config, beat_info, user_profile)

    planned_clips = planner.plan(all_shots)
    pre_grammar_clips = copy.deepcopy(planned_clips)

    # Grammar engine: apply editing grammar rules
    logger.info("=== Grammar Engine ===")
    grammar_report = apply_grammar(planned_clips, all_shots)

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
    write_all_reports(
        timeline=timeline,
        all_shots=all_shots,
        output_dir=output_dir,
        beat_info=beat_info,
        grammar_report=grammar_report,
        pre_grammar_clips=pre_grammar_clips,
        target_duration_sec=config.target_duration_sec,
        music_path=music_path,
        skipped_dng=skipped_dng,
    )

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
    items, _skipped_dng = run_ingest(input_dir, output_dir)

    videos = [i for i in items if i.media_type == MediaType.VIDEO]
    photos = [i for i in items if i.media_type == MediaType.PHOTO]

    if not videos and not photos:
        logger.error("E_NO_USABLE_MEDIA: No usable media found. Aborting.")
        sys.exit(ErrorCode.E_NO_USABLE_MEDIA)

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

    # Highlight detection
    compute_highlight_scores(all_shots)

    # Event summaries
    event_summaries = summarize_events(all_shots)

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
            "highlight_score", "highlight_reason",
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
                f"{shot.highlight_score:.4f}",
                shot.highlight_reason,
            ])

    logger.info("Candidates written: %s", candidates_path)

    # Write event summary
    event_summary_path = review_dir / "events.csv"
    with open(event_summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["event_id", "shot_count", "total_duration", "avg_quality",
                         "emotion_intensity", "time_range", "action"])
        for es in event_summaries:
            writer.writerow([
                es.event_id, es.shot_count, f"{es.total_duration:.1f}",
                f"{es.avg_quality:.3f}", f"{es.emotion_intensity:.3f}",
                es.time_range, "keep",
            ])
    logger.info("Event summary written: %s", event_summary_path)

    # Write template files (support both filename and event_id)
    all_filenames = sorted({shot.source.path.name for shot in all_shots})

    fav_template = review_dir / "favorites_template.txt"
    with open(fav_template, "w", encoding="utf-8") as f:
        f.write("# Favorites: uncomment items to force-include them\n")
        f.write("# Supports filenames and event IDs (prefix with 'event:')\n")
        f.write("# Copy this file to favorites.txt and pass with --favorites\n\n")
        f.write("# --- Events ---\n")
        for es in event_summaries:
            f.write(f"# event:{es.event_id}  ({es.shot_count} shots, {es.time_range})\n")
        f.write("\n# --- Files ---\n")
        for name in all_filenames:
            f.write(f"# {name}\n")

    exc_template = review_dir / "exclude_template.txt"
    with open(exc_template, "w", encoding="utf-8") as f:
        f.write("# Exclude: uncomment items to force-exclude them\n")
        f.write("# Supports filenames and event IDs (prefix with 'event:')\n")
        f.write("# Copy this file to exclude.txt and pass with --exclude\n\n")
        f.write("# --- Events ---\n")
        for es in event_summaries:
            f.write(f"# event:{es.event_id}  ({es.shot_count} shots, {es.time_range})\n")
        f.write("\n# --- Files ---\n")
        for name in all_filenames:
            f.write(f"# {name}\n")

    logger.info("Templates written: %s, %s", fav_template, exc_template)
