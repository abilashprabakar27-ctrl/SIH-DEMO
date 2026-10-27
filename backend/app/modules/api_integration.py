"""Institution-system (ERP) integration API: scoped API keys and idempotent enrolment push."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..models import IdempotencyRecord, Institution
from ..security import Actor, ApiError, api_client, current_actor, require_scope
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
