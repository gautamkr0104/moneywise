"""Account model - cash, bank, savings, credit card or investment accounts."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func

from ..extensions import db
from .enums import AccountType, TransactionType, enum_values
from .mixins import TimestampMixin, to_decimal


class Account(TimestampMixin, db.Model):
    """A financial account owned by a user.

    The balance is *computed* from the starting balance plus the signed effect
    of every transaction, rather than stored redundantly.
    """

    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(
        db.Enum(AccountType, values_callable=enum_values, native_enum=False),
        nullable=False,
        default=AccountType.BANK,
    )
    starting_balance = db.Column(
        db.Numeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    currency = db.Column(db.String(3), nullable=False, default="INR")
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", back_populates="accounts")
    transactions = db.relationship(
        "Transaction",
        foreign_keys="Transaction.account_id",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    incoming_transfers = db.relationship(
        "Transaction",
        foreign_keys="Transaction.to_account_id",
        back_populates="to_account",
        cascade="all, delete-orphan",
    )
    recurring_transactions = db.relationship(
        "RecurringTransaction",
        back_populates="account",
        cascade="all, delete-orphan",
    )

    @property
    def current_balance(self) -> Decimal:
        """Starting balance plus the net effect of every transaction.

        Semantics per transaction type on this account:
        * income   -> the account receives ``+amount``
        * expense  -> the account pays ``-amount``
        * transfer -> ``-amount`` when this account is the source,
                      ``+amount`` when it is the destination
        """
        # Lazy import keeps the module graph free of circular imports.
        from .transaction import Transaction

        as_source = (
            func.sum(
                case(
                    (Transaction.type == TransactionType.INCOME, Transaction.amount),
                    else_=Decimal("0"),
                )
            )
            - func.sum(
                case(
                    (Transaction.type != TransactionType.INCOME, Transaction.amount),
                    else_=Decimal("0"),
                )
            )
        )
        source_total = db.session.query(as_source).filter(
            Transaction.account_id == self.id
        ).scalar()

        destination_total = db.session.query(
            func.sum(Transaction.amount)
        ).filter(Transaction.to_account_id == self.id).scalar()

        return (
            to_decimal(self.starting_balance)
            + to_decimal(source_total)
            + to_decimal(destination_total)
        )

    def __repr__(self) -> str:
        return f"<Account {self.name!r} ({self.type.value})>"
