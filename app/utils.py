"""Small shared helpers: money formatting, date math, auth decorator."""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import wraps

from flask import flash, g, redirect, request, url_for

#: Symbol used when displaying amounts, keyed by ISO currency code.
CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}


def to_decimal(value: object) -> Decimal:
    """Coerce a value to an exact :class:`Decimal`, treating ``None`` as zero."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def format_money(value: object, currency: str = "INR") -> str:
    """Format a Decimal as a readable, 2-decimal currency amount."""
    amount = to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    symbol = CURRENCY_SYMBOLS.get(currency or "INR", "")
    return f"{symbol}{amount:,.2f}"


def format_date(value: date | datetime) -> str:
    """Render a date in a compact human format (e.g. 15 Aug 2026)."""
    return value.strftime("%d %b %Y")


def month_range(year: int, month: int) -> tuple[date, date]:
    """First and last day of a month."""
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


def add_months(value: date, months: int) -> date:
    """Add ``months`` to a date, clamping the day to the target month's end."""
    total = value.year * 12 + (value.month - 1) + months
    year, zero_based_month = divmod(total, 12)
    month = zero_based_month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))


def is_safe_next_url(target: str | None) -> bool:
    """Reject open-redirect targets (must be a same-site relative path)."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    return True


def login_required(view):
    """Require an authenticated session, redirecting guests to the login page."""

    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.get("current_user") is None:
            flash("Please log in to continue.", "warning")
            target = request.full_path if request.method == "GET" else None
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)

    return wrapped_view
