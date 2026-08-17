"""Categories: list, add custom categories, delete custom categories."""

from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..forms import CategoryForm
from ..models import Category, TransactionType
from ..utils import login_required

categories_bp = Blueprint("categories", __name__)


@categories_bp.route("/")
@login_required
def index():
    form = CategoryForm()
    categories = (
        Category.query.filter_by(user_id=g.current_user.id)
        .order_by(Category.is_system.desc(), Category.type.asc(), Category.name.asc())
        .all()
    )
    return render_template("categories/index.html", form=form, categories=categories)


@categories_bp.route("/add", methods=["POST"])
@login_required
def add():
    form = CategoryForm()
    if form.validate_on_submit():
        existing = Category.query.filter_by(
            user_id=g.current_user.id,
            name=form.name.data.strip(),
            type=TransactionType(form.type.data),
        ).first()
        if existing:
            flash("That category already exists.", "error")
            return redirect(url_for("categories.index"))
        db.session.add(
            Category(
                user_id=g.current_user.id,
                name=form.name.data.strip(),
                type=TransactionType(form.type.data),
                is_system=False,
            )
        )
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That category already exists.", "error")
            return redirect(url_for("categories.index"))
        flash("Category added.", "success")
    else:
        for errors in form.errors.values():
            for message in errors:
                flash(message, "error")
    return redirect(url_for("categories.index"))


@categories_bp.route("/<int:category_id>/delete", methods=["POST"])
@login_required
def delete(category_id: int):
    category = db.session.get(Category, category_id)
    if category is None or category.user_id != g.current_user.id:
        flash("Category not found.", "error")
        return redirect(url_for("categories.index"))
    if category.is_system:
        flash("System categories cannot be deleted.", "warning")
        return redirect(url_for("categories.index"))
    name = category.name
    db.session.delete(category)
    db.session.commit()
    flash(f"Category '{name}' deleted.", "info")
    return redirect(url_for("categories.index"))
