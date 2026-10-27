"""Test fixtures: an isolated temp var/ + SQLite DB per test session, reseeded per mutating module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="apaar-tests-"))
os.environ["APAAR_VAR_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ["APAAR_TODAY"] = "2026-10-27"
os.environ["LOGIN_RATE_PER_MINUTE"] = "100000"
os.environ["VERIFY_RATE_PER_MINUTE"] = "100000"
os.environ["VERIFIER_REQUESTS_PER_HOUR"] = "100000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.apaar_adapter import set_adapter  # noqa: E402

PASSWORD = "Demo@2026"
SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
_tokens: dict[str, str] = {}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _reseed():
    _tokens.clear()
    set_adapter(None)
    seed.run(reset=True, write_samples=True)


@pytest.fixture(scope="module")
def seeded(client):
    """Fresh seeded database for each test module (modules mutate data)."""
    _reseed()
    yield
    set_adapter(None)


@pytest.fixture
def db(seeded):
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def login(client, email: str) -> dict:
    if email not in _tokens:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        _tokens[email] = r.json()["access_token"]
    return {"Authorization": f"Bearer {_tokens[email]}"}


@pytest.fixture
def as_(client, seeded):
    return lambda email: login(client, email)


def upload(client, headers, path: Path, year="2026-27", name=None, content: bytes | None = None):
    data = content if content is not None else path.read_bytes()
    return client.post("/api/v1/imports", headers=headers, data={"academic_year": year},
                       files={"file": (name or path.name, data)})


def rows_by_roll(client, headers, job_id) -> dict:
    r = client.get(f"/api/v1/imports/{job_id}?page_size=200", headers=headers)
    assert r.status_code == 200, r.text
    return {row["data"]["institution_student_id"]: row for row in r.json()["rows"]}
