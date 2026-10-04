from __future__ import annotations

import logging
import time

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Base

log = logging.getLogger(__name__)


def build_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine, retries: int = 30, delay: float = 1.0) -> None:
    """Create tables, waiting for the database to accept connections.

    ``create_all`` keeps the demo self-contained; production deployments should
    manage schema changes with Alembic migrations.
    """
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            Base.metadata.create_all(engine)
            return
        except Exception as exc:
            if attempt == retries:
                raise
            log.warning("database not ready (%s); retry %d/%d", exc.__class__.__name__, attempt, retries)
            time.sleep(delay)
