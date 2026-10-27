"""Runtime configuration. Secrets are read from the environment or generated into var/."""

from __future__ import annotations

import os
import secrets
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


ON_VERCEL = bool(os.environ.get("VERCEL"))


def _var_dir() -> Path:
    default = Path("/tmp/apaar-var") if ON_VERCEL else REPO_ROOT / "var"  # serverless file system is read-only
    path = Path(os.environ.get("APAAR_VAR_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secret_file(name: str, env: str, nbytes: int = 32) -> str:
    """Return a secret from env, else from var/<name>, generating it (mode 0600) on first use."""
    value = os.environ.get(env)
    if value:
        return value
    path = _var_dir() / name
    if not path.exists():
        path.write_text(secrets.token_hex(nbytes))
        os.chmod(path, 0o600)
    return path.read_text().strip()


def _database_url(var_dir: Path) -> str:
    """DATABASE_URL, else a Neon/Vercel-integration variable (e.g. <prefix>_DATABASE_URL), else local SQLite."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        for key in sorted(os.environ):
            if key.endswith("_DATABASE_URL") or key == "POSTGRES_URL":
                url = os.environ[key]
                break
    if not url:
        return f"sqlite:///{var_dir / 'apaar.db'}"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings:
    def __init__(self) -> None:
        self.var_dir = _var_dir()
        self.database_url = _database_url(self.var_dir)
        self.token_minutes = int(os.environ.get("TOKEN_MINUTES", "120"))
        vercel_host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
        default_base = f"https://{vercel_host}" if vercel_host else "http://localhost:8000"
        self.public_base_url = os.environ.get("PUBLIC_BASE_URL", default_base).rstrip("/")
        self.issuer_id = os.environ.get("ISSUER_ID", f"{self.public_base_url}/issuer/aicte-register-prototype")
        self.login_rate_per_minute = int(os.environ.get("LOGIN_RATE_PER_MINUTE", "30"))
        self.verify_rate_per_minute = int(os.environ.get("VERIFY_RATE_PER_MINUTE", "60"))
        self.verifier_requests_per_hour = int(os.environ.get("VERIFIER_REQUESTS_PER_HOUR", "30"))
        self.lockout_threshold = 5
        self.lockout_minutes = int(os.environ.get("LOCKOUT_MINUTES", "15"))
        self.max_upload_bytes = 2 * 1024 * 1024
        self.max_upload_rows = 5000
        self.current_year = os.environ.get("CURRENT_ACADEMIC_YEAR", "2026-27")
        self.submission_deadline = os.environ.get("SUBMISSION_DEADLINE", "2026-11-30")
        self.adapter_mode = os.environ.get("APAAR_ADAPTER_MODE", "simulated")  # simulated | unavailable
        self.app_env = os.environ.get("APP_ENV", "development").lower()
        self.live_events = os.environ.get("LIVE_EVENTS", "0" if ON_VERCEL else "1") == "1"
        self.frontend_dist = Path(os.environ.get("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist"))


    def _secret(self, name: str, env: str) -> str:
        if os.environ.get(env):
            return os.environ[env]
        if self.database_url.startswith("postgresql"):
            from .secret_store import db_secret

            return db_secret(name, lambda: secrets.token_hex(32))
        return _secret_file(name, env)

    @property
    def jwt_secret(self) -> str:
        return self._secret("jwt_secret", "JWT_SECRET")

    @property
    def apaar_hmac_key(self) -> str:
        return self._secret("apaar_hmac_key", "APAAR_HMAC_KEY")


settings = Settings()


def today() -> date:
    """Today's date; APAAR_TODAY overrides it so tests and demos are reproducible."""
    override = os.environ.get("APAAR_TODAY")
    return date.fromisoformat(override) if override else date.today()
