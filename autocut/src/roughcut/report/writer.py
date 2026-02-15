"""Report generation: JSON report and CSV clip lists."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import numpy as np

from roughcut.editor.timeline import Timeline
from roughcut.models import BeatInfo, Shot, TimelineClip
from roughcut.planner.events import EventSummary, summarize_events


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy numeric types."""

    def default(self, obj):
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


logger = logging.getLogger(__name__)


def _compute_rhythm_stats(
    timeline: Timeline, beat_info: BeatInfo | None
) -> dict:
    """Compute rhythm alignment statistics for the report."""
    stats: dict = {
        "beat_aligned_cuts": 0,
        "total_cuts": len(timeline.clips),
        "beat_alignment_ratio": 0.0,
        "sections": [],
    }

    if not beat_info or not beat_info.beat_times:
        return stats

    tolerance = 0.12  # 120ms default tolerance
    aligned = 0
    for clip in timeline.clips:
        min_dist = min(
            (abs(clip.timeline_start - bt) for bt in beat_info.beat_times),
            default=float("inf"),
        )
        if min_dist <= tolerance:
            aligned += 1

    stats["beat_aligned_cuts"] = aligned
    stats["beat_alignment_ratio"] = round(aligned / len(timeline.clips), 4) if timeline.clips else 0.0

    # Per-section stats
    if beat_info.sections:
        for sec in beat_info.sections:
            sec_clips = [
                c for c in timeline.clips
                if c.timeline_start >= sec.start and c.timeline_start < sec.end
            ]
            avg_motion = 0.0
            if sec_clips:
                avg_motion = sum(
                    c.shot.quality.motion_intensity for c in sec_clips
                ) / len(sec_clips)

            stats["sections"].append({
                "label": sec.label,
                "start": round(sec.start, 2),
                "end": round(sec.end, 2),
                "avg_energy": round(sec.avg_energy, 4),
                "clip_count": len(sec_clips),
                "avg_motion_intensity": round(avg_motion, 4),
            })

    return stats


def write_report_json(
    timeline: Timeline,
    all_shots: list[Shot],
    output_path: Path,
    beat_info: BeatInfo | None = None,
) -> Path:
    """Write a detailed report.json with per-clip scores and timeline info."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    selected_sources = {
        f"{c.shot.source.path}:{c.shot.start_sec}" for c in timeline.clips
    }

    # Event summary
    event_summaries = summarize_events(all_shots)

    # Role coverage per chapter
    role_coverage: dict[str, dict[str, int]] = {}
    for clip in timeline.clips:
        ch = clip.chapter
        role = clip.shot.shot_role or "unknown"
        role_coverage.setdefault(ch, {})
        role_coverage[ch][role] = role_coverage[ch].get(role, 0) + 1

    # Rhythm alignment stats
    rhythm_stats = _compute_rhythm_stats(timeline, beat_info)

    report = {
        "summary": timeline.summary(),
        "role_coverage": role_coverage,
        "rhythm_alignment": rhythm_stats,
        "event_summary": [
            {
                "event_id": es.event_id,
                "shot_count": es.shot_count,
                "total_duration": round(es.total_duration, 2),
                "avg_quality": round(es.avg_quality, 4),
                "time_range": es.time_range,
            }
            for es in event_summaries
        ],
        "selected_clips": [],
        "rejected_count": 0,
    }

    for clip in timeline.clips:
        report["selected_clips"].append({
            "source": str(clip.shot.source.path),
            "event_id": clip.shot.event_id,
            "shot_role": clip.shot.shot_role,
            "source_in": clip.in_point,
            "source_out": clip.out_point,
            "timeline_start": clip.timeline_start,
            "timeline_end": clip.timeline_end,
            "chapter": clip.chapter,
            "total_score": round(clip.total_score, 4),
            "selection_reason": clip.selection_reason,
            "quality": {
                "sharpness": round(clip.shot.quality.sharpness, 4),
                "exposure": round(clip.shot.quality.exposure, 4),
                "stability": round(clip.shot.quality.stability, 4),
                "face_score": round(clip.shot.quality.face_score, 4),
                "motion_intensity": round(clip.shot.quality.motion_intensity, 4),
            },
            "transition_in": clip.transition_in.value,
            "transition_out": clip.transition_out.value,
        })

    rejected = 0
    for shot in all_shots:
        key = f"{shot.source.path}:{shot.start_sec}"
        if key not in selected_sources:
            rejected += 1
    report["rejected_count"] = rejected

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, cls=_NumpyEncoder)

    logger.info("Report written: %s", output_path)
    return output_path


def write_selected_csv(timeline: Timeline, output_path: Path) -> Path:
    """Write selected_clips.csv."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source", "media_type", "event_id", "in_point", "out_point",
            "timeline_start", "timeline_end", "chapter",
            "total_score", "sharpness", "exposure", "stability",
            "face_score", "motion_intensity", "reason",
        ])
        for clip in timeline.clips:
            q = clip.shot.quality
            writer.writerow([
                str(clip.shot.source.path),
                clip.shot.source.media_type.value,
                clip.shot.event_id,
                f"{clip.in_point:.2f}",
                f"{clip.out_point:.2f}",
                f"{clip.timeline_start:.2f}",
                f"{clip.timeline_end:.2f}",
                clip.chapter,
                f"{clip.total_score:.4f}",
                f"{q.sharpness:.4f}",
                f"{q.exposure:.4f}",
                f"{q.stability:.4f}",
                f"{q.face_score:.4f}",
                f"{q.motion_intensity:.4f}",
                clip.selection_reason,
            ])

    logger.info("Selected clips CSV: %s", output_path)
    return output_path


