"""MoneyWise application package.

Exposes the :func:`create_app` application factory.  Everything is wired
here: configuration, logging, extensions, models, blueprints, template
filters, error handlers and security headers.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session
from flask.json.provider import DefaultJSONProvider

from .config import CONFIG_MAP, ProductionConfig
from .extensions import csrf, db, migrate, register_sqlite_pragmas
from .utils import format_date, format_money

__all__ = ["create_app"]


class MoneyJSONProvider(DefaultJSONProvider):
    """Serialize money and dates for JSON responses (Decimal, date, datetime)."""

    @staticmethod
    def default(o):  # noqa: ANN001
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        return DefaultJSONProvider.default(o)


def _configure_logging(app: Flask) -> None:
    """Attach console (and, in production, rotating file) log handlers.

    Format and level follow the environment; secrets are never logged.
    """
    level = logging.DEBUG if app.debug else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )

    # Console handler.
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    app.logger.handlers.clear()
    app.logger.addHandler(console)
    app.logger.setLevel(level)

    # Rotating file handler for non-testing environments.
    if not app.testing:
        log_dir = Path(app.instance_path) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "moneywise.log", maxBytes=1_000_000, backupCount=3
        )
        file_handler.setFormatter(formatter)
        app.logger.addHandler(file_handler)


def _register_blueprints(app: Flask) -> None:
    from .routes.accounts import accounts_bp
    from .routes.api import api_bp
    from .routes.auth import auth_bp
    from .routes.budgets import budgets_bp
    from .routes.categories import categories_bp
    from .routes.dashboard import dashboard_bp
    from .routes.recurring import recurring_bp
    from .routes.reports import reports_bp
    from .routes.settings import settings_bp
    from .routes.transactions import transactions_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp, url_prefix="/accounts")
    app.register_blueprint(transactions_bp, url_prefix="/transactions")
    app.register_blueprint(budgets_bp, url_prefix="/budgets")
    app.register_blueprint(recurring_bp, url_prefix="/recurring")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(categories_bp, url_prefix="/categories")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(api_bp, url_prefix="/api")


def _register_template_helpers(app: Flask) -> None:
    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["datefmt"] = format_date

    @app.context_processor
    def inject_globals():
        from .utils import CURRENCY_SYMBOLS

        user = g.get("current_user")
        symbol = CURRENCY_SYMBOLS.get(user.currency, "") if user else "₹"
        return {"currency_symbol": symbol}


def _is_api_request() -> bool:
    return request.path.startswith("/api/")


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):
        if _is_api_request():
            return jsonify({"error": "not_found", "message": "Resource not found."}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(_error):
        if _is_api_request():
            return jsonify({"error": "forbidden", "message": "Access denied."}), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(400)
    def bad_request(_error):
        if _is_api_request():
            return jsonify({"error": "bad_request", "message": "Bad request."}), 400
        return render_template("errors/400.html"), 400

    @app.errorhandler(500)
    def internal_error(_error):
        # The exception is already logged by Flask; never leak stack traces.
        if _is_api_request():
            return jsonify({"error": "internal_error", "message": "Internal server error."}), 500
        return render_template("errors/500.html"), 500


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


def _register_cli(app: Flask) -> None:
    """``flask recurring process`` - run due recurring transactions."""

    import click

    @app.cli.command("recurring-process")
    def recurring_process_command():
        """Create transactions for due recurring templates."""
        from .services import recurring_service
        from .models import User

        with app.app_context():
            for user in User.query.all():
                result = recurring_service.process_due(user)
                click.echo(f"user {user.username}: processed={result['processed']} created={result['created']}")


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application (application factory).

    Args:
        config_name: One of ``development``, ``testing``, ``production``.
            Defaults to the ``FLASK_ENV`` environment variable, or
            ``development`` when unset.
    """
    app = Flask(__name__, instance_relative_config=True)
    # Keep the package folder (``app``) as the root path for templates/static,
    # but expose a friendly application name.
    app.name = "moneywise"

    # --- Configuration -----------------------------------------------------
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    if config_name not in CONFIG_MAP:
        raise ValueError(
            f"Unknown config '{config_name}'. Choose from {sorted(CONFIG_MAP)}."
        )
    config_cls = CONFIG_MAP[config_name]
    app.config.from_object(config_cls)
    if config_cls is ProductionConfig:
        # Fail fast in production if the insecure default secret is used.
        config_cls.validate()

    # Ensure the instance folder exists (SQLite database + logs live here).
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    # --- Logging -----------------------------------------------------------
    _configure_logging(app)

    # --- JSON provider -----------------------------------------------------
    app.json = MoneyJSONProvider(app)

    # --- Extensions --------------------------------------------------------
    db.init_app(app)
    # ``render_as_batch`` lets Alembic run ALTER TABLE migrations on SQLite.
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    register_sqlite_pragmas(app)

    # --- Models ------------------------------------------------------------
    # Importing the models package registers every table on the db metadata
    # so Flask-Migrate can autogenerate migrations and tests can create_all().
    from . import models  # noqa: F401
    from .models import User

    # --- Auth state --------------------------------------------------------
    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        g.current_user = db.session.get(User, user_id) if user_id else None

    # --- Blueprints --------------------------------------------------------
    _register_blueprints(app)

    # --- Template helpers --------------------------------------------------
    _register_template_helpers(app)

    # --- Routes ------------------------------------------------------------
    @app.get("/health")
    def health() -> tuple[dict, int]:
        """Liveness probe used to verify the application boots correctly."""
        return jsonify({"status": "ok", "app": app.name}), 200

    # --- Error handling + security -----------------------------------------
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_cli(app)

    app.logger.info("MoneyWise application created (config=%s)", config_name)
    return app
