"""Reports: Pandas-powered analytics views and CSV exports."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, Response, g, render_template, request

from ..forms import ReportPeriodForm
from ..services import analytics_service
from ..utils import login_required, month_range

reports_bp = Blueprint("reports", __name__)


def _resolve_period(form: ReportPeriodForm) -> tuple[date, date, str]:
    """Turn the form selection into (date_from, date_to, label)."""
    today = date.today()
    choice = form.period.data or "current_month"
    if choice == "current_month":
        start, end = month_range(today.year, today.month)
        return start, end, f"{today.year}-{today.month:02d}"
    if choice == "last_month":
        first = date(today.year, today.month, 1)
        from ..utils import add_months

        start = add_months(first, -1)
        start, end = month_range(start.year, start.month)
        return start, end, f"{start.year}-{start.month:02d}"
    if choice == "current_year":
        return date(today.year, 1, 1), date(today.year, 12, 31), str(today.year)
    # custom
    start = form.date_from.data or date(today.year, today.month, 1)
    end = form.date_to.data or today
    if start > end:
        start, end = end, start
    return start, end, f"{start.isoformat()} to {end.isoformat()}"


@reports_bp.route("/")
@login_required
def index():
    user = g.current_user
    form = ReportPeriodForm(request.args)
    today = date.today()
    form.year.choices = [(str(y), str(y)) for y in range(today.year - 2, today.year + 2)]
    form.month.data = str(today.month)
    form.year.data = str(today.year)

    date_from, date_to, label = _resolve_period(form)
    report = analytics_service.report_for_range(user, date_from, date_to)
    report["average_monthly_spending"] = analytics_service.average_monthly_spending(
        user, months=6
    )
    trend = analytics_service.monthly_trend(user, months=6)
    budgets = analytics_service.budget_report_csv(user, date_from.year, date_from.month)

    return render_template(
        "reports/index.html",
        form=form,
        report=report,
        trend=trend,
        label=label,
        date_from=date_from,
        date_to=date_to,
    )


@reports_bp.route("/export/transactions.csv")
@login_required
def export_transactions():
    user = g.current_user
    today = date.today()
    date_from = request.args.get("date_from", type=date.fromisoformat, default=None) or date(
        today.year, today.month, 1
    )
    date_to = request.args.get("date_to", type=date.fromisoformat, default=None) or today
    csv_text = analytics_service.transactions_csv(user, date_from, date_to)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


@reports_bp.route("/export/monthly.csv")
@login_required
def export_monthly():
    user = g.current_user
    today = date.today()
    date_from = request.args.get("date_from", type=date.fromisoformat, default=None) or date(
        today.year, today.month, 1
    )
    date_to = request.args.get("date_to", type=date.fromisoformat, default=None) or today
    csv_text = analytics_service.monthly_report_csv(user, date_from, date_to)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=monthly-report.csv"},
    )


@reports_bp.route("/export/budgets.csv")
@login_required
def export_budgets():
    user = g.current_user
    today = date.today()
    year = request.args.get("year", type=int, default=today.year)
    month = request.args.get("month", type=int, default=today.month)
    csv_text = analytics_service.budget_report_csv(user, year, month)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=budget-report.csv"},
    )
