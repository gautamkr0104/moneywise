"""Settings: change password, default currency."""

from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, url_for

from ..extensions import db
from ..forms import ChangePasswordForm
from ..utils import login_required

settings_bp = Blueprint("settings", __name__)

CURRENCIES = [
    ("INR", "INR (₹)"),
    ("USD", "USD ($)"),
    ("EUR", "EUR (€)"),
    ("GBP", "GBP (£)"),
]


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    user = g.current_user
    password_form = ChangePasswordForm()
    saved = False

    if password_form.validate_on_submit():
        if not user.check_password(password_form.current_password.data):
            flash("Current password is incorrect.", "error")
        else:
            user.set_password(password_form.new_password.data)
            db.session.commit()
            flash("Password updated.", "success")
            saved = True

    return render_template(
        "settings/index.html",
        password_form=password_form,
        currencies=CURRENCIES,
        saved=saved,
    )


@settings_bp.route("/currency", methods=["POST"])
@login_required
def update_currency():
    from flask import request

    currency = request.form.get("currency", "INR")
    if currency not in {c[0] for c in CURRENCIES}:
        flash("Invalid currency.", "error")
        return redirect(url_for("settings.index"))
    g.current_user.currency = currency
    db.session.commit()
    flash("Default currency updated.", "success")
    return redirect(url_for("settings.index"))
