#!/usr/bin/env python3
"""Run Demos A, B and C against a running server and print the evidence.

Usage:  python scripts/run_demos.py [--base http://localhost:8000]
Run on a freshly seeded database (`make seed`). Exits non-zero if any expectation fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Demo@2026"
FAILS: list[str] = []


def expect(cond: bool, label: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


class Api:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base, timeout=60)
        self.tokens: dict[str, str] = {}

    def as_(self, email: str) -> dict:
        if email not in self.tokens:
            r = self.c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            r.raise_for_status()
            self.tokens[email] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[email]}"}

    def get(self, who, url, **kw):
        return self.c.get(url, headers=self.as_(who), **kw)

    def post(self, who, url, **kw):
        return self.c.post(url, headers=self.as_(who), **kw)

    def patch(self, who, url, **kw):
        return self.c.patch(url, headers=self.as_(who), **kw)


def listen(api: Api, who: str, sink: list, stop: threading.Event) -> None:
    tok = api.post(who, "/api/v1/auth/stream-token").json()["token"]
    with httpx.Client(base_url=str(api.c.base_url), timeout=None) as c, \
            c.stream("GET", f"/api/v1/events?token={tok}") as r:
        kind = None
        for line in r.iter_lines():
            if stop.is_set():
                break
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:") and kind and kind != "ready":
                sink.append((kind, json.loads(line[5:])))


def rows(api, who, jid):
    return {r["data"]["institution_student_id"]: r for r in api.get(who, f"/api/v1/imports/{jid}?page_size=200").json()["rows"]}


def demo_a(api: Api) -> None:
    print("\nDemo A — ingestion (Kaveri staff)")
    who = "kaveri.staff@demo.local"
    seen, stop = [], threading.Event()
    t = threading.Thread(target=listen, args=(api, "aicte.admin@demo.local", seen, stop), daemon=True)
    t.start()
    time.sleep(0.5)
    path = ROOT / "sample_data" / "demo_A_kaveri_upload_2026-27.csv"
    job = api.post(who, "/api/v1/imports", data={"academic_year": "2026-27"},
                   files={"file": (path.name, path.read_bytes())}).json()
    c = job["summary"]["counts"]
    print(f"  preview: VALID {c['VALID']}, REVIEW {c['REVIEW']}, ERROR {c['ERROR']}")
    expect((c["VALID"], c["REVIEW"], c["ERROR"]) == (5, 2, 9), "preview is 5 VALID / 2 REVIEW / 9 ERROR")
    jid = job["id"]
    r = rows(api, who, jid)
    sugg = next(f["suggestion"]["value"] for f in r["KIT26ECE908"]["findings"] if f.get("suggestion"))
    expect(sugg == "911100000008", f"did-you-mean for Sanjana suggests {sugg}")
    fixes = {"KIT26ECE908": {"apaar_id": sugg}, "KIT26CSE906": {"apaar_id": "911100000006"},
             "KIT26ECE907": {"apaar_id": "911100000007"}, "KIT26ECE910": {"date_of_birth": "2008-06-18"},
             "KIT26CSE913": {"seat_category": "REGULAR"}, "KIT26MTA914": {"programme_code": "MTECH-CSE"},
             "KIT26ECE915": {"gender": "F"}}
    for roll, ch in fixes.items():
        api.patch(who, f"/api/v1/imports/{jid}/rows/{r[roll]['row_no']}", json={"changes": ch}).raise_for_status()
    api.post(who, f"/api/v1/imports/{jid}/rows/{r['KIT26CSE912']['row_no']}/exclude", json={"excluded": True})
    job = api.get(who, f"/api/v1/imports/{jid}").json()
    expect(job["summary"]["committable"] == 15 and job["summary"]["counts"]["ERROR"] == 0,
           "after fixes and leaving out the duplicate: 15 committable, 0 errors")
    res = api.post(who, f"/api/v1/imports/{jid}/commit").json()
    print(f"  commit: {res['message']}")
    expect(res["committed_now"] == 15, "committed 15 rows")
    time.sleep(1.0)
    stop.set()
    kinds = {k for k, _ in seen}
    expect("seat.changed" in kinds and "issue.opened" in kinds,
           f"AICTE live stream received {sorted(kinds)} without reload")
    flags = api.get("aicte.admin@demo.local", "/api/v1/issues?status=OPEN&rule_id=R007_APAAR_MISMATCH,R004_APAAR_PENDING"
                    ).json()["items"]
    names = [f["message"] for f in flags if "KIT26" in f["message"]]
    expect(any("R007" in f["rule_id"] for f in flags if "KIT26ECE909" in f["message"]), "R007 flag for Vignesh")
    expect(any("R004" in f["rule_id"] for f in flags if "KIT26MBA916" in f["message"]), "R004 flag for Tomas Herrera")
    print("  flags:", *names[:3], sep="\n    ")


def demo_b(api: Api) -> None:
    print("\nDemo B — conflict and excess (Godavari admin, AICTE, Kaveri)")
    g, a, k = "godavari.admin@demo.local", "aicte.admin@demo.local", "kaveri.admin@demo.local"
    sc = api.post(g, "/api/v1/seat-check", json={"programme_code": "BTECH-CSE", "seat_category": "REGULAR", "count": 1}).json()
    print(f"  seat-check: {sc['message']}")
    expect(not sc["allowed_within_rules"] and "by 1" in sc["message"], "seat-check says it would exceed by 1")
    path = ROOT / "sample_data" / "demo_B_godavari_upload_2026-27.csv"
    job = api.post(g, "/api/v1/imports", data={"academic_year": "2026-27"},
                   files={"file": (path.name, path.read_bytes())}).json()
    p = job["summary"]["projection"][0]
    print(f"  projection: {p['message']} (+{p['change_within_intake']} within intake)")
    expect(p["change_within_intake"] == 4 and p["exceeds"], "projection shows +4 and an exceed warning")
    expect(api.post(g, f"/api/v1/imports/{job['id']}/commit").json()["committed_now"] == 5, "committed 5 rows")
    flags = api.get(a, "/api/v1/issues?status=OPEN").json()["items"]
    gflags = [f for f in flags if "Godavari" in (f["institution_name"] or "")]
    c001 = next((f for f in gflags if f["rule_id"] == "C001_EXCESS_INTAKE"), None)
    c002 = next((f for f in gflags if f["rule_id"] == "C002_SUPERNUMERARY_CAP"), None)
    d003 = next((f for f in gflags if f["rule_id"] == "D003_XINST_ACTIVE"), None)
    d004 = next((f for f in gflags if f["rule_id"] == "D004_ATTR_CONFLICT"), None)
    expect(c001 is not None and c001["evidence"]["excess"] == 4, "C001 opened (+4)")
    tfw = c002 and c002["evidence"]["position"]["supernumerary"]["SN_TFW"]
    expect(bool(tfw) and (tfw["enrolled"], tfw["cap"]) == (7, 6), "C002 opened (TFW 7/6)")
    expect(d003 is not None and d004 is not None, "D003 and D004 opened")
    gv = api.get(g, f"/api/v1/issues/{d003['id']}").json()
    withheld = [s for s in gv["evidence"]["sides"] if not s["own"]]
    expect(withheld and "identity withheld" in withheld[0]["institution"] and "Kaveri" not in json.dumps(gv),
           "Godavari sees 'Another AICTE-approved institution (identity withheld)'")
    expect(len({s.get("institution_name") for s in d003["evidence"]["sides"]}) == 2, "AICTE sees both institutions")
    api.post(a, f"/api/v1/issues/{d003['id']}/actions", json={"action": "REQUEST_CLARIFICATION",
                                                              "note": "Which institution is the student attending?"})
    kv = api.get(k, f"/api/v1/issues/{d003['id']}").json()
    own = next(s for s in kv["evidence"]["sides"] if s["own"])
    en = api.get(k, f"/api/v1/enrolments/{own['enrolment_id']}").json()["enrolment"]
    r = api.post(k, f"/api/v1/enrolments/{en['id']}/status", json={"status": "TRANSFERRED_OUT", "version": en["version"],
                                                                  "reason": "Student moved to another institution"})
    expect(r.status_code == 200, "Kaveri marks the student TRANSFERRED_OUT with a reason")
    api.post(g, f"/api/v1/issues/{d003['id']}/actions", json={"action": "RESPOND",
                                                              "note": "Student joined on 1 September after transfer."})
    res = api.post(a, f"/api/v1/issues/{d003['id']}/actions", json={"action": "RESOLVE",
                                                                    "note": "Transfer confirmed by both institutions.", "outcome": "EXPLAINED_NO_ACTION"}).json()
    expect(res["status"] == "RESOLVED", "AICTE resolves D003 with a note")
    recs = api.get(g, "/api/v1/enrolments?programme_code=BTECH-CSE&academic_year=2026-27&sort=-updated&page_size=100").json()["items"]
    new = [e for e in recs if e["institution_student_id"] in ("GEC26CSE901", "GEC26CSE902", "GEC26CSE903")]
    extra = next(e for e in recs if e["seat_category"] == "REGULAR" and e["institution_student_id"].startswith("GEC26BTECHCSE"))
    for e in [*new, extra]:
        api.post(g, f"/api/v1/enrolments/{e['id']}/status", json={"status": "CANCELLED", "version": e["version"],
                                                                 "reason": "Duplicate provisional admission"}).raise_for_status()
    c = api.get(a, f"/api/v1/issues/{c001['id']}").json()
    expect(c["status"] == "RESOLVED" and any(h["action"] == "SYSTEM_AUTO_RESOLVED" for h in c["history"]),
           "C001 clears with a logged SYSTEM_AUTO_RESOLVED event after 4 cancellations")
    expect("fraud" not in json.dumps(api.get(a, "/api/v1/issues?page_size=200").json()).lower(), "no 'fraud' wording anywhere")


def demo_c(api: Api) -> None:
    print("\nDemo C — verification (Kaveri admin, student, verifier)")
    k, s, v = "kaveri.admin@demo.local", "student.ananya@demo.local", "verifier@demo.local"
    me = api.get(s, "/api/v1/me/record").json()
    en = me["enrolments"][0]
    cred = api.post(k, f"/api/v1/enrolments/{en['id']}/credentials").json()
    expect(cred.get("status") == "ACTIVE", "Kaveri admin issues a signed record for Ananya")
    pres = api.post(s, f"/api/v1/me/credentials/{cred['id']}/present",
                    json={"claims": ["institution", "programme", "enrolmentStatus"]}).json()
    res = api.c.post("/api/v1/verification/verify-token", json={"token": pres["token"]}).json()
    expect(res["valid"] and all(c["result"] == "pass" for c in res["checks"]), "public verify: all checks pass")
    expect(res["apaar_display"].startswith("XXXX-XXXX-") and "name" not in res["claims"],
           f"only chosen claims shown; APAAR masked as {res['apaar_display']}")
    t = api.c.post("/api/v1/verification/tamper-demo", json={"token": pres["token"], "mode": "disclosure"}).json()["token"]
    bad = api.c.post("/api/v1/verification/verify-token", json={"token": t}).json()
    expect(not bad["valid"] and any(c["check"] == "disclosures" and c["result"] == "fail" for c in bad["checks"]),
           "tampered record fails the digest check")
    api.post(k, f"/api/v1/credentials/{cred['id']}/revoke", json={"reason": "Issued in error during demo"})
    rv = api.c.post("/api/v1/verification/verify-token", json={"token": pres["token"]}).json()
    sentence = next(c["sentence"] for c in rv["checks"] if c["check"] == "status")
    print(f"  after revoke: {sentence}")
    expect(rv["status"] == "REVOKED" and "Issued in error during demo" in sentence, "verify shows 'Revoked on …: reason'")
    apaar, dob = me["student"]["apaar_id"], me["student"]["date_of_birth"]
    req = api.post(v, "/api/v1/verification/requests", json={"apaar_id": apaar, "date_of_birth": dob,
                                                            "purpose": "Pre-employment verification (synthetic)"}).json()
    expect(api.get(v, f"/api/v1/verification/requests/{req['id']}/result").status_code == 403, "result is 403 before consent")
    api.post(s, f"/api/v1/verification/requests/{req['id']}/consent", json={"decision": "APPROVE"})
    out = api.get(v, f"/api/v1/verification/requests/{req['id']}/result").json()
    expect(dob not in json.dumps(out) and out["apaar_id_masked"].startswith("XXXX"),
           f"verifier sees minimal fields only: {sorted(out)}")
    expect(api.get("godavari.staff@demo.local", f"/api/v1/enrolments/{en['id']}").status_code == 404,
           "Godavari staff opening Ananya's record gets 404")
    cr = api.post(s, "/api/v1/me/correction-requests", json={"enrolment_id": en["id"], "field": "full_name",
                                                            "requested_value": "Ananya S. Iyer",
                                                            "explanation": "My Class XII certificate includes my initial."}).json()
    q = api.get("kaveri.staff@demo.local", "/api/v1/correction-requests").json()
    expect(any(x["id"] == cr["id"] for x in q), "correction request appears in Kaveri's queue")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()
    api = Api(args.base)
    api.c.get("/api/health").raise_for_status()
    demo_a(api)
    demo_b(api)
    demo_c(api)
    chain = api.get("auditor@demo.local", "/api/v1/audit/verify-chain").json()
    print(f"\nAudit chain: valid={chain['valid']} events={chain['events_checked']}")
    expect(chain["valid"], "audit chain valid after all demos")
    print(f"\n{'ALL DEMOS PASSED' if not FAILS else f'{len(FAILS)} EXPECTATION(S) FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
