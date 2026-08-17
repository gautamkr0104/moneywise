"""REST API.

Session-authenticated JSON endpoints with Pydantic request validation.
Requests bodies that fail validation return ``400`` with the field errors;
ownership is enforced by scoping every query to the logged-in user.

CSRF is exempted on the API (same-origin tooling use case); see the README
security section for the trade-off and production guidance.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import wraps

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ..extensions import csrf, db
from ..models import (
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
from ..services import (
    analytics_service,
    auth_service,
    budget_service,
    recurring_service,
    transaction_service,
)

api_bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("current_user") is None:
            return jsonify(
                {"error": "unauthorized", "message": "Authentication required."}
            ), 401
        return view(*args, **kwargs)

    return wrapped


def _route(rule, *, auth=True, **options):
    """Shorthand: register an API route with auth + CSRF exemptions."""

    def decorator(view):
        if auth:
            view = _api_login_required(view)
        view = csrf.exempt(view)
        return api_bp.route(rule, **options)(view)

    return decorator


def _payload(model_cls: type[BaseModel]):
    """Parse + validate the JSON body with a Pydantic model, or return 400."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, jsonify(
            {"error": "invalid_request", "message": "A JSON object body is required."}
        ), 400
    try:
        return model_cls.model_validate(data), None, None
    except ValidationError as exc:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return None, jsonify(
            {"error": "validation_error", "message": "Invalid request body.", "details": errors}
        ), 400


def _account_json(account: Account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type.value,
        "starting_balance": account.starting_balance,
        "current_balance": account.current_balance,
        "currency": account.currency,
        "is_archived": account.is_archived,
        "created_at": account.created_at,
    }


def _category_json(category: Category) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "type": category.type.value,
        "is_system": category.is_system,
    }


def _transaction_json(txn: Transaction) -> dict:
    return {
        "id": txn.id,
        "type": txn.type.value,
        "amount": txn.amount,
        "account_id": txn.account_id,
        "account_name": txn.account.name if txn.account else None,
        "to_account_id": txn.to_account_id,
        "to_account_name": txn.to_account.name if txn.to_account else None,
        "category_id": txn.category_id,
        "category_name": txn.category.name if txn.category else None,
        "description": txn.description,
        "date": txn.date,
        "notes": txn.notes,
        "created_at": txn.created_at,
    }


def _budget_json(budget: Budget) -> dict:
    status = budget_service.budget_status(budget)
    return {
        "id": budget.id,
        "category_id": budget.category_id,
        "category_name": budget.category.name if budget.category else None,
        "year": budget.year,
        "month": budget.month,
        "amount": budget.amount,
        "spent": status["spent"],
        "remaining": status["remaining"],
        "percent_used": status["percent_used"],
        "status": status["level"],
    }


def _recurring_json(recurring: RecurringTransaction) -> dict:
    return {
        "id": recurring.id,
        "description": recurring.description,
        "amount": recurring.amount,
        "type": recurring.type.value,
        "account_id": recurring.account_id,
        "account_name": recurring.account.name if recurring.account else None,
        "category_id": recurring.category_id,
        "category_name": recurring.category.name if recurring.category else None,
        "frequency": recurring.frequency.value,
        "next_due_date": recurring.next_due_date,
        "is_active": recurring.is_active,
    }


# ---------------------------------------------------------------------------
# Request models (Pydantic)
# ---------------------------------------------------------------------------


class LoginIn(BaseModel):
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    starting_balance: Decimal = Field(default=Decimal("0.00"), ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    is_archived: bool = False


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: TransactionType

    @field_validator("type")
    @classmethod
    def no_transfers(cls, value: TransactionType) -> TransactionType:
        if value is TransactionType.TRANSFER:
            raise ValueError("Categories can only be income or expense.")
        return value


class TransactionIn(BaseModel):
    account_id: int
    to_account_id: int | None = None
    category_id: int | None = None
    amount: Decimal = Field(gt=0)
    type: TransactionType
    description: str = Field(min_length=1, max_length=200)
    date: date
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def type_rules(self):
        if self.type is TransactionType.TRANSFER:
            if self.to_account_id is None:
                raise ValueError("to_account_id is required for transfers.")
            if self.to_account_id == self.account_id:
                raise ValueError("to_account_id must differ from account_id.")
        else:
            if self.category_id is None:
                raise ValueError("category_id is required for income and expenses.")
        return self


class BudgetIn(BaseModel):
    category_id: int
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    amount: Decimal = Field(ge=0)


class RecurringIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0)
    type: TransactionType
    account_id: int
    category_id: int
    frequency: RecurringFrequency
    next_due_date: date
    is_active: bool = True

    @field_validator("type")
    @classmethod
    def no_transfers(cls, value: TransactionType) -> TransactionType:
        if value is TransactionType.TRANSFER:
            raise ValueError("Recurring transfers are not supported.")
        return value


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@_route("/auth/login", methods=["POST"], auth=False)
def api_login():
    payload, error, status = _payload(LoginIn)
    if error:
        return error, status
    identifier = payload.identifier
    user = auth_service.authenticate(identifier, payload.password)
    if user is None:
        auth_service.record_failed_attempt(identifier, request.remote_addr or "unknown")
        return jsonify({"error": "invalid_credentials", "message": "Invalid credentials."}), 401
    auth_service.clear_attempts(identifier, request.remote_addr or "unknown")
    auth_service.log_in(user)
    return jsonify({"message": "Logged in.", "user": _user_json(user)}), 200


