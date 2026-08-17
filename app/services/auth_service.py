"""Authentication business logic.

Registration, credential verification, session helpers and a lightweight
in-memory login rate limiter.  Passwords are hashed with Werkzeug and are
never stored or logged in plaintext.
"""

from __future__ import annotations

import logging
import time

from flask import session
from sqlalchemy import or_

from ..extensions import db
from ..models import DEFAULT_CATEGORIES, Category, TransactionType, User

logger = logging.getLogger(__name__)


def seed_default_categories(user: User) -> None:
    """Create the built-in income/expense categories for a new user."""
    for type_name, names in DEFAULT_CATEGORIES.items():
        txn_type = TransactionType(type_name)
        for name in names:
            db.session.add(
                Category(
                    user_id=user.id,
                    name=name,
                    type=txn_type,
                    is_system=True,
                )
            )


def register_user(username: str, email: str, password: str) -> User:
    """Create and log in a new user, seeding default categories.

    Raises:
        ValueError: if the username or email is already taken.
    """
    username = username.strip()
    email = email.strip().lower()

    if User.query.filter(or_(User.username == username, User.email == email)).first():
        raise ValueError("That username or email is already registered.")

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()  # assign user.id so categories can reference it
    seed_default_categories(user)
    db.session.commit()
    logger.info("user registered: username=%s user_id=%s", username, user.id)
    return user


def authenticate(identifier: str, password: str) -> User | None:
    """Verify credentials; accepts a username or an email."""
    identifier = identifier.strip().lower()
    user = User.query.filter(
        or_(User.username == identifier, User.email == identifier)
    ).first()
    if user is None or not user.check_password(password):
        return None
    return user


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def log_in(user: User) -> None:
    """Establish an authenticated session for ``user``."""
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    logger.info("login success: username=%s user_id=%s", user.username, user.id)


def log_out() -> None:
    """Destroy the current session."""
    session.clear()


# ---------------------------------------------------------------------------
# Rate limiting (in-memory; fine for a single-process deployment)
# ---------------------------------------------------------------------------

#: identifier -> [timestamps of failed attempts]
_attempts: dict[str, list[float]] = {}


def _rate_limit_key(identifier: str, ip: str) -> str:
    return f"{ip}|{identifier.strip().lower()}"


def _rate_limit_enabled() -> bool:
    from flask import current_app

    return current_app.config.get("LOGIN_MAX_ATTEMPTS", 5) > 0


def is_locked_out(identifier: str, ip: str) -> bool:
    """True when the identifier/IP has exceeded the failed-attempt limit."""
    if not _rate_limit_enabled():
        return False
    from flask import current_app

    window = current_app.config.get("LOGIN_LOCKOUT_SECONDS", 600)
    key = _rate_limit_key(identifier, ip)
    now = time.monotonic()
    recent = [t for t in _attempts.get(key, []) if now - t < window]
    _attempts[key] = recent
    return len(recent) >= current_app.config.get("LOGIN_MAX_ATTEMPTS", 5)


def record_failed_attempt(identifier: str, ip: str) -> None:
    if not _rate_limit_enabled():
        return
    from flask import current_app

    window = current_app.config.get("LOGIN_LOCKOUT_SECONDS", 600)
    key = _rate_limit_key(identifier, ip)
    now = time.monotonic()
    _attempts.setdefault(key, []).append(now)
    _attempts[key] = [t for t in _attempts[key] if now - t < window]


def clear_attempts(identifier: str, ip: str) -> None:
    _attempts.pop(_rate_limit_key(identifier, ip), None)
