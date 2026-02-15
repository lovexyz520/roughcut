"""Media scanning, metadata extraction, and deduplication."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from roughcut.constants import (
    HASH_CHUNK_SIZE,
    MUSIC_EXTENSIONS,
    PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from roughcut.models import MediaItem, MediaType

logger = logging.getLogger(__name__)


def classify_file(path: Path) -> MediaType | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    if ext in PHOTO_EXTENSIONS:
        return MediaType.PHOTO
    if ext in MUSIC_EXTENSIONS:
        return MediaType.MUSIC
    return None


def file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def probe_media(path: Path) -> dict:
    """Use ffprobe to extract metadata from a media file."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe failed for %s: %s", path, result.stderr)
            return {}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning("ffprobe error for %s: %s", path, e)
        return {}


def extract_metadata(path: Path, media_type: MediaType) -> MediaItem:
    """Extract metadata from a media file using ffprobe."""
    item = MediaItem(path=path, media_type=media_type)
    item.file_size = path.stat().st_size
    item.file_hash = file_hash(path)

    probe = probe_media(path)
    if not probe:
        return item

    # Extract format-level info
    fmt = probe.get("format", {})
    item.duration_sec = float(fmt.get("duration", 0))
    tags = fmt.get("tags", {})
    item.creation_time = tags.get("creation_time", tags.get("com.apple.quicktime.creationdate", ""))

    # Extract stream-level info
    for stream in probe.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video":
            item.width = int(stream.get("width", 0))
            item.height = int(stream.get("height", 0))
            # Parse fps from r_frame_rate (e.g., "30000/1001")
            r_fps = stream.get("r_frame_rate", "0/1")
            try:
                num, den = r_fps.split("/")
                item.fps = float(num) / float(den) if float(den) else 0
            except (ValueError, ZeroDivisionError):
                item.fps = 0
            break

    # GPS extraction from tags (Apple devices)
    location = tags.get("com.apple.quicktime.location.ISO6709", "")
    if location:
        try:
            # Format: +DD.DDDD+DDD.DDDD+AAA.AAA/
            parts = location.replace("/", "").split("+")
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                # Handle negative values (split on -)
                coords = location.replace("/", "")
                # Simple parse: find lat/lon
                import re
                match = re.match(r"([+-][\d.]+)([+-][\d.]+)", coords)
                if match:
                    item.gps_lat = float(match.group(1))
                    item.gps_lon = float(match.group(2))
        except (ValueError, IndexError):
            pass

    return item


def convert_dng_proxy(dng_path: Path, output_dir: Path) -> Path | None:
    """Convert a DNG file to a proxy JPEG using multiple strategies.

    Tries ffmpeg first, then falls back to rawpy/imageio if available.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = output_dir / (dng_path.stem + ".jpg")
    if proxy_path.exists() and proxy_path.stat().st_size > 1000:
        return proxy_path

    # Strategy 1: ffmpeg with explicit raw demuxer
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(dng_path),
                "-vf", "scale=1920:-1",
                "-q:v", "2",
                str(proxy_path),
            ],
            capture_output=True,
            timeout=60,
        )
        if proxy_path.exists() and proxy_path.stat().st_size > 1000:
            logger.info("DNG proxy created (ffmpeg): %s", proxy_path.name)
            return proxy_path
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("ffmpeg DNG conversion failed for %s: %s", dng_path.name, e)

    # Strategy 2: extract embedded JPEG preview via exiftool
    try:
        result = subprocess.run(
            ["exiftool", "-b", "-JpgFromRaw", str(dng_path)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and len(result.stdout) > 1000:
            with open(proxy_path, "wb") as f:
                f.write(result.stdout)
            logger.info("DNG proxy created (exiftool preview): %s", proxy_path.name)
            return proxy_path
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.debug("exiftool not available for DNG preview extraction")

    logger.warning("E_PROXY_FAIL: All DNG conversion strategies failed for %s", dng_path.name)
    return None


def scan_directory(input_dir: Path, proxy_dir: Path | None = None) -> list[MediaItem]:
    """Recursively scan a directory and return classified media items."""
    items: list[MediaItem] = []
    input_dir = Path(input_dir)

    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return items

    # Directories to skip
    skip_dirs = {".venv", "venv", "node_modules", "__pycache__", ".git", "output"}

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        # Skip files inside excluded directories
        if any(part in skip_dirs for part in path.relative_to(input_dir).parts):
            continue
        media_type = classify_file(path)
        if media_type is None:
            continue

        logger.info("Scanning: %s", path.name)
        item = extract_metadata(path, media_type)

        # Handle DNG proxy conversion
        if path.suffix.lower() == ".dng" and proxy_dir:
            proxy = convert_dng_proxy(path, proxy_dir)
            if proxy:
                item.proxy_path = proxy
                # Get proxy dimensions
                proxy_probe = probe_media(proxy)
                for s in proxy_probe.get("streams", []):
                    if s.get("codec_type") == "video":
                        item.width = int(s.get("width", 0))
                        item.height = int(s.get("height", 0))
                        break

        items.append(item)

    logger.info("Scanned %d media files", len(items))
    return items


def deduplicate(items: list[MediaItem]) -> list[MediaItem]:
    """Remove duplicate media items based on hash + file_size + duration."""
    seen: set[tuple[str, int, float]] = set()
    unique: list[MediaItem] = []
    duplicates = 0

    for item in items:
        key = (item.file_hash, item.file_size, round(item.duration_sec, 1))
        if key in seen:
            duplicates += 1
            logger.info("Duplicate skipped: %s", item.path.name)
            continue
        seen.add(key)
        unique.append(item)

    if duplicates:
        logger.info("Removed %d duplicates, %d unique items", duplicates, len(unique))
    return unique


def save_media_index(items: list[MediaItem], output_path: Path) -> None:
    """Save media index to JSON."""
    data = []
    for item in items:
        d = {
            "path": str(item.path),
            "media_type": item.media_type.value,
            "file_hash": item.file_hash,
            "file_size": item.file_size,
            "width": item.width,
            "height": item.height,
            "duration_sec": item.duration_sec,
            "fps": item.fps,
            "creation_time": item.creation_time,
        }
        if item.gps_lat is not None:
            d["gps_lat"] = item.gps_lat
            d["gps_lon"] = item.gps_lon
        if item.proxy_path:
            d["proxy_path"] = str(item.proxy_path)
        data.append(d)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved media index to %s", output_path)


def run_ingest(input_dir: Path, output_dir: Path) -> list[MediaItem]:
    """Full ingest pipeline: scan, dedup, save index."""
    proxy_dir = output_dir / "proxies"
    items = scan_directory(input_dir, proxy_dir=proxy_dir)
    items = deduplicate(items)
    save_media_index(items, output_dir / "media_index.json")
    return items