@_route("/auth/register", methods=["POST"], auth=False)
def api_register():
    payload, error, status = _payload(RegisterIn)
    if error:
        return error, status
    try:
        user = auth_service.register_user(payload.username, payload.email, payload.password)
    except ValueError as exc:
        return jsonify({"error": "conflict", "message": str(exc)}), 409
    auth_service.log_in(user)
    return jsonify({"message": "Registered.", "user": _user_json(user)}), 201


@_route("/auth/logout", methods=["POST"])
def api_logout():
    auth_service.log_out()
    return jsonify({"message": "Logged out."}), 200


def _user_json(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "currency": user.currency,
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@_route("/accounts", methods=["GET"])
def api_list_accounts():
    accounts = (
        Account.query.filter_by(user_id=g.current_user.id)
        .order_by(Account.created_at.asc())
        .all()
    )
    return jsonify({"accounts": [_account_json(a) for a in accounts]}), 200


@_route("/accounts", methods=["POST"])
def api_create_account():
    payload, error, status = _payload(AccountIn)
    if error:
        return error, status
    account = Account(
        user_id=g.current_user.id,
        name=payload.name.strip(),
        type=payload.type,
        starting_balance=payload.starting_balance,
        currency=payload.currency,
        is_archived=payload.is_archived,
    )
    db.session.add(account)
    db.session.commit()
    return jsonify({"account": _account_json(account)}), 201


def _account_or_404(account_id: int) -> Account | None:
    account = db.session.get(Account, account_id)
    if account is None or account.user_id != g.current_user.id:
        return None
    return account


@_route("/accounts/<int:account_id>", methods=["GET"])
def api_get_account(account_id: int):
    account = _account_or_404(account_id)
    if account is None:
        return jsonify({"error": "not_found", "message": "Account not found."}), 404
    return jsonify({"account": _account_json(account)}), 200


@_route("/accounts/<int:account_id>", methods=["PUT"])
def api_update_account(account_id: int):
    account = _account_or_404(account_id)
    if account is None:
        return jsonify({"error": "not_found", "message": "Account not found."}), 404
    payload, error, status = _payload(AccountIn)
    if error:
        return error, status
    account.name = payload.name.strip()
    account.type = payload.type
    account.starting_balance = payload.starting_balance
    account.currency = payload.currency
    account.is_archived = payload.is_archived
    db.session.commit()
    return jsonify({"account": _account_json(account)}), 200


@_route("/accounts/<int:account_id>", methods=["DELETE"])
def api_delete_account(account_id: int):
    account = _account_or_404(account_id)
    if account is None:
        return jsonify({"error": "not_found", "message": "Account not found."}), 404
    db.session.delete(account)
    db.session.commit()
    return jsonify({"message": "Account deleted."}), 200


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@_route("/categories", methods=["GET"])
def api_list_categories():
    categories = (
        Category.query.filter_by(user_id=g.current_user.id)
        .order_by(Category.type.asc(), Category.name.asc())
        .all()
    )
    return jsonify({"categories": [_category_json(c) for c in categories]}), 200


@_route("/categories", methods=["POST"])
def api_create_category():
    payload, error, status = _payload(CategoryIn)
    if error:
        return error, status
    existing = Category.query.filter_by(
        user_id=g.current_user.id, name=payload.name.strip(), type=payload.type
    ).first()
    if existing:
        return jsonify({"error": "conflict", "message": "Category already exists."}), 409
    category = Category(
        user_id=g.current_user.id,
        name=payload.name.strip(),
        type=payload.type,
        is_system=False,
    )
    db.session.add(category)
    db.session.commit()
    return jsonify({"category": _category_json(category)}), 201


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


@_route("/transactions", methods=["GET"])
def api_list_transactions():
    args = request.args
    filters = {
        "q": args.get("q"),
        "txn_type": args.get("type"),
        "account_id": _int_arg(args.get("account_id")),
        "category_id": _int_arg(args.get("category_id")),
        "date_from": _date_arg(args.get("date_from")),
        "date_to": _date_arg(args.get("date_to")),
        "min_amount": _decimal_arg(args.get("min_amount")),
        "max_amount": _decimal_arg(args.get("max_amount")),
        "sort": args.get("sort", "date"),
        "order": args.get("order", "desc"),
    }
    page = max(_int_arg(args.get("page", "1")) or 1, 1)
    per_page = min(max(_int_arg(args.get("per_page", "25")) or 25, 1), 100)

    pagination = transaction_service.paginate_transactions(
        g.current_user, page=page, per_page=per_page, **filters
    )
    return jsonify(
        {
            "transactions": [_transaction_json(t) for t in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
            "per_page": pagination.per_page,
        }
    ), 200


def _int_arg(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_arg(value) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _decimal_arg(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


@_route("/transactions", methods=["POST"])
def api_create_transaction():
    payload, error, status = _payload(TransactionIn)
    if error:
        return error, status
    try:
        txn = transaction_service.create_transaction(
            g.current_user,
            amount=payload.amount,
            txn_type=payload.type,
            account_id=payload.account_id,
            to_account_id=payload.to_account_id,
            category_id=payload.category_id,
            description=payload.description,
            txn_date=payload.date,
            notes=payload.notes,
        )
    except transaction_service.TransactionValidationError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    return jsonify({"transaction": _transaction_json(txn)}), 201


def _transaction_or_404(txn_id: int) -> Transaction | None:
    return transaction_service.get_user_transaction(g.current_user, txn_id)


@_route("/transactions/<int:txn_id>", methods=["GET"])
def api_get_transaction(txn_id: int):
    txn = _transaction_or_404(txn_id)
    if txn is None:
        return jsonify({"error": "not_found", "message": "Transaction not found."}), 404
    return jsonify({"transaction": _transaction_json(txn)}), 200


@_route("/transactions/<int:txn_id>", methods=["PUT"])
def api_update_transaction(txn_id: int):
    txn = _transaction_or_404(txn_id)
    if txn is None:
        return jsonify({"error": "not_found", "message": "Transaction not found."}), 404
    payload, error, status = _payload(TransactionIn)
    if error:
        return error, status
    try:
        transaction_service.update_transaction(
            g.current_user,
            txn,
            amount=payload.amount,
            txn_type=payload.type,
            account_id=payload.account_id,
            to_account_id=payload.to_account_id,
            category_id=payload.category_id,
            description=payload.description,
            date=payload.date,
            notes=payload.notes,
        )
    except transaction_service.TransactionValidationError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    return jsonify({"transaction": _transaction_json(txn)}), 200


@_route("/transactions/<int:txn_id>", methods=["DELETE"])
def api_delete_transaction(txn_id: int):
    txn = _transaction_or_404(txn_id)
    if txn is None:
        return jsonify({"error": "not_found", "message": "Transaction not found."}), 404
    transaction_service.delete_transaction(txn)
    return jsonify({"message": "Transaction deleted."}), 200


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@_route("/budgets", methods=["GET"])
def api_list_budgets():
    year = _int_arg(request.args.get("year")) or date.today().year
    month = _int_arg(request.args.get("month")) or date.today().month
    budgets = budget_service.budgets_for_period(g.current_user, year, month)
    return jsonify(
        {"year": year, "month": month, "budgets": [_budget_json(b) for b in budgets]}
    ), 200


@_route("/budgets", methods=["POST"])
def api_create_budget():
    payload, error, status = _payload(BudgetIn)
    if error:
        return error, status
    try:
        budget = budget_service.create_budget(
            g.current_user,
            category_id=payload.category_id,
            year=payload.year,
            month=payload.month,
            amount=payload.amount,
        )
    except budget_service.BudgetValidationError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    return jsonify({"budget": _budget_json(budget)}), 201


def _budget_or_404(budget_id: int) -> Budget | None:
    return budget_service.get_user_budget(g.current_user, budget_id)


@_route("/budgets/<int:budget_id>", methods=["PUT"])
def api_update_budget(budget_id: int):
    budget = _budget_or_404(budget_id)
    if budget is None:
        return jsonify({"error": "not_found", "message": "Budget not found."}), 404
    payload, error, status = _payload(BudgetIn)
    if error:
        return error, status
    try:
        budget_service.update_budget(g.current_user, budget, amount=payload.amount)
    except budget_service.BudgetValidationError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    return jsonify({"budget": _budget_json(budget)}), 200


@_route("/budgets/<int:budget_id>", methods=["DELETE"])
def api_delete_budget(budget_id: int):
    budget = _budget_or_404(budget_id)
    if budget is None:
        return jsonify({"error": "not_found", "message": "Budget not found."}), 404
    budget_service.delete_budget(budget)
    return jsonify({"message": "Budget deleted."}), 200


# ---------------------------------------------------------------------------
# Recurring transactions
# ---------------------------------------------------------------------------


@_route("/recurring", methods=["GET"])
def api_list_recurring():
    items = (
        RecurringTransaction.query.filter_by(user_id=g.current_user.id)
        .order_by(RecurringTransaction.next_due_date.asc())
        .all()
    )
    return jsonify({"recurring": [_recurring_json(r) for r in items]}), 200


@_route("/recurring", methods=["POST"])
def api_create_recurring():
    payload, error, status = _payload(RecurringIn)
    if error:
        return error, status
    try:
        recurring = recurring_service.create_recurring(
            g.current_user,
            description=payload.description,
            amount=payload.amount,
            txn_type=payload.type,
            account_id=payload.account_id,
            category_id=payload.category_id,
            frequency=payload.frequency,
            next_due_date=payload.next_due_date,
            is_active=payload.is_active,
        )
    except recurring_service.RecurringValidationError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    return jsonify({"recurring": _recurring_json(recurring)}), 201


@_route("/recurring/<int:recurring_id>", methods=["PUT"])
def api_update_recurring(recurring_id: int):
    recurring = recurring_service.get_user_recurring(g.current_user, recurring_id)
    if recurring is None:
        return jsonify({"error": "not_found", "message": "Recurring not found."}), 404
    payload, error, status = _payload(RecurringIn)
    if error:
        return error, status
    try:
        recurring_service.update_recurring(
            recurring,
            description=payload.description.strip(),
            amount=payload.amount,
            type=payload.type,
            account_id=payload.account_id,
            category_id=payload.category_id,
            frequency=payload.frequency,
            next_due_date=payload.next_due_date,
            is_active=payload.is_active,
        )
    except recurring_service.RecurringValidationError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    return jsonify({"recurring": _recurring_json(recurring)}), 200


@_route("/recurring/<int:recurring_id>", methods=["DELETE"])
def api_delete_recurring(recurring_id: int):
    recurring = recurring_service.get_user_recurring(g.current_user, recurring_id)
    if recurring is None:
        return jsonify({"error": "not_found", "message": "Recurring not found."}), 404
    recurring_service.delete_recurring(recurring)
    return jsonify({"message": "Recurring deleted."}), 200


@_route("/recurring/process", methods=["POST"])
def api_process_recurring():
    result = recurring_service.process_due(g.current_user)
    return jsonify({"processed": result["processed"], "created": result["created"]}), 200


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@_route("/reports/monthly", methods=["GET"])
def api_monthly_report():
    today = date.today()
    year = _int_arg(request.args.get("year")) or today.year
    month = _int_arg(request.args.get("month")) or today.month
    report = analytics_service.monthly_report(g.current_user, year, month)
    return jsonify({"year": year, "month": month, **_report_json(report)}), 200


@_route("/reports/categories", methods=["GET"])
def api_category_report():
    today = date.today()
    year = _int_arg(request.args.get("year")) or today.year
    month = _int_arg(request.args.get("month")) or today.month
    report = analytics_service.monthly_report(g.current_user, year, month)
    return jsonify(
        {
            "year": year,
            "month": month,
            "spending_by_category": _series_json(report["spending_by_category"]),
            "income_by_category": _series_json(report["income_by_category"]),
            "highest_spending_category": report["highest_spending_category"],
        }
    ), 200


@_route("/reports/trend", methods=["GET"])
def api_trend_report():
    months = min(max(_int_arg(request.args.get("months")) or 6, 1), 24)
    trend = analytics_service.monthly_trend(g.current_user, months=months)
    return jsonify(
        {
            "months": months,
            "trend": trend.to_dict(orient="records"),
        }
    ), 200


def _report_json(report: dict) -> dict:
    return {
        "total_income": report["total_income"],
        "total_expenses": report["total_expenses"],
        "total_transfers": report["total_transfers"],
        "savings": report["savings"],
        "savings_rate": report["savings_rate"],
        "spending_by_category": _series_json(report["spending_by_category"]),
        "spending_by_account": _series_json(report["spending_by_account"]),
        "highest_spending_category": report["highest_spending_category"],
        "highest_transaction": report["highest_transaction"],
        "transaction_count": report["transaction_count"],
    }


def _series_json(series) -> dict:
    return {str(name): float(value) for name, value in series.items()}
