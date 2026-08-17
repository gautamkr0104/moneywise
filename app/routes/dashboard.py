"""Dashboard: a live snapshot of the user's finances."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Blueprint, g, render_template

from ..models import Account, Transaction, TransactionType
from ..services import analytics_service, budget_service
from ..utils import login_required, month_range

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    user = g.current_user
    today = date.today()
    start, end = month_range(today.year, today.month)

    accounts = (
        Account.query.filter_by(user_id=user.id, is_archived=False)
        .order_by(Account.created_at.asc())
        .all()
    )
    total_balance = sum((a.current_balance for a in accounts), start=Decimal("0"))

    month_report = analytics_service.monthly_report(user, today.year, today.month)
    trend = analytics_service.monthly_trend(user, months=6)

    # Top spending categories this month (from the same report).
    top_categories = [
        {"name": name, "amount": amount}
        for name, amount in month_report["spending_by_category"].head(5).items()
    ]

    recent_transactions = (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(6)
        .all()
    )

    budgets = budget_service.budgets_for_period(user, today.year, today.month)
    budget_rows = []
    for budget in budgets:
        status = budget_service.budget_status(budget)
        budget_rows.append(
            {
                "budget": budget,
                "status": status,
                "warning": status["level"],
            }
        )
    over_budget = budget_service.over_budget_categories(user, today.year, today.month)

    return render_template(
        "dashboard/index.html",
        accounts=accounts,
        total_balance=total_balance,
        month_report=month_report,
        top_categories=top_categories,
        recent_transactions=recent_transactions,
        budgets=budget_rows,
        over_budget=over_budget,
        trend=trend,
        year=today.year,
        month=today.month,
    )
