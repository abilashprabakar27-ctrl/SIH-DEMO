# Production readiness review

This is a prototype gap register based on the checked source and observed behavior. It is not a legal or policy determination. Owners below are proposed and require confirmation. All policy and legal points are **to confirm with counsel**.

| ID | Dependency or decision | Proposed owner | Blocks production | Prototype behavior / evidence |
|---|---|---|---|---|
| P1 | Official APAAR verification contract, onboarding, credentials and permitted fields | AICTE integration owner | Yes | `SIMULATED` synthetic table only; no official API is implemented. |
| P2 | AICTE approval and intake source, authoritative feed and correction process | AICTE data owner | Yes | Intake values are prototype-maintained; no official feed. |
| P3 | Current seat-cap and supernumerary rules, primary source, scope and effective dates | AICTE policy owner | Yes | Versioned prototype rule sets now support source metadata, scope, effective dates and integer calculations. Values remain unverified and are not represented as authoritative. |
| P4 | Identity matching thresholds, reviewer process, and labelled evaluation data | AICTE review owner | Yes | Heuristic candidate suggestions; decisions require human action. Thresholds are provisional. |
| P5 | Rule explanation and false-positive outcome taxonomy | AICTE review owner | Yes | Flags persist calculation evidence, explanation, evidence hash and required human outcome. Rule-specific performance metrics and taxonomy validation remain incomplete. |
| P6 | Import transaction, lock recovery, idempotence and concurrency guarantees | Engineering owner | Yes | Alembic migration, commit leases/recovery and idempotency expiry are implemented. PostgreSQL concurrency and fault guarantees still require validation. |
| P7 | Institution authentication, national roles, isolation review and session revocation | Security owner | Yes | Local roles and scoped checks exist; no complete permission matrix or SSO/MFA. |
| P8 | Consent purpose, notice, minors/guardian process and access-log policy | Privacy owner | Yes | Verification request consent exists; durable consent records are incomplete. To confirm with counsel. |
| P9 | Retention periods, deletion/archival policy and subject requests | Privacy owner | Yes | No production retention job; retention schedule is to confirm with counsel. |
| P10 | Credential issuer trust, managed key lifecycle, revocation/status service | Credential owner | Yes | Ed25519 prototype key; no managed key registry or production key custody. |
| P11 | QR/share disclosure defaults, expiry, revocation, rate limits and threat review | Security owner | Yes | Existing verification path requires privacy/security review; opaque share-code lifecycle incomplete. |
| P12 | Tamper-evident audit, append controls, anchoring, backup and restore | Security/operations owner | Yes | Hash chain exists; database update/delete protection and signed anchors are incomplete. |
| P13 | Production database, migrations, backup/restore, monitoring and load targets | Operations owner | Yes | SQLite and `create_all`; no migration history or production restore evidence. |
| P14 | DPIA, accessibility, incident response, breach process and jurisdictional review | Privacy/security owner | Yes | Synthetic-data prototype only. All legal requirements are to confirm with counsel. |

## Current code status

- The registry adapter remains `SIMULATED`; there is no official contract, `LIVE` implementation, or production verification claim.
- `/api/v1/integration/system/status` is a prototype status report, not a compliance certification.
- CSV parsing accepts UTF-8/UTF-8 BOM and Windows-1252, comma/semicolon delimiters; XLSM, oversized XLSX archives, and external links are rejected.
- Non-Latin-only names retain a Unicode matching key. Matching remains heuristic and requires review.
- Capacity rules have prototype versioning and effective-date metadata, but values and application remain unverified pending an authoritative policy feed.
- Credentials, consent, audit immutability, role matrix, retention, and end-to-end failure coverage remain production blockers.

## Deployment gate

Do not set `APP_ENV=production` until a contract-backed live adapter, production database controls, and the P1–P14 decisions are complete. An Alembic bootstrap migration now exists; this does not settle production backup/restore, concurrency, or operations requirements. The application deliberately refuses production startup when its configured registry mode is not `live`; this guard does not itself implement a live adapter.
