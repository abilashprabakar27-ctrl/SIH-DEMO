"""In-process live event bus for Server-Sent Events.

Events are published only after the transaction that caused them commits. Scoping:
institution users receive events about their own institution only; AICTE roles receive all.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db import after_commit, utcnow


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    role: str
    institution_id: str | None


_subs: set[Subscriber] = set()
_lock = threading.Lock()


def subscribe(role: str, institution_id: str | None) -> Subscriber:
    sub = Subscriber(asyncio.Queue(maxsize=200), asyncio.get_running_loop(), role, institution_id)
    with _lock:
        _subs.add(sub)
    return sub


def unsubscribe(sub: Subscriber) -> None:
    with _lock:
        _subs.discard(sub)


def visible_to(sub_role: str, sub_institution: str | None, institution_ids: list[str]) -> bool:
    if sub_role in ("AICTE_ADMIN", "AICTE_ANALYST"):
        return True
    if sub_role in ("INST_ADMIN", "INST_STAFF"):
        return sub_institution in institution_ids
    return False


def _deliver(event_type: str, data: dict, institution_ids: list[str]) -> None:
    payload = json.dumps({"type": event_type, "at": utcnow().isoformat(), "data": data}, default=str)
    with _lock:
        targets = [s for s in _subs if visible_to(s.role, s.institution_id, institution_ids)]
    for s in targets:
        try:
            s.loop.call_soon_threadsafe(_put, s.queue, event_type, payload)
        except RuntimeError:
            pass  # loop closed


def _put(q: asyncio.Queue, event_type: str, payload: str) -> None:
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait((event_type, payload))


def publish(db: Session, event_type: str, data: dict, institution_ids: list[str]) -> None:
    """Queue an event; delivered after db commits."""
    ids = [i for i in institution_ids if i]
    after_commit(db, lambda: _deliver(event_type, data, ids))


def subscriber_count() -> int:
    with _lock:
        return len(_subs)
