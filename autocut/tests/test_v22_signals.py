"""Tests for V2.2 semantic signals: expression, composition, camera motion,
color, dedup, the emotion proxy, and their planner/grammar wiring."""

from __future__ import annotations

import numpy as np

from roughcut.analyze.camera_motion import classify_camera_motion, motion_conflict
from roughcut.analyze.color import color_distance, measure_color_temp
from roughcut.analyze.composition import measure_composition
from roughcut.analyze.dedup import compute_phash, hamming, mark_near_duplicates
from roughcut.analyze.expression import measure_smile, measure_smile_multi
from roughcut.models import ProjectConfig, QualityScores, SignalsConfig
from tests.conftest import make_shot


class TestExpression:
    def test_blank_frame_no_smile(self):
        blank = np.zeros((240, 320, 3), np.uint8)
        assert measure_smile(blank) == 0.0

    def test_empty_multi(self):
        assert measure_smile_multi([]) == 0.0

    def test_multi_takes_peak(self):
        # A list with one non-face frame still returns a valid [0,1] score.
        frames = [np.zeros((240, 320, 3), np.uint8) for _ in range(3)]
        score = measure_smile_multi(frames)
        assert 0.0 <= score <= 1.0


class TestComposition:
    def test_flat_frame_low_score(self):
        flat = np.full((240, 320, 3), 128, np.uint8)
        assert measure_composition(flat) <= 0.4

    def test_returns_normalized(self):
        img = np.random.randint(0, 255, (240, 320, 3), np.uint8)
        assert 0.0 <= measure_composition(img) <= 1.0


class TestCameraMotion:
    def test_static(self):
        base = np.random.randint(0, 255, (240, 320, 3), np.uint8)
        assert classify_camera_motion([base.copy() for _ in range(5)]) == "static"

    def test_pan(self):
        base = np.random.randint(0, 255, (240, 320, 3), np.uint8)
        frames = [np.roll(base, i * 6, axis=1) for i in range(5)]
        assert classify_camera_motion(frames) == "pan"

    def test_tilt(self):
        base = np.random.randint(0, 255, (240, 320, 3), np.uint8)
        frames = [np.roll(base, i * 6, axis=0) for i in range(5)]
        assert classify_camera_motion(frames) == "tilt"

    def test_single_frame_static(self):
        assert classify_camera_motion([np.zeros((10, 10, 3), np.uint8)]) == "static"

    def test_conflict(self):
        assert motion_conflict("pan", "pan") is True
        assert motion_conflict("pan", "static") is False
        assert motion_conflict("static", "static") is False


class TestColor:
    def test_warm_vs_cool(self):
        warm = np.zeros((64, 64, 3), np.uint8); warm[:] = (30, 60, 200)  # BGR high R
        cool = np.zeros((64, 64, 3), np.uint8); cool[:] = (200, 60, 30)  # BGR high B
        assert measure_color_temp(warm) > 0.6
        assert measure_color_temp(cool) < 0.4

    def test_distance(self):
        assert color_distance(0.9, 0.1) == 0.8
        assert color_distance(0.5, 0.5) == 0.0


class TestDedup:
    def test_phash_stable_and_discriminating(self):
        base = np.random.randint(0, 255, (240, 320, 3), np.uint8)
        assert compute_phash(base) == compute_phash(base.copy())
        other = np.random.randint(0, 255, (240, 320, 3), np.uint8)
        assert hamming(compute_phash(base), compute_phash(other)) > 12

    def test_mark_near_duplicates(self):
        # Two shots with identical phash in the same event -> one suppressed.
        a = make_shot(name="a.mp4", event_id=1)
        b = make_shot(name="b.mp4", event_id=1)
        a.shot_index, b.shot_index = 0, 1
        a.phash = b.phash = 0b1010101010101010
        a.window_score, b.window_score = 0.9, 0.5  # a is better
        marked = mark_near_duplicates([a, b], threshold=6)
        assert marked == 1
        assert a.near_dup_of == -1        # keeper
        assert b.near_dup_of == a.shot_index  # suppressed

    def test_different_events_not_deduped(self):
        a = make_shot(name="a.mp4", event_id=1)
        b = make_shot(name="b.mp4", event_id=2)
        a.phash = b.phash = 0b1111000011110000
        assert mark_near_duplicates([a, b]) == 0


class TestEmotionProxy:
    def test_semantic_smile_drives_emotion(self):
        q = QualityScores(face_score=0.2, motion_intensity=0.1, smile_score=0.9)
        # Real smile should push emotion well above the legacy (face+motion)/2 = 0.15
        assert q.emotion > 0.5

    def test_fallback_when_no_semantic(self):
        q = QualityScores(face_score=0.6, motion_intensity=0.4)
        assert abs(q.emotion - 0.5) < 1e-6  # (0.6+0.4)/2


class TestSignalsConfig:
    def test_defaults_all_enabled(self):
        s = SignalsConfig()
        assert s.expression and s.source_audio and s.composition
        assert s.camera_motion and s.color_continuity and s.dedup

    def test_from_dict_parses_signals(self):
        cfg = ProjectConfig.from_dict({
            "project_type": "growth",
            "signals": {
                "source_audio": False,
                "smile_weight": 0.3,
                "dedup_threshold": 4,
            },
        })
        assert cfg.signals.source_audio is False
        assert cfg.signals.smile_weight == 0.3
        assert cfg.signals.dedup_threshold == 4
        assert cfg.signals.expression is True  # untouched default

    def test_planner_score_uses_signals(self):
        """A shot with a strong smile should outscore an identical one without,
        proving the planner reads the new signal."""
        from roughcut.planner.growth import GrowthPlanner
        cfg = ProjectConfig.from_dict({"project_type": "growth"})
        planner = GrowthPlanner(cfg)
        chapter = planner.chapters()[0]

        plain = make_shot(name="p.mp4")
        happy = make_shot(name="h.mp4")
        happy.quality.smile_score = 0.9
        happy.quality.composition = 0.9

        s_plain = planner.compute_score(plain, chapter, 0.0)
        s_happy = planner.compute_score(happy, chapter, 0.0)
        assert s_happy > s_plain
