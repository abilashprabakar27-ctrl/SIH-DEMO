#!/usr/bin/env bash
# Vercel build: seed the Neon database once (only if empty), then build the frontend.
set -euo pipefail

if env | grep -qE '(^DATABASE_URL=|_DATABASE_URL=|^POSTGRES_URL=)'; then
  echo "Database configured; seeding if empty..."
  python3 -m venv /tmp/seedenv
  /tmp/seedenv/bin/pip install --quiet -r requirements.txt
  (cd backend && /tmp/seedenv/bin/python -m app.seed --if-empty)
else
  echo "WARNING: no DATABASE_URL / Neon variables found; skipping seed. Connect a Neon database and redeploy."
fi

cd frontend && npm run build
