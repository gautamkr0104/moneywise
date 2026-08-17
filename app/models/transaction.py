"""Transaction model - the core financial record."""

from __future__ import annotations

from decimal import Decimal

from ..extensions import db
from .enums import TransactionType, enum_values
from .mixins import TimestampMixin, to_decimal


class Transaction(TimestampMixin, db.Model):
    """A single income, expense or transfer entry.

    ``amount`` is always positive; the *direction* of money is expressed by
    ``type``:

    * ``income``  - money into ``account``
    * ``expense`` - money out of ``account``
    * ``transfer``- money out of ``account`` into ``to_account``

    Amounts are stored as ``Numeric(14, 2)`` (exact ``Decimal``), never float.
    """

    __tablename__ = "transactions"

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
    #: Destination account, required only for transfers.
    to_account_id = db.Column(
        db.Integer,
        db.ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    #: Optional category (not used for transfers).
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    type = db.Column(
        db.Enum(TransactionType, values_callable=enum_values, native_enum=False),
        nullable=False,
    )
    description = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )

    user = db.relationship("User", back_populates="transactions")
    account = db.relationship(
        "Account", foreign_keys=[account_id], back_populates="transactions"
    )
    to_account = db.relationship(
        "Account", foreign_keys=[to_account_id], back_populates="incoming_transfers"
    )
    category = db.relationship("Category", back_populates="transactions")

    @property
    def net_effect(self) -> Decimal:
        """Signed effect of this transaction on its source account.

        Income adds the amount; expenses and transfers subtract it.  The
        destination account of a transfer sees ``+amount`` separately.
        """
        if self.type is TransactionType.INCOME:
            return to_decimal(self.amount)
        return -to_decimal(self.amount)

    def __repr__(self) -> str:
        return (
            f"<Transaction {self.description!r} "
            f"{self.type.value} {self.amount} @ {self.date}>"
        )
