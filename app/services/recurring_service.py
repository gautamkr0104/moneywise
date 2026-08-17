"""Recurring transaction business logic.

A pure-Python service (no Celery/Redis) that materializes due recurring
templates into real transactions and advances their ``next_due_date``.  Can
be triggered from a web route, the REST API, or a ``flask`` CLI command.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ..extensions import db
from ..models import (
    Account,
    Category,
    RecurringFrequency,
    RecurringTransaction,
    Transaction,
    TransactionType,
    User,
)
from ..utils import add_months, to_decimal

logger = logging.getLogger(__name__)


class RecurringValidationError(ValueError):
    """Raised when recurring transaction data violates business rules."""


def _advance(next_due: date, frequency: RecurringFrequency) -> date:
    """The next due date after ``next_due`` for the given frequency."""
    if frequency is RecurringFrequency.DAILY:
        return date.fromordinal(next_due.toordinal() + 1)
    if frequency is RecurringFrequency.WEEKLY:
        return date.fromordinal(next_due.toordinal() + 7)
    if frequency is RecurringFrequency.MONTHLY:
        return add_months(next_due, 1)
    if frequency is RecurringFrequency.YEARLY:
        return add_months(next_due, 12)
    raise RecurringValidationError(f"Unknown frequency: {frequency}")


def create_recurring(
    user: User,
    *,
    description: str,
    amount: Decimal,
    txn_type: TransactionType,
    account_id: int,
    category_id: int,
    frequency: RecurringFrequency,
    next_due_date: date,
    is_active: bool = True,
) -> RecurringTransaction:
    """Create a recurring template, validating ownership and type rules."""
    if not isinstance(txn_type, TransactionType):
        txn_type = TransactionType(txn_type)
    if txn_type is TransactionType.TRANSFER:
        raise RecurringValidationError("Recurring transfers are not supported yet.")
    amount = to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise RecurringValidationError("Amount must be greater than zero.")

    account = db.session.get(Account, account_id)
    category = db.session.get(Category, category_id)
    if account is None or account.user_id != user.id:
        raise RecurringValidationError("Account does not exist.")
    if category is None or category.user_id != user.id:
        raise RecurringValidationError("Category does not exist.")

    recurring = RecurringTransaction(
        user_id=user.id,
        account_id=account.id,
        category_id=category.id,
        description=description.strip(),
        amount=amount,
        type=txn_type,
        frequency=frequency,
        next_due_date=next_due_date,
        is_active=is_active,
    )
    db.session.add(recurring)
    db.session.commit()
    return recurring


def update_recurring(recurring: RecurringTransaction, **fields) -> RecurringTransaction:
    """Update editable fields (ownership is unchanged)."""
    for field, value in fields.items():
        setattr(recurring, field, value)
    db.session.commit()
    return recurring


def delete_recurring(recurring: RecurringTransaction) -> None:
    db.session.delete(recurring)
    db.session.commit()


def get_user_recurring(user: User, recurring_id: int) -> RecurringTransaction | None:
    return RecurringTransaction.query.filter_by(id=recurring_id, user_id=user.id).first()


def get_user_recurring_or_404(user: User, recurring_id: int) -> RecurringTransaction:
    recurring = get_user_recurring(user, recurring_id)
    if recurring is None:
        from flask import abort

        abort(404)
    return recurring


def due_recurring(user: User, as_of: date) -> list[RecurringTransaction]:
    """Active templates whose next due date is on or before ``as_of``."""
    return (
        RecurringTransaction.query.filter_by(user_id=user.id, is_active=True)
        .filter(RecurringTransaction.next_due_date <= as_of)
        .order_by(RecurringTransaction.next_due_date.asc())
        .all()
    )


def process_due(user: User, as_of: date | None = None) -> dict:
    """Materialize every due recurring template into transactions.

    For each due template, one transaction is created per missed period and
    ``next_due_date`` is advanced until it is after ``as_of``.  Returns a
    summary dict ``{created, processed}``.
    """
    as_of = as_of or date.today()
    due = due_recurring(user, as_of)
    created = 0
    processed = 0

    for recurring in due:
        # Deactivate templates whose account has since been deleted.
        if db.session.get(Account, recurring.account_id) is None:
            recurring.is_active = False
            continue

        next_due = recurring.next_due_date
        while next_due <= as_of:
            db.session.add(
                Transaction(
                    user_id=user.id,
                    account_id=recurring.account_id,
                    category_id=recurring.category_id,
                    amount=recurring.amount,
                    type=recurring.type,
                    description=recurring.description,
                    date=next_due,
                )
            )
            created += 1
            next_due = _advance(next_due, recurring.frequency)
        recurring.next_due_date = next_due
        processed += 1

    db.session.commit()
    if created:
        logger.info(
            "recurring processed: user_id=%s processed=%d created=%d",
            user.id, processed, created,
        )
    return {"created": created, "processed": processed}
