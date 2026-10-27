# API design

The OpenAPI document is generated from the code: **`/api/docs`** (Swagger UI) and **`/api/openapi.json`**.
This page records the conventions and the deviations from the build brief.

## Conventions
- **Versioning.** Everything lives under `/api/v1`. Issuer keys are at `/.well-known/issuer-keys`, and health at `/api/health`.
- **Authentication.**
  - Users send `Authorization: Bearer <HS256 JWT>` (120 min) from `POST /api/v1/auth/login`. The user is reloaded from the database on every request.
  - Integration clients send `X-API-Key: apk_xxxxxxxx.<secret>`. Only its SHA-256 is stored, and each key carries scopes (`enrolments:write`, `seat:check`).
  - The live event stream (`GET /api/v1/events?token=`) needs a 2-minute stream token from `POST /api/v1/auth/stream-token`, because EventSource cannot send headers. API tokens are not accepted there.
- **Errors.** Every error has the shape `{"error": {"status", "message", "request_id", ...}}`, with no stack traces.
  - Extra keys such as `findings`, `row_status`, `needs_acknowledgement`, `current_version` and `missing_columns` sit inside `error`.
  - It is always `row_status`, never `status`, so the HTTP status field is never overwritten.
- **Authorization outcomes.**
  - 401: not signed in.
  - 403: role or scope not allowed, or an explicit cross-institution filter.
  - 404: an object that belongs to another institution, so its existence is not disclosed.
  - 409: version or lock conflict, a locked rule, or a reused idempotency key with a different body.
  - 422: validation, including invalid status transitions.
  - Every 403 is written to the audit chain.
- **Pagination.** `page` and `page_size` (capped), with the response returning `total`.
- **Headers.** CSP with `script-src 'self'`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` on the API.

## Endpoint groups
| Group | Endpoints |
|---|---|
| Auth | `POST auth/login`, `GET auth/me`, `POST auth/stream-token`, `GET auth/demo-accounts` |
| Registry | `GET institutions`, `GET programmes`, `POST intakes` (AICTE_ADMIN), `PATCH intakes/{id}/quotas/{category}`, `POST intakes/{id}/submit`, `POST seat-check`, `GET events` (SSE), `GET/PATCH rules`, `GET notifications` |
| Imports | `GET imports/template.csv`, `GET imports/template.xlsx`, `POST imports`, `GET imports`, `GET imports/{id}`, `PATCH imports/{id}/rows/{n}`, `POST imports/{id}/rows/{n}/exclude`, `POST imports/{id}/bulk-fix` (`{field, from, to}`), `POST imports/{id}/commit`, `POST imports/{id}/discard`, `GET imports/{id}/report.csv` |
| Records | `GET enrolments`, `POST enrolments` (manual entry; `acknowledge_review`), `GET enrolments/{id}`, `PATCH enrolments/{id}` (`version`, `reason`, `changes`), `POST enrolments/{id}/status`, `GET identity/candidates`, `POST identity/candidates/{id}/decision` |
| Flags | `GET issues`, `GET issues/{id}`, `POST issues/{id}/actions`, `GET issues/export.csv` |
| Dashboards and reports | `GET dashboard/national`, `GET dashboard/institution`, `GET dashboard/review-priority`, `GET reports/intake-utilisation.csv`, `GET reports/nationality.csv`, `GET reports/review-priority.csv` |
| Credentials | `POST/GET enrolments/{id}/credentials`, `POST credentials/{id}/revoke`, `GET credentials/{id}/certificate`, `GET credentials/{id}/qr.svg`, `GET /.well-known/issuer-keys` |
| Verification | `POST verification/verify-token` (public), `POST verification/tamper-demo` (public, demo only), `GET verification/credentials/{id}` (public status), `POST/GET verification/requests`, `POST verification/requests/{id}/consent`, `GET verification/requests/{id}/result` |
| Student | `GET me/record`, `POST me/credentials/{id}/present`, `GET/POST me/correction-requests`, `GET correction-requests` (institution queue), `POST correction-requests/{id}/actions` |
| Integration | `POST integration/enrolments` (needs `Idempotency-Key`), `GET integration/status` |
| Audit | `GET audit`, `GET audit/verify-chain`, `GET audit/export.csv` |

## Deviations from the build brief
- **R009 added.** The brief's table lists 24 rule IDs but says "25 rules". `R009_DUPLICATE_ENROLMENT` (ERROR) covers the same student enrolled in the same programme and year under a different roll number. This case cannot be reached otherwise without breaking a unique constraint.
- **Additive columns.**
  - `created_at`/`updated_at` on mutable tables.
  - `users.locked_until` (lockout).
  - `validation_rules.locked`.
  - `institutions.short_name`.
  - `integration_clients.name`/`active`.
  - `idempotency_records.status_code`.
  - `approved_intakes.submitted_by`.
  - `identity_candidates.decision_note`.
  - An index on `students.date_of_birth` (identity blocking).
- **F004 is file-level.** The repeated-file check is reported in `summary.file_findings`, not on each row, so row counts stay meaningful.
- **Credential issuance** requires `apaar_status = VERIFIED` (registry-matched), following the blueprint's "only registry-matched IDs" for R10.
- **APAAR on verification.** When a presentation does not disclose `apaarId`, verification still returns the masked form (`XXXX-XXXX-1234`) from the register, as Demo C expects.
- **Extra endpoints**, each additive:
  - `PATCH intakes/{id}/quotas/{category}`: AICTE-configurable caps, needed for `SN_OTHER`.
  - `POST verification/tamper-demo`: so the UI tamper button makes no client-side crypto claims.
  - `POST me/credentials/{id}/present`: assembles the selective-disclosure token.
  - `GET auth/demo-accounts`: the login picker.
  - `POST auth/stream-token`.
