"""Environment-driven configuration.

All tunables come from environment variables (optionally loaded from a local
``.env`` file). No third-party settings library is needed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    return default if v in (None, "") else float(v)


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return default if v in (None, "") else int(v)


def _str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None else v


@dataclass(frozen=True)
class Settings:
    # Persistence
    database_url: str = "sqlite:///./vap.db"
    persist_detections: bool = True
    persist_every_n: int = 1
    metrics_persist_interval_s: float = 5.0

    # Detection
    detector: str = "mock"  # mock | yolo
    detector_fallback_to_mock: bool = False
    yolo_model: str = "yolov8n.pt"
    yolo_device: str = ""
    detect_classes: tuple = ("person", "car", "truck", "bus", "bicycle", "motorcycle")
    confidence_threshold: float = 0.4

    # Pipeline
    processing_fps: float = 10.0
    tracker: str = "iou"  # iou | bytetrack
    queue_size: int = 8
    jpeg_quality: int = 70
    status_publish_interval_s: float = 2.0

    # Sources
    video_dir: str = "sample_videos"
    file_playback_speed: float = 1.0  # 1.0 = real time, 0 = as fast as possible
    loop_video: bool = False
    rtsp_reconnect_max_s: float = 30.0

    # Analytics
    zones_config_path: str = "configs/zones.json"
    zones_json: str = ""
    crowd_threshold: Optional[int] = None

    # App
    autostart_sample: bool = False
    sample_video: str = "sample_videos/lobby_demo.mp4"
    log_level: str = "INFO"
    cors_origins: tuple = ("*",)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        crowd = os.getenv("CROWD_THRESHOLD")
        return cls(
            database_url=_str("DATABASE_URL", cls.database_url),
            persist_detections=_bool("PERSIST_DETECTIONS", True),
            persist_every_n=max(1, _int("PERSIST_EVERY_N", 1)),
            metrics_persist_interval_s=_float("METRICS_PERSIST_INTERVAL_S", 5.0),
            detector=_str("DETECTOR", "mock").lower(),
            detector_fallback_to_mock=_bool("DETECTOR_FALLBACK_TO_MOCK", False),
            yolo_model=_str("YOLO_MODEL", "yolov8n.pt"),
            yolo_device=_str("YOLO_DEVICE", ""),
            detect_classes=tuple(
                c.strip() for c in _str("DETECT_CLASSES", ",".join(cls.detect_classes)).split(",") if c.strip()
            ),
            confidence_threshold=_float("CONFIDENCE_THRESHOLD", 0.4),
            processing_fps=_float("PROCESSING_FPS", 10.0),
            tracker=_str("TRACKER", "iou").lower(),
            queue_size=max(1, _int("QUEUE_SIZE", 8)),
            jpeg_quality=_int("JPEG_QUALITY", 70),
            status_publish_interval_s=_float("STATUS_PUBLISH_INTERVAL_S", 2.0),
            video_dir=_str("VIDEO_DIR", "sample_videos"),
            file_playback_speed=_float("FILE_PLAYBACK_SPEED", 1.0),
            loop_video=_bool("LOOP_VIDEO", False),
            rtsp_reconnect_max_s=_float("RTSP_RECONNECT_MAX_S", 30.0),
            zones_config_path=_str("ZONES_CONFIG", "configs/zones.json"),
            zones_json=_str("ZONES_JSON", ""),
            crowd_threshold=int(crowd) if crowd not in (None, "") else None,
            autostart_sample=_bool("AUTOSTART_SAMPLE", False),
            sample_video=_str("SAMPLE_VIDEO", "sample_videos/lobby_demo.mp4"),
            log_level=_str("LOG_LEVEL", "INFO").upper(),
            cors_origins=tuple(o.strip() for o in _str("CORS_ORIGINS", "*").split(",") if o.strip()),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
