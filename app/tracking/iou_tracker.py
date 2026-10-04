"""Dependency-free IoU tracker (SORT-style association without a Kalman filter).

Greedy highest-IoU matching, class-aware. Tracks must be matched ``min_hits``
times before they are confirmed and receive a public ID, which avoids burning
IDs on one-frame false positives. Good enough for static cameras and modest
motion; for crowded scenes use ByteTrack/DeepSORT behind the same interface.
"""
from __future__ import annotations

from datetime import datetime

from app.core.geometry import iou
from app.core.schemas import Detection
from app.tracking.base import TrackedObject, Tracker


class IoUTracker(Tracker):
    name = "iou"

    def __init__(self, iou_threshold: float = 0.2, max_age: int = 15, min_hits: int = 3, start_id: int = 1):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits
        self._start_id = start_id
        self.reset()

    def reset(self) -> None:
        self._tracks: list[TrackedObject] = []
        self._next_id = self._start_id

    def update(self, detections: list[Detection], timestamp: datetime) -> list[TrackedObject]:
        pairs = []
        for ti, t in enumerate(self._tracks):
            for di, d in enumerate(detections):
                if t.cls != d.cls:
                    continue
                score = iou(t.bbox.as_tuple(), d.bbox.as_tuple())
                if score >= self.iou_threshold:
                    pairs.append((score, ti, di))
        pairs.sort(reverse=True)

        used_t: set[int] = set()
        used_d: set[int] = set()
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            t, d = self._tracks[ti], detections[di]
            t.bbox, t.confidence = d.bbox, d.confidence
            t.last_seen = timestamp
            t.hits += 1
            t.time_since_update = 0
            t.history.append(t.anchor)
            if not t.confirmed and t.hits >= self.min_hits:
                t.confirmed = True
                t.track_id = self._next_id
                self._next_id += 1

        for ti, t in enumerate(self._tracks):
            if ti not in used_t:
                t.time_since_update += 1

        for di, d in enumerate(detections):
            if di in used_d:
                continue
            t = TrackedObject(track_id=0, cls=d.cls, confidence=d.confidence, bbox=d.bbox,
                              first_seen=timestamp, last_seen=timestamp, confirmed=False)
            t.history.append(t.anchor)
            if self.min_hits <= 1:
                t.confirmed = True
                t.track_id = self._next_id
                self._next_id += 1
            self._tracks.append(t)

        self._tracks = [
            t for t in self._tracks
            if t.time_since_update <= (self.max_age if t.confirmed else 1)
        ]
        return [t for t in self._tracks if t.confirmed and t.time_since_update == 0]
