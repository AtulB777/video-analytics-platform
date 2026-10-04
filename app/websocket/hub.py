"""WebSocket fan-out hub.

Pipeline threads call ``publish`` (thread-safe); the hub schedules the actual
sends on the FastAPI event loop. Slow clients are dropped after a send timeout
rather than allowed to block the others.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

log = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self, send_timeout: float = 1.0):
        self._clients: dict[WebSocket, Optional[set[int]]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._timeout = send_timeout

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket, stream_ids: Optional[set[int]] = None) -> None:
        await ws.accept()
        self._clients[ws] = stream_ids

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    def subscribe(self, ws: WebSocket, stream_ids: Optional[set[int]]) -> None:
        if ws in self._clients:
            self._clients[ws] = stream_ids

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, message: dict) -> None:
        """Thread-safe; no-op when nobody is listening."""
        if not self._clients or self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
        except RuntimeError:
            pass

    async def _broadcast(self, message: dict) -> None:
        text = json.dumps(message, default=str)
        sid = message.get("stream_id")
        for ws, flt in list(self._clients.items()):
            if flt is not None and sid not in flt:
                continue
            try:
                await asyncio.wait_for(ws.send_text(text), self._timeout)
            except Exception:
                log.info("dropping websocket client")
                self._clients.pop(ws, None)
