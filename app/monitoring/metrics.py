"""Pipeline metrics abstraction.

``PipelineMetrics`` is a small, thread-safe collector used by every stream
pipeline. It records *measured* values only: nothing here is estimated or
hard-coded. Rates are computed over a sliding window.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Optional

from app.core.schemas import iso, utcnow


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; returns 0.0 for empty input."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class Timer:
    """``with Timer() as t: ...; t.ms``"""

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000.0


class PipelineMetrics:
    def __init__(self, window_s: float = 5.0, clock: Callable[[], float] = time.monotonic):
        self._window = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._started_at = clock()
        self._frames: deque[tuple[float, float, dict[str, float]]] = deque()  # (t, pipeline_ms, stages)
        self._inputs: deque[float] = deque()
        self._dropped = 0
        self._skipped = 0
        self._processed = 0
        self._received = 0
        self._queue_size = 0
        self._last_frame_ts: Optional[datetime] = None

    # --- recording -------------------------------------------------
    def reset_clock(self) -> None:
        with self._lock:
            self._started_at = self._clock()

    def record_input(self) -> None:
        now = self._clock()
        with self._lock:
            self._received += 1
            self._inputs.append(now)
            self._trim(now)

    def record_frame(self, pipeline_ms: float, stages: Optional[dict[str, float]] = None,
                     frame_ts: Optional[datetime] = None) -> None:
        """pipeline_ms: capture -> done (includes queue wait). stages: per-stage ms."""
        now = self._clock()
        with self._lock:
            self._processed += 1
            self._frames.append((now, pipeline_ms, dict(stages or {})))
            self._last_frame_ts = frame_ts or utcnow()
            self._trim(now)

    def record_dropped(self, n: int = 1) -> None:
        with self._lock:
            self._dropped += n

    def record_skipped(self, n: int = 1) -> None:
        with self._lock:
            self._skipped += n

    def set_queue_size(self, n: int) -> None:
        with self._lock:
            self._queue_size = n

    # --- reading ---------------------------------------------------
    def _trim(self, now: float) -> None:
        cutoff = now - self._window
        while self._frames and self._frames[0][0] < cutoff:
            self._frames.popleft()
        while self._inputs and self._inputs[0] < cutoff:
            self._inputs.popleft()

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            self._trim(now)
            span = max(1e-6, min(self._window, now - self._started_at))
            pipe = [f[1] for f in self._frames]
            stage_names = {k for f in self._frames for k in f[2]}
            stages = {}
            for name in sorted(stage_names):
                vals = [f[2][name] for f in self._frames if name in f[2]]
                stages[name] = {"avg_ms": round(sum(vals) / len(vals), 3), "p95_ms": round(percentile(vals, 95), 3)}
            inf = stages.get("inference", {})
            return {
                "processing_fps": round(len(self._frames) / span, 2),
                "input_fps": round(len(self._inputs) / span, 2),
                "inference_ms_avg": inf.get("avg_ms", 0.0),
                "inference_ms_p95": inf.get("p95_ms", 0.0),
                "pipeline_ms_avg": round(sum(pipe) / len(pipe), 3) if pipe else 0.0,
                "pipeline_ms_p95": round(percentile(pipe, 95), 3),
                "stages": stages,
                "queue_size": self._queue_size,
                "dropped_frames": self._dropped,
                "skipped_frames": self._skipped,
                "frames_received": self._received,
                "frames_processed": self._processed,
                "last_frame_timestamp": iso(self._last_frame_ts),
                "window_s": self._window,
            }
