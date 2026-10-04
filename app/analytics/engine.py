"""Per-stream analytics: object/people counts, line crossings, zone occupancy."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.analytics.config import AnalyticsConfig
from app.core.geometry import crossing_direction, point_in_polygon
from app.core.schemas import iso
from app.tracking.base import TrackedObject


@dataclass
class LineCrossing:
    line: str
    track_id: int
    cls: str
    direction: str  # "in" | "out" relative to the directed line p1->p2


@dataclass
class AnalyticsSnapshot:
    timestamp: datetime
    object_counts: dict[str, int]
    people_count: int
    visible_track_ids: set[int]
    zone_occupancy: dict[str, list[int]]  # zone -> ids of people inside
    new_crossings: list[LineCrossing]
    line_counts: dict[str, dict[str, int]]  # cumulative since stream start
    unique_objects: dict[str, int]  # distinct track IDs seen per class

    def to_dict(self) -> dict:
        return {
            "timestamp": iso(self.timestamp),
            "object_counts": self.object_counts,
            "people_count": self.people_count,
            "zone_occupancy": {z: len(ids) for z, ids in self.zone_occupancy.items()},
            "line_counts": self.line_counts,
            "unique_objects": self.unique_objects,
        }


class AnalyticsEngine:
    def __init__(self, config: AnalyticsConfig):
        self._config = config
        self._abs: Optional[AnalyticsConfig] = None if config.normalized else config
        self._line_counts = {l.name: {"in": 0, "out": 0} for l in config.lines}
        self._seen: dict[str, set[int]] = {}

    @property
    def config(self) -> AnalyticsConfig:
        return self._abs or self._config

    @property
    def crowd_threshold(self) -> int:
        return self._config.crowd_threshold

    def set_frame_size(self, width: int, height: int) -> None:
        self._abs = self._config.resolve(width, height)

    def update(self, tracks: list[TrackedObject], timestamp: datetime) -> AnalyticsSnapshot:
        cfg = self.config
        counts = Counter(t.cls for t in tracks)
        for t in tracks:
            self._seen.setdefault(t.cls, set()).add(t.track_id)

        crossings: list[LineCrossing] = []
        for t in tracks:
            if len(t.history) < 2:
                continue
            prev, cur = t.history[-2], t.history[-1]
            for line in cfg.lines:
                direction = crossing_direction(prev, cur, line.p1, line.p2)
                if direction:
                    self._line_counts[line.name][direction] += 1
                    crossings.append(LineCrossing(line.name, t.track_id, t.cls, direction))

        people = [t for t in tracks if t.cls == "person"]
        occupancy = {
            z.name: [t.track_id for t in people if point_in_polygon(t.anchor, z.polygon)]
            for z in cfg.zones
        }
        return AnalyticsSnapshot(
            timestamp=timestamp,
            object_counts=dict(counts),
            people_count=len(people),
            visible_track_ids={t.track_id for t in tracks},
            zone_occupancy=occupancy,
            new_crossings=crossings,
            line_counts={k: dict(v) for k, v in self._line_counts.items()},
            unique_objects={k: len(v) for k, v in self._seen.items()},
        )
