# APAAR Student Register (SIH26263 prototype). One command each: make setup && make seed && make run
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8000

.PHONY: setup seed run dev test lint typecheck build demos tour clean

setup: ## create venv, install backend + frontend deps, build the frontend
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements-dev.txt
	cd frontend && npm install --no-audit --no-fund && npm run build

build: ## rebuild the frontend into frontend/dist (served by FastAPI)
	cd frontend && npm run build

seed: ## reset the database and load deterministic synthetic data + sample files
	cd backend && ../$(BIN)/python -m app.seed --reset

run: ## start the app (API + built frontend) on http://localhost:$(PORT)
	cd backend && ../$(BIN)/uvicorn app.main:app --host 0.0.0.0 --port $(PORT)

dev: ## backend with reload; run `cd frontend && npm run dev` in another terminal (http://localhost:5173)
	cd backend && ../$(BIN)/uvicorn app.main:app --reload --port $(PORT)

test: ## backend test suite (isolated temp database)
	$(BIN)/python -m pytest -q

lint:
	$(BIN)/ruff check backend scripts

typecheck:
	cd frontend && npx tsc --noEmit

demos: ## run Demos A, B, C against a running server on a freshly seeded DB
	$(BIN)/python scripts/run_demos.py --base http://localhost:$(PORT)

tour: ## Playwright smoke tour of every page at 1360px and 390px (server must be running)
	$(BIN)/python scripts/ui_tour.py --base http://localhost:$(PORT)

clean:
	rm -rf var frontend/dist .pytest_cache .ruff_cache
