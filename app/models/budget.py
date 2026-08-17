"""Budget model - a monthly spending limit for one category."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func

from ..extensions import db
from .enums import TransactionType
from .mixins import TimestampMixin, to_decimal


class Budget(TimestampMixin, db.Model):
    """A monthly budget: the amount a user plans to spend in a category.

    Spent / remaining / percent-used are computed from the user's expense
    transactions for the budget's year and month, never stored.
    """

    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "category_id",
            "year",
            "month",
            name="uq_budgets_user_category_period",
        ),
        db.CheckConstraint("amount >= 0", name="ck_budgets_amount_non_negative"),
        db.CheckConstraint("month BETWEEN 1 AND 12", name="ck_budgets_month_range"),
    )

    user = db.relationship("User", back_populates="budgets")
    category = db.relationship("Category", back_populates="budgets")

    @property
    def spent(self) -> Decimal:
        """Total expenses in this category during the budget period."""
        from .transaction import Transaction  # lazy import avoids cycles

        total = db.session.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).filter(
            Transaction.user_id == self.user_id,
            Transaction.category_id == self.category_id,
            Transaction.type == TransactionType.EXPENSE,
            func.extract("year", Transaction.date) == self.year,
            func.extract("month", Transaction.date) == self.month,
        ).scalar()
        return to_decimal(total)

    @property
    def remaining(self) -> Decimal:
        """Budgeted amount minus spending, floored at zero."""
        return max(to_decimal(self.amount) - self.spent, Decimal("0"))

    @property
    def percent_used(self) -> Decimal:
        """Spending as a percentage of the budget (0-100+)."""
        if to_decimal(self.amount) == 0:
            return Decimal("0")
        return (self.spent / to_decimal(self.amount)) * Decimal("100")

    @property
    def is_exceeded(self) -> bool:
        return self.spent > to_decimal(self.amount)

    def __repr__(self) -> str:
        return f"<Budget {self.year}-{self.month:02d} {self.amount}>"
