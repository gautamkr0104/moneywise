"""User model - the root owner of every piece of financial data."""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .mixins import TimestampMixin


class User(TimestampMixin, db.Model):
    """A registered MoneyWise user.

    All financial records (accounts, categories, transactions, budgets,
    recurring transactions) belong to a user and are cascade-deleted with
    them, so a user can never see another user's data.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    #: Preferred currency code (ISO 4217), used as a default for new accounts.
    currency = db.Column(db.String(3), nullable=False, default="INR")

    accounts = db.relationship(
        "Account", back_populates="user", cascade="all, delete-orphan"
    )
    categories = db.relationship(
        "Category", back_populates="user", cascade="all, delete-orphan"
    )
    transactions = db.relationship(
        "Transaction", back_populates="user", cascade="all, delete-orphan"
    )
    budgets = db.relationship(
        "Budget", back_populates="user", cascade="all, delete-orphan"
    )
    recurring_transactions = db.relationship(
        "RecurringTransaction", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        """Hash and store a password (never store plaintext)."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify a plaintext password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"
