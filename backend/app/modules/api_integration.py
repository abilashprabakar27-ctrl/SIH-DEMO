"""Institution-system (ERP) integration API: scoped API keys and idempotent enrolment push."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db, utcnow
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
    if prior is not None and prior.expires_at is not None and prior.expires_at <= utcnow():
        db.delete(prior)
        db.flush()
        prior = None
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
    db.add(IdempotencyRecord(key=key, request_sha256=body_hash, response=response, status_code=200,
                             expires_at=utcnow() + timedelta(hours=72)))
    audit.record(db, actor, "integration.push", "integration_client", actor.id,
                 detail={"accepted": response["accepted"], "rejected": response["rejected"]})
    db.commit()
    return response


@router.get("/status")
def integration_status(actor: Actor = Depends(current_actor)):
    """Honest integration states. Nothing here pretends to be a live national integration."""
    adapter = get_adapter()
    registry_state = "SIMULATED" if adapter.mode == "SIMULATED" else getattr(adapter, "state", adapter.mode)
    registry_detail = ("Checks run against a synthetic registry table. No official APAAR API contract or credentials "
                       "were available; a live adapter replaces it behind the same interface."
                       if adapter.mode == "SIMULATED" else
                       "No real registry request is made. A contract-backed API schema and credentials are still required.")
    return {
        "integrations": [
            {"name": "APAAR registry verification", "state": registry_state,
             "detail": registry_detail,
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


@router.get("/system/status")
def system_status(actor: Actor = Depends(current_actor)):
    """Expose prototype capability states without implying production integrations."""
    adapter = get_adapter()
    return {
        "environment": settings.app_env,
        "registry": {"mode": adapter.mode,
                     "state": "SIMULATED" if adapter.mode == "SIMULATED" else getattr(adapter, "state", adapter.mode),
                     "available": adapter.available,
                     "contract_status": "NO_OFFICIAL_CONTRACT", "production_verification": False},
        "capacity_rules": {"status": "VERSIONED", "source_verification": "UNVERIFIED"},
        "credentials": {"status": "IMPLEMENTED", "key_registry": "NOT_IMPLEMENTED"},
        "audit": {"status": "TAMPER_EVIDENT", "database_immutability": False},
        "imports": {"status": "IMPLEMENTED", "lease_recovery": "IMPLEMENTED"},
        "prototype_features": [
            {"feature": "APAAR registry check", "state": "SIMULATED", "detail": "Synthetic registry only; no official API contract."},
            {"feature": "AICTE capacity rules", "state": "VERSIONED_UNVERIFIED", "detail": "Versioned prototype values; policy sources need confirmation."},
            {"feature": "Institution uploads", "state": "IMPLEMENTED", "detail": "Validation, correction, retry and commit lease recovery."},
            {"feature": "Identity matching", "state": "REVIEW_ASSIST", "detail": "Heuristic candidates; no automatic merge or rejection."},
            {"feature": "Flag explanations and outcomes", "state": "IMPLEMENTED", "detail": "Evidence hash, rule snapshot and human closure outcome."},
            {"feature": "Credentials", "state": "PROTOTYPE", "detail": "Signed selective-disclosure records; signature does not prove source-data truth."},
            {"feature": "QR verification", "state": "STATUS_ONLY", "detail": "QR checks record status; claims require a student-shared token or consent."},
            {"feature": "Privacy and access", "state": "PROTOTYPE", "detail": "Role and institution scoping; consent, retention and production review remain incomplete."},
            {"feature": "Audit trail", "state": "TAMPER_EVIDENT", "detail": "Hash-chain verification; no database-level immutability or external anchor."},
            {"feature": "End-to-end demos", "state": "A_B_C_VERIFIED", "detail": "Synthetic upload, review, credential and verification demos."},
        ],
        "production_ready": False,
        "production_blockers": [
            "Official APAAR contract and credentials are unavailable.",
            "Capacity rule sources and effective dates require verification.",
            "Credential key lifecycle, privacy review, and production database migration remain incomplete.",
        ],
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
