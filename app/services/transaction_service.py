"""Transaction business logic: CRUD, validation, filtering, pagination.

The service is the single source of truth for transaction rules; web forms,
CSV import and the REST API all funnel through it.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select

from ..extensions import db
from ..models import Account, Category, Transaction, TransactionType, User
from ..utils import to_decimal


class TransactionValidationError(ValueError):
    """Raised when transaction data violates business rules."""


def _quantize(amount: object) -> Decimal:
    return to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _validate_transfer_targets(
    user: User,
    account_id: int,
    to_account_id: int | None,
    category_id: int | None,
    txn_type: TransactionType,
) -> tuple[Account, Account | None, Category | None]:
    """Verify ownership and type-specific rules; returns resolved entities."""
    account = db.session.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise TransactionValidationError("Account does not exist.")

    category: Category | None = None
    to_account: Account | None = None

    if txn_type is TransactionType.TRANSFER:
        if not to_account_id:
            raise TransactionValidationError("A destination account is required for a transfer.")
        if to_account_id == account_id:
            raise TransactionValidationError("Destination must differ from the source account.")
        to_account = db.session.get(Account, to_account_id)
        if to_account is None or to_account.user_id != user.id:
            raise TransactionValidationError("Destination account does not exist.")
        if category_id:
            raise TransactionValidationError("Transfers do not use a category.")
    else:
        if to_account_id:
            raise TransactionValidationError("Only transfers use a destination account.")
        category = db.session.get(Category, category_id) if category_id else None
        if category is None or category.user_id != user.id:
            raise TransactionValidationError("A valid category is required.")

    return account, to_account, category


def create_transaction(
    user: User,
    *,
    amount: Decimal,
    txn_type: TransactionType,
    account_id: int,
    description: str,
    txn_date: date,
    to_account_id: int | None = None,
    category_id: int | None = None,
    notes: str | None = None,
) -> Transaction:
    """Create a transaction after validating ownership and type rules."""
    amount = _quantize(amount)
    if amount <= 0:
        raise TransactionValidationError("Amount must be greater than zero.")

    account, to_account, category = _validate_transfer_targets(
        user, account_id, to_account_id, category_id, txn_type
    )

    txn = Transaction(
        user_id=user.id,
        account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        category_id=category.id if category else None,
        amount=amount,
        type=txn_type,
        description=description.strip(),
        date=txn_date,
        notes=(notes or "").strip() or None,
    )
    db.session.add(txn)
    db.session.commit()
    return txn


def update_transaction(
    user: User, txn: Transaction, **fields
) -> Transaction:
    """Update an existing transaction, re-validating type-specific rules."""
    txn_type = fields.get("type", txn.type)
    if isinstance(txn_type, str):
        txn_type = TransactionType(txn_type)

    account, to_account, category = _validate_transfer_targets(
        user,
        fields.get("account_id", txn.account_id),
        fields.get("to_account_id", txn.to_account_id),
        fields.get("category_id", txn.category_id),
        txn_type,
    )

    txn.account = account
    txn.to_account = to_account
    txn.category = category
    txn.type = txn_type
    if "amount" in fields:
        amount = _quantize(fields["amount"])
        if amount <= 0:
            raise TransactionValidationError("Amount must be greater than zero.")
        txn.amount = amount
    if "description" in fields:
        txn.description = fields["description"].strip()
    if "date" in fields:
        txn.date = fields["date"]
    if "notes" in fields:
        txn.notes = (fields["notes"] or "").strip() or None

    db.session.commit()
    return txn


def delete_transaction(txn: Transaction) -> None:
    db.session.delete(txn)
    db.session.commit()


def get_user_transaction(user: User, txn_id: int) -> Transaction | None:
    return Transaction.query.filter_by(id=txn_id, user_id=user.id).first()


def get_user_transaction_or_404(user: User, txn_id: int) -> Transaction:
    txn = get_user_transaction(user, txn_id)
    if txn is None:
        from flask import abort

        abort(404)
    return txn


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

SORT_COLUMNS = {
    "date": Transaction.date,
    "amount": Transaction.amount,
    "description": Transaction.description,
}


def query_transactions(
    user: User,
    *,
    q: str | None = None,
    txn_type: TransactionType | str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    sort: str = "date",
    order: str = "desc",
) -> "select":
    """Build a SELECT for the user's transactions matching every filter."""
    stmt = select(Transaction).where(Transaction.user_id == user.id)

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Transaction.description.ilike(like), Transaction.notes.ilike(like))
        )
    if txn_type:
        stmt = stmt.where(Transaction.type == TransactionType(txn_type))
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if category_id:
        stmt = stmt.where(Transaction.category_id == category_id)
    if date_from:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.date <= date_to)
    if min_amount is not None:
        stmt = stmt.where(Transaction.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Transaction.amount <= max_amount)

    column = SORT_COLUMNS.get(sort, Transaction.date)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())
    return stmt


def paginate_transactions(
    user: User,
    *,
    page: int = 1,
    per_page: int = 20,
    **filters,
):
    """Filter, sort and paginate the user's transactions."""
    stmt = query_transactions(user, **filters)
    return db.paginate(stmt, page=max(page, 1), per_page=per_page, error_out=False)


def serialize_filters(form) -> dict:
    """Extract validated filter values from a TransactionFilterForm."""
    return {
        "q": form.q.data,
        "txn_type": form.type.data or None,
        "account_id": form.account.data,
        "category_id": form.category.data,
        "date_from": form.date_from.data,
        "date_to": form.date_to.data,
        "min_amount": form.min_amount.data,
        "max_amount": form.max_amount.data,
        "sort": form.sort.data or "date",
        "order": form.order.data or "desc",
    }
