"""Engine, session factory and post-commit hooks.

Audit events and live events are buffered on the session and written/published only
after the business transaction commits (see audit.py). Durable entries (denied or failed
actions) are also written after a rollback.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import ON_VERCEL, settings


def settings_on_vercel() -> bool:
    return ON_VERCEL


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns timezone-aware UTC (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _make_engine(url: str):
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["connect_args"] = {"prepare_threshold": None}  # safe behind PgBouncer (Neon pooled endpoint)
        if settings_on_vercel():
            from sqlalchemy.pool import NullPool  # serverless: let Neon's pooler hold connections

            kwargs["poolclass"] = NullPool
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return eng


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def after_commit(db: Session, fn: Callable[[], None], durable: bool = False) -> None:
    """Run fn once the current transaction commits (or, if durable, also after rollback)."""
    db.info.setdefault("post_commit", []).append((fn, durable))


@event.listens_for(Session, "after_commit")
def _run_post_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a savepoint released; the outer transaction (and its database lock) is still open
    hooks = session.info.pop("post_commit", [])
    for fn, _ in hooks:
        fn()


def run_durable_hooks(session: Session) -> None:
    """After a rolled-back request, still run durable hooks (denied/failed audit events)."""
    hooks = session.info.pop("post_commit", [])
    for fn, durable in hooks:
        if durable:
            fn()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        if db.info.get("post_commit"):
            # Endpoint finished without an explicit commit but queued hooks (e.g. a read audit).
            db.commit()
            if db.info.get("post_commit"):  # commit was a no-op (no transaction began)
                _run_post_commit(db)
    except Exception:
        db.rollback()
        run_durable_hooks(db)
        raise
    finally:
        db.close()


def init_db() -> None:
    from alembic import command
    from alembic.config import Config

    from .config import REPO_ROOT

    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    from .models import SimRegistryBase
    if settings.adapter_mode == "simulated" and settings.app_env != "production":
        SimRegistryBase.metadata.create_all(engine)
    else:
        SimRegistryBase.metadata.drop_all(engine)


def snapshot_hooks(db: Session) -> tuple[int, int]:
    """Remember queued hooks/audit events so a rolled-back savepoint can drop what it queued."""
    return len(db.info.get("post_commit", [])), len(db.info.get("audit_buffer", []))


def restore_hooks(db: Session, snap: tuple[int, int]) -> None:
    hooks, audits = snap
    if "post_commit" in db.info:
        del db.info["post_commit"][hooks:]
    if "audit_buffer" in db.info:
        del db.info["audit_buffer"][audits:]
