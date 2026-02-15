"""Constants used across the roughcut package."""

from pathlib import Path

# Supported file extensions
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".png", ".dng"}
MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a"}
ALL_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | PHOTO_EXTENSIONS | MUSIC_EXTENSIONS

# Default output settings
DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_FPS = 30
DEFAULT_BITRATE_MBPS = 12
DEFAULT_CODEC = "libx264"
DEFAULT_PHOTO_DURATION_SEC = 4.0

# Quality scoring thresholds
LAPLACIAN_BLUR_THRESHOLD = 100.0
EXPOSURE_LOW_THRESHOLD = 40
EXPOSURE_HIGH_THRESHOLD = 220
STABILITY_JITTER_THRESHOLD = 5.0

# Shot detection
HISTOGRAM_DIFF_THRESHOLD = 0.4
MIN_SHOT_DURATION_SEC = 0.5
MAX_SHOT_DURATION_SEC = 8.0  # Force-split shots longer than this
OPTICAL_FLOW_THRESHOLD = 12.0  # Mean pixel displacement for cut detection
LUMINANCE_JUMP_THRESHOLD = 30.0  # Mean luminance change for cut detection

# Beat alignment
BEAT_SNAP_TOLERANCE_MS = 120

# Ken Burns defaults
KEN_BURNS_ZOOM_RANGE = (1.0, 1.15)
KEN_BURNS_PAN_RANGE = 0.05  # fraction of frame

# Hash chunk size for dedup
HASH_CHUNK_SIZE = 8192

# FCP7 XML constants
FCP7_TIMEBASE = 30  # NTB timebase
FCP7_NTSC = False

# Logging
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


# --- Error codes ---
class ErrorCode:
    """Exit codes for CLI error reporting."""

    SUCCESS = 0
    E_NO_USABLE_MEDIA = 10
    E_MUSIC_NOT_FOUND = 11
    E_PROXY_FAIL = 12
    E_RENDER_FAIL = 20
    E_EXPORT_FAIL = 21
