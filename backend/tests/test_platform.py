"""Integration API, audit chain, dashboards vs SQL, review priority, rules admin, live events."""

import asyncio

from sqlalchemy import func, select, text

from app.config import settings
from app.db import SessionLocal
from app.models import AuditEvent, Enrolment
from app.modules import events

REC = {"apaar_id": "911100000001", "institution_student_id": "KIT26API1", "full_name": "Meenakshi Sundaram",
       "date_of_birth": "2008-05-12", "gender": "F", "nationality_status": "INDIAN", "citizenship_country": "India",
       "programme_code": "BTECH-CSE", "academic_year": "2026-27", "seat_category": "REGULAR",
       "admission_date": "2026-08-03"}


def key():
    return (settings.var_dir / "demo_api_key.txt").read_text().strip()


def test_integration_push(client, seeded):
    url = "/api/v1/integration/enrolments"
    body = {"academic_year": "2026-27", "records": [REC]}
    assert client.post(url, json=body, headers={"X-API-Key": "apk_bad.nope", "Idempotency-Key": "k1"}).status_code == 401
    assert client.post(url, json=body, headers={"X-API-Key": key()}).status_code == 400
    r1 = client.post(url, json=body, headers={"X-API-Key": key(), "Idempotency-Key": "k1"})
    assert r1.status_code == 200 and r1.json()["accepted"] == 1 and r1.json()["results"][0]["outcome"] == "CREATED"
    r2 = client.post(url, json=body, headers={"X-API-Key": key(), "Idempotency-Key": "k1"})
    assert r2.json() == r1.json() and r2.headers.get("idempotent-replay") == "true"
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(Enrolment)
                         .where(Enrolment.institution_student_id == "KIT26API1")).scalar() == 1
    body2 = {"academic_year": "2026-27", "records": [dict(REC, email="m@example.org")]}
    assert client.post(url, json=body2, headers={"X-API-Key": key(), "Idempotency-Key": "k1"}).status_code == 409
    bad = client.post(url, json={"records": [dict(REC, institution_student_id="KIT26API2", gender="X")]},
                      headers={"X-API-Key": key(), "Idempotency-Key": "k2"}).json()
    assert bad["rejected"] == 1 and bad["results"][0]["outcome"] == "REJECTED"
    # seat-check works with the key (scope seat:check)
    sc = client.post("/api/v1/seat-check", headers={"X-API-Key": key()},
                     json={"programme_code": "BTECH-CSE", "seat_category": "REGULAR"})
    assert sc.status_code == 200


def test_missing_scope_403(client, seeded):
    from app.models import IntegrationClient
    from app.security import hash_api_key, new_api_key
    k, prefix = new_api_key()
    with SessionLocal() as s:
        inst = s.execute(select(IntegrationClient.institution_id)).scalar()
        s.add(IntegrationClient(name="read-only", key_prefix=prefix, key_hash=hash_api_key(k), institution_id=inst,
                                scopes=["seat:check"]))
        s.commit()
    r = client.post("/api/v1/integration/enrolments", json={"records": [REC]},
                    headers={"X-API-Key": k, "Idempotency-Key": "z"})
    assert r.status_code == 403


def test_integration_status_is_honest(client, as_):
    states = {i["name"]: i["state"] for i in client.get("/api/v1/integration/status",
                                                         headers=as_("aicte.admin@demo.local")).json()["integrations"]}
    assert states["APAAR registry verification"] == "SIMULATED"
    assert "NOT_IMPLEMENTED" in states.values()


def test_audit_chain_valid_then_tamper_detected(client, as_):
    a = as_("auditor@demo.local")
    r = client.get("/api/v1/audit/verify-chain", headers=a).json()
    assert r["valid"] is True and r["events_checked"] > 100
    with SessionLocal() as s:
        seq = s.execute(select(AuditEvent.seq).where(AuditEvent.action == "enrolment.create")
                        .order_by(AuditEvent.seq).offset(10).limit(1)).scalar()
        s.execute(text("UPDATE audit_events SET detail = :d WHERE seq = :s"), {"d": '{"edited": true}', "s": seq})
        s.commit()
    r = client.get("/api/v1/audit/verify-chain", headers=a).json()
    assert r["valid"] is False and r["first_broken_seq"] == seq
    assert client.get("/api/v1/audit", headers=as_("kaveri.admin@demo.local")).status_code == 403
    exp = client.get("/api/v1/audit/export.csv", headers=a)
    assert exp.status_code == 200 and exp.text.startswith("seq,at")


def test_national_totals_equal_sql(client, as_):
    d = client.get("/api/v1/dashboard/national?academic_year=2026-27", headers=as_("aicte.analyst@demo.local")).json()
    with SessionLocal() as s:
        total = s.execute(select(func.count()).select_from(Enrolment).where(
            Enrolment.academic_year == "2026-27", Enrolment.status.in_(("ACTIVE", "PROVISIONAL")))).scalar()
        within = s.execute(select(func.count()).select_from(Enrolment).where(
            Enrolment.academic_year == "2026-27", Enrolment.status.in_(("ACTIVE", "PROVISIONAL")),
            Enrolment.seat_category.in_(("REGULAR", "NRI")))).scalar()
        intake = s.execute(text("SELECT SUM(approved_intake) FROM approved_intakes WHERE academic_year='2026-27'")).scalar()
    f = d["figures"]
    assert f["total_enrolled"] == total and f["within_intake_enrolled"] == within and f["approved_intake"] == intake
    assert sum(d["nationality"].values()) == total
    narmada = next(p for p in d["excess_alerts"] if p["programme_code"] == "MBA" and "Narmada" in p["institution_name"])
    assert narmada["excess_over_intake"] == 8 and narmada["supernumerary"]["SN_CIWG"]["excess"] == 1
    assert d["apaar_coverage"]["mode"] == "SIMULATED"
    filtered = client.get("/api/v1/dashboard/national?state=Delhi", headers=as_("aicte.admin@demo.local")).json()
    assert filtered["figures"]["institutions"] == 1


