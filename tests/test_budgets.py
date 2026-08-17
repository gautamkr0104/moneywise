"""Budget tests: CRUD, progress, warnings, period rules (Phase 6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Budget, Category, User
from app.services import budget_service
from conftest import make_account, make_transaction


def _food_category_id(user) -> int:
    return Category.query.filter_by(user_id=user.id, name="Food").first().id


def _create_via_form(client, category_id, amount="5000.00", month="8", year="2026"):
    return client.post(
        "/budgets/new?year=2026&month=8",
        data={"month": month, "year": year, "category": str(category_id), "amount": amount},
    )


def test_create_budget(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        category_id = _food_category_id(user)

    response = _create_via_form(auth_client, category_id, amount="10000.00")
    assert response.status_code == 302
    with auth_client.application.app_context():
        budget = Budget.query.first()
        assert budget is not None
        assert budget.amount == Decimal("10000.00")
        assert budget.year == 2026 and budget.month == 8


def test_duplicate_budget_rejected(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        category_id = _food_category_id(user)

    _create_via_form(auth_client, category_id)
    response = _create_via_form(auth_client, category_id, amount="9999.00")
    assert response.status_code == 200
    assert b"already exists" in response.data


def test_budget_list_shows_progress(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        budget = Budget(user_id=user.id, category_id=food.id, year=2026, month=8,
                        amount=Decimal("10000.00"))
        db.session.add(budget)
        db.session.commit()
        make_transaction(user, account, amount="2500.00", category=food,
                         txn_date=date(2026, 8, 5))

    response = auth_client.get("/budgets/?year=2026&month=8")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Food" in body
    assert "2,500.00" in body  # spent
    assert "7,500.00" in body  # remaining


def test_budget_warning_levels(app, user):
    assert budget_service.warning_level(Decimal("30")) == "ok"
    assert budget_service.warning_level(Decimal("50")) == "warn50"
    assert budget_service.warning_level(Decimal("76")) == "warn75"
    assert budget_service.warning_level(Decimal("92")) == "warn90"
    assert budget_service.warning_level(Decimal("100")) == "exceeded"
    assert budget_service.warning_level(Decimal("140")) == "exceeded"


def test_budget_status(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        budget = Budget(user_id=user.id, category_id=food.id, year=2026, month=8,
                        amount=Decimal("1000.00"))
        db.session.add(budget)
        db.session.commit()
        make_transaction(user, account, amount="750.00", category=food,
                         txn_date=date(2026, 8, 3))

        status = budget_service.budget_status(budget)
        assert status["spent"] == Decimal("750.00")
        assert status["remaining"] == Decimal("250.00")
        assert status["percent_used"] == Decimal("75.000")
        assert status["level"] == "warn75"


def test_edit_and_delete_budget(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        budget = Budget(user_id=user.id, category_id=food.id, year=2026, month=8,
                        amount=Decimal("1000.00"))
        db.session.add(budget)
        db.session.commit()
        budget_id = budget.id
        food_id = food.id

    response = auth_client.post(
        f"/budgets/{budget_id}/edit",
        data={"month": "8", "year": "2026", "category": str(food_id), "amount": "2000.00"},
    )
    assert response.status_code == 302
    with auth_client.application.app_context():
        assert db.session.get(Budget, budget_id).amount == Decimal("2000.00")

    auth_client.post(f"/budgets/{budget_id}/delete")
    with auth_client.application.app_context():
        assert db.session.get(Budget, budget_id) is None


def test_over_budget_detection(app, user):
    with app.app_context():
        account = make_account(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        rent = Category.query.filter_by(user_id=user.id, name="Rent").first()
        for category, amount in ((food, "500.00"), (rent, "2000.00")):
            budget = Budget(user_id=user.id, category_id=category.id, year=2026, month=8,
                            amount=Decimal(amount))
            db.session.add(budget)
        db.session.commit()
        make_transaction(user, account, amount="600.00", category=food,
                         txn_date=date(2026, 8, 2))  # over Food's budget

        over = budget_service.over_budget_categories(user, 2026, 8)
        assert [b.category.name for b in over] == ["Food"]


def test_service_rejects_foreign_category(app):
    from app.services import auth_service

    with app.app_context():
        alice = auth_service.register_user("alice", "alice@example.com", "password123")
        bob = auth_service.register_user("bob", "bob@example.com", "password123")
        bob_food = Category.query.filter_by(user_id=bob.id, name="Food").first()

        with pytest.raises(budget_service.BudgetValidationError):
            budget_service.create_budget(
                alice, category_id=bob_food.id, year=2026, month=8,
                amount=Decimal("100"),
            )
