"""SQLAlchemy 2.0 models: cameras, streams, detections, tracks, events, processing_metrics."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.schemas import iso, utcnow

BigPK = BigInteger().with_variant(Integer, "sqlite")  # SQLite only autoincrements INTEGER PKs


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Stream(Base):
    __tablename__ = "streams"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20))  # file | webcam | rtsp
    uri: Mapped[str] = mapped_column(String(1000))
    profile: Mapped[str] = mapped_column(String(100), default="default")
    status: Mapped[str] = mapped_column(String(20), default="created")
    last_error: Mapped[Optional[str]] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "camera_id": self.camera_id, "name": self.name,
                "source_type": self.source_type, "uri": self.uri, "profile": self.profile,
                "status": self.status, "last_error": self.last_error,
                "created_at": iso(self.created_at), "started_at": iso(self.started_at),
                "stopped_at": iso(self.stopped_at)}


class Detection(Base):
    __tablename__ = "detections"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    frame_index: Mapped[Optional[int]] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cls: Mapped[str] = mapped_column("class", String(50))
    confidence: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index("ix_detections_stream_ts", "stream_id", "timestamp"),)


class Track(Base):
    __tablename__ = "tracks"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    track_id: Mapped[int] = mapped_column(Integer)  # per-stream tracker ID
    cls: Mapped[str] = mapped_column("class", String(50))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    x1: Mapped[float] = mapped_column(Float)  # last known box
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("stream_id", "track_id", name="uq_tracks_stream_track"),)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    type: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    track_id: Mapped[Optional[int]] = mapped_column(Integer)
    cls: Mapped[Optional[str]] = mapped_column("class", String(50))
    zone: Mapped[Optional[str]] = mapped_column(String(100))
    line: Mapped[Optional[str]] = mapped_column(String(100))
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    __table_args__ = (Index("ix_events_stream_ts", "stream_id", "timestamp"), Index("ix_events_type", "type"))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "stream_id": self.stream_id, "type": self.type,
                "timestamp": iso(self.timestamp), "track_id": self.track_id, "class": self.cls,
                "zone": self.zone, "line": self.line, "payload": self.payload or {}}


class ProcessingMetric(Base):
    __tablename__ = "processing_metrics"
    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20))
    processing_fps: Mapped[float] = mapped_column(Float)
    input_fps: Mapped[float] = mapped_column(Float)
    inference_ms_avg: Mapped[float] = mapped_column(Float)
    pipeline_ms_avg: Mapped[float] = mapped_column(Float)
    pipeline_ms_p95: Mapped[float] = mapped_column(Float)
    queue_size: Mapped[int] = mapped_column(Integer)
    dropped_frames: Mapped[int] = mapped_column(Integer)
    frames_processed: Mapped[int] = mapped_column(Integer)
    __table_args__ = (Index("ix_metrics_stream_ts", "stream_id", "timestamp"),)

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": iso(self.timestamp), "status": self.status,
                "processing_fps": self.processing_fps, "input_fps": self.input_fps,
                "inference_ms_avg": self.inference_ms_avg, "pipeline_ms_avg": self.pipeline_ms_avg,
                "pipeline_ms_p95": self.pipeline_ms_p95, "queue_size": self.queue_size,
                "dropped_frames": self.dropped_frames, "frames_processed": self.frames_processed}