def _infer_rejection_reason(shot: Shot) -> str:
    """Infer why a shot was not selected based on its quality scores."""
    reasons = []
    q = shot.quality
    if q.overall < 0.3:
        reasons.append("low_overall_quality")
    if q.sharpness < 0.2:
        reasons.append("blurry")
    if q.exposure < 0.3:
        reasons.append("poor_exposure")
    if q.stability < 0.3:
        reasons.append("too_shaky")
    if not reasons:
        reasons.append("outranked_by_better_candidates")
    return "; ".join(reasons)


def write_rejected_csv(
    all_shots: list[Shot],
    timeline: Timeline,
    output_path: Path,
) -> Path:
    """Write rejected_clips.csv."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    selected_sources = {
        f"{c.shot.source.path}:{c.shot.start_sec}" for c in timeline.clips
    }

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source", "media_type", "event_id", "shot_role", "start_sec", "end_sec",
            "duration", "sharpness", "exposure", "stability", "face_score",
            "motion_intensity", "overall_quality", "rejection_reason",
        ])
        for shot in all_shots:
            key = f"{shot.source.path}:{shot.start_sec}"
            if key in selected_sources:
                continue
            q = shot.quality
            # Determine rejection reason
            reason = _infer_rejection_reason(shot)
            writer.writerow([
                str(shot.source.path),
                shot.source.media_type.value,
                shot.event_id,
                shot.shot_role or "unknown",
                f"{shot.start_sec:.2f}",
                f"{shot.end_sec:.2f}",
                f"{shot.duration_sec:.2f}",
                f"{q.sharpness:.4f}",
                f"{q.exposure:.4f}",
                f"{q.stability:.4f}",
                f"{q.face_score:.4f}",
                f"{q.motion_intensity:.4f}",
                f"{q.overall:.4f}",
                reason,
            ])

    logger.info("Rejected clips CSV: %s", output_path)
    return output_path


def write_all_reports(
    timeline: Timeline,
    all_shots: list[Shot],
    output_dir: Path,
    beat_info: BeatInfo | None = None,
) -> None:
    """Write all report files."""
    report_dir = output_dir / "report"
    write_report_json(timeline, all_shots, report_dir / "report.json", beat_info)
    write_selected_csv(timeline, report_dir / "selected_clips.csv")
    write_rejected_csv(all_shots, timeline, report_dir / "rejected_clips.csv")
