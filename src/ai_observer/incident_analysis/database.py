from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_observer.incident_analysis.models import Base


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_database(url: str, echo_sql: bool = False) -> None:
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = create_engine(url, echo=echo_sql, future=True)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=_engine)


def get_session() -> Session:
    if _session_factory is None:
        raise RuntimeError("database not initialized")
    return _session_factory()


def get_db_session() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()
