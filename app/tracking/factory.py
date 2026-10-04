from __future__ import annotations

from app.core.config import Settings
from app.tracking.base import Tracker
from app.tracking.iou_tracker import IoUTracker


def create_tracker(settings: Settings, start_id: int = 1) -> Tracker:
    if settings.tracker == "iou":
        return IoUTracker(start_id=start_id)
    if settings.tracker == "bytetrack":
        from app.tracking.bytetrack import ByteTrackTracker

        return ByteTrackTracker(fps=settings.processing_fps)
    raise ValueError(f"Unknown TRACKER '{settings.tracker}' (expected 'iou' or 'bytetrack')")
