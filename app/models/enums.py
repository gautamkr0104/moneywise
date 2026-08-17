"""Enumerations shared across the models.

Each enum is a ``str``-based enum so the stored value is a friendly,
database-portable string (e.g. ``"credit_card"``, ``"income"``).
"""

from __future__ import annotations

import enum


class AccountType(enum.StrEnum):
    """The kind of financial account a user can hold."""

    CASH = "cash"
    BANK = "bank"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"


class TransactionType(enum.StrEnum):
    """How a transaction affects money."""

    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class RecurringFrequency(enum.StrEnum):
    """How often a recurring transaction repeats."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Return enum member *values* so the database stores friendly strings."""
    return [member.value for member in enum_cls]
