"""Recurring transaction tests (Phase 10)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import (
    Category,
    RecurringFrequency,
    RecurringTransaction,
    Transaction,
    User,
)
from app.services import recurring_service
from conftest import make_account


def _make_recurring(user, *, next_due, frequency=RecurringFrequency.MONTHLY,
                    amount="499.00", description="Netflix", is_active=True):
    account = make_account(user, name="Bank")
    category = Category.query.filter_by(user_id=user.id, name="Entertainment").first()
    return recurring_service.create_recurring(
        user,
        description=description,
        amount=amount,
        txn_type="expense",
        account_id=account.id,
        category_id=category.id,
        frequency=frequency,
        next_due_date=next_due,
        is_active=is_active,
    )


def test_create_recurring(app, user):
    with app.app_context():
        recurring = _make_recurring(user, next_due=date(2026, 9, 1))
        assert recurring.is_active is True
        assert recurring.user_id == user.id


def test_due_recurring_filters_by_date(app, user):
    with app.app_context():
        recurring = _make_recurring(user, next_due=date(2026, 8, 1))
        due = recurring_service.due_recurring(user, date(2026, 8, 15))
        assert recurring in due
        assert recurring_service.due_recurring(user, date(2026, 7, 31)) == []


def test_inactive_recurring_never_due(app, user):
    with app.app_context():
        _make_recurring(user, next_due=date(2026, 1, 1), is_active=False)
        assert recurring_service.due_recurring(user, date.today()) == []


def test_process_due_creates_transactions_and_advances(app, user):
    with app.app_context():
        recurring = _make_recurring(user, next_due=date(2026, 8, 1))

        result = recurring_service.process_due(user, as_of=date(2026, 8, 31))
        assert result == {"created": 1, "processed": 1}

        txns = Transaction.query.filter_by(user_id=user.id).all()
        assert len(txns) == 1
        assert txns[0].date == date(2026, 8, 1)
        assert txns[0].amount == Decimal("499.00")
        assert txns[0].description == "Netflix"

        refreshed = recurring_service.get_user_recurring(user, recurring.id)
        assert refreshed.next_due_date == date(2026, 9, 1)


def test_process_catches_up_multiple_periods(app, user):
    with app.app_context():
        _make_recurring(user, next_due=date(2026, 1, 1))
        result = recurring_service.process_due(user, as_of=date(2026, 8, 31))
        assert result["created"] == 8  # Jan..Aug
        txns = Transaction.query.filter_by(user_id=user.id).all()
        assert len(txns) == 8
        assert sorted({t.date.month for t in txns}) == list(range(1, 9))


def test_process_is_idempotent(app, user):
    with app.app_context():
        _make_recurring(user, next_due=date(2026, 8, 1))
        recurring_service.process_due(user, as_of=date(2026, 8, 31))
        result = recurring_service.process_due(user, as_of=date(2026, 8, 31))
        assert result["created"] == 0
        assert Transaction.query.count() == 1


def test_weekly_and_yearly_frequencies(app, user):
    with app.app_context():
        _make_recurring(user, next_due=date(2026, 8, 1),
                        frequency=RecurringFrequency.WEEKLY, description="Gym")
        recurring_service.process_due(user, as_of=date(2026, 8, 22))
        assert Transaction.query.filter_by(description="Gym").count() == 4  # 1, 8, 15, 22

        _make_recurring(user, next_due=date(2026, 3, 1),
                        frequency=RecurringFrequency.YEARLY, description="Insurance")
        recurring_service.process_due(user, as_of=date(2027, 3, 1))
        assert Transaction.query.filter_by(description="Insurance").count() == 2


def test_web_process_route(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        _make_recurring(user, next_due=date(2026, 8, 1))

    response = auth_client.post("/recurring/process")
    assert response.status_code == 302
    with auth_client.application.app_context():
        assert Transaction.query.count() == 1


def test_web_list_shows_items(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        _make_recurring(user, next_due=date(2026, 9, 1))

    response = auth_client.get("/recurring/")
    assert response.status_code == 200
    assert b"Netflix" in response.data


def test_deactivating_recurring_prevents_future_processing(app, user):
    with app.app_context():
        recurring = _make_recurring(user, next_due=date(2026, 8, 1))
        recurring_service.update_recurring(recurring, is_active=False)
        result = recurring_service.process_due(user, as_of=date(2026, 8, 31))
        assert result["created"] == 0
        assert Transaction.query.count() == 0
