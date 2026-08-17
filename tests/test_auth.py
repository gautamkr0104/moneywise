"""Authentication tests: registration, login, logout, protection (Phase 3)."""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models import Category, TransactionType, User
from app.services import auth_service, transaction_service
from conftest import TEST_PASSWORD, register


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_creates_user_and_logs_in(client):
    response = register(client)
    assert response.status_code == 302
    assert "/" in response.headers["Location"]  # redirected to the dashboard

    with client.session_transaction() as sess:
        assert "user_id" in sess

    with client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        assert user is not None
        assert user.email == "alice@example.com"
        assert user.password_hash != "password123"
        # Werkzeug's default scheme (scrypt on recent versions, pbkdf2 on older).
        assert user.password_hash.split("$")[0] in ("scrypt", "pbkdf2")


def test_register_seeds_default_categories(client):
    register(client)
    with client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        categories = Category.query.filter_by(user_id=user.id).all()
        names = {c.name for c in categories}
        assert {"Salary", "Food", "Rent", "Utilities"} <= names
        assert all(c.is_system for c in categories)


def test_register_rejects_duplicate_username(client):
    register(client)
    client.post("/auth/logout")
    response = register(client, email="other@example.com")
    assert response.status_code == 200  # re-renders the form
    assert b"already registered" in response.data


def test_register_rejects_duplicate_email(client):
    register(client)
    client.post("/auth/logout")
    response = register(client, username="bob")
    assert response.status_code == 200
    assert b"already registered" in response.data


def test_register_validates_password_strength(client):
    response = register(client, password="short")
    assert b"at least 8 characters" in response.data
    assert User.query.count() == 0


def test_register_requires_matching_confirmation(client):
    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": TEST_PASSWORD,
            "confirm_password": "different",
        },
    )
    assert b"Passwords must match" in response.data


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------


def test_login_with_username(client):
    register(client)
    client.post("/auth/logout")

    response = client.post(
        "/auth/login",
        data={"identifier": "alice", "password": TEST_PASSWORD},
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" in sess


def test_login_with_email(client):
    register(client)
    client.post("/auth/logout")
    response = client.post(
        "/auth/login",
        data={"identifier": "alice@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 302


def test_login_rejects_wrong_password(client):
    register(client)
    client.post("/auth/logout")
    response = client.post(
        "/auth/login",
        data={"identifier": "alice", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert b"Invalid" in response.data


def test_login_rejects_unknown_user(client):
    response = client.post(
        "/auth/login",
        data={"identifier": "ghost", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401


def test_logout_clears_session(auth_client):
    with auth_client.session_transaction() as sess:
        assert "user_id" in sess
    response = auth_client.post("/auth/logout")
    assert response.status_code == 302
    with auth_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_authenticate_service(app, user):
    with app.app_context():
        authenticated = auth_service.authenticate("alice", TEST_PASSWORD)
        assert authenticated is not None
        assert authenticated.id == user.id
        assert auth_service.authenticate("alice@example.com", TEST_PASSWORD).id == user.id
        assert auth_service.authenticate("alice", "nope") is None


# ---------------------------------------------------------------------------
# Protected routes / authorization
# ---------------------------------------------------------------------------


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_protected_pages_redirect_to_login(client):
    for path in [
        "/accounts/",
        "/transactions/",
        "/budgets/",
        "/reports/",
        "/recurring/",
        "/categories/",
        "/settings/",
    ]:
        response = client.get(path)
        assert response.status_code == 302, path
        assert "/auth/login" in response.headers["Location"], path


def test_users_cannot_access_each_others_data(app, client):
    """Registration seeds data; a second user must never see the first's."""
    register(client)  # alice
    client.get("/auth/logout")
    register(client, username="bob", email="bob@example.com")  # bob

    with app.app_context():
        alice = User.query.filter_by(username="alice").first()
        bob = User.query.filter_by(username="bob").first()
        alice_account_ids = {a.id for a in alice.accounts}
        bob_account_ids = {a.id for a in bob.accounts}
        assert alice_account_ids.isdisjoint(bob_account_ids)
        # Alice's categories are not visible to Bob.
        alice_names = {c.name for c in alice.categories}
        bob_names = {c.name for c in bob.categories}
        assert alice_names == bob_names  # both seeded the same defaults


def test_service_rejects_cross_user_transaction_target(app):
    from app.models import Account, Category

    with app.app_context():
        alice = auth_service.register_user("alice", "alice@example.com", TEST_PASSWORD)
        account = Account(user_id=alice.id, name="A")
        db.session.add(account)
        db.session.commit()

        bob = auth_service.register_user("bob", "bob@example.com", TEST_PASSWORD)
        bob_account = Account(user_id=bob.id, name="B")
        db.session.add(bob_account)
        db.session.commit()
        bob_category = Category.query.filter_by(user_id=bob.id, name="Food").first()

        # Alice cannot use Bob's account as her transfer destination.
        with pytest.raises(transaction_service.TransactionValidationError):
            transaction_service.create_transaction(
                alice,
                amount="10",
                txn_type=TransactionType.TRANSFER,
                account_id=account.id,
                to_account_id=bob_account.id,
                description="steal",
                txn_date=date(2026, 8, 1),
            )
        # Alice cannot use Bob's category.
        with pytest.raises(transaction_service.TransactionValidationError):
            transaction_service.create_transaction(
                alice,
                amount="10",
                txn_type=TransactionType.EXPENSE,
                account_id=account.id,
                category_id=bob_category.id,
                description="oops",
                txn_date=date(2026, 8, 1),
            )
