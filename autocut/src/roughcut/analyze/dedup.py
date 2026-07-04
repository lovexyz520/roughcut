"""Near-duplicate detection via perceptual hashing.

Phone bursts and "take 1/2/3" of the same moment produce many near-identical
shots. The old diversity system only penalized the same *source file*; it could
not tell that two different files show the same instant. A DCT perceptual hash
clusters visually-identical shots so the planner keeps only the best one.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def compute_phash(frame: np.ndarray) -> int:
    """64-bit DCT perceptual hash of a frame."""
    if frame is None or frame.size == 0:
        return 0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)
    low = dct[:8, :8]
    med = np.median(low[1:, 1:])  # exclude DC term from the threshold
    bits = (low > med).flatten()
    h = 0
    for bit in bits:
        h = (h << 1) | int(bit)
    return h


def hamming(a: int, b: int) -> int:
    """Hamming distance between two 64-bit hashes."""
    return bin(a ^ b).count("1")


def mark_near_duplicates(shots: list, threshold: int = 6) -> int:
    """Cluster near-duplicate shots and mark all but the best in each cluster.

    Only shots from the same event are compared (duplicates are, by definition,
    the same moment). The keeper is the highest window_score / overall-quality
    shot; the rest get ``near_dup_of = keeper.shot_index``.

    Returns the number of shots marked as duplicates.
    """
    by_event: dict[int, list] = {}
    for s in shots:
        if getattr(s, "phash", 0):
            by_event.setdefault(s.event_id, []).append(s)

    marked = 0
    for _eid, group in by_event.items():
        # Best-first so the first-seen representative of a cluster is the keeper.
        group.sort(
            key=lambda s: (s.window_score, s.quality.overall), reverse=True
        )
        kept: list = []
        for s in group:
            dup_of = None
            for k in kept:
                if hamming(s.phash, k.phash) <= threshold:
                    dup_of = k
                    break
            if dup_of is not None:
                s.near_dup_of = dup_of.shot_index
                marked += 1
            else:
                s.near_dup_of = -1
                kept.append(s)

    if marked:
        logger.info("Near-duplicate detection: %d shots suppressed as duplicates", marked)
    return marked
