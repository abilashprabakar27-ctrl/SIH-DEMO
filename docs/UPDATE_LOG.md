# Architecture v2 update log

- [x] Baseline tests, demos, lint and typecheck recorded.
- [x] Current-state audit and known defects recorded.
- [ ] WS5 import reliability and parser hardening — **partial**: parser checks added for XLSM, XLSX expansion/external links, Students worksheet selection, Windows-1252 and semicolon CSV; lease recovery, atomic audit/row commit and content-hash no-op remain open.
- [ ] WS2 registry adapter boundary and simulation separation — **partial**: protocol/result metadata and outage toggle added; official HTTP adapter, persisted per-student metadata and production schema separation remain open.
- [ ] WS6 identity resolution upgrade — **partial**: Unicode fallback added; honorific/generic weighting, decision memory and golden fixture remain open.
- [ ] WS12 production readiness docs — **partial**: P1–P14 blocker register added; production decisions remain outstanding.
- [ ] WS1 claims register and system status. A system status endpoint and integrations view exist, but the claims YAML/checker/traceability generator are not implemented.
- [ ] WS3 versioned capacity rule sets.
- [ ] WS2 registry adapter boundary and simulation separation.
- [ ] WS4 explanations, outcomes, metrics and peer minimum.
- [ ] WS6 identity resolution upgrade.
- [ ] WS7 credential security and assurance statements.
- [ ] WS8 opaque QR/share links.
- [ ] WS9 privacy, permissions, consent and retention.
- [ ] WS10 audit hardening and anchors.
- [ ] WS11 end-to-end and failure scenarios.
- [ ] WS12 production readiness documentation.
- [ ] Frontend pages and tour updated for the new endpoints.
- [ ] Final clean-clone validation and Vercel preview checked.

## Current verification snapshot

- Backend suite: **112 passed** on this branch before the final production-startup guard tightening; one existing Starlette/httpx deprecation warning.
- Frontend: `npx tsc --noEmit` and Vite production build succeeded.
- Ruff: all checks passed.
- Demo A/B/C: all passed after resetting the local synthetic database; A 5/2/9 and 15 committed, B C001 +4 / C002 TFW 7/6 / D003+D004, C all exercised checks.
- PostgreSQL concurrency suite: **NOT RUN**; Docker is installed but a running daemon was not confirmed.
- Demos D, migration validation, full claims checker, Playwright tour, and complete P0/P1 implementation: **NOT RUN / NOT IMPLEMENTED**. This branch is an interim hardening change, not architecture-v2 completion.
