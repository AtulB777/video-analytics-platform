"""All database access lives here. Methods are synchronous and thread-safe
(one short-lived session per call), so pipeline threads and API handlers can share it."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, Optional

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.schemas import Detection as DetectionSchema
from app.core.schemas import Event as EventSchema
from app.core.schemas import utcnow
from app.database import models as m


class Repository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._sf()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def ping(self) -> bool:
        try:
            with self.session() as s:
                s.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    # ---------------------------------------------------------- streams
    def create_stream(self, name: str, source_type: str, uri: str, profile: str,
                      camera_name: Optional[str] = None, location: Optional[str] = None) -> dict:
        with self.session() as s:
            cam = m.Camera(name=camera_name or name, location=location)
            s.add(cam)
            s.flush()
            st = m.Stream(camera_id=cam.id, name=name, source_type=source_type, uri=uri, profile=profile)
            s.add(st)
            s.flush()
            return st.to_dict()

    def list_streams(self) -> list[dict]:
        with self.session() as s:
            return [r.to_dict() for r in s.scalars(select(m.Stream).order_by(m.Stream.id))]

    def get_stream(self, stream_id: int) -> Optional[dict]:
        with self.session() as s:
            row = s.get(m.Stream, stream_id)
            return row.to_dict() if row else None

    def update_stream_status(self, stream_id: int, status: str, error: Optional[str] = None,
                             started: bool = False, stopped: bool = False) -> None:
        values: dict[str, Any] = {"status": status, "last_error": error}
        if started:
            values["started_at"] = utcnow()
            values["stopped_at"] = None
        if stopped:
            values["stopped_at"] = utcnow()
        with self.session() as s:
            s.execute(update(m.Stream).where(m.Stream.id == stream_id).values(**values))

    def reset_stale_statuses(self) -> None:
        """After a restart nothing is actually running; fix leftover statuses."""
        with self.session() as s:
            s.execute(update(m.Stream)
                      .where(m.Stream.status.in_(["starting", "running", "reconnecting"]))
                      .values(status="stopped", stopped_at=utcnow()))

    def delete_stream(self, stream_id: int) -> bool:
        with self.session() as s:
            row = s.get(m.Stream, stream_id)
            if not row:
                return False
            camera_id = row.camera_id
            for table in (m.Detection, m.Track, m.Event, m.ProcessingMetric):
                s.execute(delete(table).where(table.stream_id == stream_id))
            s.execute(delete(m.Stream).where(m.Stream.id == stream_id))
            remaining = s.scalar(select(func.count()).select_from(m.Stream).where(m.Stream.camera_id == camera_id))
            if not remaining:
                s.execute(delete(m.Camera).where(m.Camera.id == camera_id))
            return True

    # ------------------------------------------------------- write path
    def insert_detections(self, stream_id: int, detections: list[DetectionSchema]) -> None:
        if not detections:
            return
        rows = [{"stream_id": stream_id, "frame_index": d.frame_index, "timestamp": d.timestamp,
                 "cls": d.cls, "confidence": d.confidence, "x1": d.bbox.x1, "y1": d.bbox.y1,
                 "x2": d.bbox.x2, "y2": d.bbox.y2} for d in detections]
        with self.session() as s:
            s.execute(m.Detection.__table__.insert(), [
                {("class" if k == "cls" else k): v for k, v in r.items()} for r in rows])

    def max_track_id(self, stream_id: int) -> int:
        with self.session() as s:
            return s.scalar(select(func.max(m.Track.track_id)).where(m.Track.stream_id == stream_id)) or 0

    def upsert_tracks(self, stream_id: int, tracks: list) -> None:
        if not tracks:
            return
        ids = [t.track_id for t in tracks]
        with self.session() as s:
            existing = {r.track_id: r for r in s.scalars(
                select(m.Track).where(m.Track.stream_id == stream_id, m.Track.track_id.in_(ids)))}
            for t in tracks:
                row = existing.get(t.track_id)
                b = t.bbox
                if row:
                    row.last_seen, row.x1, row.y1, row.x2, row.y2 = t.last_seen, b.x1, b.y1, b.x2, b.y2
                else:
                    s.add(m.Track(stream_id=stream_id, track_id=t.track_id, cls=t.cls,
                                  first_seen=t.first_seen, last_seen=t.last_seen,
                                  x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2))

    def insert_events(self, stream_id: int, events: list[EventSchema]) -> None:
        if not events:
            return
        with self.session() as s:
            for e in events:
                s.add(m.Event(stream_id=stream_id, type=e.type.value, timestamp=e.timestamp,
                              track_id=e.track_id, cls=e.cls, zone=e.zone, line=e.line, payload=e.payload))

    def insert_metric(self, stream_id: int, health: dict) -> None:
        with self.session() as s:
            s.add(m.ProcessingMetric(
                stream_id=stream_id, status=health.get("status", ""),
                processing_fps=health["processing_fps"], input_fps=health["input_fps"],
                inference_ms_avg=health["inference_ms_avg"], pipeline_ms_avg=health["pipeline_ms_avg"],
                pipeline_ms_p95=health["pipeline_ms_p95"], queue_size=health["queue_size"],
                dropped_frames=health["dropped_frames"], frames_processed=health["frames_processed"]))

    # -------------------------------------------------------- read path
    def list_events(self, stream_id: Optional[int] = None, type_: Optional[str] = None,
                    since: Optional[datetime] = None, limit: int = 100, offset: int = 0) -> list[dict]:
        q = select(m.Event).order_by(m.Event.timestamp.desc(), m.Event.id.desc())
        if stream_id is not None:
            q = q.where(m.Event.stream_id == stream_id)
        if type_:
            q = q.where(m.Event.type == type_)
        if since:
            q = q.where(m.Event.timestamp >= since)
        with self.session() as s:
            return [r.to_dict() for r in s.scalars(q.limit(limit).offset(offset))]

    def recent_metrics(self, stream_id: int, limit: int = 60) -> list[dict]:
        with self.session() as s:
            q = (select(m.ProcessingMetric).where(m.ProcessingMetric.stream_id == stream_id)
                 .order_by(m.ProcessingMetric.id.desc()).limit(limit))
            return [r.to_dict() for r in reversed(list(s.scalars(q)))]

    def stream_summary(self, stream_id: int) -> dict:
        """Aggregates from stored data (used when a stream has no live runtime)."""
        with self.session() as s:
            tracks = dict(s.execute(select(m.Track.cls, func.count()).where(m.Track.stream_id == stream_id)
                                    .group_by(m.Track.cls)).all())
            events = dict(s.execute(select(m.Event.type, func.count()).where(m.Event.stream_id == stream_id)
                                    .group_by(m.Event.type)).all())
        return {"unique_objects": tracks, "event_counts": events}