def test_review_priority(client, as_):
    d = client.get("/api/v1/dashboard/review-priority", headers=as_("aicte.admin@demo.local")).json()
    assert d["disclaimer"] == "Ranks institutions for review attention. A high score is not evidence of wrongdoing."
    top = d["items"][0]
    assert "Narmada" in top["institution_name"] and top["band"] in ("MEDIUM", "HIGH")
    keys = {s["key"] for s in top["signals"]}
    assert {"seats_over_intake", "supernumerary_over_cap", "enrolment_jump"} <= keys
    assert all(s["sentence"] and s["points"] > 0 for s in top["signals"])
    assert "all institutions" in top["peer_basis"]
    assert "fraud" not in str(d).lower()
    csv = client.get("/api/v1/reports/review-priority.csv", headers=as_("aicte.admin@demo.local"))
    assert csv.status_code == 200 and "not evidence of wrongdoing" in csv.text


def test_csv_formula_injection_neutralised():
    from app.csvout import to_csv
    out = to_csv(["a"], [["=HYPERLINK(1)"], ["+1"], ["-2"], ["@x"], ["ok"]])
    assert "'=HYPERLINK" in out and "'+1" in out and "'-2" in out and "'@x" in out and "\nok" in out


def test_rules_admin(client, as_):
    a = as_("aicte.admin@demo.local")
    assert client.patch("/api/v1/rules/R001_REQUIRED", headers=a, json={"enabled": False}).status_code == 409
    r = client.patch("/api/v1/rules/R011_DATE_UNUSUAL", headers=a, json={"severity": "REVIEW"})
    assert r.status_code == 200 and r.json()["severity"] == "REVIEW"
    client.patch("/api/v1/rules/R011_DATE_UNUSUAL", headers=a, json={"severity": "WARNING"})
    assert client.patch("/api/v1/rules/R011_DATE_UNUSUAL", headers=as_("aicte.analyst@demo.local"),
                        json={"enabled": False}).status_code == 403


def test_event_scoping():
    async def run():
        k = events.subscribe("INST_STAFF", "inst-k")
        g = events.subscribe("INST_STAFF", "inst-g")
        a = events.subscribe("AICTE_ADMIN", None)
        events._deliver("seat.changed", {"x": 1}, ["inst-k"])
        await asyncio.sleep(0.01)
        got = (k.queue.qsize(), g.queue.qsize(), a.queue.qsize())
        for s in (k, g, a):
            events.unsubscribe(s)
        return got

    assert asyncio.run(run()) == (1, 0, 1)


def test_sse_requires_stream_token(client, as_):
    assert client.get("/api/v1/events?token=bad").status_code == 401
    # a normal API token is not accepted as a stream token
    api_token = as_("aicte.admin@demo.local")["Authorization"].split()[1]
    assert client.get(f"/api/v1/events?token={api_token}").status_code == 401
    tok = client.post("/api/v1/auth/stream-token", headers=as_("aicte.admin@demo.local")).json()["token"]
    assert tok


def test_api_key_lifecycle(client, as_):
    h = as_("godavari.admin@demo.local")
    r = client.post("/api/v1/integration/clients", headers=h, json={"name": "Godavari ERP", "scopes": ["seat:check"]})
    assert r.status_code == 200 and r.json()["api_key"].startswith(r.json()["key_prefix"] + ".")
    key, cid = r.json()["api_key"], r.json()["id"]
    listed = client.get("/api/v1/integration/clients", headers=h).json()
    assert all("api_key" not in c for c in listed) and any(c["id"] == cid for c in listed)
    assert client.post("/api/v1/seat-check", headers={"X-API-Key": key},
                       json={"programme_code": "BTECH-ME", "seat_category": "REGULAR"}).status_code == 200
    assert client.post("/api/v1/integration/enrolments", json={"records": [REC]},
                       headers={"X-API-Key": key, "Idempotency-Key": "g1"}).status_code == 403  # scope missing
    assert client.post(f"/api/v1/integration/clients/{cid}/revoke",
                       headers=as_("kaveri.admin@demo.local")).status_code == 404
    assert client.post(f"/api/v1/integration/clients/{cid}/revoke", headers=h).status_code == 200
    assert client.post("/api/v1/seat-check", headers={"X-API-Key": key},
                       json={"programme_code": "BTECH-ME", "seat_category": "REGULAR"}).status_code == 401
    assert client.post("/api/v1/integration/clients", headers=as_("godavari.staff@demo.local"),
                       json={"name": "x" * 5, "scopes": ["seat:check"]}).status_code == 403


def test_notifications_listed(client, as_):
    items = client.get("/api/v1/notifications", headers=as_("narmada.admin@demo.local")).json()
    assert items and all({"message", "link", "created_at"} <= set(i) for i in items)
