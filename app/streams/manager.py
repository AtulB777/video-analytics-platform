"""StreamManager: owns the lifecycle of every stream's pipeline."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from app.analytics.config import AnalyticsConfig
from app.analytics.engine import AnalyticsEngine
from app.core.config import Settings
from app.core.schemas import StreamStatus
from app.core.utils import mask_uri
from app.database.repository import Repository
from app.detection.factory import create_detector
from app.events.engine import EventEngine
from app.streams.factory import create_source, validate_source
from app.streams.pipeline import StreamPipeline
from app.tracking.factory import create_tracker
from app.websocket.hub import WebSocketHub

log = logging.getLogger(__name__)


class StreamNotFound(KeyError):
    pass


class StreamManager:
    def __init__(self, settings: Settings, repo: Repository, hub: WebSocketHub,
                 profiles: dict[str, AnalyticsConfig]):
        self.settings, self.repo, self.hub, self.profiles = settings, repo, hub, profiles
        self._runtimes: dict[int, StreamPipeline] = {}
        self._lock = threading.RLock()

    # --------------------------------------------------------------- helpers
    def _view(self, row: dict) -> dict:
        rt = self._runtimes.get(row["id"])
        out = dict(row)
        out["uri"] = mask_uri(row["uri"])
        if rt:
            out["status"] = rt.status.value
            out["last_error"] = rt._error
            out["health"] = rt.health()
        else:
            out["health"] = None
        return out

    def _require(self, stream_id: int) -> dict:
        row = self.repo.get_stream(stream_id)
        if not row:
            raise StreamNotFound(stream_id)
        return row

    def _on_status(self, stream_id: int, status: StreamStatus, error: Optional[str]) -> None:
        stopped = status in (StreamStatus.STOPPED, StreamStatus.COMPLETED, StreamStatus.ERROR)
        self.repo.update_stream_status(stream_id, status.value, error,
                                       started=status == StreamStatus.STARTING, stopped=stopped)

    # ------------------------------------------------------------------- API
    def create_stream(self, name: str, source_type: str, uri: Optional[str], profile: str = "default",
                      camera_name: Optional[str] = None, location: Optional[str] = None) -> dict:
        if profile not in self.profiles:
            raise ValueError(f"Unknown analytics profile '{profile}'. Available: {sorted(self.profiles)}")
        normalized = validate_source(source_type, uri, self.settings)
        row = self.repo.create_stream(name, source_type, normalized, profile, camera_name, location)
        return self._view(row)

    def list_streams(self) -> list[dict]:
        return [self._view(r) for r in self.repo.list_streams()]

    def get_stream(self, stream_id: int) -> dict:
        return self._view(self._require(stream_id))

    def statuses(self) -> list[dict]:
        return [{"id": s["id"], "name": s["name"], "status": s["status"]} for s in self.list_streams()]

    def start_stream(self, stream_id: int) -> dict:
        with self._lock:
            row = self._require(stream_id)
            existing = self._runtimes.get(stream_id)
            if existing and existing.running:
                return self._view(row)

            cfg = self.profiles[row["profile"]]
            start_id = self.repo.max_track_id(stream_id) + 1  # keep (stream_id, track_id) unique across restarts
            analytics = AnalyticsEngine(cfg)
            pipeline = StreamPipeline(
                stream_id=stream_id, name=row["name"],
                source=create_source(row["source_type"], row["uri"], self.settings),
                detector=create_detector(self.settings),
                tracker=create_tracker(self.settings, start_id=start_id),
                analytics=analytics,
                events=EventEngine(stream_id, cfg.crowd_threshold, cfg.crowd_hysteresis,
                                   exit_grace_s=cfg.exit_grace_s),
                settings=self.settings, repo=self.repo, hub=self.hub, on_status=self._on_status,
            )
            self._runtimes[stream_id] = pipeline
            pipeline.start()
            return self._view(self._require(stream_id))

    def stop_stream(self, stream_id: int) -> dict:
        with self._lock:
            row = self._require(stream_id)
            rt = self._runtimes.get(stream_id)
        if rt and rt.running:
            rt.stop()
        return self._view(self._require(stream_id) if rt else row)

    def delete_stream(self, stream_id: int) -> None:
        self._require(stream_id)
        with self._lock:
            rt = self._runtimes.pop(stream_id, None)
        if rt:
            rt.stop()
        self.repo.delete_stream(stream_id)

    def runtime(self, stream_id: int) -> Optional[StreamPipeline]:
        self._require(stream_id)
        return self._runtimes.get(stream_id)

    def analytics(self, stream_id: int) -> dict:
        row = self._require(stream_id)
        rt = self._runtimes.get(stream_id)
        summary = self.repo.stream_summary(stream_id)
        base = {"stream_id": stream_id, "name": row["name"], "event_counts": summary["event_counts"]}
        if rt:
            snap = rt.snapshot()
            cur = snap["analytics"]
            return {**base, "status": rt.status.value, "source": "live",
                    "current": {"object_counts": cur.get("object_counts", {}),
                                "people_count": cur.get("people_count", 0),
                                "zone_occupancy": cur.get("zone_occupancy", {}),
                                "timestamp": cur.get("timestamp")},
                    "cumulative": {"line_counts": cur.get("line_counts", {}),
                                   "unique_objects": cur.get("unique_objects", {})},
                    "objects": snap["objects"], "health": rt.health()}
        return {**base, "status": row["status"], "source": "database", "current": None,
                "cumulative": {"line_counts": None, "unique_objects": summary["unique_objects"]},
                "objects": [], "health": None}

    def shutdown(self) -> None:
        with self._lock:
            runtimes = list(self._runtimes.values())
        for rt in runtimes:
            if rt.running:
                rt.stop(timeout=3.0)

    # --------------------------------------------------------------- bootstrap
    def bootstrap_sample(self) -> Optional[int]:
        """Create (generating the video if needed) and start the demo stream. Idempotent."""
        from app.streams.sample import generate_sample_video

        path = Path(self.settings.sample_video)
        if not path.is_file():
            log.info("generating sample video at %s", path)
            generate_sample_video(path)
        uri = validate_source("file", str(path), self.settings)
        for s in self.repo.list_streams():
            if s["uri"] == uri:
                self.start_stream(s["id"])
                return s["id"]
        row = self.repo.create_stream("Sample lobby camera", "file", uri, "default",
                                      camera_name="Sample lobby camera", location="synthetic")
        self.start_stream(row["id"])
        return row["id"]
