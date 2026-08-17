"""Shared pytest fixtures.

The ``app`` fixture builds a fresh application per test using the testing
configuration (in-memory SQLite) and creates/drops all tables around each
test so tests are fully isolated.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db

TEST_PASSWORD = "password123"


@pytest.fixture()
def app():
    """A configured Flask application backed by an in-memory database."""
    application = create_app("testing")

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """A test client bound to the per-test application."""
    return app.test_client()


@pytest.fixture()
def user(app):
    """A registered user (Alice) with default categories seeded.

    Depends on ``app`` so the user lives in the same in-memory database the
    test client uses.
    """
    from app.services import auth_service

    with app.app_context():
        return auth_service.register_user("alice", "alice@example.com", TEST_PASSWORD)


def register(client, username="alice", email="alice@example.com", password=TEST_PASSWORD):
    """POST the registration form and return the response."""
    return client.post(
        "/auth/register",
        data={
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )


@pytest.fixture()
def auth_client(app):
    """A test client that is already registered and logged in (Alice)."""
    client = app.test_client()
    register(client)
    return client


def make_account(
    user,
    name="Bank",
    account_type="bank",
    starting_balance="0.00",
    currency="INR",
):
    """Create an account for ``user`` directly in the database."""
    from app.models import Account
    from decimal import Decimal

    account = Account(
        user_id=user.id,
        name=name,
        type=account_type,
        starting_balance=Decimal(starting_balance),
        currency=currency,
    )
    db.session.add(account)
    db.session.commit()
    return account


def make_transaction(
    user,
    account,
    amount="100.00",
    txn_type="expense",
    description="Test",
    category=None,
    txn_date=None,
    to_account=None,
    notes=None,
):
    """Create a transaction for ``user`` directly in the database."""
    from datetime import date

    from app.models import Transaction

    txn = Transaction(
        user_id=user.id,
        account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        category_id=category.id if category else None,
        amount=amount,
        type=txn_type,
        description=description,
        date=txn_date or date(2026, 8, 15),
        notes=notes,
    )
    db.session.add(txn)
    db.session.commit()
    return txn
