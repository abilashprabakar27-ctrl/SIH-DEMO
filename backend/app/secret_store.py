"""Server-generated secrets kept in the database, so serverless instances share them and they never
pass through deploy tooling. Used only when the database is PostgreSQL and no environment override is set."""

from __future__ import annotations

import threading
from collections.abc import Callable

from sqlalchemy import Column, MetaData, String, Table, Text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

_meta = MetaData()
app_secrets = Table("app_secrets", _meta, Column("name", String(64), primary_key=True), Column("value", Text, nullable=False))
_cache: dict[str, str] = {}
_lock = threading.Lock()


def db_secret(name: str, generate: Callable[[], str]) -> str:
    with _lock:
        if name in _cache:
            return _cache[name]
        from .db import engine

        _meta.create_all(engine, checkfirst=True)
        with engine.begin() as conn:
            conn.execute(pg_insert(app_secrets).values(name=name, value=generate()).on_conflict_do_nothing())
            value = conn.execute(select(app_secrets.c.value).where(app_secrets.c.name == name)).scalar_one()
        _cache[name] = value
        return value
