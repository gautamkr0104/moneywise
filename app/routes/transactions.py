"""Transactions: list/filter, create, detail, edit, delete, CSV import."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from ..extensions import db
from ..forms import CsvImportForm, TransactionFilterForm, TransactionForm
from ..models import Account, Category, Transaction, TransactionType
from ..services import import_service, transaction_service
from ..utils import login_required

logger = logging.getLogger(__name__)

transactions_bp = Blueprint("transactions", __name__)

ALLOWED_EXTENSIONS = {"csv"}
_IMPORT_SESSION_KEY = "pending_import_file"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_accounts():
    return (
        Account.query.filter_by(user_id=g.current_user.id, is_archived=False)
        .order_by(Account.name.asc())
        .all()
    )


def _user_categories():
    return (
        Category.query.filter_by(user_id=g.current_user.id)
        .order_by(Category.type.asc(), Category.name.asc())
        .all()
    )


def _populate_transaction_form(form: TransactionForm, txn: Transaction | None = None) -> None:
    accounts = _user_accounts()
    form.account.choices = [(a.id, a.name) for a in accounts]
    form.to_account.choices = [(a.id, a.name) for a in accounts]
    form.category.choices = [
        (c.id, f"{c.name} ({c.type.value})") for c in _user_categories()
    ]
    if txn is not None:
        form.type.data = txn.type.value
        form.account.data = txn.account_id
        form.to_account.data = txn.to_account_id
        form.category.data = txn.category_id


def _user_transaction_or_404(txn_id: int) -> Transaction:
    return transaction_service.get_user_transaction_or_404(g.current_user, txn_id)


# ---------------------------------------------------------------------------
# List / filter / paginate
# ---------------------------------------------------------------------------


@transactions_bp.route("/")
@login_required
def list_transactions():
    form = TransactionFilterForm(request.args)
    form.account.choices = [(0, "All accounts"), *[(a.id, a.name) for a in _user_accounts()]]
    form.category.choices = [(0, "All categories"), *[(c.id, c.name) for c in _user_categories()]]
    # coerce=int turns "" into None already; guard empty selects:
    filters = {
        "q": form.q.data,
        "txn_type": form.type.data or None,
        "account_id": form.account.data or None,
        "category_id": form.category.data or None,
        "date_from": form.date_from.data,
        "date_to": form.date_to.data,
        "min_amount": form.min_amount.data,
        "max_amount": form.max_amount.data,
        "sort": form.sort.data or "date",
        "order": form.order.data or "desc",
    }
    pagination = transaction_service.paginate_transactions(
        g.current_user,
        page=request.args.get("page", 1, type=int),
        per_page=25,
        **filters,
    )
    return render_template(
        "transactions/list.html",
        form=form,
        pagination=pagination,
        filters=filters,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@transactions_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    form = TransactionForm()
    _populate_transaction_form(form)
    if form.validate_on_submit():
        try:
            txn = transaction_service.create_transaction(
                g.current_user,
                amount=form.amount.data,
                txn_type=TransactionType(form.type.data),
                account_id=form.account.data,
                to_account_id=form.to_account.data,
                category_id=form.category.data,
                description=form.description.data,
                txn_date=form.date.data,
                notes=form.notes.data,
            )
        except transaction_service.TransactionValidationError as exc:
            flash(str(exc), "error")
            return render_template("transactions/form.html", form=form, title="New transaction")
        logger.info("transaction created: user_id=%s txn_id=%s", g.current_user.id, txn.id)
        flash("Transaction saved.", "success")
        return redirect(url_for("transactions.detail", txn_id=txn.id))
    return render_template("transactions/form.html", form=form, title="New transaction")


@transactions_bp.route("/<int:txn_id>")
@login_required
def detail(txn_id: int):
    txn = _user_transaction_or_404(txn_id)
    return render_template("transactions/detail.html", txn=txn)


@transactions_bp.route("/<int:txn_id>/edit", methods=["GET", "POST"])
@login_required
def edit(txn_id: int):
    txn = _user_transaction_or_404(txn_id)
    form = TransactionForm(obj=txn)
    _populate_transaction_form(form, txn)
    if form.validate_on_submit():
        try:
            transaction_service.update_transaction(
                g.current_user,
                txn,
                amount=form.amount.data,
                txn_type=form.type.data,
                account_id=form.account.data,
                to_account_id=form.to_account.data,
                category_id=form.category.data,
                description=form.description.data,
                date=form.date.data,
                notes=form.notes.data,
            )
        except transaction_service.TransactionValidationError as exc:
            flash(str(exc), "error")
            return render_template("transactions/form.html", form=form, title="Edit transaction", txn=txn)
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions.detail", txn_id=txn.id))
    return render_template("transactions/form.html", form=form, title="Edit transaction", txn=txn)


@transactions_bp.route("/<int:txn_id>/delete", methods=["POST"])
@login_required
def delete(txn_id: int):
    txn = _user_transaction_or_404(txn_id)
    transaction_service.delete_transaction(txn)
    flash("Transaction deleted.", "info")
    return redirect(url_for("transactions.list_transactions"))


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


def _import_dir() -> Path:
    from flask import current_app

    path = Path(current_app.instance_path) / "imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cleanup_pending_file() -> None:
    filename = session.pop(_IMPORT_SESSION_KEY, None)
    if filename:
        try:
            (_import_dir() / filename).unlink(missing_ok=True)
        except OSError:
            pass


@transactions_bp.route("/import", methods=["GET", "POST"])
@login_required
def csv_import():
    form = CsvImportForm()

    # Step 2: confirmation of the previously parsed preview.
    if request.method == "POST" and request.form.get("confirm") == "1":
        filename = session.get(_IMPORT_SESSION_KEY)
        if not filename:
            flash("Import session expired - please upload the file again.", "warning")
            return redirect(url_for("transactions.csv_import"))
        path = _import_dir() / filename
        try:
            preview = import_service.build_preview(g.current_user, path.open("rb"), filename)
        except import_service.CsvImportError as exc:
            _cleanup_pending_file()
            flash(str(exc), "error")
            return redirect(url_for("transactions.csv_import"))
        result = import_service.import_preview(g.current_user, preview)
        _cleanup_pending_file()
        logger.info(
            "csv import confirmed: user_id=%s imported=%d skipped=%d",
            g.current_user.id, result.imported, result.skipped_duplicates,
        )
        flash(
            f"Imported {result.imported} transaction(s), skipped "
            f"{result.skipped_duplicates} duplicate(s).",
            "success",
        )
        return redirect(url_for("transactions.list_transactions"))

    # Step 1: upload and preview.
    if form.validate_on_submit():
        file = form.file.data
        original_name = secure_filename(file.filename or "upload.csv")
        if not original_name.lower().endswith(".csv"):
            flash("Only .csv files are accepted.", "error")
            return render_template("transactions/import.html", form=form)

        filename = f"{uuid.uuid4().hex}.csv"
        path = _import_dir() / filename
        file.save(path)
        session[_IMPORT_SESSION_KEY] = filename
        try:
            # Read back from disk: ``file.save`` consumed the upload stream.
            preview = import_service.build_preview(g.current_user, path.open("rb"), original_name)
        except import_service.CsvImportError as exc:
            _cleanup_pending_file()
            flash(str(exc), "error")
            return render_template("transactions/import.html", form=form)

        if preview.total_rows == 0:
            _cleanup_pending_file()
            flash("The file contains no data rows.", "warning")
            return render_template("transactions/import.html", form=form)

        return render_template(
            "transactions/import_preview.html",
            preview=preview,
            filename=filename,
        )

    return render_template("transactions/import.html", form=form)


@transactions_bp.route("/import/cancel", methods=["POST"])
@login_required
def cancel_import():
    _cleanup_pending_file()
    flash("Import cancelled.", "info")
    return redirect(url_for("transactions.list_transactions"))
