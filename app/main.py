"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.analytics.config import load_profiles
from app.api.routes import router as api_router
from app.core.config import Settings, get_settings
from app.database.repository import Repository
from app.database.session import build_engine, init_db, make_session_factory
from app.streams.manager import StreamManager
from app.websocket.hub import WebSocketHub
from app.websocket.routes import router as ws_router

log = logging.getLogger("app")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings.database_url)
        await run_in_threadpool(init_db, engine)
        repo = Repository(make_session_factory(engine))
        repo.reset_stale_statuses()
        hub = WebSocketHub()
        hub.set_loop(asyncio.get_running_loop())
        manager = StreamManager(settings, repo, hub, load_profiles(settings))
        app.state.hub, app.state.manager, app.state.settings = hub, manager, settings
        if settings.autostart_sample:
            try:
                await run_in_threadpool(manager.bootstrap_sample)
            except Exception:
                log.exception("could not start the sample stream")
        yield
        await run_in_threadpool(manager.shutdown)
        engine.dispose()

    app = FastAPI(title="Real-Time Video Analytics Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(api_router)
    app.include_router(ws_router)
    return app


app = create_app()
