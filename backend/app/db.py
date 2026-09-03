"""Engine, session and pragmas.

WAL is set on connect rather than once at creation, because a connection made
by Alembic, by the seeder or by a test would otherwise not have it, and
without WAL a read blocks a write. The nightly job would then freeze the
interface, which is the failure this one line prevents.
"""

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_ROOT / "treasury.db"
DATABASE_URL = os.environ.get("TREASURY_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

engine = create_engine(
    DATABASE_URL,
    future=True,
    # One session per request, but FastAPI runs synchronous endpoints in a
    # threadpool, so the connection must not be pinned to the creating thread.
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _record):
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency. One session per request, yielded and closed here."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
