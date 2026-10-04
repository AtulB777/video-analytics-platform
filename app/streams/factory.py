from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.streams.base import FileVideoSource, RTSPVideoSource, VideoSource, WebcamVideoSource

SOURCE_TYPES = ("file", "webcam", "rtsp")


def resolve_video_path(uri: str, settings: Settings) -> Path:
    """Resolve a file URI and make sure it lives inside VIDEO_DIR."""
    root = Path(settings.video_dir).resolve()
    candidate = Path(uri)
    options = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, root / candidate]
    for opt in options:
        resolved = opt.resolve()
        if resolved.is_file():
            if root != resolved and root not in resolved.parents:
                raise ValueError(f"Video files must be inside VIDEO_DIR ({root})")
            return resolved
    raise ValueError(f"Video file not found: {uri} (looked in VIDEO_DIR={root})")


def validate_source(source_type: str, uri: str | None, settings: Settings) -> str:
    """Validate and normalise a source URI. Returns the URI to store."""
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {SOURCE_TYPES}")
    if source_type == "file":
        if not uri:
            raise ValueError("uri is required for file sources")
        return str(resolve_video_path(uri, settings))
    if source_type == "webcam":
        uri = uri or "0"
        if not uri.isdigit():
            raise ValueError("webcam uri must be a device index such as '0'")
        return uri
    if not uri or not uri.lower().startswith(("rtsp://", "rtsps://")):
        raise ValueError("rtsp uri must start with rtsp:// or rtsps://")
    return uri


def create_source(source_type: str, uri: str, settings: Settings) -> VideoSource:
    if source_type == "file":
        return FileVideoSource(uri, loop=settings.loop_video)
    if source_type == "webcam":
        return WebcamVideoSource(uri)
    if source_type == "rtsp":
        return RTSPVideoSource(uri)
    raise ValueError(f"Unknown source_type: {source_type}")
