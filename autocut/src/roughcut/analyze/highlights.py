"""Highlight detection: identify memorable human moments in shots."""

from __future__ import annotations

import logging

from roughcut.models import Shot

logger = logging.getLogger(__name__)

# Thresholds for highlight detection
SMILE_THRESHOLD = 0.6       # face_score threshold for "smile/interaction"
ACTION_COMPLETE_THRESHOLD = 0.5  # motion that peaks then drops
GAZE_THRESHOLD = 0.7        # face_score + stability combo


def compute_highlight_scores(shots: list[Shot]) -> None:
    """Compute highlight_score and highlight_reason for each shot in-place.

    Highlight signals (heuristic):
    - High face score + moderate motion = interaction/smile
    - High face score + high stability = looking at camera
    - High motion + high sharpness = action completion moment
    - Photo with high face score = posed moment
    """
    if not shots:
        return

    for shot in shots:
        q = shot.quality
        score = 0.0
        reasons: list[str] = []

        # Smile / interaction detection
        if q.face_score >= SMILE_THRESHOLD:
            smile_signal = q.face_score * 0.6 + q.motion_intensity * 0.2 + q.exposure * 0.2
            if smile_signal > score:
                score = smile_signal
                reasons.append("interaction")

        # Gaze / looking at camera
        if q.face_score >= 0.5 and q.stability >= GAZE_THRESHOLD:
            gaze_signal = q.face_score * 0.5 + q.stability * 0.3 + q.sharpness * 0.2
            if gaze_signal > score:
                score = gaze_signal
                reasons.append("gaze")

        # Action completion (high motion + sharp = captured a moment)
        if q.motion_intensity >= ACTION_COMPLETE_THRESHOLD and q.sharpness >= 0.5:
            action_signal = q.motion_intensity * 0.4 + q.sharpness * 0.3 + q.exposure * 0.3
            if action_signal > score:
                score = action_signal
                reasons.append("action_moment")

        # Photo with face = posed moment
        if shot.source.is_photo and q.face_score >= 0.3:
            photo_signal = q.face_score * 0.5 + q.sharpness * 0.3 + q.exposure * 0.2
            if photo_signal > score:
                score = photo_signal
                reasons.append("posed_photo")

        shot.highlight_score = min(score, 1.0)
        shot.highlight_reason = ", ".join(reasons) if reasons else ""

    # Log summary
    highlights = [s for s in shots if s.highlight_score >= 0.5]
    logger.info(
        "Highlight detection: %d/%d shots marked as highlights (score >= 0.5)",
        len(highlights), len(shots),
    )
    for s in sorted(highlights, key=lambda x: x.highlight_score, reverse=True)[:5]:
        logger.info(
            "  Top highlight: %s @ %.1fs, score=%.2f, reason=%s",
            s.source.path.name, s.start_sec, s.highlight_score, s.highlight_reason,
        )
