"""Tests for Task 5: semantic transitions."""

from tests.conftest import make_shot, make_timeline_clip
from roughcut.models import MediaType, TransitionType
from roughcut.planner.grammar import apply_grammar


def test_time_jump_triggers_cross_dissolve():
    """Same event with >30s time gap should get cross dissolve."""
    s1 = make_shot("a.mp4", start=0.0, end=3.0, event_id=1)
    s2 = make_shot("a.mp4", start=40.0, end=43.0, event_id=1)  # 37s gap
    s3 = make_shot("b.mp4", start=0.0, end=3.0, event_id=2)
    clips = [
        make_timeline_clip(s1, 0.0, 3.0, "learning"),
        make_timeline_clip(s2, 3.0, 6.0, "learning"),
        make_timeline_clip(s3, 6.0, 9.0, "learning"),
    ]
    report = apply_grammar(clips)
    # The time jump between clip 0 and 1 should trigger cross dissolve
    assert clips[0].transition_out == TransitionType.CROSS_DISSOLVE
    assert clips[1].transition_in == TransitionType.CROSS_DISSOLVE
    assert report.semantic_transitions_added >= 1


def test_emotion_contrast_triggers_fade():
    """High emotion contrast (>0.5) should get fade transition."""
    s1 = make_shot("a.mp4", start=0.0, end=3.0, face_score=0.9, motion_intensity=0.8, event_id=0)
    s2 = make_shot("b.mp4", start=0.0, end=3.0, face_score=0.0, motion_intensity=0.0, event_id=1)
    s3 = make_shot("c.mp4", start=0.0, end=3.0, face_score=0.5, motion_intensity=0.5, event_id=2)
    clips = [
        make_timeline_clip(s1, 0.0, 3.0, "highlights"),
        make_timeline_clip(s2, 3.0, 6.0, "highlights"),
        make_timeline_clip(s3, 6.0, 9.0, "highlights"),
    ]
    report = apply_grammar(clips)
    # Emotion contrast between clip 0 (0.85) and clip 1 (0.0) = 0.85
    assert clips[0].transition_out == TransitionType.FADE_OUT
    assert clips[1].transition_in == TransitionType.FADE_IN


def test_media_switch_triggers_cross_dissolve():
    """Photo→video switch should get cross dissolve."""
    s1 = make_shot("photo.jpg", start=0.0, end=4.0, media_type=MediaType.PHOTO, event_id=0)
    s2 = make_shot("video.mp4", start=0.0, end=3.0, event_id=1)
    s3 = make_shot("video2.mp4", start=0.0, end=3.0, event_id=2)
    clips = [
        make_timeline_clip(s1, 0.0, 4.0, "closing"),
        make_timeline_clip(s2, 4.0, 7.0, "closing"),
        make_timeline_clip(s3, 7.0, 10.0, "closing"),
    ]
    report = apply_grammar(clips)
    assert clips[0].transition_out == TransitionType.CROSS_DISSOLVE
    assert clips[1].transition_in == TransitionType.CROSS_DISSOLVE
    assert report.semantic_transitions_added >= 1


def test_chapter_boundary_not_overridden():
    """Semantic rules should NOT override existing chapter boundary transitions."""
    s1 = make_shot("a.mp4", start=0.0, end=3.0, face_score=0.9, motion_intensity=0.8, event_id=0)
    s2 = make_shot("b.mp4", start=0.0, end=3.0, face_score=0.0, motion_intensity=0.0, event_id=1)
    s3 = make_shot("c.mp4", start=0.0, end=3.0, event_id=2)
    clips = [
        make_timeline_clip(s1, 0.0, 3.0, "opening"),
        make_timeline_clip(s2, 3.0, 6.0, "learning"),  # Different chapter
        make_timeline_clip(s3, 6.0, 9.0, "learning"),
    ]
    # Pre-set chapter boundary transition
    clips[0].transition_out = TransitionType.FADE_OUT
    clips[1].transition_in = TransitionType.FADE_IN
    report = apply_grammar(clips)
    # The chapter boundary transitions should remain
    assert clips[0].transition_out == TransitionType.FADE_OUT
    assert clips[1].transition_in == TransitionType.FADE_IN
