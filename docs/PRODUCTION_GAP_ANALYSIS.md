# Production gap analysis

What separates this prototype from a national deployment. It is ordered roughly by risk.

| Area | Prototype today | Needed for production |
|---|---|---|
| APAAR registry | **SIMULATED** adapter over a synthetic table (`sim_apaar_registry`) | An official verification contract with ABC/APAAR (API Setu), a live adapter behind the same interface, retry/queue for UNVERIFIED records, and legal basis and DPDP review |
| Database | SQLite file, single process | PostgreSQL with backups and point-in-time recovery, read replica for dashboards, migrations (Alembic); the schema already avoids SQLite-only SQL |
| Audit atomicity | Audit events are appended in a separate transaction **right after** the business commit, under a process lock. A crash between the two can lose an event. Denied and failed events are written even on rollback | Append in the same transaction under `pg_advisory_xact_lock`; periodically anchor the chain head to write-once storage; retain for at least 1 year |
| Signing keys | Ed25519 key in `var/` (file mode 0600); single key, no rotation UI | KMS/HSM-held keys, key rotation with multiple JWKS entries, a status list (e.g. Bitstring Status List) for offline revocation checks, holder binding (KB-JWT) |
| Secrets | Generated into `var/` or read from env | Vault/KMS, rotation, no secrets on disk |
| Identity and access | Local accounts, PBKDF2 210k, HS256 JWT, lockout, in-memory rate limits | SSO (Parichay/OIDC), MFA for AICTE and institution admins, distributed rate limiting (Redis), session revocation, ASVS L2 review |
| Live events | In-process SSE bus (single worker) | Redis/NATS pub-sub across workers; backpressure and reconnection IDs |
| Scale | Validation prefetches per file; about 5 s to seed 1,347 rows through the full engine | Background workers for large files; partitioning by academic year; indexes reviewed against real query plans; load test at admission-season peaks |
| Identity resolution | Blocking on DOB (± day/month swap); greedy token matching | Tune weights on labelled pairs; more blocking keys (phonetic surname); reviewer tooling for controlled merges |
| Review priority | Robust z-scores against **all 5 institutions**, because fewer than 8 peers of a type exist. With so few peers, zero-valued metrics (e.g. no NRI students) can exceed \|z\| = 3.5 | Real peer groups (type, discipline, state); minimum-cell-size rules; calibration with AICTE reviewers |
| Integrations | ERP push and seat-check live; AICTE approval-process intake feed, DigiLocker/NAD and degree-awarding body feeds **not implemented** | Build these adapters; onboarding and keys per institution system |
| Offline-friendly submission | Excel template with drop-down lists only | Client-side pre-check exporting the rule catalogue as JSON (blueprint innovation 9) |
| Accessibility and language | Keyboard navigation, visible focus, 390 px layout, sentence-case labels; English only | Formal WCAG 2.1 AA audit; Hindi and regional languages |
| Observability | Request IDs in errors and headers; logs to stdout | Structured logs, metrics, tracing, alerting, an integration health dashboard |
| Data protection | Synthetic data, masking, consent, minimal verifier fields | DPIA, retention schedule, breach procedures, verifiable parental consent for minors, legal review of the AICTE processing basis |
