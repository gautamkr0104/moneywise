"""Category model - income/expense categories, system-provided or custom."""

from __future__ import annotations

from ..extensions import db
from .enums import TransactionType, enum_values
from .mixins import TimestampMixin

#: Categories created automatically for every new user.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "income": ["Salary", "Freelance", "Investment", "Other"],
    "expense": [
        "Food",
        "Transport",
        "Rent",
        "Utilities",
        "Shopping",
        "Entertainment",
        "Healthcare",
        "Education",
        "Other",
    ],
}


class Category(TimestampMixin, db.Model):
    """A user's spending/saving category, flagged when it is a system default."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(80), nullable=False)
    #: Only income/expense categories exist; transfers use accounts, not categories.
    type = db.Column(
        db.Enum(TransactionType, values_callable=enum_values, native_enum=False),
        nullable=False,
    )
    is_system = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "name", "type", name="uq_categories_user_name_type"
        ),
    )

    user = db.relationship("User", back_populates="categories")
    transactions = db.relationship("Transaction", back_populates="category")
    budgets = db.relationship(
        "Budget", back_populates="category", cascade="all, delete-orphan"
    )
    recurring_transactions = db.relationship(
        "RecurringTransaction", back_populates="category"
    )

    def __repr__(self) -> str:
        return f"<Category {self.name!r} ({self.type.value})>"
