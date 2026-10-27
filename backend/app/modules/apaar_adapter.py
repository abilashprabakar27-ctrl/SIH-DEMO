"""APAAR registry adapter boundary.

No official APAAR verification API contract was available, so the only implementation here
is SIMULATED: it reads the synthetic `sim_apaar_registry` table. A live adapter would implement
the same interface. Every result carries mode="SIMULATED".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import SimApaarRegistry
from .normalize import name_key

MODE = "SIMULATED"


@dataclass
class AdapterResult:
    status: str  # OK | NOT_FOUND | INACTIVE | NAME_MISMATCH | DOB_MISMATCH | UNAVAILABLE
    mode: str = MODE
    registry_name: str | None = None
    registry_dob: date | None = None


class SimulatedRegistryAdapter:
    mode = MODE

    def __init__(self, available: bool = True):
        self.available = available

    def lookup_many(self, db: Session, ids: list[str]) -> dict[str, SimApaarRegistry]:
        out: dict[str, SimApaarRegistry] = {}
        ids = sorted(set(ids))
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            for rec in db.execute(select(SimApaarRegistry).where(SimApaarRegistry.apaar_id.in_(chunk))).scalars():
                out[rec.apaar_id] = rec
        return out

    def check(self, rec: SimApaarRegistry | None, full_name: str | None, dob: date | None) -> AdapterResult:
        if not self.available:
            return AdapterResult("UNAVAILABLE")
        if rec is None:
            return AdapterResult("NOT_FOUND")
        if not rec.active:
            return AdapterResult("INACTIVE")
        if full_name and name_key(full_name) != name_key(rec.full_name):
            return AdapterResult("NAME_MISMATCH", registry_name=rec.full_name, registry_dob=rec.date_of_birth)
        if dob and dob != rec.date_of_birth:
            return AdapterResult("DOB_MISMATCH", registry_name=rec.full_name, registry_dob=rec.date_of_birth)
        return AdapterResult("OK", registry_name=rec.full_name, registry_dob=rec.date_of_birth)


_override: SimulatedRegistryAdapter | None = None


def get_adapter() -> SimulatedRegistryAdapter:
    if _override is not None:
        return _override
    return SimulatedRegistryAdapter(available=settings.adapter_mode != "unavailable")


def set_adapter(adapter: SimulatedRegistryAdapter | None) -> None:
    """Test hook: force the adapter (e.g. unavailable)."""
    global _override
    _override = adapter


def near_variants(apaar_id: str) -> list[str]:
    """All single-digit substitutions (108) and adjacent transpositions (up to 11)."""
    out: list[str] = []
    for i, ch in enumerate(apaar_id):
        for d in "0123456789":
            if d != ch:
                out.append(apaar_id[:i] + d + apaar_id[i + 1 :])
    for i in range(len(apaar_id) - 1):
        if apaar_id[i] != apaar_id[i + 1]:
            out.append(apaar_id[:i] + apaar_id[i + 1] + apaar_id[i] + apaar_id[i + 2 :])
    return out


def did_you_mean(db: Session, apaar_id: str, full_name: str | None, dob: date | None) -> str | None:
    """Return the single near-variant whose registry name and DOB match the row, else None."""
    if not full_name or not dob or len(apaar_id) != 12 or not apaar_id.isdigit():
        return None
    adapter = get_adapter()
    if not adapter.available:
        return None
    variants = near_variants(apaar_id)
    found = adapter.lookup_many(db, variants)
    key = name_key(full_name)
    matches = [
        v for v, rec in found.items() if rec.active and name_key(rec.full_name) == key and rec.date_of_birth == dob
    ]
    return matches[0] if len(matches) == 1 else None
