"""Report generation: JSON report and CSV clip lists."""

from __future__ import annotations

import csv
import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from roughcut.editor.timeline import Timeline
from roughcut.models import BeatInfo, Shot, TimelineClip
from roughcut.planner.events import EventSummary, summarize_events
from roughcut.planner.grammar import GrammarReport, GrammarViolation, count_grammar_violations


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy numeric types."""

    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
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


SECTION_ROLE_MAP = {
    "intro": ["establishing", "detail"],
    "verse": ["establishing", "detail", "reaction"],
    "chorus": ["action", "reaction"],
    "bridge": ["reaction", "detail"],
    "outro": ["detail", "establishing", "reaction"],
}


def _compute_section_role_stats(
    timeline: Timeline, beat_info: BeatInfo | None
) -> dict:
    """Compute section→role distribution and conflict rate."""
    if not beat_info or not beat_info.sections:
        return {"available": False}

    section_roles: dict[str, dict[str, int]] = {}
    total_clips = 0
    mismatches = 0

    for clip in timeline.clips:
        section = beat_info.section_at(clip.timeline_start)
        if section is None:
            continue
        role = clip.shot.shot_role or "unknown"
        section_roles.setdefault(section.label, {})
        section_roles[section.label][role] = section_roles[section.label].get(role, 0) + 1
        total_clips += 1

        preferred = SECTION_ROLE_MAP.get(section.label, [])
        if role and preferred and role not in preferred:
            mismatches += 1

    mismatch_rate = mismatches / max(total_clips, 1)

    # Chorus highlight lift: fraction of highlights in chorus vs overall
    chorus_clips = [
        c for c in timeline.clips
        if beat_info.section_at(c.timeline_start) and
        beat_info.section_at(c.timeline_start).label == "chorus"
    ]
    non_chorus_clips = [
        c for c in timeline.clips
        if not beat_info.section_at(c.timeline_start) or
        beat_info.section_at(c.timeline_start).label != "chorus"
    ]
    chorus_highlight_rate = (
        sum(1 for c in chorus_clips if c.shot.highlight_score >= 0.5) / max(len(chorus_clips), 1)
    )
    non_chorus_highlight_rate = (
        sum(1 for c in non_chorus_clips if c.shot.highlight_score >= 0.5) / max(len(non_chorus_clips), 1)
    )

    return {
        "available": True,
        "section_roles": section_roles,
        "total_clips_in_sections": total_clips,
        "mismatches": mismatches,
        "mismatch_rate": round(mismatch_rate, 4),
        "chorus_highlight_rate": round(chorus_highlight_rate, 4),
        "non_chorus_highlight_rate": round(non_chorus_highlight_rate, 4),
        "chorus_highlight_lift": round(chorus_highlight_rate - non_chorus_highlight_rate, 4),
    }


def write_report_json(
    timeline: Timeline,
    all_shots: list[Shot],
    output_path: Path,
    beat_info: BeatInfo | None = None,
    grammar_report: GrammarReport | None = None,
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
    story_structure = _build_story_structure(timeline)

    # Section-role distribution and conflict rate
    section_role_stats = _compute_section_role_stats(timeline, beat_info)

    # Chapter role coverage rate (fraction of chapters with 2+ distinct roles)
    chapters_with_good_coverage = sum(
        1 for ch_roles in role_coverage.values() if len(ch_roles) >= 2
    )
    chapter_role_coverage_rate = (
        chapters_with_good_coverage / len(role_coverage) if role_coverage else 0.0
    )

    report = {
        "summary": timeline.summary(),
        "story_structure": story_structure,
        "role_coverage": role_coverage,
        "chapter_role_coverage_rate": round(chapter_role_coverage_rate, 4),
        "section_role_stats": section_role_stats,
        "rhythm_alignment": rhythm_stats,
        "grammar_violations": {
            "consecutive_same_role": grammar_report.consecutive_same_role if grammar_report else 0,
            "missing_breath_points": grammar_report.missing_breath_points if grammar_report else 0,
            "chapter_transitions_fixed": grammar_report.chapter_transitions_fixed if grammar_report else 0,
            "cross_event_jump_violations": grammar_report.cross_event_jump_violations if grammar_report else 0,
            "total": grammar_report.total_violations if grammar_report else 0,
            "violations_before": grammar_report.violations_before if grammar_report else 0,
            "violations_after": grammar_report.violations_after if grammar_report else 0,
            "details": [
                {"rule": v.rule, "clip_index": v.clip_index, "description": v.description}
                for v in (grammar_report.details if grammar_report else [])
            ],
        },
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
            "is_highlight": bool(clip.shot.highlight_score >= 0.5),
            "highlight_score": round(clip.shot.highlight_score, 4),
            "highlight_reason": clip.shot.highlight_reason,
            "window_in": clip.in_point,
            "window_out": clip.out_point,
            "window_score": round(clip.shot.window_score, 4),
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


def _build_story_structure(timeline: Timeline) -> dict:
    """Build chapter->events->clips hierarchy for story inspection."""
    chapter_nodes = []
    chapter_map = timeline.get_chapters()

    for chapter_name, clips in chapter_map.items():
        event_map: dict[int, list[TimelineClip]] = {}
        for clip in clips:
            event_map.setdefault(clip.shot.event_id, []).append(clip)

        event_nodes = []
        for event_id, e_clips in sorted(event_map.items(), key=lambda x: x[0]):
            clip_nodes = []
            for clip in e_clips:
                clip_nodes.append({
                    "source": str(clip.shot.source.path),
                    "timeline_start": round(clip.timeline_start, 3),
                    "timeline_end": round(clip.timeline_end, 3),
                    "shot_role": clip.shot.shot_role or "unknown",
                    "is_highlight": bool(clip.shot.highlight_score >= 0.5),
                    "selection_reason": clip.selection_reason,
                })
            event_nodes.append({
                "event_id": event_id,
                "clip_count": len(e_clips),
                "duration": round(sum(c.timeline_duration for c in e_clips), 3),
                "clips": clip_nodes,
            })

        chapter_nodes.append({
            "name": chapter_name,
            "clip_count": len(clips),
            "duration": round(sum(c.timeline_duration for c in clips), 3),
            "events": event_nodes,
        })

    return {"chapters": chapter_nodes}


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


def write_story_notes(
    timeline: Timeline,
    all_shots: list[Shot],
    output_path: Path,
) -> Path:
    """Write story_notes.md: chapter summaries and suggested replacement points."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chapters = timeline.get_chapters()
    event_summaries = summarize_events(all_shots)
    event_map = {es.event_id: es for es in event_summaries}

    lines = ["# Story Notes\n"]
    lines.append(f"Total duration: {timeline.duration:.1f}s, {len(timeline.clips)} clips\n\n")

    for ch_name, ch_clips in chapters.items():
        lines.append(f"## {ch_name}\n")
        ch_dur = sum(c.timeline_duration for c in ch_clips)
        lines.append(f"- Duration: {ch_dur:.1f}s, {len(ch_clips)} clips\n")

        # Events used in this chapter
        ch_events = {c.shot.event_id for c in ch_clips}
        for eid in sorted(ch_events):
            es = event_map.get(eid)
            if es:
                lines.append(f"- Event {eid}: {es.time_range} ({es.shot_count} shots)\n")

        # Highlights in chapter
        highlights = [c for c in ch_clips if c.shot.highlight_score >= 0.5]
        if highlights:
            lines.append(f"- Highlights: {len(highlights)}\n")
            for h in highlights[:3]:
                lines.append(
                    f"  - {h.shot.source.path.name} @ {h.timeline_start:.1f}s "
                    f"({h.shot.highlight_reason})\n"
                )

        # Suggest replacement points (lowest score clips)
        sorted_clips = sorted(ch_clips, key=lambda c: c.total_score)
        weakest = sorted_clips[:2]
        if weakest:
            lines.append("- Suggested replacements:\n")
            for w in weakest:
                lines.append(
                    f"  - {w.shot.source.path.name} @ {w.timeline_start:.1f}s "
                    f"(score={w.total_score:.3f})\n"
                )
        lines.append("\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    logger.info("Story notes written: %s", output_path)
    return output_path


def write_all_reports(
    timeline: Timeline,
    all_shots: list[Shot],
    output_dir: Path,
    beat_info: BeatInfo | None = None,
    grammar_report: GrammarReport | None = None,
    pre_grammar_clips: list[TimelineClip] | None = None,
    target_duration_sec: int | None = None,
    music_path: Path | None = None,
) -> None:
    """Write all report files."""
    report_dir = output_dir / "report"
    write_report_json(
        timeline,
        all_shots,
        report_dir / "report.json",
        beat_info,
        grammar_report,
    )
    write_selected_csv(timeline, report_dir / "selected_clips.csv")
    write_rejected_csv(all_shots, timeline, report_dir / "rejected_clips.csv")
    write_story_notes(timeline, all_shots, report_dir / "story_notes.md")
    write_comparison_v3_v4(
        timeline=timeline,
        all_shots=all_shots,
        output_path=report_dir / "comparison_v3_v4.json",
        pre_grammar_clips=pre_grammar_clips,
        target_duration_sec=target_duration_sec or int(round(timeline.duration)),
        music_path=music_path,
        beat_info=beat_info,
    )


def _compute_story_metrics(
    clips: list[TimelineClip],
    all_shots: list[Shot],
    target_duration_sec: int,
    audio_present: bool,
    beat_info: BeatInfo | None = None,
) -> dict:
    """Compute quantitative story metrics for regression comparison."""
    if not clips:
        return {
            "duration_achievement_rate": 0.0,
            "event_coverage_rate": 0.0,
            "repeated_shot_rate": 0.0,
            "highlight_hit_rate": 0.0,
            "audio_presence_rate": 1.0 if audio_present else 0.0,
            "grammar_violations": 0,
            "chapter_role_coverage_rate": 0.0,
            "chorus_highlight_lift": 0.0,
        }

    selected_event_ids = {c.shot.event_id for c in clips if c.shot.event_id >= 0}
    all_event_ids = {s.event_id for s in all_shots if s.event_id >= 0}
    event_coverage = (
        len(selected_event_ids) / len(all_event_ids)
        if all_event_ids else 0.0
    )

    repeated = 0
    for i in range(1, len(clips)):
        if clips[i].shot.source.path == clips[i - 1].shot.source.path:
            repeated += 1
    repeated_rate = repeated / max(len(clips) - 1, 1)

    highlight_hits = sum(1 for c in clips if c.shot.highlight_score >= 0.5)
    highlight_rate = highlight_hits / len(clips)

    total_duration = sum(c.timeline_duration for c in clips)
    duration_achievement = total_duration / max(float(target_duration_sec), 1.0)

    # Chapter role coverage rate
    ch_roles: dict[str, set[str]] = {}
    for c in clips:
        ch_roles.setdefault(c.chapter, set()).add(c.shot.shot_role or "unknown")
    chapters_with_coverage = sum(1 for roles in ch_roles.values() if len(roles) >= 2)
    chapter_role_coverage_rate = chapters_with_coverage / max(len(ch_roles), 1)

    # Chorus highlight lift
    chorus_highlight_lift = 0.0
    if beat_info and beat_info.sections:
        chorus_clips = [
            c for c in clips
            if beat_info.section_at(c.timeline_start) and
            beat_info.section_at(c.timeline_start).label == "chorus"
        ]
        non_chorus_clips = [
            c for c in clips
            if not beat_info.section_at(c.timeline_start) or
            beat_info.section_at(c.timeline_start).label != "chorus"
        ]
        ch_rate = sum(1 for c in chorus_clips if c.shot.highlight_score >= 0.5) / max(len(chorus_clips), 1)
        nc_rate = sum(1 for c in non_chorus_clips if c.shot.highlight_score >= 0.5) / max(len(non_chorus_clips), 1)
        chorus_highlight_lift = ch_rate - nc_rate

    return {
        "duration_achievement_rate": round(duration_achievement, 4),
        "event_coverage_rate": round(event_coverage, 4),
        "repeated_shot_rate": round(repeated_rate, 4),
        "highlight_hit_rate": round(highlight_rate, 4),
        "audio_presence_rate": 1.0 if audio_present else 0.0,
        "grammar_violations": count_grammar_violations(clips),
        "chapter_role_coverage_rate": round(chapter_role_coverage_rate, 4),
        "chorus_highlight_lift": round(chorus_highlight_lift, 4),
    }


def _probe_audio_track(music_path: Path | None) -> dict:
    """Probe audio metadata for report diagnostics."""
    if not music_path or not music_path.exists():
        return {"exists": False}

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(music_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return {"exists": True, "probe_error": "ffprobe_failed"}
        payload = json.loads(result.stdout)
        audio_stream = next(
            (s for s in payload.get("streams", []) if s.get("codec_type") == "audio"),
            None,
        )
        if not audio_stream:
            return {"exists": True, "audio_stream_found": False}
        return {
            "exists": True,
            "audio_stream_found": True,
            "codec": audio_stream.get("codec_name"),
            "channels": audio_stream.get("channels"),
            "sample_rate": audio_stream.get("sample_rate"),
        }
    except Exception:
        return {"exists": True, "probe_error": "probe_exception"}


def write_comparison_v3_v4(
    timeline: Timeline,
    all_shots: list[Shot],
    output_path: Path,
    pre_grammar_clips: list[TimelineClip] | None,
    target_duration_sec: int,
    music_path: Path | None = None,
    beat_info: BeatInfo | None = None,
) -> Path:
    """Write `comparison_v3_v4.json`: V3 baseline (pre-grammar) vs V4 (final)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    v4_metrics = _compute_story_metrics(
        timeline.clips, all_shots, target_duration_sec,
        audio_present=bool(music_path), beat_info=beat_info,
    )
    v3_proxy_metrics = _compute_story_metrics(
        pre_grammar_clips or [], all_shots, target_duration_sec,
        audio_present=bool(music_path), beat_info=beat_info,
    )
    audio_probe = _probe_audio_track(music_path)

    metric_keys = (
        "duration_achievement_rate",
        "event_coverage_rate",
        "repeated_shot_rate",
        "highlight_hit_rate",
        "audio_presence_rate",
        "grammar_violations",
        "chapter_role_coverage_rate",
        "chorus_highlight_lift",
    )

    comparison = {
        "baseline": "v3_proxy_pre_grammar",
        "target_duration_sec": target_duration_sec,
        "audio_probe": audio_probe,
        "v3_proxy": v3_proxy_metrics,
        "v4": v4_metrics,
        "delta": {
            k: round(v4_metrics[k] - v3_proxy_metrics.get(k, 0.0), 4)
            for k in metric_keys
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False, cls=_NumpyEncoder)

    logger.info("Comparison report written: %s", output_path)
    return output_path
