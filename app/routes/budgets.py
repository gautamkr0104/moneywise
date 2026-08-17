"""Budgets: monthly list, create, edit, delete."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func

from ..forms import BudgetForm
from ..models import Category, TransactionType
from ..services import budget_service
from ..utils import add_months, login_required

budgets_bp = Blueprint("budgets", __name__)


def _current_period() -> tuple[int, int]:
    today = date.today()
    return today.year, today.month


def _parse_period() -> tuple[int, int]:
    today = date.today()
    year = request.args.get("year", type=int, default=today.year)
    month = request.args.get("month", type=int, default=today.month)
    if not 1 <= month <= 12:
        month = today.month
    if not 2000 <= year <= 2100:
        year = today.year
    return year, month


@budgets_bp.route("/")
@login_required
def list_budgets():
    year, month = _parse_period()
    period = date(year, month, 1)
    budgets = budget_service.budgets_for_period(g.current_user, year, month)
    rows = [
        {"budget": b, "status": budget_service.budget_status(b)}
        for b in budgets
    ]
    return render_template(
        "budgets/list.html",
        rows=rows,
        year=year,
        month=month,
        prev_period=add_months(period, -1),
        next_period=add_months(period, 1),
        months_unbudgeted=_unbudgeted_categories(year, month),
    )


def _unbudgeted_categories(year: int, month: int) -> list[Category]:
    """Expense categories without a budget for the selected month."""
    user = g.current_user
    budgeted_ids = {
        b.category_id for b in budget_service.budgets_for_period(user, year, month)
    }
    query = Category.query.filter_by(user_id=user.id, type=TransactionType.EXPENSE)
    if budgeted_ids:
        query = query.filter(~Category.id.in_(budgeted_ids))
    return query.order_by(Category.name.asc()).all()


@budgets_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_budget():
    form = BudgetForm()
    year, month = _parse_period()
    form.year.choices = _year_choices()
    form.category.choices = _category_choices()
    form.month.data = str(month)
    form.year.data = str(year)
    if form.validate_on_submit():
        try:
            budget = budget_service.create_budget(
                g.current_user,
                category_id=form.category.data,
                year=int(form.year.data),
                month=int(form.month.data),
                amount=form.amount.data,
            )
        except budget_service.BudgetValidationError as exc:
            flash(str(exc), "error")
            return render_template("budgets/form.html", form=form, title="New budget")
        flash(f"Budget for '{budget.category.name}' saved.", "success")
        return redirect(url_for("budgets.list_budgets", year=budget.year, month=budget.month))
    return render_template("budgets/form.html", form=form, title="New budget")


@budgets_bp.route("/<int:budget_id>/edit", methods=["GET", "POST"])
@login_required
def edit(budget_id: int):
    budget = budget_service.get_user_budget_or_404(g.current_user, budget_id)
    form = BudgetForm(obj=budget)
    form.year.choices = _year_choices()
    form.category.choices = _category_choices()
    form.month.data = str(budget.month)
    form.year.data = str(budget.year)
    form.category.data = budget.category_id
    if form.validate_on_submit():
        try:
            budget_service.update_budget(
                g.current_user, budget, amount=form.amount.data
            )
        except budget_service.BudgetValidationError as exc:
            flash(str(exc), "error")
            return render_template("budgets/form.html", form=form, title="Edit budget")
        flash("Budget updated.", "success")
        return redirect(url_for("budgets.list_budgets", year=budget.year, month=budget.month))
    return render_template("budgets/form.html", form=form, title="Edit budget", budget=budget)


@budgets_bp.route("/<int:budget_id>/delete", methods=["POST"])
@login_required
def delete(budget_id: int):
    budget = budget_service.get_user_budget_or_404(g.current_user, budget_id)
    year, month = budget.year, budget.month
    budget_service.delete_budget(budget)
    flash("Budget deleted.", "info")
    return redirect(url_for("budgets.list_budgets", year=year, month=month))


def _year_choices() -> list[tuple[str, str]]:
    current = date.today().year
    return [(str(y), str(y)) for y in range(current - 1, current + 3)]


def _category_choices() -> list[tuple[int, str]]:
    categories = (
        Category.query.filter_by(user_id=g.current_user.id, type=TransactionType.EXPENSE)
        .order_by(Category.name.asc())
        .all()
    )
    return [(c.id, c.name) for c in categories]
