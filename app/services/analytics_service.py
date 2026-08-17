"""Financial analytics built on Pandas.

Transactions are loaded into a DataFrame once per report, then every
aggregation (monthly totals, category breakdowns, trends, savings rate)
derives from that frame.  Amounts are converted to ``float`` *only* inside
this module for Pandas aggregation; canonical money values elsewhere stay
``Decimal``.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..models import Transaction, TransactionType, User
from ..utils import add_months, month_range


def _load_transactions(user: User, date_from: date, date_to: date) -> pd.DataFrame:
    rows = (
        Transaction.query.filter_by(user_id=user.id)
        .filter(Transaction.date >= date_from, Transaction.date <= date_to)
        .all()
    )
    data = [
        {
            "id": t.id,
            "date": t.date,
            "amount": float(t.amount),
            "type": t.type.value,
            "description": t.description,
            "account_id": t.account_id,
            "account_name": t.account.name if t.account else "",
            "category_id": t.category_id,
            "category_name": t.category.name if t.category else "",
            "to_account_id": t.to_account_id,
        }
        for t in rows
    ]
    df = pd.DataFrame(data, columns=[
        "id", "date", "amount", "type", "description",
        "account_id", "account_name", "category_id", "category_name", "to_account_id",
    ])
    # Normalize python ``date`` objects to a pandas datetime column so .dt
    # accessors and date formatting behave consistently.
    df["date"] = pd.to_datetime(df["date"])
    return df


def _signed_amount(df: pd.DataFrame) -> pd.Series:
    """Expenses and outgoing transfers are negative; income is positive."""
    sign = df["type"].map(
        {TransactionType.INCOME.value: 1, TransactionType.EXPENSE.value: -1,
         TransactionType.TRANSFER.value: -1}
    )
    return df["amount"] * sign


def _expenses(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["type"] == TransactionType.EXPENSE.value]


# ---------------------------------------------------------------------------
# Single-period report
# ---------------------------------------------------------------------------


def monthly_report(user: User, year: int, month: int) -> dict:
    """Totals and breakdowns for one month (or year) of activity."""
    start, end = month_range(year, month)
    df = _load_transactions(user, start, end)
    return report_for_range(user, start, end, df=df)


def report_for_range(user: User, date_from: date, date_to: date, df: pd.DataFrame | None = None) -> dict:
    """Full analytics for an arbitrary date range."""
    if df is None:
        df = _load_transactions(user, date_from, date_to)

    expenses = _expenses(df)
    income = df[df["type"] == TransactionType.INCOME.value]
    transfers = df[df["type"] == TransactionType.TRANSFER.value]

    total_income = float(income["amount"].sum()) if not income.empty else 0.0
    total_expenses = float(expenses["amount"].sum()) if not expenses.empty else 0.0
    savings = total_income - total_expenses

    spending_by_category = (
        expenses.groupby("category_name")["amount"].sum().sort_values(ascending=False)
    )
    spending_by_account = (
        expenses.groupby("account_name")["amount"].sum().sort_values(ascending=False)
    )
    income_by_category = (
        income.groupby("category_name")["amount"].sum().sort_values(ascending=False)
    )

    highest_spending_category = (
        (spending_by_category.index[0], float(spending_by_category.iloc[0]))
        if not spending_by_category.empty else None
    )
    highest_transaction = (
        (df.loc[df["amount"].idxmax(), "description"], float(df["amount"].max()))
        if not df.empty else None
    )

    savings_rate = (savings / total_income * 100) if total_income else None

    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "total_transfers": float(transfers["amount"].sum()) if not transfers.empty else 0.0,
        "savings": savings,
        "savings_rate": savings_rate,
        "average_monthly_spending": None,  # computed by trend() for multi-month ranges
        "spending_by_category": spending_by_category,
        "spending_by_account": spending_by_account,
        "income_by_category": income_by_category,
        "highest_spending_category": highest_spending_category,
        "highest_transaction": highest_transaction,
        "transaction_count": len(df),
    }


def average_monthly_spending(user: User, months: int = 6) -> float:
    """Average of the last ``months`` months' total expenses."""
    end = date.today()
    start = date(end.year, end.month, 1)
    df = _load_transactions(user, start.replace(year=start.year - 1), end)
    expenses = _expenses(df)
    if expenses.empty:
        return 0.0
    monthly = expenses.groupby(expenses["date"].dt.to_period("M"))["amount"].sum()
    return float(monthly.tail(months).mean())


# ---------------------------------------------------------------------------
# Trends (multi-month)
# ---------------------------------------------------------------------------


def monthly_trend(user: User, months: int = 6) -> pd.DataFrame:
    """Income / expense / savings per month for the last ``months`` months."""
    today = date.today()
    end = date(today.year, today.month, 1)
    start = add_months(end, -(months - 1))

    df = _load_transactions(user, start, end)
    if df.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "savings"])

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").astype(str)
    pivot = df.pivot_table(
        index="month", columns="type", values="amount", aggfunc="sum", fill_value=0.0
    )
    for column in ("income", "expense", "transfer"):
        if column not in pivot.columns:
            pivot[column] = 0.0
    out = pivot.reset_index()  # "month" becomes a plain column
    out = out.rename(columns={"expense": "expenses"})
    out["savings"] = out["income"] - out["expenses"]
    return out[["month", "income", "expenses", "savings"]].sort_values(
        "month"
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------


def transactions_csv(user: User, date_from: date, date_to: date) -> str:
    """CSV of all transactions in the range."""
    df = _load_transactions(user, date_from, date_to)
    if df.empty:
        return "date,type,amount,account,category,description,notes\n"
    out = df[[
        "date", "type", "amount", "account_name", "category_name", "description"
    ]].copy()
    out.columns = ["date", "type", "amount", "account", "category", "description"]
    out["amount"] = out["amount"].map(lambda v: f"{v:.2f}")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False)


def monthly_report_csv(user: User, date_from: date, date_to: date) -> str:
    """CSV with income/expense totals and category breakdown for a range."""
    report = report_for_range(user, date_from, date_to)
    lines = [
        "MoneyWise monthly report",
        f"Period,{date_from.isoformat()},{date_to.isoformat()}",
        "",
        "Total income,{:.2f}".format(report["total_income"]),
        "Total expenses,{:.2f}".format(report["total_expenses"]),
        "Savings,{:.2f}".format(report["savings"]),
        (
            "Savings rate,{:.1f}%".format(report["savings_rate"])
            if report["savings_rate"] is not None else "Savings rate,n/a"
        ),
        "",
        "Spending by category",
        "category,amount",
    ]
    for name, amount in report["spending_by_category"].items():
        lines.append(f"{name},{amount:.2f}")
    lines.append("")
    lines.append("Spending by account")
    lines.append("account,amount")
    for name, amount in report["spending_by_account"].items():
        lines.append(f"{name},{amount:.2f}")
    return "\n".join(lines) + "\n"


def budget_report_csv(user: User, year: int, month: int) -> str:
    """CSV of budget progress for one month."""
    from .budget_service import budgets_for_period, budget_status

    budgets = budgets_for_period(user, year, month)
    lines = [
        "MoneyWise budget report",
        f"Period,{year:04d}-{month:02d}",
        "",
        "category,budgeted,spent,remaining,percent_used,status",
    ]
    for budget in budgets:
        status = budget_status(budget)
        lines.append(
            f"{budget.category.name},{float(budget.amount):.2f},"
            f"{float(status['spent']):.2f},{float(status['remaining']):.2f},"
            f"{float(status['percent_used']):.1f},{status['level']}"
        )
    return "\n".join(lines) + "\n"
