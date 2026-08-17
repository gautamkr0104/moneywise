"""Transaction tests: CRUD, validation, filtering, sorting, pagination (Phase 5)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Account, Category, Transaction, TransactionType, User
from app.services import auth_service, transaction_service
from conftest import make_account, make_transaction


def _expense_ids(auth_client):
    """Create Alice's account + Food category; return their ids."""
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user, name="Bank")
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        return account.id, food.id


def _post_transaction(client, account_id, food_id=None, **overrides):
    data = {
        "type": "expense",
        "amount": "100.00",
        "account": str(account_id),
        "to_account": "",
        "category": str(food_id) if food_id else "",
        "description": "Groceries",
        "date": "2026-08-10",
        "notes": "",
    }
    data.update(overrides)
    return client.post("/transactions/new", data=data)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_expense(auth_client):
    account_id, food_id = _expense_ids(auth_client)
    response = _post_transaction(auth_client, account_id, food_id)
    assert response.status_code == 302

    with auth_client.application.app_context():
        txn = Transaction.query.filter_by(description="Groceries").first()
        assert txn is not None
        assert txn.amount == Decimal("100.00")
        assert txn.type is TransactionType.EXPENSE


def test_create_transfer(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        source = make_account(user, name="Bank")
        target = make_account(user, name="Savings")
        source_id, target_id = source.id, target.id

    response = _post_transaction(
        auth_client, source_id,
        type="transfer",
        amount="250.00",
        to_account=str(target_id),
        description="Move money",
    )
    assert response.status_code == 302
    with auth_client.application.app_context():
        txn = Transaction.query.filter_by(description="Move money").first()
        assert txn.to_account_id == target_id
        assert txn.category_id is None
        assert db.session.get(Account, source_id).current_balance == Decimal("-250.00")
        assert db.session.get(Account, target_id).current_balance == Decimal("250.00")


def test_transfer_requires_different_accounts(auth_client):
    account_id, _ = _expense_ids(auth_client)
    response = _post_transaction(
        auth_client, account_id,
        type="transfer",
        to_account=str(account_id),
        description="Oops",
    )
    assert response.status_code == 200  # form re-rendered
    assert b"different" in response.data
    with auth_client.application.app_context():
        assert Transaction.query.count() == 0


def test_income_requires_category(auth_client):
    account_id, _ = _expense_ids(auth_client)
    response = _post_transaction(
        auth_client, account_id,
        type="income",
        description="Salary",
    )
    assert response.status_code == 200
    assert b"category" in response.data


def test_negative_amount_rejected(auth_client):
    account_id, food_id = _expense_ids(auth_client)
    response = _post_transaction(auth_client, account_id, food_id, amount="-5.00")
    assert response.status_code == 200
    assert b"greater than zero" in response.data


def test_edit_transaction(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        txn = make_transaction(user, account, amount="10.00", category=food)
        txn_id, account_id, food_id = txn.id, account.id, food.id

    response = auth_client.post(
        f"/transactions/{txn_id}/edit",
        data={
            "type": "expense",
            "amount": "20.00",
            "account": str(account_id),
            "to_account": "",
            "category": str(food_id),
            "description": "Renamed",
            "date": "2026-08-11",
            "notes": "updated",
        },
    )
    assert response.status_code == 302
    with auth_client.application.app_context():
        updated = db.session.get(Transaction, txn_id)
        assert updated.amount == Decimal("20.00")
        assert updated.description == "Renamed"


def test_delete_transaction(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        txn = make_transaction(user, account, category=food)
        txn_id = txn.id

    response = auth_client.post(f"/transactions/{txn_id}/delete")
    assert response.status_code == 302
    with auth_client.application.app_context():
        assert db.session.get(Transaction, txn_id) is None


def test_detail_and_404(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        txn = make_transaction(user, account, description="Visible", category=food)
        txn_id = txn.id

    assert b"Visible" in auth_client.get(f"/transactions/{txn_id}").data
    assert auth_client.get("/transactions/9999").status_code == 404


def test_cross_user_transaction_404(client):
    with client.application.app_context():
        alice = auth_service.register_user("alice", "alice@example.com", "password123")
        account = make_account(alice)
        food = Category.query.filter_by(user_id=alice.id, name="Food").first()
        txn = make_transaction(alice, account, category=food)
        txn_id = txn.id
        auth_service.register_user("bob", "bob@example.com", "password123")

    client.post("/auth/login", data={"identifier": "bob", "password": "password123"})
    assert client.get(f"/transactions/{txn_id}").status_code == 404


# ---------------------------------------------------------------------------
# Service validation
# ---------------------------------------------------------------------------


def test_service_rejects_other_users_account(app, user):
    with app.app_context():
        bob = auth_service.register_user("bob", "bob@example.com", "password123")
        bob_account = make_account(bob)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()

        with pytest.raises(transaction_service.TransactionValidationError):
            transaction_service.create_transaction(
                user,
                amount="10.00",
                txn_type=TransactionType.EXPENSE,
                account_id=bob_account.id,
                category_id=food.id,
                description="x",
                txn_date=date(2026, 8, 1),
            )


# ---------------------------------------------------------------------------
# Filters / sort / pagination
# ---------------------------------------------------------------------------


def _filtered(user, **filters):
    """Run a query_transactions select in the caller's active app context."""
    stmt = transaction_service.query_transactions(user, **filters)
    return db.session.scalars(stmt).all()


def test_filter_by_type(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, amount="10.00", txn_type="expense", category=food)
        make_transaction(user, account, amount="20.00", txn_type="income", category=food)

        result = _filtered(user, txn_type="expense")
        assert len(result) == 1
        assert result[0].type is TransactionType.EXPENSE


def test_filter_by_date_range(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, txn_date=date(2026, 8, 1), category=food)
        make_transaction(user, account, txn_date=date(2026, 9, 1), category=food)

        result = _filtered(user, date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
        assert len(result) == 1
        assert result[0].date == date(2026, 8, 1)


def test_filter_by_amount_range(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, amount="50.00", category=food)
        make_transaction(user, account, amount="150.00", category=food)

        result = _filtered(user, min_amount="100", max_amount="200")
        assert len(result) == 1
        assert result[0].amount == Decimal("150.00")


def test_filter_by_search(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, description="Coffee with friends", category=food)
        make_transaction(user, account, description="Rent", category=food)

        result = _filtered(user, q="coffee")
        assert len(result) == 1
        assert "Coffee" in result[0].description


def test_sort_by_amount_desc(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, amount="10.00", category=food)
        make_transaction(user, account, amount="99.00", category=food)

        result = _filtered(user, sort="amount", order="desc")
        assert [t.amount for t in result] == [Decimal("99.00"), Decimal("10.00")]


def test_web_list_renders_filters(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user, name="Wallet")
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, description="Snacks", category=food)

    response = auth_client.get("/transactions/?q=snacks&type=expense")
    assert response.status_code == 200
    assert b"Snacks" in response.data


def test_pagination(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        for i in range(5):
            make_transaction(user, account, amount=f"{i + 1}.00", category=food)

        page1 = transaction_service.paginate_transactions(user, page=1, per_page=2)
        assert len(page1.items) == 2
        assert page1.total == 5
        assert page1.pages == 3
        assert page1.has_next is True
        page3 = transaction_service.paginate_transactions(user, page=3, per_page=2)
        assert len(page3.items) == 1
