"""Accounts: list, detail, create, edit, archive, delete."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..extensions import db
from ..forms import AccountForm
from ..models import Account, Transaction
from ..utils import format_money, login_required

accounts_bp = Blueprint("accounts", __name__)


def _user_account_or_404(account_id: int) -> Account:
    account = db.session.get(Account, account_id)
    if account is None or account.user_id != g.current_user.id:
        abort(404)
    return account


@accounts_bp.route("/")
@login_required
def list_accounts():
    accounts = (
        Account.query.filter_by(user_id=g.current_user.id)
        .order_by(Account.is_archived.asc(), Account.created_at.asc())
        .all()
    )
    rows = [
        {"account": a, "balance": a.current_balance, "balance_formatted": format_money(a.current_balance, a.currency)}
        for a in accounts
    ]
    return render_template("accounts/list.html", rows=rows)


@accounts_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_account():
    form = AccountForm()
    if form.validate_on_submit():
        account = Account(
            user_id=g.current_user.id,
            name=form.name.data.strip(),
            type=form.type.data,
            starting_balance=Decimal(form.starting_balance.data or 0),
            currency=form.currency.data,
            is_archived=form.is_archived.data,
        )
        db.session.add(account)
        db.session.commit()
        flash(f"Account '{account.name}' created.", "success")
        return redirect(url_for("accounts.detail", account_id=account.id))
    return render_template("accounts/form.html", form=form, title="New account")


@accounts_bp.route("/<int:account_id>")
@login_required
def detail(account_id: int):
    account = _user_account_or_404(account_id)
    transactions = (
        Transaction.query.filter_by(user_id=g.current_user.id)
        .filter(
            (Transaction.account_id == account.id)
            | (Transaction.to_account_id == account.id)
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(15)
        .all()
    )
    return render_template(
        "accounts/detail.html",
        account=account,
        balance=account.current_balance,
        transactions=transactions,
    )


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def edit(account_id: int):
    account = _user_account_or_404(account_id)
    form = AccountForm(obj=account)
    if form.validate_on_submit():
        account.name = form.name.data.strip()
        account.type = form.type.data
        account.starting_balance = Decimal(form.starting_balance.data or 0)
        account.currency = form.currency.data
        account.is_archived = form.is_archived.data
        db.session.commit()
        flash(f"Account '{account.name}' updated.", "success")
        return redirect(url_for("accounts.detail", account_id=account.id))
    return render_template("accounts/form.html", form=form, title="Edit account", account=account)


@accounts_bp.route("/<int:account_id>/archive", methods=["POST"])
@login_required
def archive(account_id: int):
    account = _user_account_or_404(account_id)
    account.is_archived = not account.is_archived
    db.session.commit()
    state = "archived" if account.is_archived else "restored"
    flash(f"Account '{account.name}' {state}.", "info")
    return redirect(request.referrer or url_for("accounts.list_accounts"))


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@login_required
def delete(account_id: int):
    account = _user_account_or_404(account_id)
    name = account.name
    db.session.delete(account)
    db.session.commit()
    flash(f"Account '{name}' deleted (its transactions were removed too).", "info")
    return redirect(url_for("accounts.list_accounts"))
