"""Budget business logic: CRUD, progress and warning levels."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Budget, Category, User
from ..utils import to_decimal


class BudgetValidationError(ValueError):
    """Raised when budget data violates business rules."""


#: Progress thresholds at which the UI shows a warning badge.
WARNING_LEVELS = (
    (Decimal("100"), "exceeded"),
    (Decimal("90"), "warn90"),
    (Decimal("75"), "warn75"),
    (Decimal("50"), "warn50"),
)


def warning_level(percent_used: Decimal) -> str:
    """Map a usage percentage to its highest warning level."""
    for threshold, level in WARNING_LEVELS:
        if percent_used >= threshold:
            return level
    return "ok"


def create_budget(
    user: User,
    *,
    category_id: int,
    year: int,
    month: int,
    amount: Decimal,
) -> Budget:
    """Create a budget, rejecting duplicates for the same user/category/period."""
    if not 1 <= month <= 12:
        raise BudgetValidationError("Month must be between 1 and 12.")
    if year < 2000 or year > 2100:
        raise BudgetValidationError("Year out of range.")

    amount = to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount < 0:
        raise BudgetValidationError("Budget amount cannot be negative.")

    category = db.session.get(Category, category_id)
    if category is None or category.user_id != user.id:
        raise BudgetValidationError("Category does not exist.")

    existing = Budget.query.filter_by(
        user_id=user.id, category_id=category_id, year=year, month=month
    ).first()
    if existing:
        raise BudgetValidationError(
            "A budget for this category and month already exists."
        )

    budget = Budget(
        user_id=user.id,
        category_id=category.id,
        year=year,
        month=month,
        amount=amount,
    )
    db.session.add(budget)
    db.session.commit()
    return budget


def update_budget(user: User, budget: Budget, *, amount: Decimal) -> Budget:
    amount = to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount < 0:
        raise BudgetValidationError("Budget amount cannot be negative.")
    budget.amount = amount
    db.session.commit()
    return budget


def delete_budget(budget: Budget) -> None:
    db.session.delete(budget)
    db.session.commit()


def get_user_budget(user: User, budget_id: int) -> Budget | None:
    return Budget.query.filter_by(id=budget_id, user_id=user.id).first()


def get_user_budget_or_404(user: User, budget_id: int) -> Budget:
    budget = get_user_budget(user, budget_id)
    if budget is None:
        from flask import abort

        abort(404)
    return budget


def budgets_for_period(user: User, year: int, month: int) -> list[Budget]:
    """All budgets a user has for one month, newest first."""
    return (
        Budget.query.filter_by(user_id=user.id, year=year, month=month)
        .order_by(Budget.created_at.desc())
        .all()
    )


def budget_status(budget: Budget) -> dict:
    """Computed progress for one budget (spent/remaining/percent/level)."""
    spent = budget.spent
    amount = budget.amount
    percent = (spent / amount * Decimal("100")) if amount else Decimal("0")
    return {
        "spent": spent,
        "remaining": max(amount - spent, Decimal("0")),
        "percent_used": percent,
        "level": warning_level(percent),
    }


def over_budget_categories(user: User, year: int, month: int) -> list[Budget]:
    """Budgets whose spending has exceeded the budgeted amount."""
    return [b for b in budgets_for_period(user, year, month) if b.is_exceeded]
