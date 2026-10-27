# Baseline audit — 27 October 2026

## Repository state

- Source branch: `claude/busy-newton-qnsfmy` at `8699d0ee73eff8dcbd09d665a7f00b570a197ee1`.
- The requested `docs/SIH26263_Architecture_Blueprint_v2.md` is not present. The repository contains the v1.0 PDF blueprint and `docs/BUILD_PROMPT.md`; this update follows the provided v2 update prompt, the v1 blueprint, and observed code. Any claim that depends on a missing v2 section is marked for verification.
- Baseline was run on the clean source snapshot using Python 3.12.14 and Node 24.18.0.

## Baseline commands and results

| Command | Observed result |
|---|---|
| `make setup PY=/home/sanjayvasudevan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3` | Succeeded; backend requirements installed, TypeScript/Vite production build completed (59 modules). |
| `make test` | **109 passed**, 0 failed, 1 Starlette/httpx deprecation warning, 99.22 seconds. |
| `make lint` | **All checks passed.** |
| `make typecheck` | **No errors.** |
| `make seed` | Succeeded; 1,347 synthetic enrolments seeded across 10 institution-years. |
| `make demos` | **Demos A, B and C passed.** Audit chain valid after the runs with 1,448 events. |

### Demo regression values

- Demo A: preview **5 VALID / 2 REVIEW / 9 ERROR**; after fixes, **15 rows committed**.
- Demo B: seat check warns at 120/120; commit opens **C001 +4**, **C002 TFW 7/6**, **D003** and **D004**; cross-institution redaction and resolution flow work.
- Demo C: issue, selective disclosure, public verification, tamper detection, revocation, consent gate, cross-institution 404, and correction request flow all passed.

## Known defects and gaps at start

1. `docs/REQUIREMENTS_TRACEABILITY.md` and the README describe a static 25-rule catalogue. Capacity rules have no versioned rule-set record, source verification state, or effective-date resolution.
2. `backend/app/modules/apaar_adapter.py` is a single SIMULATED adapter. There is no adapter protocol/contract, official HTTP adapter boundary, production startup guard, or registry result metadata beyond mode/status.
3. `backend/app/db.py` enables SQLite foreign keys, but schema setup uses `create_all`; there is no Alembic migration history.
4. Import commits use a time-based `COMMITTING` stale-lock check, but there is no lease token, recovery route, or startup recovery sweep. Import parsing does not reject `.xlsm`, cap XLSX ZIP expansion, select a `Students` worksheet, reject external links, support Windows-1252, or detect semicolon CSV. Commit side effects and audit writes are not atomic with each import row.
5. `name_key()` strips all non-ASCII characters; a non-Latin-only name produces an empty key. Numeric Excel cells are converted to integer text when integral, but are not marked as numeric or warned about.
6. Identity candidates use heuristic token/DOB/gender scoring, but have no documented model/band version, pair fingerprint, decision suppression, or labelled golden fixture. Existing candidates are never auto-merged, which is retained.
7. Audit details redact a limited set of keys and 12-digit runs, but do not reject names/DOB/email fields centrally. Audit events are appended after the business transaction in a separate transaction; there are no database immutability triggers or signed anchors.
8. Credential signing uses one generated Ed25519 key without an ACTIVE/RETIRED/COMPROMISED registry. Verification is not backed by a registry record, and the public status response identifies a credential by ID. QR payload construction and status currency need tightening before demo/publication.
9. Consent uses verification-request state and expiry but lacks a separate revocable consent record and student access log. There is no declared default-deny route permission matrix; route checks are distributed through dependencies and handlers.
10. There is no System status endpoint/page, claims registry/checker, rule metrics/history, minimum peer-group threshold, or documented false-positive outcome classification.
11. End-to-end automation covers A/B/C and the README-reported UI tour, but not the requested fault-injection catalogue, Demo D rule-set activation, or post-demo audit privacy scan.
12. `docs/PRODUCTION_GAP_ANALYSIS.md` already identifies real integration, key management, PostgreSQL, multi-worker events and legal/privacy review as gaps; these remain external dependencies and must not be represented as solved by this update.

## Scope notes

- Preserve the established A/B/C regression values.
- Do not claim a live APAAR API exists. `LIVE` remains unavailable until an official contract and credentials are supplied.
- Treat the legacy blueprint as a reference, not evidence that every feature is implemented.
- PostgreSQL-only concurrency behavior must be reported `NOT RUN` if no PostgreSQL test service is available.
