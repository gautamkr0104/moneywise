"""Application configuration.

Configuration is environment-driven.  Values are read from environment
variables (optionally loaded from a local ``.env`` file) and grouped into
per-environment classes:

* :class:`DevelopmentConfig` - local development (SQLite, debug on)
* :class:`TestingConfig`     - pytest runs (in-memory SQLite, CSRF off)
* :class:`ProductionConfig`  - hardened defaults (secure cookies, no debug)

The active class is selected in :func:`app.create_app` via the ``FLASK_ENV``
environment variable (see ``.env.example``).  The same settings work against
PostgreSQL by pointing ``DATABASE_URL`` at a PostgreSQL DSN; no code changes
are required.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

# Project root: the directory containing this file's parent (app/ -> root).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the project root if present (development convenience).
load_dotenv(BASE_DIR / ".env")


class BaseConfig:
    """Settings shared by every environment."""

    # Core Flask -----------------------------------------------------------
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-only-insecure-secret")

    # Database -------------------------------------------------------------
    # Default is an instance-local SQLite file; override with DATABASE_URL.
    #   sqlite:      sqlite:///moneywise.db
    #   postgresql:  postgresql+psycopg://user:pass@host:5432/moneywise
    SQLALCHEMY_DATABASE_URI: str = os.environ.get("DATABASE_URL", "sqlite:///moneywise.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Session / security ---------------------------------------------------
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_SECURE: bool = False  # turned on for production
    SESSION_PERMANENT: bool = True
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(days=7)

    # Login rate limiting (in-memory) --------------------------------------
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 600

    # CSRF (Flask-WTF) -----------------------------------------------------
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int | None = None  # tokens do not expire during a session

    # Uploads (CSV import) -------------------------------------------------
    MAX_CONTENT_LENGTH: int = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))

    # Pydantic -------------------------------------------------------------
    PYDANTIC_STRICT: bool = False


class DevelopmentConfig(BaseConfig):
    """Local development: verbose logging, debug on, relaxed cookie policy."""

    DEBUG: bool = True
    TESTING: bool = False
    SESSION_COOKIE_SECURE: bool = False


class TestingConfig(BaseConfig):
    """pytest configuration: isolated in-memory database, CSRF disabled."""

    TESTING: bool = True
    DEBUG: bool = False
    SECRET_KEY: str = "test-secret-key"
    SQLALCHEMY_DATABASE_URI: str = "sqlite://"
    # A single shared in-memory connection is required so every request sees
    # the same database.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }
    WTF_CSRF_ENABLED: bool = False
    MAX_CONTENT_LENGTH: int = 1 * 1024 * 1024
    LOGIN_MAX_ATTEMPTS: int = 0  # rate limiter disabled in tests


class ProductionConfig(BaseConfig):
    """Production hardening: no debug, secure cookies, strict session flags."""

    DEBUG: bool = False
    TESTING: bool = False
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"

    # In production the SECRET_KEY must come from the environment; fail fast
    # if the insecure default would be used.
    @classmethod
    def validate(cls) -> None:
        if os.environ.get("SECRET_KEY", "").strip() in ("", "dev-only-insecure-secret"):
            raise RuntimeError(
                "ProductionConfig requires SECRET_KEY to be set in the environment."
            )


#: Maps ``FLASK_ENV`` values to configuration classes.
CONFIG_MAP: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
