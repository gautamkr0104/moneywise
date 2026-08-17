"""Recurring transactions: list, create, edit, delete, process due."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..forms import RecurringForm
from ..models import Account, Category, RecurringTransaction, TransactionType
from ..services import recurring_service
from ..utils import login_required

recurring_bp = Blueprint("recurring", __name__)


def _populate_recurring_form(form: RecurringForm, recurring=None) -> None:
    accounts = (
        Account.query.filter_by(user_id=g.current_user.id, is_archived=False)
        .order_by(Account.name.asc())
        .all()
    )
    categories = (
        Category.query.filter_by(user_id=g.current_user.id)
        .order_by(Category.name.asc())
        .all()
    )
    form.account.choices = [(a.id, a.name) for a in accounts]
    form.category.choices = [(c.id, c.name) for c in categories]
    if recurring is not None:
        form.account.data = recurring.account_id
        form.category.data = recurring.category_id
        form.type.data = recurring.type.value
        form.frequency.data = recurring.frequency.value


@recurring_bp.route("/")
@login_required
def list_recurring():
    items = (
        RecurringTransaction.query.filter_by(user_id=g.current_user.id)
        .order_by(
            RecurringTransaction.is_active.desc(),
            RecurringTransaction.next_due_date.asc(),
        )
        .all()
    )
    return render_template("recurring/list.html", items=items, today=date.today())


@recurring_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_recurring():
    form = RecurringForm()
    _populate_recurring_form(form)
    if form.validate_on_submit():
        try:
            recurring_service.create_recurring(
                g.current_user,
                description=form.description.data,
                amount=form.amount.data,
                txn_type=TransactionType(form.type.data),
                account_id=form.account.data,
                category_id=form.category.data,
                frequency=form.frequency.data,
                next_due_date=form.next_due_date.data,
                is_active=form.is_active.data,
            )
        except recurring_service.RecurringValidationError as exc:
            flash(str(exc), "error")
            return render_template("recurring/form.html", form=form, title="New recurring transaction")
        flash("Recurring transaction saved.", "success")
        return redirect(url_for("recurring.list_recurring"))
    return render_template("recurring/form.html", form=form, title="New recurring transaction")


@recurring_bp.route("/<int:recurring_id>/edit", methods=["GET", "POST"])
@login_required
def edit(recurring_id: int):
    recurring = recurring_service.get_user_recurring_or_404(g.current_user, recurring_id)
    form = RecurringForm(obj=recurring)
    _populate_recurring_form(form, recurring)
    if form.validate_on_submit():
        try:
            recurring_service.update_recurring(
                recurring,
                description=form.description.data.strip(),
                amount=form.amount.data,
                type=TransactionType(form.type.data),
                account_id=form.account.data,
                category_id=form.category.data,
                frequency=form.frequency.data,
                next_due_date=form.next_due_date.data,
                is_active=form.is_active.data,
            )
        except recurring_service.RecurringValidationError as exc:
            flash(str(exc), "error")
            return render_template("recurring/form.html", form=form, title="Edit recurring transaction")
        flash("Recurring transaction updated.", "success")
        return redirect(url_for("recurring.list_recurring"))
    return render_template("recurring/form.html", form=form, title="Edit recurring transaction")


@recurring_bp.route("/<int:recurring_id>/delete", methods=["POST"])
@login_required
def delete(recurring_id: int):
    recurring = recurring_service.get_user_recurring_or_404(g.current_user, recurring_id)
    recurring_service.delete_recurring(recurring)
    flash("Recurring transaction deleted.", "info")
    return redirect(url_for("recurring.list_recurring"))


@recurring_bp.route("/process", methods=["POST"])
@login_required
def process_due():
    result = recurring_service.process_due(g.current_user)
    flash(
        f"Processed {result['processed']} recurring template(s), created "
        f"{result['created']} transaction(s).",
        "success",
    )
    return redirect(request.referrer or url_for("recurring.list_recurring"))
