"""Analytics + report tests: Pandas aggregations and CSV exports (Phase 8)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import Budget, Category, User
from app.services import analytics_service
from app.utils import add_months
from conftest import make_account, make_transaction


def _seed(user, account=None):
    """Food + Rent expenses and a Salary income in August 2026.

    Must be called inside an active app context.
    """
    account = account or make_account(user)
    food = Category.query.filter_by(user_id=user.id, name="Food").first()
    rent = Category.query.filter_by(user_id=user.id, name="Rent").first()
    salary = Category.query.filter_by(user_id=user.id, name="Salary").first()
    make_transaction(user, account, amount="2000.00", category=food,
                     txn_date=date(2026, 8, 2))
    make_transaction(user, account, amount="1500.00", category=food,
                     txn_date=date(2026, 8, 10))
    make_transaction(user, account, amount="8000.00", category=rent,
                     txn_date=date(2026, 8, 1))
    make_transaction(user, account, amount="50000.00", category=salary,
                     txn_type="income", txn_date=date(2026, 8, 1))
    return account


def test_monthly_report_totals(app, user):
    with app.app_context():
        _seed(user)
        report = analytics_service.monthly_report(user, 2026, 8)

        assert report["total_income"] == 50000.0
        assert report["total_expenses"] == 11500.0
        assert report["savings"] == 38500.0
        assert report["savings_rate"] == 77.0
        assert report["transaction_count"] == 4


def test_monthly_report_ignores_other_months(app, user):
    with app.app_context():
        _seed(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, make_account(user), amount="99999.00", category=food,
                         txn_date=date(2026, 9, 1))
        report = analytics_service.monthly_report(user, 2026, 8)
        assert report["total_expenses"] == 11500.0


def test_spending_by_category(app, user):
    with app.app_context():
        _seed(user)
        report = analytics_service.monthly_report(user, 2026, 8)
        breakdown = report["spending_by_category"]
        assert breakdown["Rent"] == 8000.0
        assert breakdown["Food"] == 3500.0
        assert report["highest_spending_category"] == ("Rent", 8000.0)


def test_spending_by_account(app, user):
    with app.app_context():
        _seed(user)
        report = analytics_service.monthly_report(user, 2026, 8)
        assert report["spending_by_account"]["Bank"] == 11500.0


def test_highest_transaction(app, user):
    with app.app_context():
        _seed(user)
        report = analytics_service.monthly_report(user, 2026, 8)
        assert report["highest_transaction"][1] == 50000.0


def test_average_monthly_spending(app, user):
    with app.app_context():
        account = _seed(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        today = date.today()
        for i in range(3):
            month_start = add_months(date(today.year, today.month, 1), -i)
            make_transaction(user, account, amount="100.00", category=food,
                             txn_date=month_start)
        avg = analytics_service.average_monthly_spending(user, months=3)
        assert avg > 0


def test_monthly_trend(app, user):
    with app.app_context():
        _seed(user)
        trend = analytics_service.monthly_trend(user, months=6)
        assert "2026-08" in set(trend["month"])
        row = trend[trend["month"] == "2026-08"].iloc[0]
        assert row["income"] == 50000.0
        assert row["expenses"] == 11500.0
        assert row["savings"] == 38500.0


def test_budget_report_csv(app, user):
    with app.app_context():
        _seed(user)
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        db.session.add(
            Budget(user_id=user.id, category_id=food.id, year=2026, month=8,
                   amount=Decimal("4000.00"))
        )
        db.session.commit()

        csv_text = analytics_service.budget_report_csv(user, 2026, 8)
        assert "category,budgeted,spent,remaining,percent_used,status" in csv_text
        assert "Food,4000.00,3500.00,500.00,87.5" in csv_text


def test_transactions_csv_export(app, user):
    with app.app_context():
        _seed(user)
        csv_text = analytics_service.transactions_csv(
            user, date(2026, 8, 1), date(2026, 8, 31)
        )
        lines = csv_text.strip().splitlines()
        assert lines[0] == "date,type,amount,account,category,description"
        assert len(lines) == 5  # header + 4 transactions
        assert "2026-08-01,income,50000.00" in csv_text


def test_web_report_page(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        _seed(user)

    response = auth_client.get("/reports/?period=current_year")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Spending by category" in body
    assert "Rent" in body


def test_web_csv_download(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        _seed(user)

    response = auth_client.get(
        "/reports/export/transactions.csv?date_from=2026-08-01&date_to=2026-08-31"
    )
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    assert b"2026-08-01,income,50000.00" in response.data
