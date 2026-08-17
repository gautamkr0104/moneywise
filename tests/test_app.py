"""Smoke tests for the application factory and configuration (Phase 1)."""

from __future__ import annotations

import pytest
from app import create_app
from app.config import CONFIG_MAP
from app.extensions import db


def test_app_creation(app):
    """The factory builds a working Flask application."""
    assert app is not None
    assert app.name == "moneywise"


def test_health_endpoint(client):
    """The health probe confirms the app boots and responds."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "app": "moneywise"}


def test_extensions_initialized(app):
    """SQLAlchemy, Migrate and CSRF are bound to the application."""
    with app.app_context():
        # The default (bind-key ``None``) engine is created for the app.
        assert db.engines[None] is not None
    # Flask-Migrate and Flask-WTF register themselves on app.extensions.
    assert app.extensions["migrate"] is not None
    assert app.extensions["csrf"] is not None


def test_testing_config_loaded(app):
    """The testing config is applied when requested."""
    assert app.config["TESTING"] is True
    assert app.config["SECRET_KEY"] == "test-secret-key"
    assert app.config["WTF_CSRF_ENABLED"] is False


def test_unknown_config_raises():
    """An invalid config name is rejected loudly."""
    with pytest.raises(ValueError, match="Unknown config"):
        create_app("does-not-exist")


def test_known_configs():
    """Every supported FLASK_ENV value maps to a config class."""
    assert set(CONFIG_MAP) == {"development", "testing", "production"}


def test_development_defaults():
    """Development config turns on debugging and keeps cookies HTTP-only."""
    config = CONFIG_MAP["development"]
    assert config.DEBUG is True
    assert config.SESSION_COOKIE_HTTPONLY is True


def test_production_requires_secret(monkeypatch):
    """Production refuses to start with the insecure default secret."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        CONFIG_MAP["production"].validate()
