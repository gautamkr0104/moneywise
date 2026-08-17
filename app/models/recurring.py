"""RecurringTransaction model - scheduled, repeating transactions."""

from __future__ import annotations

from ..extensions import db
from .enums import RecurringFrequency, TransactionType, enum_values
from .mixins import TimestampMixin


class RecurringTransaction(TimestampMixin, db.Model):
    """A transaction template that repeats on a schedule (e.g. monthly rent).

    The :func:`app.services.recurring_service` (later phase) turns due
    templates into real :class:`Transaction` rows and advances
    ``next_due_date``.
    """

    __tablename__ = "recurring_transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    type = db.Column(
        db.Enum(TransactionType, values_callable=enum_values, native_enum=False),
        nullable=False,
    )
    frequency = db.Column(
        db.Enum(RecurringFrequency, values_callable=enum_values, native_enum=False),
        nullable=False,
        default=RecurringFrequency.MONTHLY,
    )
    next_due_date = db.Column(db.Date, nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_recurring_amount_positive"),
    )

    user = db.relationship("User", back_populates="recurring_transactions")
    account = db.relationship("Account", back_populates="recurring_transactions")
    category = db.relationship("Category", back_populates="recurring_transactions")

    def __repr__(self) -> str:
        return f"<Recurring {self.description!r} {self.frequency.value} due {self.next_due_date}>"
