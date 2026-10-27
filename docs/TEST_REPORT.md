# Test report

Run on 27 Oct 2026. The table was first produced from a **fresh clone**; the tests, demos and tour were re-run after the government-portal restyle and the gap fixes of branch `claude/busy-newton-qnsfmy`. The environment was Linux, Python 3.13, Node 22 and Chromium 1243.
Every number below was observed in that run. Nothing is estimated.

| Step | Command | Result |
|---|---|---|
| Setup | `make setup` | OK in 21 s (venv, pip, npm install, `tsc --noEmit` + Vite build) |
| Seed | `make seed` | OK in 4.9 s. 10 import jobs and 1,347 enrolment rows committed through the validation engine (2025-26: 627; 2026-27: 720) |
| Health | `curl /api/health` | `{"status":"ok","apaar_registry":"SIMULATED","data":"synthetic"}`; `/` serves the built frontend |
| Backend tests | `make test` (`pytest -q`) | **109 passed**, 0 failed, 1 warning (Starlette TestClient/httpx deprecation notice), 58.4 s |
| Lint | `make lint` (`ruff check backend scripts`) | All checks passed |
| Typecheck | `make typecheck` (`tsc --noEmit`) | No errors |
| Demos | `make demos` (`scripts/run_demos.py`) | **ALL DEMOS PASSED**: 29 expectations, 0 failed; audit chain valid over 1,448 events |
| UI tour | `make tour` (`scripts/ui_tour.py`) | **UI TOUR PASSED**: 64 page views (2 public pages + 30 role pages including import, record and flag detail pages, each at 1360 px and 390 px); 0 console errors, 0 error banners, 0 horizontal scroll. Screenshots in `docs/screenshots/` |

## Demo results (key numbers)
- **Demo A:**
  - The preview gave **5 VALID / 2 REVIEW / 9 ERROR**.
  - Did-you-mean suggested `911100000008` for `911100000098`.
  - After 7 fixes and leaving out one row, 15 rows were committable with 0 errors, and **15 committed**.
  - The AICTE live stream received `seat.changed` and `issue.opened`.
  - R007 (Vignesh) and R004 (Tomas Herrera) flags opened.
- **Demo B:**
  - Seat check answered "would exceed approved intake by 1 (120 of 120)".
  - The projection showed +4 within intake with the exceed warning, and 5 rows committed.
  - **C001 +4**, **C002 TFW 7/6**, D003 and D004 opened.
  - Godavari saw "identity withheld"; AICTE saw both institutions.
  - The workflow ran: clarification, then TRANSFERRED_OUT, then response, then resolve.
  - Cancelling 4 admissions closed C001 with `SYSTEM_AUTO_RESOLVED`.
  - The word "fraud" appeared nowhere.
- **Demo C:**
  - The credential was issued; selective disclosure of 3 claims passed all 6 checks, with APAAR masked as `XXXX-XXXX-0001`.
  - Tampering failed the digest check.
  - After revocation, verify showed "Revoked on 27 Oct 2026: Issued in error during demo".
  - The consent result was 403 before consent; after consent it returned minimal fields only.
  - Godavari got 404 on Ananya's record.
  - The correction request appeared in Kaveri's queue.

## What the 109 tests cover (`backend/tests/`)

| File | Tests | Covers |
|---|---|---|
| `test_ledger.py` | 20 | Seat rules: 0 enrolled, exactly intake, intake+1, NRI counted, supernumerary excluded, cap and cap+1 for each of the 4 categories, non-transferability, rounding examples (60 UG eng → 6/3/3; 60 PG mgmt → 10/5/3; 10 UG eng → 1/0/0), WITHDRAWN not counted (DB), seat-check advice at intake−1, intake, intake+1 and per category (pure + API) |
| `test_rules.py` | 38 | A positive and a negative case for every rule R001–R014, F001–F003, D001–D004; adapter unavailable → R008 WARNING with SIMULATED label; did-you-mean has exactly one suggestion and none when two variants match; gating skips repository rules; disabled rule and severity change; 25-rule catalogue |
| `test_identity.py` | 6 | Name key and phonetic fold; Subramaniam/Subramanian ≥ 9 → D005 with weights; "K. Anil Rao"/"Anil Kumar Rao" in the 6–9 band; a different DOB gives no candidate; seeded candidates via API; DIFFERENT_PEOPLE dismisses D005; analyst cannot decide |
| `test_imports.py` | 7 | Demo A counts for CSV and XLSX; F004 repeated file; full Demo A flow (suggestion, fixes, exclude, commit 15, re-commit no-op, committed row 409); partial commit then retry; concurrent commit 409; bulk fix; 415/413/422 uploads and header aliases; templates with drop-downs |
| `test_security.py` | 11 | 401 shape; cross-institution detail/write/status 404; cross-institution list filters 403 and scoped lists and reports; verifier and student blocked; analyst sees masked APAAR and no sensitive fields; APAAR search is exact only; every 403 audited; no raw APAAR anywhere in the audit log; security headers; lockout after 5 failures; login rate limit; PBKDF2 ≥ 210k |
| `test_corrections.py` | 5 | Optimistic lock 409 and revision with reason; re-validation rejects an invalid seat; invalid transition 422, WITHDRAWN→ACTIVE; pending-APAAR student later gets an ID on the same record; manual entry needs acknowledgement for REVIEW |
| `test_demo_b.py` | 1 | End-to-end Demo B including redaction, the permission matrix, the review workflow, auto-resolve and reopen |
| `test_credentials.py` | 9 | Issue permissions; valid selective disclosure; altered payload; altered disclosure; undisclosed claims hidden; unknown kid; garbage; expired; superseded; revoked with reason; JWKS; certificate shows both IDs and QR; consent (no-match indistinguishable, 403 before consent, fixed fields only); correction-request queue |
| `test_platform.py` | 12 | Integration: bad key 401, missing Idempotency-Key 400, idempotent replay, same key with a different body 409, rejected row, missing scope 403; honest integration status; audit chain valid, then tampering one row reports that row's seq; national totals equal direct SQL counts; review priority with disclaimer; CSV injection; rules admin (locked 409); SSE scoping; stream-token required; API keys (create shown once, scope enforced, other institution 404, revoke then 401, staff 403); notifications listed |

## Reproduce
```bash
make setup && make test && make lint && make typecheck
make seed && make run          # terminal 1
make demos && make tour        # terminal 2 (run `make seed` again before re-running demos)
```
