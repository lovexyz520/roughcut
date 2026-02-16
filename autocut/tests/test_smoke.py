"""Smoke tests: basic import, config loading, CLI, and version."""

from pathlib import Path

import yaml

from roughcut.models import ProjectConfig


def test_import_pipeline():
    """Pipeline module imports successfully."""
    from roughcut.pipeline import run_pipeline, run_review
    assert callable(run_pipeline)
    assert callable(run_review)


def test_import_cli():
    """CLI module imports successfully."""
    from roughcut.cli import app
    assert app is not None


def test_load_growth_config():
    """Growth config YAML loads and parses correctly."""
    config_path = Path(__file__).parent.parent / "config" / "profile_growth.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    config = ProjectConfig.from_dict(data)
    assert config.project_type == "growth"
    assert config.target_duration_sec == 240
    assert config.clip_duration_sec.min == 1.5
    assert config.clip_duration_sec.max == 6.0


def test_load_travel_config():
    """Travel config YAML loads and parses correctly."""
    config_path = Path(__file__).parent.parent / "config" / "profile_travel.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    config = ProjectConfig.from_dict(data)
    assert config.project_type == "travel"
    assert config.target_duration_sec == 300


def test_version():
    """Version string is available."""
    from roughcut import __version__
    assert __version__
    assert isinstance(__version__, str)


def test_error_codes():
    """Error codes are defined."""
    from roughcut.constants import ErrorCode
    assert ErrorCode.E_NO_USABLE_MEDIA == 10
    assert ErrorCode.E_MUSIC_NOT_FOUND == 11
    assert ErrorCode.E_RENDER_FAIL == 20


def test_suppressed_loggers_defined():
    """SUPPRESSED_LOGGERS constant exists."""
    from roughcut.constants import SUPPRESSED_LOGGERS
    assert "numba" in SUPPRESSED_LOGGERS
    assert "librosa" in SUPPRESSED_LOGGERS
