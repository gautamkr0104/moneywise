"""CSV transaction import: parse, validate, preview, insert.

Uploaded files are never trusted: headers are checked, every cell is
validated, duplicates are detected, and nothing is written to the database
until the user explicitly confirms the preview.  ``build_preview`` is
strictly read-only; ``import_preview`` resolves (and auto-creates) missing
categories and inserts transactions.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, select

from ..extensions import db
from ..models import (
    Account,
    Category,
    Transaction,
    TransactionType,
    User,
)

REQUIRED_COLUMNS = ("date", "description", "amount", "category", "type")
OPTIONAL_COLUMNS = ("account", "notes")
EXPECTED_HEADERS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


class CsvImportError(ValueError):
    """Raised when the uploaded file itself is unusable."""


@dataclass
class RowResult:
    """Validation outcome for one CSV row."""

    line_number: int
    data: dict | None = None
    errors: list[str] = field(default_factory=list)
    duplicate_of: int | None = None

    @property
    def is_valid(self) -> bool:
        return self.data is not None and not self.errors


@dataclass
class ImportPreview:
    """What the importer found, shown to the user before inserting."""

    filename: str
    total_rows: int
    valid_rows: list[RowResult]
    invalid_rows: list[RowResult]
    duplicate_rows: list[RowResult]
    default_account: Account | None = None

    @property
    def valid_count(self) -> int:
        return len(self.valid_rows)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid_rows) + len(self.duplicate_rows)

    @property
    def new_categories(self) -> set[str]:
        return {
            row.data["category_name"]
            for row in self.valid_rows
            if row.data and row.data.get("category_is_new")
        }


@dataclass
class ImportResult:
    """Outcome of a confirmed import."""

    imported: int = 0
    skipped_duplicates: int = 0
    invalid: int = 0


def read_csv(file_storage) -> list[dict]:
    """Read an uploaded file into a list of row dicts (utf-8, BOM-safe)."""
    raw = file_storage.read()
    if not raw:
        raise CsvImportError("The file is empty.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvImportError("The file must be UTF-8 encoded.") from None

    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]

    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise CsvImportError(
            f"Missing required columns: {', '.join(missing)}. "
            f"Expected: {', '.join(EXPECTED_HEADERS)}."
        )

    return [
        {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        for raw_row in reader
    ]


def _parse_amount(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        amount = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount


def _parse_date(value: str) -> "datetime.date | None":
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _find_duplicate(user: User, data: dict) -> Transaction | None:
    stmt = (
        select(Transaction)
        .where(
            and_(
                Transaction.user_id == user.id,
                Transaction.date == data["date"],
                Transaction.amount == data["amount"],
                Transaction.description == data["description"],
                Transaction.type == data["type"],
            )
        )
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


def _default_account(user: User) -> Account | None:
    return (
        Account.query.filter_by(user_id=user.id, is_archived=False)
        .order_by(Account.created_at.asc())
        .first()
    )


def _validate_rows(user: User, rows: list[dict]) -> tuple[list[RowResult], list[RowResult]]:
    """Validate rows without writing anything to the database.

    Returns ``(results, duplicates)`` where ``results`` holds every row
    (valid or not, so the preview can render them in order).
    """
    results: list[RowResult] = []
    duplicates: list[RowResult] = []
    seen: set[tuple] = set()

    for index, row in enumerate(rows, start=2):  # line 1 is the header
        result = RowResult(line_number=index)

        amount = _parse_amount(row.get("amount", ""))
        txn_date = _parse_date(row.get("date", ""))
        try:
            txn_type = TransactionType(row.get("type", "").strip().lower())
        except ValueError:
            txn_type = None

        description = row.get("description", "")
        category_name = row.get("category", "").strip()

        if txn_date is None:
            result.errors.append("Invalid date (expected YYYY-MM-DD).")
        if amount is None:
            result.errors.append("Invalid amount (must be a positive number).")
        if txn_type is None:
            result.errors.append("Invalid type (must be 'income' or 'expense').")
        elif txn_type is TransactionType.TRANSFER:
            result.errors.append("Transfers cannot be imported via CSV.")
        if not description:
            result.errors.append("Description is required.")
        if not category_name:
            result.errors.append("Category is required.")

        account: Account | None = None
        if not result.errors:
            account_name = row.get("account", "").strip()
            if account_name:
                account = Account.query.filter_by(user_id=user.id, name=account_name).first()
                if account is None:
                    result.errors.append(f"Unknown account '{account_name}'.")
            else:
                account = _default_account(user)
                if account is None:
                    result.errors.append("No account to import into - create one first.")

        if result.errors:
            results.append(result)
            continue

        category = (
            Category.query.filter_by(user_id=user.id, name=category_name, type=txn_type).first()
            if txn_type
            else None
        )

        data = {
            "date": txn_date,
            "amount": amount,
            "type": txn_type,
            "description": description,
            "account": account,
            "category_name": category_name,
            "category_is_new": category is None,
            "notes": row.get("notes", "") or None,
        }

        dup_key = (data["date"], data["amount"], data["description"], txn_type)
        if dup_key in seen:
            result.errors.append("Duplicate row within this file.")
            results.append(result)
            continue
        seen.add(dup_key)

        existing = _find_duplicate(user, data)
        if existing is not None:
            result.duplicate_of = existing.id
            duplicates.append(result)
            continue

        result.data = data
        results.append(result)

    return results, duplicates


def build_preview(user: User, file_storage, filename: str) -> ImportPreview:
    """Parse + validate an uploaded file into a preview. No database writes."""
    rows = read_csv(file_storage)
    results, duplicates = _validate_rows(user, rows)
    valid_rows = [r for r in results if r.is_valid]
    invalid_rows = [r for r in results if not r.is_valid]
    return ImportPreview(
        filename=filename,
        total_rows=len(rows),
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        duplicate_rows=duplicates,
        default_account=_default_account(user),
    )


def _get_or_create_category(user: User, name: str, txn_type: TransactionType) -> Category:
    category = Category.query.filter_by(user_id=user.id, name=name, type=txn_type).first()
    if category is None:
        category = Category(user_id=user.id, name=name, type=txn_type, is_system=False)
        db.session.add(category)
        db.session.flush()
    return category


def import_preview(user: User, preview: ImportPreview) -> ImportResult:
    """Insert every valid row of an already-built preview.

    Missing categories are created here (not during preview), and duplicates
    are re-checked defensively before each insert.
    """
    result = ImportResult()
    for row in preview.valid_rows:
        data = row.data
        if data is None:
            result.invalid += 1
            continue
        if _find_duplicate(user, data) is not None:
            result.skipped_duplicates += 1
            continue
        category = _get_or_create_category(user, data["category_name"], data["type"])
        db.session.add(
            Transaction(
                user_id=user.id,
                account_id=data["account"].id,
                category_id=category.id,
                amount=data["amount"],
                type=data["type"],
                description=data["description"],
                date=data["date"],
                notes=data["notes"],
            )
        )
        result.imported += 1
    db.session.commit()
    return result
