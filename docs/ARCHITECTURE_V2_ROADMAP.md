# SIH26263 architecture-v2 roadmap

Updated 2026-10-27 as work lands on `codex/sih26263-architecture-v2`. The first interim commit is pushed; the verified follow-up changes below are local until pushed. The user-provided v2 markdown blueprint was not present in the repository, so this roadmap follows the supplied update prompt and observed prototype behavior. No official APAAR contract is available.

Status meanings: **DONE** = implemented and verified against its acceptance scope; **PARTIAL** = useful code landed but listed acceptance work remains; **PENDING** = not implemented.

| Workstream | Concern | Status | Completed | Remaining |
|---|---:|---|---|---|
| WS1 Claims and status | 10 | PARTIAL | Current state audit; authenticated system-status endpoint and integrations status display. | `FEATURE_STATUS.yaml`, claim checker, generated traceability, and complete claim reconciliation. |
| WS2 Registry boundary | 1 | PARTIAL | Protocol/result metadata; SIMULATED outage toggle; production guard; adapter-state display; separate synthetic metadata; awaiting HTTP boundary. Demos confirm simulated status is surfaced; no official integration is claimed. | Resilience/retries/circuit breaker; national dashboard separation; final config contract tests. No live adapter without official contract. |
| WS3 Versioned capacity rules | 2 | PARTIAL | Rule-set/entry/year models, unverified prototype and draft sets, integer cap calculations, source/version metadata, impact/activation APIs and admin UI. Focused tests and Demo B confirm the normal capacity path. | Effective-date/scope conflict validation, locked-year and override regressions, migration review and user-level rule caveats. |
| WS4 Explanations and outcomes | 4 | PARTIAL | Flags persist canonical evidence hashes, rule snapshot references, calculation/review explanation and benign alternatives; closures require an outcome; issue detail displays these fields. Redaction uses viewer-scoped evidence. Full suite and cross-institution Demo B pass. | Rule history/metrics, richer rule-specific calculations and recommendations, peer minimum, suppression policy, wording and response-shape coverage. |
| WS5 Import reliability | 5 | PARTIAL | CSV/XLSX parser hardening; Alembic bootstrap; leases/recovery endpoint; row status within savepoint; content hashes; 72-hour idempotency; revalidation change count. Full backend suite and Demos A/B/C pass. | Fault-injection and concurrent commit acceptance, atomic audit/business transaction proof, repeat-import revision tests, Excel numeric-ID warning, recovery UI and PostgreSQL concurrency. |
| WS6 Identity resolution | 3 | PARTIAL | Unicode fallback keys. | Honorific/generic weighting, second blocking pass, memory/no-merge outcomes, R009 name-quality/R015 minor-consent rules, guardian consent, 60-pair golden set and review UI. |
| WS7 Credential security | 7 | PENDING | Existing signed selective-disclosure prototype checked in baseline. | Key registry/lifecycle, fail-closed status, verification pipeline hardening, assurance statement and tests. |
| WS8 QR and shares | 8 | PENDING | Existing QR/token verification prototype checked in baseline. | Opaque expiring hashed share codes, revoke/rate limit, fragment-only URLs, status-only endpoint shape and UI. |
| WS9 Privacy and access | 6 | PARTIAL | Existing role checks and institution isolation tests; current status explicitly reports gaps. | Route permission registry/default deny, separate consent/access log, minor hold, audit sanitizer, analyst suppression, token versioning, SSE tickets, retention report and expanded response-shape tests. |
| WS10 Audit hardening | 9 | PARTIAL | Hash-chain verify and prototype audit event redaction. | Database update/delete triggers, signed anchors, truncation check, audit read logging, sanitizer scan and daily verifier. Describe only as tamper-evident. |
| WS11 End-to-end/faults | 11 | PARTIAL | Demos A/B/C passed in baseline and after the first interim change. | Full upload-to-verification E2E, failure catalogue, Demo D and dashboard/chain assertions after faults. |
| WS12 Production readiness | 12 | PARTIAL | Baseline audit, production gap register, P1–P14 decision/owner table, configuration notes. | Reconcile with the missing blueprint section 19; update API/demo/test docs; confirm external policy/privacy decisions; clean-clone acceptance report. |
| Video deliverable | — | PENDING | Script and storyboard prepared; 64 repository screenshots inventoried. | Resume only after code work is complete: complete Chatterbox narration, animation/editing, final render and review. |

## Current verification (2026-10-27)

- Backend suite: **117 passed**, one Starlette/httpx deprecation warning.
- Ruff, frontend typecheck, and Vite production build passed.
- Demos A/B/C passed after clean synthetic reseed: A **5 VALID / 2 REVIEW / 9 ERROR**, **15 committed**; B **C001 +4**, **C002 TFW 7/6**, D003/D004 and identity withholding; C signature/claim verification, tamper detection, revocation, consent gate and least disclosure. Audit chain verified valid at **1,450 events**.
- The follow-up is local at this checkpoint. Full PostgreSQL concurrency, browser tour, Demos D, complete failure catalogue and all WS1–WS12 criteria remain outstanding.
- PostgreSQL tests are not run until a test service is available. No production alias has been promoted.
