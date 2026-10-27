# Handoff: SIH26263 prototype build (read this first)

This file lets a new Claude session (or another account) continue the build from the repository alone.
It is updated at every checkpoint commit on branch `claude/busy-newton-qnsfmy`.

## Inputs
- `docs/BUILD_PROMPT.md`: the full build brief, sections 0–13. It is the source of truth for scope and acceptance.
- `docs/SIH26263_Architecture_Blueprint.pdf`: the architecture blueprint (42 pages). Do not redesign it.
- No web searches were used. All research comes from the blueprint (section 6 lists its sources).

## How to resume
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic cryptography PyJWT openpyxl qrcode pytest httpx python-multipart ruff pillow
cd backend && python -m app.seed --reset        # ~5 s; DB + keys go to ../var/ (gitignored)
uvicorn app.main:app --reload --port 8000       # API docs at http://localhost:8000/api/docs
ruff check .                                    # lint
```
Tell the new session: "Continue the build in HANDOFF.md, following docs/BUILD_PROMPT.md."

## Status by execution-plan step (BUILD_PROMPT §12)
| # | Step | State |
|---|------|-------|
| 1 | Scaffold, config, DB, models, auth/roles, audit chain | done (code); tests pending |
| 2 | Seat rules + registry + intake APIs | done (code); tests pending |
| 3 | Normaliser, rule catalogue (25 rules), engine, simulated adapter, commit path | done (code); tests pending |
| 4 | Import API, did-you-mean, Excel template | done (code); tests pending |
| 5 | Issues, review actions, redaction, capacity checks, identity resolution | done (code); tests pending |
| 6 | Credentials (SD-JWT style), verification, consent, certificate, QR | done (code); tests pending |
| 7 | Dashboards, review priority, reports, seat-check, SSE, correction requests | done (code); tests pending |
| 8 | Full seed + sample files | done, runs clean; `scripts/run_demos.py` not yet written |
| 9 | React frontend + Playwright tour | NOT STARTED |
| 10 | Docs (README, DEMO_SCRIPT, TEST_REPORT, traceability, API design, gap analysis, .env.example) | NOT STARTED |
| 11 | Clean-clone validation | NOT STARTED |

Immediate next actions:
1. Write `backend/tests/` (conftest with a temp `APAAR_VAR_DIR` + `DATABASE_URL`, then the cases in BUILD_PROMPT §11). Run them and fix what fails.
2. Write `scripts/run_demos.py` (Demos A, B and C against the API; see §10) and check the Demo A preview gives 5 VALID, 2 REVIEW, 9 ERROR.
3. Build the frontend (`frontend/`, Vite + React + TS), served by FastAPI from `frontend/dist`.
4. Write the docs, Makefile, `.env.example` and Playwright tour.

## Code map (backend/app)
- `config.py`: settings; secrets are generated into `var/`; `APAAR_TODAY` overrides today's date for tests.
- `db.py`: engine and session. `after_commit()` hooks run only after the outermost commit; savepoint commits are skipped. That guard fixed a SQLite "database is locked" deadlock.
- `models.py`: all tables in §2. Additive columns: created_at/updated_at, `users.locked_until`, `validation_rules.locked`, `identity_candidates.decision_note`, `institutions.short_name`, `integration_clients.name/active`, `idempotency_records.status_code`, `approved_intakes.submitted_by`.
- `security.py`: PBKDF2 210k, HS256 JWT, Actor model (user or API-key client), masking, `apaar_ref` HMAC, rate limiter, `ApiError`.
- `audit.py`: hash chain. Events are buffered per session and appended after commit under a process lock. DENIED/FAILED events are written even on rollback. Raw 12-digit IDs are scrubbed from details.
- `modules/normalize.py`: template columns, aliases, R001/R002.
- `modules/rules.py`: the catalogue. It has 25 rules because I added `R009_DUPLICATE_ENROLMENT` (same student, programme and year under a different roll number). Locked rules: R001, R002, D002, F001, F002.
- `modules/engine.py`: `validate_rows()` and `commit_values()`. This is the only writer of students and enrolments. It handles the §4 pitfalls (pending-APAAR re-submit, self-findings filter).
- `modules/ledger.py`: pure seat rules (`position_from_counts`, `default_caps`, `seat_check`) and status transitions.
- `modules/identity.py`: phonetic fold, Jaro–Winkler, weights, candidates (≥9 gives D005; 6–9 are listed only).
- `modules/apaar_adapter.py`: SIMULATED adapter (`set_adapter()` is a test hook), did-you-mean.
- `modules/issues.py`: dedupe open/update, C001/C002 capacity checks with system auto-resolve, action permissions, privacy redaction ("identity withheld").
- `modules/intake.py`: upload parsing (415/413/422), preview, projection, row edit, exclude, bulk-fix, commit (conditional-update lock, per-row savepoints), CSV/XLSX templates.
- `modules/credentials.py`: Ed25519 key in `var/`, JWKS, SD-JWT token, `present()`, `tamper()`, `verify()` (6 ordered checks plus a currency note).
- `modules/analytics.py`: national and institution dashboards, review priority (rule signals plus robust-z peer stats), report rows.
- `modules/api_*.py`: routers under `/api/v1` (see §7). `main.py` holds the error shape, security headers/CSP, 403 auditing and the SPA fallback.
- `seed.py`: deterministic seed (`random.Random(2026)`). All rows go through `intake.create_job` and `commit_job`. Seeded anomalies:
  - Narmada MBA is +8 over intake (C001), with CIWG at 6/5 (C002) and 6 admissions outside the window.
  - Yamuna and Narmada share one student, which gives D003.
  - "K. Anil Rao" and "Anil Kumar Rao" form a listed identity candidate.
  - "Mohammed Farook" and "Mohamed Farooq" give D005.
  - Linh Tran gives R004.
  - Four Brahmaputra registry spellings differ (R007).
  - Yamuna has declared its submission.
  - Ananya Iyer has a student account and one credential.
  - The Kaveri ERP key is in `var/demo_api_key.txt`.

## Decisions and deviations (keep docs consistent with these)
- Audit events are appended in a separate transaction right after the business commit, not inside it. This is documented as a gap; production should use a PostgreSQL advisory lock in the same transaction.
- F004 (repeated file) is a file-level finding in `job.summary.file_findings`, not a row finding. That keeps Demo A at 5/2/9 when the file is uploaded again.
- C001/C002 are aggregate checks. The preview shows a projection; issues open after commit.
- Credential issuance requires `apaar_status == VERIFIED`, not just an APAAR ID being present. This follows the blueprint's "only registry-matched IDs".
- When a credential is presented without `apaarId`, verification still returns the masked APAAR (`XXXX-XXXX-1234`) from the register, as Demo C expects.
- Institution users cannot change shared identity fields of a student enrolled elsewhere (409). AICTE must correct the master record.
- Review-priority "seats over intake" uses institution totals (excess ÷ total intake). Overdue correction requests add min(10, 3×n).

## Known issues / not yet verified
- No tests have been run yet. Treat every module as unverified until §11 tests pass.
- SSE has been written but not exercised.
