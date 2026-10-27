# Current-state audit — 27 October 2026

The table distinguishes repository behavior from design claims. Evidence is from the checked source branch and the baseline commands in `docs/BASELINE.md`. `SIMULATED` means a path is exercised only against synthetic or in-process dependencies. The v2 markdown blueprint referenced by the update prompt was not present in the clone.

| Claim / capability | Evidence in source | Status | Audit note |
|---|---|---|---|
| CSV/XLSX upload, preview, correction, partial commits | `backend/app/modules/intake.py`, `/api/v1/imports`, `backend/tests/test_imports.py` | IMPLEMENTED | Demo A baseline is 5/2/9 and 15 committed; parser hardening and crash recovery are incomplete. |
| Institution manual entry and ERP push | `api_records.py`, `api_integration.py`, `AddStudent.tsx`, `SystemAccess.tsx` | IMPLEMENTED | Both use shared validation; ERP uses scoped keys/idempotency. |
| APAAR registry lookup | `modules/apaar_adapter.py`, `sim_apaar_registry`, README data notice | SIMULATED | No official API contract or live adapter is present. Production must not select a fake LIVE mode. |
| Intake and supernumerary cap accounting | `modules/ledger.py`, `models.py`, `api_registry.py`, `test_ledger.py` | IMPLEMENTED | Current percentages are code defaults and quota overrides; there is no versioned source/effective-date rule set. |
| 25-rule validation catalogue | `modules/rules.py`, `README.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, `test_rules.py` | IMPLEMENTED | The count is 25 at baseline; the provided v2 update calls for R009/R015 and 26 total after work. Rule snapshots are absent. |
| Duplicate and identity candidates | `modules/identity.py`, `api_records.py`, `Identity.tsx`, `test_identity.py` | PARTIAL | Heuristic scoring and human decisions exist; non-Latin-only names collapse to an empty key, and there is no golden-set report or decision memory. |
| Explainable capacity/conflict flags | `modules/issues.py`, `Issues.tsx`, `test_demo_b.py` | PARTIAL | Capacity evidence and cross-institution redaction work; explanations, benign alternatives, outcomes and false-positive metrics are incomplete. |
| Dashboards and review priority | `modules/analytics.py`, `api_dashboard.py`, `National.tsx`, `ReviewPriority.tsx` | IMPLEMENTED | Seeded counts are DB-derived; peer statistics currently use only five named institutions. |
| Institution privacy and role separation | `security.py`, route dependencies, `test_security.py` | PARTIAL | Basic role and institution isolation is tested; route coverage is not declared in a default-deny matrix. |
| Consent-based verification | `api_verification.py`, `MyRecord.tsx`, `VerifierRequests.tsx`, `test_credentials.py` | PARTIAL | Request/decision flow exists; separate expiry/revocation consent records, access log and guardian-consent hold are absent. |
| Selective-disclosure signed records | `modules/credentials.py`, `api_credentials.py`, `api_verification.py`, `test_credentials.py` | PARTIAL | Ed25519, selective disclosure and tamper checks exist; keys are not registry-managed and verification status failure handling is not fail-closed to UNKNOWN. |
| QR and public share links | `api_credentials.py`, `Verify.tsx`, `test_credentials.py` | PARTIAL | QR verification exists, but legacy credential-ID status addressing and token/credential linkage need replacement by opaque hashed share codes. |
| Audit chain | `audit.py`, `api_audit.py`, `test_platform.py` | PARTIAL | Hash verification and tamper detection work; writes are post-commit, no DB update/delete triggers or signed anchors exist, and detail sanitization is incomplete. |
| APAAR verification metadata per record | `Student` model and API views | MISSING | Results do not persist mode/version/check time at the student verification level. |
| Import stale-job recovery | `ImportJob`, `modules/intake.py`, `/api/v1/imports/{id}/commit` | PARTIAL | Stale lock reset is time-based; no lease token, explicit recovery route, or startup sweep. |
| Demo A/B/C workflows | `scripts/run_demos.py`, baseline `make demos` | IMPLEMENTED | All three ran successfully; A/B/C regression values recorded in baseline. |
| Failure-mode suite and Demo D | `scripts/run_demos.py`, test tree | MISSING | No fault-injection suite, versioned rule-set demo, or rule restore workflow. |
| System status and feature claims registry | `main.py`, `api_*`, docs | MISSING | No `/api/v1/system/status`, `FEATURE_STATUS.yaml`, or claim consistency script. |
| Production readiness | `docs/PRODUCTION_GAP_ANALYSIS.md`, `.env.example`, README | PARTIAL | Major real-world dependencies are documented, but not assigned owners/blocks and not reconciled with a claims register. |

## Focus checks

- SQLite `PRAGMA foreign_keys=ON`: **present** in `backend/app/db.py`.
- Database-level immutability for `audit_events`: **absent** at baseline.
- Non-Latin `name_key`: **empty** when NFKD-to-ASCII removes all letters.
- Numeric APAAR Excel cell: `clean_cell()` converts integral floats to integer text; no corruption was observed by inspection, but there is no import warning/test.
- Stuck `COMMITTING` import: no explicit lease recovery or startup sweep.
- Audit `detail`: the sanitizer redacts 12-digit sequences and selected secret keys, but can retain names and other personal fields if passed by a caller.
- Credential/QR URL: status is addressed by credential ID; no opaque, expiring, revocable share-code table exists.
- Route role/scope checks: individual dependencies/handlers enforce access, but there is no declared permission registry or coverage test. This is a coverage gap, not evidence that every route is currently unprotected.
