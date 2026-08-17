"""WTForms definitions for every web form.

Choices for user-owned data (accounts, categories) are populated in the
routes before rendering so the forms stay generic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    FileField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    EqualTo,
    Length,
    NumberRange,
    Optional,
    Regexp,
)

from .models import AccountType, RecurringFrequency, TransactionType

USERNAME_RE = r"^[A-Za-z0-9_.-]{3,30}$"
#: Pragmatic email check (no external ``email-validator`` dependency).
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
AMOUNT_PLACES = 2


def _money_field(label: str, **kwargs) -> DecimalField:
    return DecimalField(
        label,
        places=AMOUNT_PLACES,
        rounding=ROUND_HALF_UP,
        validators=[
            DataRequired(message="Amount is required."),
            NumberRange(min=0.01, message="Amount must be greater than zero."),
        ],
        render_kw={"step": "0.01", "min": "0.01"},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Regexp(USERNAME_RE, message="3-30 characters: letters, numbers, _ . -"),
        ],
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Regexp(EMAIL_RE, message="Enter a valid email address."),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=8, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match."),
        ],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    identifier = StringField(
        "Username or email",
        validators=[DataRequired(message="Enter your username or email.")],
    )
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password",
        validators=[
            DataRequired(),
            Length(min=8, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Passwords must match."),
        ],
    )
    submit = SubmitField("Update password")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class AccountForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(), Length(max=120)],
    )
    type = SelectField(
        "Type",
        choices=[(m.value, m.name.replace("_", " ").title()) for m in AccountType],
        validators=[DataRequired()],
    )
    starting_balance = _money_field("Starting balance")
    currency = SelectField(
        "Currency",
        choices=[("INR", "INR (₹)"), ("USD", "USD ($)"), ("EUR", "EUR (€)"), ("GBP", "GBP (£)")],
        validators=[DataRequired()],
    )
    is_archived = BooleanField("Archived (hidden from balances)")
    submit = SubmitField("Save account")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionForm(FlaskForm):
    type = SelectField(
        "Type",
        choices=[(m.value, m.name.title()) for m in TransactionType],
        validators=[DataRequired()],
    )
    amount = _money_field("Amount")
    account = SelectField("Account", coerce=int, validators=[DataRequired()])
    to_account = SelectField("Transfer to account", coerce=int, validators=[Optional()])
    category = SelectField("Category", coerce=int, validators=[Optional()])
    description = StringField(
        "Description", validators=[DataRequired(), Length(max=200)]
    )
    date = DateField("Date", format="%Y-%m-%d", validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save transaction")

    def validate(self, extra_validators=None) -> bool:
        """Enforce transfer/category rules that depend on the chosen type."""
        if not super().validate(extra_validators):
            return False

        txn_type = self.type.data
        errors: list[tuple[str, str]] = []

        if txn_type == TransactionType.TRANSFER.value:
            if not self.to_account.data:
                errors.append(("to_account", "A destination account is required for a transfer."))
            elif self.to_account.data == self.account.data:
                errors.append(("to_account", "Destination must be different from the source account."))
            if self.category.data:
                errors.append(("category", "Transfers do not use a category."))
        else:
            if not self.category.data:
                errors.append(("category", "A category is required for income and expenses."))
            if self.to_account.data:
                errors.append(("to_account", "Only transfers use a destination account."))

        for field_name, message in errors:
            self.errors.setdefault(field_name, []).append(message)
        return not errors


class TransactionFilterForm(FlaskForm):
    """Read-only filter panel for the transactions list (GET form)."""

    q = StringField("Search", validators=[Optional(), Length(max=100)])
    type = SelectField(
        "Type",
        choices=[("", "All types"), *[(m.value, m.name.title()) for m in TransactionType]],
        validators=[Optional()],
    )
    account = SelectField("Account", coerce=int, validators=[Optional()])
    category = SelectField("Category", coerce=int, validators=[Optional()])
    date_from = DateField("From", format="%Y-%m-%d", validators=[Optional()])
    date_to = DateField("To", format="%Y-%m-%d", validators=[Optional()])
    min_amount = DecimalField(
        "Min amount", places=AMOUNT_PLACES, validators=[Optional()]
    )
    max_amount = DecimalField(
        "Max amount", places=AMOUNT_PLACES, validators=[Optional()]
    )
    sort = SelectField(
        "Sort by",
        choices=[("date", "Date"), ("amount", "Amount"), ("description", "Description")],
        validators=[Optional()],
    )
    order = SelectField(
        "Order", choices=[("desc", "Newest first"), ("asc", "Oldest first")]
    )
    submit = SubmitField("Apply filters")


class CsvImportForm(FlaskForm):
    file = FileField(
        "CSV file",
        validators=[DataRequired(message="Choose a CSV file.")],
    )
    submit = SubmitField("Preview import")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class BudgetForm(FlaskForm):
    month = SelectField(
        "Month",
        choices=[(str(m), f"{m:02d}") for m in range(1, 13)],
        validators=[DataRequired()],
    )
    year = SelectField("Year", choices=[], validators=[DataRequired()])
    category = SelectField("Category", coerce=int, validators=[DataRequired()])
    amount = _money_field("Monthly budget")
    submit = SubmitField("Save budget")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class CategoryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=80)])
    type = SelectField(
        "Type",
        choices=[(m.value, m.name.title()) for m in TransactionType
                 if m is not TransactionType.TRANSFER],
        validators=[DataRequired()],
    )
    submit = SubmitField("Add category")


# ---------------------------------------------------------------------------
# Recurring transactions
# ---------------------------------------------------------------------------


class RecurringForm(FlaskForm):
    description = StringField("Description", validators=[DataRequired(), Length(max=200)])
    amount = _money_field("Amount")
    type = SelectField(
        "Type",
        choices=[(m.value, m.name.title()) for m in TransactionType
                 if m is not TransactionType.TRANSFER],
        validators=[DataRequired()],
    )
    category = SelectField("Category", coerce=int, validators=[DataRequired()])
    account = SelectField("Account", coerce=int, validators=[DataRequired()])
    frequency = SelectField(
        "Frequency",
        choices=[(m.value, m.name.title()) for m in RecurringFrequency],
        validators=[DataRequired()],
    )
    next_due_date = DateField("Next due date", format="%Y-%m-%d", validators=[DataRequired()])
    is_active = BooleanField("Active")
    submit = SubmitField("Save recurring transaction")

    def validate(self, extra_validators=None) -> bool:
        if not super().validate(extra_validators):
            return False
        if self.next_due_date.data is not None and self.next_due_date.data.year < 2000:
            self.errors["next_due_date"] = ["Pick a realistic date."]
            return False
        return True


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class ReportPeriodForm(FlaskForm):
    period = SelectField(
        "Period",
        choices=[
            ("current_month", "Current month"),
            ("last_month", "Last month"),
            ("current_year", "Current year"),
            ("custom", "Custom range"),
        ],
        validators=[DataRequired()],
    )
    month = SelectField("Month", choices=[(str(m), f"{m:02d}") for m in range(1, 13)])
    year = SelectField("Year", choices=[])
    date_from = DateField("From", format="%Y-%m-%d", validators=[Optional()])
    date_to = DateField("To", format="%Y-%m-%d", validators=[Optional()])
    submit = SubmitField("Show report")



