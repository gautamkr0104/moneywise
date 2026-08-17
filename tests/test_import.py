"""CSV import tests: parsing, validation, duplicates, preview, import (Phase 9)."""

from __future__ import annotations

import io
from datetime import date

from app.models import Category, Transaction, User
from app.services import import_service
from conftest import make_account, make_transaction

CSV_GOOD = """date,description,amount,category,type
2026-08-01,Salary,50000,Salary,income
2026-08-02,Groceries,2500,Food,expense
2026-08-03,Gift shopping,300,Gifts,expense
"""

CSV_WITH_ERRORS = """date,description,amount,category,type
2026-08-01,Salary,50000,Salary,income
bad-date,Broken,100,Food,expense
2026-08-02,Negative,-5,Food,expense
2026-08-03,BadType,100,Food,transfer
2026-08-04,,100,Food,expense
"""

CSV_MISSING_HEADER = """date,description,amount,type
2026-08-01,Salary,50000,income
"""


def _upload(client, csv_text, filename="transactions.csv"):
    return client.post(
        "/transactions/import",
        data={"file": (io.BytesIO(csv_text.encode("utf-8")), filename)},
        content_type="multipart/form-data",
    )


def test_parse_valid_csv(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        make_account(user, name="Bank")

    response = _upload(auth_client, CSV_GOOD)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "3 ready" in body
    assert "Salary" in body


def test_invalid_rows_flagged(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        make_account(user, name="Bank")

    response = _upload(auth_client, CSV_WITH_ERRORS)
    body = response.get_data(as_text=True)
    assert "4 invalid" in body or "5 invalid" in body
    assert "Invalid date" in body
    assert "Invalid amount" in body
    assert "Transfers cannot be imported" in body


def test_missing_required_column_rejected(auth_client):
    response = _upload(auth_client, CSV_MISSING_HEADER)
    body = response.get_data(as_text=True)
    assert b"Missing required columns" in response.data or "Missing required columns" in body


def test_non_csv_rejected(auth_client):
    response = _upload(auth_client, CSV_GOOD, filename="evil.exe")
    assert b"Only .csv files" in response.data


def test_duplicate_detection(app, user):
    with app.app_context():
        account = make_account(user, name="Bank")
        food = Category.query.filter_by(user_id=user.id, name="Food").first()
        make_transaction(user, account, amount="2500.00", description="Groceries",
                         category=food, txn_date=date(2026, 8, 2))

        preview = import_service.build_preview(
            user, io.BytesIO(CSV_GOOD.encode("utf-8")), "t.csv"
        )
        assert preview.total_rows == 3
        assert len(preview.duplicate_rows) == 1
        assert len(preview.valid_rows) == 2


def test_import_creates_transactions_and_categories(app, user):
    with app.app_context():
        make_account(user, name="Bank")
        preview = import_service.build_preview(
            user, io.BytesIO(CSV_GOOD.encode("utf-8")), "t.csv"
        )
        assert preview.valid_count == 3
        # "Gifts" does not exist yet -> flagged as a new category, created on import.
        assert "Gifts" in preview.new_categories

        result = import_service.import_preview(user, preview)
        assert result.imported == 3
        assert Transaction.query.count() == 3

        categories = {c.name for c in Category.query.filter_by(user_id=user.id).all()}
        assert {"Food", "Salary", "Transport", "Gifts"} <= categories
        gifts = Category.query.filter_by(user_id=user.id, name="Gifts").first()
        assert gifts is not None and gifts.is_system is False


def test_import_skips_duplicates_again(app, user):
    with app.app_context():
        make_account(user, name="Bank")
        preview = import_service.build_preview(
            user, io.BytesIO(CSV_GOOD.encode("utf-8")), "t.csv"
        )
        import_service.import_preview(user, preview)
        # Re-building the preview now flags every row as an existing duplicate.
        preview2 = import_service.build_preview(
            user, io.BytesIO(CSV_GOOD.encode("utf-8")), "t.csv"
        )
        assert len(preview2.duplicate_rows) == 3
        assert len(preview2.valid_rows) == 0
        result2 = import_service.import_preview(user, preview2)
        assert result2.imported == 0
        assert Transaction.query.count() == 3


def test_import_requires_existing_account(auth_client):
    # No account exists for alice -> every row is invalid.
    response = _upload(auth_client, CSV_GOOD)
    body = response.get_data(as_text=True)
    assert "No account to import into" in body


def test_confirm_flow_imports(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        make_account(user, name="Bank")

    response = _upload(auth_client, CSV_GOOD)
    assert response.status_code == 200
    # Extract the pending filename from the form action isn't needed; confirm
    # posts back to the same URL with the session cookie.
    confirm = auth_client.post(
        "/transactions/import", data={"confirm": "1"}
    )
    assert confirm.status_code == 302
    with auth_client.application.app_context():
        assert Transaction.query.count() == 3


def test_cancel_import(auth_client):
    with auth_client.application.app_context():
        user = User.query.filter_by(username="alice").first()
        make_account(user, name="Bank")

    _upload(auth_client, CSV_GOOD)
    cancel = auth_client.post("/transactions/import/cancel")
    assert cancel.status_code == 302
    with auth_client.application.app_context():
        assert Transaction.query.count() == 0
