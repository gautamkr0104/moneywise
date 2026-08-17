"""Authentication routes: register, login, logout."""

from __future__ import annotations

import logging

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from ..forms import LoginForm, RegisterForm
from ..services import auth_service
from ..utils import is_safe_next_url, login_required

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if g.get("current_user") is not None:
        return redirect(url_for("dashboard.index"))

    form = RegisterForm()
    if form.validate_on_submit():
        try:
            user = auth_service.register_user(
                form.username.data, form.email.data, form.password.data
            )
        except ValueError as exc:
            form.username.errors.append(str(exc))
            flash(str(exc), "error")
            return render_template("auth/register.html", form=form)

        auth_service.log_in(user)
        flash(f"Welcome, {user.username}! Your account is ready.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("current_user") is not None:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.identifier.data
        client_ip = request.remote_addr or "unknown"

        if auth_service.is_locked_out(identifier, client_ip):
            logger.warning("login blocked by rate limit: identifier=%s ip=%s", identifier, client_ip)
            flash("Too many failed attempts. Please try again later.", "error")
            return render_template("auth/login.html", form=form), 429

        user = auth_service.authenticate(identifier, form.password.data)
        if user is None:
            auth_service.record_failed_attempt(identifier, client_ip)
            logger.warning("login failed: identifier=%s ip=%s", identifier, client_ip)
            flash("Invalid username/email or password.", "error")
            return render_template("auth/login.html", form=form), 401

        auth_service.clear_attempts(identifier, client_ip)
        auth_service.log_in(user)
        flash(f"Welcome back, {user.username}!", "success")

        target = request.args.get("next")
        if is_safe_next_url(target):
            return redirect(target)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    auth_service.log_out()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
