"""Shared domain schemas (detections, events, stream status)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 in UTC; naive datetimes (e.g. from SQLite) are treated as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class StreamStatus(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    COMPLETED = "completed"  # file source reached EOF
    ERROR = "error"


class EventType(str, Enum):
    PERSON_ENTERED_ZONE = "PERSON_ENTERED_ZONE"
    PERSON_EXITED_ZONE = "PERSON_EXITED_ZONE"
    LINE_CROSSED = "LINE_CROSSED"
    CROWD_THRESHOLD_EXCEEDED = "CROWD_THRESHOLD_EXCEEDED"
    CROWD_THRESHOLD_CLEARED = "CROWD_THRESHOLD_CLEARED"


class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def bottom_center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, self.y2)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


class Detection(BaseModel):
    """A single raw detection produced by a Detector."""

    model_config = ConfigDict(populate_by_name=True)

    stream_id: int
    cls: str = Field(alias="class")
    confidence: float
    bbox: BBox
    timestamp: datetime
    frame_index: Optional[int] = None


class Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: EventType
    stream_id: int
    timestamp: datetime
    track_id: Optional[int] = None
    cls: Optional[str] = Field(default=None, alias="class")
    zone: Optional[str] = None
    line: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")
