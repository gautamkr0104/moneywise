"""Account tests: CRUD, archiving, ownership, balances (Phase 4)."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import Account, Category, User
from conftest import make_account, make_transaction


def _create_via_form(client, name="Cash", account_type="cash", starting="0.00"):
    return client.post(
        "/accounts/new",
        data={
            "name": name,
            "type": account_type,
            "starting_balance": starting,
            "currency": "INR",
            "is_archived": "n",
        },
    )


def test_create_account(auth_client):
    response = _create_via_form(auth_client, name="Savings", starting="5000.50")
    assert response.status_code == 302
    with auth_client.application.app_context():
        account = Account.query.filter_by(name="Savings").first()
        assert account is not None
        assert account.starting_balance == Decimal("5000.50")
        assert account.user.username == "alice"


def test_account_list_shows_balance(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user, name="Bank", starting_balance="100.00")
        category = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, amount="50.00", category=category)

    response = auth_client.get("/accounts/")
    assert response.status_code == 200
    assert b"Bank" in response.data
    assert "150.00" in response.get_data(as_text=True)


def test_account_detail_shows_recent_transactions(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user)
        category = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, description="Groceries", category=category)

    response = auth_client.get(f"/accounts/{account_id(auth_client)}")
    assert response.status_code == 200
    assert b"Groceries" in response.data


def account_id(client) -> int:
    with client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        return user.accounts[0].id


def test_edit_account(auth_client):
    _create_via_form(auth_client)
    account_id_ = account_id(auth_client)
    response = auth_client.post(
        f"/accounts/{account_id_}/edit",
        data={
            "name": "Renamed",
            "type": "savings",
            "starting_balance": "10.00",
            "currency": "USD",
            "is_archived": "n",
        },
    )
    assert response.status_code == 302
    with auth_client.application.app_context():
        account = db.session.get(Account, account_id_)
        assert account.name == "Renamed"
        assert account.currency == "USD"
        assert account.starting_balance == Decimal("10.00")


def test_archive_and_restore_account(auth_client):
    _create_via_form(auth_client)
    account_id_ = account_id(auth_client)
    response = auth_client.post(f"/accounts/{account_id_}/archive")
    assert response.status_code == 302
    with auth_client.application.app_context():
        assert db.session.get(Account, account_id_).is_archived is True
    auth_client.post(f"/accounts/{account_id_}/archive")
    with auth_client.application.app_context():
        assert db.session.get(Account, account_id_).is_archived is False


def test_delete_account(auth_client):
    _create_via_form(auth_client)
    account_id_ = account_id(auth_client)
    auth_client.post(f"/accounts/{account_id_}/delete")
    with auth_client.application.app_context():
        assert db.session.get(Account, account_id_) is None


def test_unknown_account_404(auth_client):
    assert auth_client.get("/accounts/9999").status_code == 404


def test_cannot_access_another_users_account(app, client):
    register_alice(client)
    client.post("/auth/logout")
    register_bob(client)

    with app.app_context():
        alice = User.query.filter_by(username="alice").first()
        alice_account = make_account(alice)
        alice_account_id = alice_account.id

    response = client.get(f"/accounts/{alice_account_id}")
    assert response.status_code == 404


def register_alice(client):
    client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )


def register_bob(client):
    client.post(
        "/auth/register",
        data={
            "username": "bob",
            "email": "bob@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
