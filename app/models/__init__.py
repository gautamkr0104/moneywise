"""SQLAlchemy models.

Importing this package registers every table on the shared ``db`` metadata,
which is what lets ``db.create_all()`` and Flask-Migrate see the schema.
Model files use string-based relationship targets and lazy imports inside
properties, so there are no circular imports between them.
"""

from .account import Account
from .budget import Budget
from .category import DEFAULT_CATEGORIES, Category
from .enums import AccountType, RecurringFrequency, TransactionType, enum_values
from .mixins import TimestampMixin, to_decimal, utcnow
from .recurring import RecurringTransaction
from .transaction import Transaction
from .user import User

__all__ = [
    "Account",
    "AccountType",
    "Budget",
    "Category",
    "DEFAULT_CATEGORIES",
    "RecurringFrequency",
    "RecurringTransaction",
    "TimestampMixin",
    "Transaction",
    "TransactionType",
    "User",
    "enum_values",
    "to_decimal",
    "utcnow",
]
