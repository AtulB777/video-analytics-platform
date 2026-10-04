"""Draw detections, lines and zones on a frame for the dashboard preview."""
from __future__ import annotations

import cv2
import numpy as np

from app.analytics.config import AnalyticsConfig
from app.analytics.engine import AnalyticsSnapshot
from app.tracking.base import TrackedObject

_COLORS = {"person": (80, 200, 80), "car": (60, 160, 255)}


def draw_overlay(frame: np.ndarray, tracks: list[TrackedObject], cfg: AnalyticsConfig,
                 snap: AnalyticsSnapshot, fps: float) -> np.ndarray:
    layer = frame.copy()
    for z in cfg.zones:
        pts = np.array(z.polygon, dtype=np.int32)
        cv2.fillPoly(layer, [pts], (200, 120, 0))
    frame = cv2.addWeighted(layer, 0.18, frame, 0.82, 0)
    for z in cfg.zones:
        pts = np.array(z.polygon, dtype=np.int32)
        cv2.polylines(frame, [pts], True, (255, 160, 0), 1)
        cv2.putText(frame, f"{z.name}: {len(snap.zone_occupancy.get(z.name, []))}",
                    (pts[:, 0].min() + 4, pts[:, 1].min() + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 80), 1)
    for l in cfg.lines:
        cv2.line(frame, tuple(map(int, l.p1)), tuple(map(int, l.p2)), (0, 0, 255), 2)
        c = snap.line_counts.get(l.name, {})
        cv2.putText(frame, f"{l.name} in:{c.get('in', 0)} out:{c.get('out', 0)}",
                    (int(min(l.p1[0], l.p2[0])) + 6, int(max(l.p1[1], l.p2[1])) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 255), 1)
    for t in tracks:
        color = _COLORS.get(t.cls, (200, 200, 200))
        b = t.bbox
        cv2.rectangle(frame, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), color, 2)
        cv2.putText(frame, f"{t.cls} #{t.track_id}", (int(b.x1), max(12, int(b.y1) - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    cv2.putText(frame, f"people: {snap.people_count}  fps: {fps:.1f}", (8, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return frame
