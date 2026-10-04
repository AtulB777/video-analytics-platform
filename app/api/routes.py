from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.schemas import StreamCreate, StreamOut
from app.streams.manager import StreamManager, StreamNotFound

router = APIRouter()


def _mgr(request: Request) -> StreamManager:
    return request.app.state.manager


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except StreamNotFound:
        raise HTTPException(404, "Stream not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/streams", response_model=StreamOut, status_code=201)
def create_stream(body: StreamCreate, request: Request):
    mgr = _mgr(request)
    stream = _call(mgr.create_stream, body.name, body.source_type, body.uri, body.profile,
                   body.camera_name, body.location)
    if body.autostart:
        stream = _call(mgr.start_stream, stream["id"])
    return stream


@router.get("/streams", response_model=list[StreamOut])
def list_streams(request: Request):
    return _mgr(request).list_streams()


@router.get("/streams/{stream_id}", response_model=StreamOut)
def get_stream(stream_id: int, request: Request):
    return _call(_mgr(request).get_stream, stream_id)


@router.delete("/streams/{stream_id}", status_code=204)
def delete_stream(stream_id: int, request: Request):
    _call(_mgr(request).delete_stream, stream_id)
    return Response(status_code=204)


@router.post("/streams/{stream_id}/start", response_model=StreamOut)
def start_stream(stream_id: int, request: Request):
    return _call(_mgr(request).start_stream, stream_id)


@router.post("/streams/{stream_id}/stop", response_model=StreamOut)
def stop_stream(stream_id: int, request: Request):
    return _call(_mgr(request).stop_stream, stream_id)


@router.get("/streams/{stream_id}/analytics")
def stream_analytics(stream_id: int, request: Request):
    return _call(_mgr(request).analytics, stream_id)


@router.get("/streams/{stream_id}/metrics")
def stream_metrics(stream_id: int, request: Request, limit: int = Query(60, ge=1, le=1000)):
    """Live pipeline metrics plus recently persisted samples."""
    mgr = _mgr(request)
    rt = _call(mgr.runtime, stream_id)
    return {"live": rt.health() if rt else None, "history": mgr.repo.recent_metrics(stream_id, limit)}


@router.get("/streams/{stream_id}/frame.jpg")
def stream_frame(stream_id: int, request: Request):
    """Latest annotated frame (JPEG) for previews."""
    rt = _call(_mgr(request).runtime, stream_id)
    jpeg = rt.latest_jpeg() if rt else None
    if jpeg is None:
        raise HTTPException(404, "No frame available yet")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/events")
def list_events(request: Request, stream_id: Optional[int] = None, type: Optional[str] = None,
                since: Optional[datetime] = None, limit: int = Query(100, ge=1, le=1000),
                offset: int = Query(0, ge=0)):
    return _mgr(request).repo.list_events(stream_id, type, since, limit, offset)


@router.get("/health")
def health(request: Request):
    mgr = _mgr(request)
    db_ok = mgr.repo.ping()
    streams = mgr.list_streams() if db_ok else []
    body = {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "detector": mgr.settings.detector,
        "tracker": mgr.settings.tracker,
        "streams": {"total": len(streams),
                    "running": sum(1 for s in streams if s["status"] == "running"),
                    "reconnecting": sum(1 for s in streams if s["status"] == "reconnecting"),
                    "error": sum(1 for s in streams if s["status"] == "error")},
        "websocket_clients": request.app.state.hub.client_count,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
