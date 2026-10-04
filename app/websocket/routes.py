from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, stream_id: Optional[int] = None):
    """Real-time feed.

    Message envelope: ``{"type", "stream_id", "timestamp", "data"}`` where type is one of
    ``stream_status`` | ``detections`` | ``analytics`` | ``event``.

    Optional ``?stream_id=N`` filter. The client may also send
    ``{"subscribe": [1, 2]}`` (or ``{"subscribe": null}`` for everything) at any time.
    """
    hub = ws.app.state.hub
    manager = ws.app.state.manager
    await hub.connect(ws, {stream_id} if stream_id is not None else None)
    try:
        await ws.send_json({"type": "hello", "stream_id": None, "data": {"streams": manager.statuses()}})
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict) and "subscribe" in msg:
                sub = msg["subscribe"]
                hub.subscribe(ws, {int(i) for i in sub} if sub else None)
                await ws.send_json({"type": "subscribed", "stream_id": None, "data": {"subscribe": sub}})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.disconnect(ws)
