"""Per-stream processing pipeline.

Two threads per stream, connected by a bounded queue:

    reader thread:    VideoSource.read() -> queue   (drops oldest when full on live/real-time input)
    processor thread: queue -> throttle -> detect -> track -> analytics -> events
                      -> persist + publish + overlay

Decoupling reading from processing keeps a slow detector from stalling the
camera connection; the queue + drop counter make that back-pressure visible.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import cv2
import numpy as np

from app.analytics.engine import AnalyticsEngine, AnalyticsSnapshot
from app.core.config import Settings
from app.core.schemas import StreamStatus, iso, utcnow
from app.detection.base import Detector
from app.events.engine import EventEngine
from app.monitoring.metrics import PipelineMetrics
from app.streams.base import VideoSource
from app.streams.overlay import draw_overlay
from app.tracking.base import Tracker, TrackedObject

log = logging.getLogger(__name__)


@dataclass
class FrameItem:
    frame: np.ndarray
    index: int
    pts: float  # seconds on the source timeline (file) or monotonic clock (live)
    wall_ts: datetime
    t_read: float  # perf_counter at capture, for end-to-end latency


class StreamPipeline:
    def __init__(self, stream_id: int, name: str, source: VideoSource, detector: Detector,
                 tracker: Tracker, analytics: AnalyticsEngine, events: EventEngine,
                 settings: Settings, repo=None, hub=None,
                 on_status: Optional[Callable[[int, StreamStatus, Optional[str]], None]] = None):
        self.stream_id, self.name = stream_id, name
        self.source, self.detector, self.tracker = source, detector, tracker
        self.analytics, self.events = analytics, events
        self.settings, self.repo, self.hub = settings, repo, hub
        self._on_status = on_status

        self.metrics = PipelineMetrics()
        self._queue: queue.Queue[FrameItem] = queue.Queue(maxsize=settings.queue_size)
        self._stop = threading.Event()
        self._reader_done = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._status = StreamStatus.CREATED
        self._error: Optional[str] = None

        # realtime pacing for files (speed 0 = as fast as possible, with back-pressure)
        self._realtime = source.is_live or settings.file_playback_speed > 0
        self._min_interval = 1.0 / settings.processing_fps if settings.processing_fps > 0 else 0.0
        self._last_pts: Optional[float] = None
        self._frame_size_set = False

        self._latest: dict = {}
        self._latest_jpeg: Optional[bytes] = None
        self._latest_tracks: list[dict] = []
        self._dirty_tracks: dict[int, TrackedObject] = {}
        self._last_track_flush = time.monotonic()
        self._last_metric_persist = time.monotonic()
        self._last_status_pub = 0.0
        self._processed = 0

    # ------------------------------------------------------------------ status
    @property
    def status(self) -> StreamStatus:
        return self._status

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def _set_status(self, status: StreamStatus, error: Optional[str] = None) -> None:
        if status == self._status and error == self._error:
            return
        self._status, self._error = status, error
        log.info("stream %s -> %s%s", self.stream_id, status.value, f" ({error})" if error else "")
        if self._on_status:
            try:
                self._on_status(self.stream_id, status, error)
            except Exception:
                log.exception("status callback failed")
        self._publish_status()

    def _publish_status(self) -> None:
        if self.hub:
            self.hub.publish({"type": "stream_status", "stream_id": self.stream_id, "timestamp": iso(utcnow()),
                              "data": {"status": self._status.value, "error": self._error,
                                       "health": self.health()}})
        self._last_status_pub = time.monotonic()

    def health(self) -> dict:
        m = self.metrics.snapshot()
        m["status"] = self._status.value
        m["error"] = self._error
        m["source_fps"] = round(self.source.fps, 2)
        m["detector"] = self.detector.name
        m["tracker"] = self.tracker.name
        return m

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._set_status(StreamStatus.STARTING)
        self.metrics.reset_clock()
        reader = threading.Thread(target=self._reader_loop, name=f"reader-{self.stream_id}", daemon=True)
        proc = threading.Thread(target=self._processor_loop, name=f"proc-{self.stream_id}", daemon=True)
        self._threads = [reader, proc]
        reader.start()
        proc.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        try:
            self.source.close()
        except Exception:
            pass

    # ----------------------------------------------------------------- reader
    def _enqueue(self, item: FrameItem) -> None:
        if self._realtime:
            while True:
                try:
                    self._queue.put_nowait(item)
                    return
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self.metrics.record_dropped()
                    except queue.Empty:
                        pass
        else:  # offline file mode: back-pressure instead of dropping
            while not self._stop.is_set():
                try:
                    self._queue.put(item, timeout=0.2)
                    return
                except queue.Full:
                    continue

    def _reader_loop(self) -> None:
        backoff = 1.0
        idx = 0
        t0 = time.monotonic()
        opened = False
        next_t = time.perf_counter()
        try:
            while not self._stop.is_set():
                if not opened:
                    try:
                        self.source.open()
                        opened = True
                        backoff = 1.0
                    except Exception as exc:
                        if not self.source.is_live:
                            self._set_status(StreamStatus.ERROR, str(exc))
                            return
                        self._set_status(StreamStatus.RECONNECTING, str(exc))
                        if self._stop.wait(backoff):
                            return
                        backoff = min(backoff * 2, self.settings.rtsp_reconnect_max_s)
                        continue
                    fps = self.source.fps or 25.0
                    pace = (1.0 / (fps * self.settings.file_playback_speed)
                            if (not self.source.is_live and self.settings.file_playback_speed > 0) else 0.0)
                    next_t = time.perf_counter()

                ok, frame = self.source.read()
                if not ok or frame is None:
                    if not self.source.is_live:
                        return  # EOF
                    self._set_status(StreamStatus.RECONNECTING, "no frames received")
                    self.source.close()
                    opened = False
                    if self._stop.wait(backoff):
                        return
                    backoff = min(backoff * 2, self.settings.rtsp_reconnect_max_s)
                    continue

                if self._status != StreamStatus.RUNNING:
                    self._set_status(StreamStatus.RUNNING)
                now = time.perf_counter()
                src_fps = self.source.fps or 25.0
                pts = (time.monotonic() - t0) if self.source.is_live else idx / src_fps
                self.metrics.record_input()
                self._enqueue(FrameItem(frame, idx, pts, utcnow(), now))
                idx += 1

                if pace:
                    next_t += pace
                    delay = next_t - time.perf_counter()
                    if delay > 0:
                        self._stop.wait(delay)
                    else:
                        next_t = time.perf_counter()
        except Exception as exc:
            log.exception("reader crashed")
            self._set_status(StreamStatus.ERROR, f"reader: {exc}")
            self._stop.set()
        finally:
            self._reader_done.set()

    # -------------------------------------------------------------- processor
    def _processor_loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    item = self._queue.get(timeout=0.25)
                except queue.Empty:
                    if self._reader_done.is_set():
                        break
                    self._maybe_publish_status()
                    continue
                self.metrics.set_queue_size(self._queue.qsize())
                if (self._last_pts is not None and self._min_interval
                        and item.pts - self._last_pts < self._min_interval - 1e-6):
                    self.metrics.record_skipped()
                    continue
                self._last_pts = item.pts
                self._process(item)
        except Exception as exc:
            log.exception("processor crashed")
            self._set_status(StreamStatus.ERROR, f"processor: {exc}")
            self._stop.set()
        finally:
            self._finish()

    def _finish(self) -> None:
        try:
            self._flush_tracks(force=True)
            self._persist_metrics(force=True)
        except Exception:
            log.exception("final flush failed")
        try:
            self.source.close()
            self.detector.close()
        except Exception:
            pass
        if self._status not in (StreamStatus.ERROR,):
            clean_eof = self._reader_done.is_set() and not self._stop.is_set() and not self.source.is_live
            self._set_status(StreamStatus.COMPLETED if clean_eof else StreamStatus.STOPPED)

    def _process(self, item: FrameItem) -> None:
        t0 = time.perf_counter()
        frame = item.frame
        if not self._frame_size_set:
            h, w = frame.shape[:2]
            self.analytics.set_frame_size(w, h)
            self._frame_size_set = True

        detections = self.detector.detect(frame, self.stream_id, item.wall_ts)
        for d in detections:
            d.frame_index = item.index
        t1 = time.perf_counter()
        tracks = self.tracker.update(detections, item.wall_ts)
        t2 = time.perf_counter()
        snap = self.analytics.update(tracks, item.wall_ts)
        events = self.events.process(snap)
        t3 = time.perf_counter()

        fps_now = self.metrics.snapshot()["processing_fps"]
        annotated = draw_overlay(frame, tracks, self.analytics.config, snap, fps_now)
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality])
        t4 = time.perf_counter()

        self._processed += 1
        self._remember(item, tracks, snap)
        self._persist(item, detections, tracks, events)
        self._publish(item, tracks, snap, events)

        done = time.perf_counter()
        self.metrics.record_frame(
            pipeline_ms=(done - item.t_read) * 1000.0,
            stages={"inference": (t1 - t0) * 1000, "tracking": (t2 - t1) * 1000,
                    "analytics": (t3 - t2) * 1000, "render": (t4 - t3) * 1000,
                    "processing": (done - t0) * 1000},
            frame_ts=item.wall_ts,
        )
        with self._lock:
            if ok:
                self._latest_jpeg = buf.tobytes()
        self._persist_metrics()
        self._maybe_publish_status()

    # ------------------------------------------------------- state / outputs
    def _remember(self, item: FrameItem, tracks: list[TrackedObject], snap: AnalyticsSnapshot) -> None:
        with self._lock:
            self._latest = snap.to_dict()
            self._latest["frame_index"] = item.index
            self._latest_tracks = [t.to_dict() for t in tracks]
        for t in tracks:
            self._dirty_tracks[t.track_id] = t

    def _persist(self, item: FrameItem, detections, tracks, events) -> None:
        if not self.repo:
            return
        if self.settings.persist_detections and self._processed % self.settings.persist_every_n == 0:
            self.repo.insert_detections(self.stream_id, detections)
        if events:
            self.repo.insert_events(self.stream_id, events)
        self._flush_tracks()

    def _flush_tracks(self, force: bool = False) -> None:
        if not self.repo or not self._dirty_tracks:
            return
        if force or time.monotonic() - self._last_track_flush >= 1.0:
            self.repo.upsert_tracks(self.stream_id, list(self._dirty_tracks.values()))
            self._dirty_tracks.clear()
            self._last_track_flush = time.monotonic()

    def _persist_metrics(self, force: bool = False) -> None:
        if not self.repo:
            return
        if force or time.monotonic() - self._last_metric_persist >= self.settings.metrics_persist_interval_s:
            self.repo.insert_metric(self.stream_id, self.health())
            self._last_metric_persist = time.monotonic()

    def _publish(self, item: FrameItem, tracks, snap: AnalyticsSnapshot, events) -> None:
        if not self.hub:
            return
        ts = iso(item.wall_ts)
        sid = self.stream_id
        self.hub.publish({"type": "detections", "stream_id": sid, "timestamp": ts,
                          "data": {"frame_index": item.index, "objects": [t.to_dict() for t in tracks]}})
        self.hub.publish({"type": "analytics", "stream_id": sid, "timestamp": ts, "data": snap.to_dict()})
        for e in events:
            self.hub.publish({"type": "event", "stream_id": sid, "timestamp": ts, "data": e.to_dict()})

    def _maybe_publish_status(self) -> None:
        if time.monotonic() - self._last_status_pub >= self.settings.status_publish_interval_s:
            self._publish_status()

    # ------------------------------------------------------------ read access
    def snapshot(self) -> dict:
        with self._lock:
            return {"analytics": dict(self._latest), "objects": list(self._latest_tracks)}

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg
