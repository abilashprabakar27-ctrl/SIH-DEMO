"""Institution-system (ERP) integration API: scoped API keys and idempotent enrolment push."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..models import IdempotencyRecord, Institution, IntegrationClient
from ..security import (
    Actor,
    ApiError,
    api_client,
    current_actor,
    hash_api_key,
    new_api_key,
    require_roles,
    require_scope,
)
from . import engine, events, issues
from .apaar_adapter import get_adapter

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])


class PushIn(BaseModel):
    academic_year: str = settings.current_year
    records: list[dict[str, str]] = Field(min_length=1, max_length=500)


@router.post("/enrolments")
def push_enrolments(body: PushIn, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    actor: Actor = Depends(api_client), db: Session = Depends(get_db)):
    require_scope(actor, "enrolments:write")
    if not idempotency_key or len(idempotency_key) > 100:
        raise ApiError(400, "Send an Idempotency-Key header (up to 100 characters) so retries are safe.")
    key = f"{actor.id}:{idempotency_key}"
    body_hash = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    prior = db.get(IdempotencyRecord, key)
    if prior is not None:
        if prior.request_sha256 != body_hash:
            raise ApiError(409, "This Idempotency-Key was already used with a different request body.")
        return JSONResponse(prior.response, status_code=prior.status_code, headers={"Idempotent-Replay": "true"})
    inst = db.get(Institution, actor.institution_id)
    plans = engine.validate_rows(db, inst, body.academic_year, list(enumerate(body.records)))
    results, affected = [], set()
    for plan in plans:
        if plan.status == "ERROR":
            results.append({"index": plan.row_no, "outcome": "REJECTED", "row_status": plan.status,
                            "findings": plan.findings})
            continue
        en = engine.commit_values(db, plan, institution=inst, academic_year=body.academic_year, actor=actor,
                                  source="API", reason=f"Pushed by integration client {actor.client.name}")
        affected.add((en.programme_id, en.academic_year))
        results.append({"index": plan.row_no, "outcome": "UPDATED" if plan.enrolment_id else "CREATED",
                        "enrolment_id": en.id, "row_status": plan.status, "findings": plan.findings})
    for pid, year in sorted(affected):
        issues.run_capacity_checks(db, pid, year, actor)
    response = {"accepted": sum(1 for r in results if r["outcome"] != "REJECTED"),
                "rejected": sum(1 for r in results if r["outcome"] == "REJECTED"), "results": results,
                "apaar_check_mode": "SIMULATED"}
    db.add(IdempotencyRecord(key=key, request_sha256=body_hash, response=response, status_code=200))
    audit.record(db, actor, "integration.push", "integration_client", actor.id,
                 detail={"accepted": response["accepted"], "rejected": response["rejected"]})
    db.commit()
    return response


@router.get("/status")
def integration_status(actor: Actor = Depends(current_actor)):
    """Honest integration states. Nothing here pretends to be a live national integration."""
    adapter = get_adapter()
    return {
        "integrations": [
            {"name": "APAAR registry verification", "state": "SIMULATED",
             "detail": "Checks run against a synthetic registry table. No official APAAR API contract or credentials "
                       "were available; a live adapter replaces it behind the same interface.",
             "available": adapter.available},
            {"name": "Institution ERP push (this API)", "state": "LIVE",
             "detail": "POST /api/v1/integration/enrolments with X-API-Key and Idempotency-Key."},
            {"name": "Seat-check API", "state": "LIVE", "detail": "POST /api/v1/seat-check (scope seat:check)."},
            {"name": "AICTE approval-process intake feed", "state": "NOT_IMPLEMENTED",
             "detail": "Approved intake is entered by AICTE admins; an automated feed is planned."},
            {"name": "DigiLocker / NAD publication", "state": "NOT_IMPLEMENTED",
             "detail": "Planned; needs API Setu onboarding."},
            {"name": "Degree-awarding body data feed", "state": "NOT_IMPLEMENTED", "detail": "Planned (requirement 10)."},
            {"name": "Live event stream (SSE)", "state": "LIVE", "subscribers": events.subscriber_count()},
        ]
    }


# ---------------------------------------------------------------- API keys for institution systems

SCOPES = ("enrolments:write", "seat:check")


def _client_view(c: IntegrationClient) -> dict:
    return {"id": c.id, "name": c.name, "key_prefix": c.key_prefix, "scopes": c.scopes, "active": c.active,
            "created_at": c.created_at.isoformat()}


@router.get("/clients")
def list_clients(actor: Actor = Depends(require_roles("INST_ADMIN")), db: Session = Depends(get_db)):
    rows = db.execute(select(IntegrationClient).where(IntegrationClient.institution_id == actor.institution_id)
                      .order_by(IntegrationClient.created_at.desc())).scalars()
    return [_client_view(c) for c in rows]


class ClientIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    scopes: list[str] = Field(min_length=1)


@router.post("/clients")
def create_client(body: ClientIn, actor: Actor = Depends(require_roles("INST_ADMIN")), db: Session = Depends(get_db)):
    """Create an API key for an institution system. The full key is returned once; only its hash is stored."""
    bad = [s for s in body.scopes if s not in SCOPES]
    if bad:
        raise ApiError(422, "Unknown scope(s): " + ", ".join(bad) + ". Allowed: " + ", ".join(SCOPES))
    key, prefix = new_api_key()
    c = IntegrationClient(name=body.name, key_prefix=prefix, key_hash=hash_api_key(key),
                          institution_id=actor.institution_id, scopes=sorted(set(body.scopes)))
    db.add(c)
    db.flush()
    audit.record(db, actor, "integration.key_create", "integration_client", c.id,
                 detail={"prefix": prefix, "scopes": c.scopes})
    db.commit()
    return dict(_client_view(c), api_key=key, note="Copy this key now. It is shown only once.")


@router.post("/clients/{client_id}/revoke")
def revoke_client(client_id: str, actor: Actor = Depends(require_roles("INST_ADMIN")), db: Session = Depends(get_db)):
    c = db.get(IntegrationClient, client_id)
    if c is None or c.institution_id != actor.institution_id:
        raise ApiError(404, "Not found.")
    c.active = False
    audit.record(db, actor, "integration.key_revoke", "integration_client", c.id, detail={"prefix": c.key_prefix})
    db.commit()
    return _client_view(c)
