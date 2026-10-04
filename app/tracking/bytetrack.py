"""ByteTrack adapter built on the optional ``supervision`` package.

Experimental: this adapter is not exercised by the test-suite (the dependency
is optional and not installed by default). It exists to show where a
production tracker plugs in; DeepSORT can be wrapped the same way.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from app.core.schemas import BBox, Detection
from app.tracking.base import TrackedObject, Tracker


class ByteTrackTracker(Tracker):
    name = "bytetrack"

    def __init__(self, fps: float = 10.0):
        try:
            import supervision as sv  # type: ignore
        except ImportError as exc:
            raise RuntimeError("ByteTrack needs supervision: pip install supervision") from exc
        self._sv = sv
        self._fps = max(1, int(round(fps)))
        self.reset()

    def reset(self) -> None:
        self._bt = self._sv.ByteTrack(frame_rate=self._fps)
        self._classes: list[str] = []
        self._objs: dict[int, TrackedObject] = {}

    def update(self, detections: list[Detection], timestamp: datetime) -> list[TrackedObject]:
        sv = self._sv
        for d in detections:
            if d.cls not in self._classes:
                self._classes.append(d.cls)
        if detections:
            xyxy = np.array([d.bbox.as_tuple() for d in detections], dtype=float)
            conf = np.array([d.confidence for d in detections], dtype=float)
            cid = np.array([self._classes.index(d.cls) for d in detections], dtype=int)
            sv_det = sv.Detections(xyxy=xyxy, confidence=conf, class_id=cid)
        else:
            sv_det = sv.Detections.empty()
        out = self._bt.update_with_detections(sv_det)
        result: list[TrackedObject] = []
        for i in range(len(out)):
            tid = int(out.tracker_id[i])
            x1, y1, x2, y2 = (float(v) for v in out.xyxy[i])
            cls = self._classes[int(out.class_id[i])]
            obj = self._objs.get(tid)
            bbox = BBox(x1=x1, y1=y1, x2=x2, y2=y2)
            conf = float(out.confidence[i]) if out.confidence is not None else 0.0
            if obj is None:
                obj = TrackedObject(track_id=tid, cls=cls, confidence=conf, bbox=bbox,
                                    first_seen=timestamp, last_seen=timestamp)
                self._objs[tid] = obj
            obj.bbox, obj.confidence, obj.last_seen = bbox, conf, timestamp
            obj.hits += 1
            obj.history.append(obj.anchor)
            result.append(obj)
        return result
