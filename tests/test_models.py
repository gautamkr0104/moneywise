"""Model tests: constraints, relationships, balance math, budgets (Phase 2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.extensions import db
from app.models import (
    Account,
    AccountType,
    Budget,
    Category,
    RecurringFrequency,
    RecurringTransaction,
    Transaction,
    TransactionType,
    User,
)
from sqlalchemy.exc import IntegrityError


def _make_user(username: str = "alice", email: str = "alice@example.com") -> User:
    user = User(username=username, email=email, password_hash="not-plaintext")
    db.session.add(user)
    db.session.commit()
    return user


def _make_account(
    user: User,
    name: str = "Bank",
    starting_balance: str = "0.00",
) -> Account:
    account = Account(
        user_id=user.id,
        name=name,
        type=AccountType.BANK,
        starting_balance=Decimal(starting_balance),
    )
    db.session.add(account)
    db.session.commit()
    return account


def _make_category(user: User, name: str = "Food") -> Category:
    category = Category(user_id=user.id, name=name, type=TransactionType.EXPENSE)
    db.session.add(category)
    db.session.commit()
    return category


def _add_transaction(
    *,
    user: User,
    account: Account,
    amount: str,
    type_: TransactionType,
    description: str = "test",
    category: Category | None = None,
    txn_date: date = date(2026, 8, 15),
    to_account: Account | None = None,
) -> Transaction:
    txn = Transaction(
        user_id=user.id,
        account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        category_id=category.id if category else None,
        amount=Decimal(amount),
        type=type_,
        description=description,
        date=txn_date,
    )
    db.session.add(txn)
    db.session.commit()
    return txn


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


def test_create_user(app):
    user = _make_user()
    assert user.id is not None
    assert user.currency == "INR"
    assert user in db.session


def test_duplicate_username_rejected(app):
    _make_user(username="alice")
    with pytest.raises(IntegrityError):
        _make_user(username="alice", email="other@example.com")
    db.session.rollback()


def test_duplicate_email_rejected(app):
    _make_user(email="alice@example.com")
    with pytest.raises(IntegrityError):
        _make_user(username="bob", email="alice@example.com")
    db.session.rollback()


def test_deleting_user_cascades_to_owned_data(app):
    user = _make_user()
    account = _make_account(user, starting_balance="100.00")
    category = _make_category(user)
    txn = _add_transaction(
        user=user, account=account, amount="50.00", type_=TransactionType.EXPENSE,
        category=category,
    )
    db.session.add(
        Budget(user_id=user.id, category_id=category.id, year=2026, month=8,
               amount=Decimal("1000"))
    )
    db.session.commit()

    db.session.delete(user)
    db.session.commit()

    assert db.session.get(User, user.id) is None
    assert db.session.get(Account, account.id) is None
    assert db.session.get(Transaction, txn.id) is None
    assert db.session.get(Category, category.id) is None
    assert Budget.query.count() == 0


# ---------------------------------------------------------------------------
# Accounts and balance math
# ---------------------------------------------------------------------------


def test_account_current_balance_from_income_and_expenses(app):
    user = _make_user()
    account = _make_account(user, starting_balance="1000.00")
    _add_transaction(user=user, account=account, amount="500.00",
                     type_=TransactionType.INCOME)
    _add_transaction(user=user, account=account, amount="200.00",
                     type_=TransactionType.EXPENSE)

    assert account.current_balance == Decimal("1300.00")


def test_transfer_moves_money_between_accounts(app):
    user = _make_user()
    source = _make_account(user, name="Bank", starting_balance="1000.00")
    destination = _make_account(user, name="Savings", starting_balance="500.00")

    _add_transaction(
        user=user, account=source, to_account=destination, amount="300.00",
        type_=TransactionType.TRANSFER, description="transfer",
    )

    assert source.current_balance == Decimal("700.00")
    assert destination.current_balance == Decimal("800.00")


def test_amounts_are_exact_decimals_not_floats(app):
    user = _make_user()
    account = _make_account(user)
    txn = _add_transaction(user=user, account=account, amount="123.45",
                           type_=TransactionType.INCOME)

    assert isinstance(txn.amount, Decimal)
    assert isinstance(account.starting_balance, Decimal)
    assert txn.amount == Decimal("123.45")
    assert txn.net_effect == Decimal("123.45")
    assert _add_transaction(
        user=user, account=account, amount="10.00",
        type_=TransactionType.EXPENSE,
    ).net_effect == Decimal("-10.00")


def test_negative_amount_rejected_by_check_constraint(app):
    user = _make_user()
    account = _make_account(user)
    with pytest.raises(IntegrityError):
        _add_transaction(user=user, account=account, amount="-10.00",
                         type_=TransactionType.EXPENSE)
    db.session.rollback()


def test_foreign_keys_enforced(app):
    """The SQLite FK pragma is active: dangling user_id is rejected."""
    txn = Transaction(
        user_id=9999, account_id=9999, amount=Decimal("1.00"),
        type=TransactionType.EXPENSE, description="orphan", date=date(2026, 8, 1),
    )
    db.session.add(txn)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_deleting_account_deletes_its_transactions(app):
    user = _make_user()
    account = _make_account(user)
    txn = _add_transaction(user=user, account=account, amount="10.00",
                           type_=TransactionType.EXPENSE)

    db.session.delete(account)
    db.session.commit()

    assert db.session.get(Transaction, txn.id) is None


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_category_unique_per_user_name_and_type(app):
    user = _make_user()
    _make_category(user, name="Food")
    with pytest.raises(IntegrityError):
        _make_category(user, name="Food")
    db.session.rollback()
    # The same name is fine for a different type...
    other = Category(user_id=user.id, name="Food", type=TransactionType.INCOME)
    db.session.add(other)
    db.session.commit()
    # ...and the same name is fine for a different user.
    bob = _make_user(username="bob", email="bob@example.com")
    _make_category(bob, name="Food")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_budget_spent_remaining_percent(app):
    user = _make_user()
    account = _make_account(user)
    category = _make_category(user, name="Food")
    budget = Budget(
        user_id=user.id, category_id=category.id, year=2026, month=8,
        amount=Decimal("10000.00"),
    )
    db.session.add(budget)
    db.session.commit()

    _add_transaction(user=user, account=account, category=category,
                     amount="2500.00", type_=TransactionType.EXPENSE,
                     txn_date=date(2026, 8, 1))
    _add_transaction(user=user, account=account, category=category,
                     amount="1500.00", type_=TransactionType.EXPENSE,
                     txn_date=date(2026, 8, 10))
    # Outside the budget period - must not count.
    _add_transaction(user=user, account=account, category=category,
                     amount="9999.00", type_=TransactionType.EXPENSE,
                     txn_date=date(2026, 9, 1))
    # Income in the same category - must not count as spending.
    _add_transaction(user=user, account=account, category=category,
                     amount="5000.00", type_=TransactionType.INCOME,
                     txn_date=date(2026, 8, 5))

    assert budget.spent == Decimal("4000.00")
    assert budget.remaining == Decimal("6000.00")
    assert budget.percent_used == Decimal("40.000")
    assert budget.is_exceeded is False


def test_budget_exceeded(app):
    user = _make_user()
    account = _make_account(user)
    category = _make_category(user)
    budget = Budget(
        user_id=user.id, category_id=category.id, year=2026, month=8,
        amount=Decimal("100.00"),
    )
    db.session.add(budget)
    db.session.commit()
    _add_transaction(user=user, account=account, category=category,
                     amount="150.00", type_=TransactionType.EXPENSE)

    assert budget.is_exceeded is True
    assert budget.remaining == Decimal("0")
    assert budget.percent_used == Decimal("150.000")


def test_budget_zero_amount_never_divides_by_zero(app):
    user = _make_user()
    category = _make_category(user)
    budget = Budget(
        user_id=user.id, category_id=category.id, year=2026, month=8,
        amount=Decimal("0.00"),
    )
    db.session.add(budget)
    db.session.commit()
    assert budget.percent_used == Decimal("0")
    assert budget.remaining == Decimal("0")


def test_budget_unique_per_user_category_period(app):
    user = _make_user()
    category = _make_category(user)
    db.session.add(
        Budget(user_id=user.id, category_id=category.id, year=2026, month=8,
               amount=Decimal("1000"))
    )
    db.session.commit()
    with pytest.raises(IntegrityError):
        db.session.add(
            Budget(user_id=user.id, category_id=category.id, year=2026, month=8,
                   amount=Decimal("2000"))
        )
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# Recurring transactions
# ---------------------------------------------------------------------------


def test_recurring_transaction_creation(app):
    user = _make_user()
    account = _make_account(user)
    category = _make_category(user)
    recurring = RecurringTransaction(
        user_id=user.id,
        account_id=account.id,
        category_id=category.id,
        description="Netflix",
        amount=Decimal("499.00"),
        type=TransactionType.EXPENSE,
        frequency=RecurringFrequency.MONTHLY,
        next_due_date=date(2026, 9, 1),
    )
    db.session.add(recurring)
    db.session.commit()

    assert recurring.is_active is True
    assert recurring in user.recurring_transactions
    assert recurring in account.recurring_transactions
