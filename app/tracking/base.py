from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.core.schemas import BBox, Detection, iso


@dataclass
class TrackedObject:
    track_id: int
    cls: str
    confidence: float
    bbox: BBox
    first_seen: datetime
    last_seen: datetime
    hits: int = 1
    time_since_update: int = 0
    confirmed: bool = True
    history: deque = field(default_factory=lambda: deque(maxlen=30))  # anchor points

    @property
    def anchor(self) -> tuple[float, float]:
        """Point used for line/zone tests: feet for people, centre otherwise."""
        return self.bbox.bottom_center if self.cls == "person" else self.bbox.center

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "class": self.cls,
            "confidence": round(self.confidence, 3),
            "bbox": {"x1": round(self.bbox.x1, 1), "y1": round(self.bbox.y1, 1),
                     "x2": round(self.bbox.x2, 1), "y2": round(self.bbox.y2, 1)},
            "first_seen": iso(self.first_seen),
            "last_seen": iso(self.last_seen),
        }


class Tracker(ABC):
    """Detections in, persistent object IDs out.

    ``update`` returns only tracks that were *matched in this frame*.
    """

    name = "base"

    @abstractmethod
    def update(self, detections: list[Detection], timestamp: datetime) -> list[TrackedObject]: ...

    def reset(self) -> None:
        return None
