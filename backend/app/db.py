"""SQLAlchemy engine/session wiring."""
from __future__ import annotations

import pathlib
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.app.config import get_settings


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent folder for relative sqlite files (sqlite:///./data/x.db)."""
    if not url.startswith("sqlite"):
        return
    path_part = url.split("///", 1)[-1]
    if not path_part or path_part.startswith(":memory:") or ":memory:" in path_part:
        return
    pathlib.Path(path_part).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _make_engine(database_url: str):
    _ensure_sqlite_dir(database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return sa.create_engine(database_url, connect_args=connect_args, future=True)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = _make_engine(settings.DATABASE_URL)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory():
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine() -> None:
    """Drop cached engine (used by tests that change DATABASE_URL)."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None


def init_db() -> None:
    from backend.app import models  # noqa: F401  (register mappers)
    Base = models.Base
    Base.metadata.create_all(get_engine())


def dispose_db() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db():
    """FastAPI dependency yielding a scoped session."""
    SessionFactory = get_session_factory()
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()
