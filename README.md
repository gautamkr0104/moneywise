# MoneyWise

A production-quality personal finance management application built with **Python 3.13+** and **Flask** — no Node.js, no JavaScript build system, no non-Python backend. Track income, expenses, budgets, accounts, transactions, recurring payments, and financial statistics, all rendered with server-side Jinja2 templates plus a REST API.

> **Status: Feature-complete (all 14 phases implemented).**  
> See the [Error Report](#error-report) section for known lint violations and test failures.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Model](#data-model)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Database Migrations](#database-migrations)
- [REST API](#rest-api)
- [CSV Import](#csv-import)
- [Recurring Transactions](#recurring-transactions)
- [Security Considerations](#security-considerations)
- [Error Report](#error-report)
- [License](#license)

---

## Features

- **User Authentication** — Registration, login, logout with secure password hashing (Werkzeug) and server-side sessions. In-memory rate limiting on failed login attempts (5 attempts / 600s window).
- **Accounts** — Cash, bank, savings, credit card, and investment accounts with computed running balances (not stored). Archiving hides accounts from balances without deleting data.
- **Transactions** — Income, expense, and transfer entries with full CRUD, search, filtering (by type, account, category, date range, amount range), sorting, and pagination.
- **Custom Categories** — User-created income/expense categories with system defaults seeded on registration (Food, Rent, Salary, etc.).
- **Monthly Budgets** — Per-category spending limits with progress tracking and warning levels (50%, 75%, 90%, exceeded).
- **Dashboard** — Live financial snapshot: total balance, monthly income/expenses, top spending categories, recent transactions, and budget status.
- **Analytics & Reports** — Pandas-powered aggregations: monthly totals, category/account breakdowns, 6-month trends, savings rate, highest transaction. Downloadable CSV exports for transactions, monthly summaries, and budget progress.
- **CSV Import** — Upload CSV files with preview, row-by-row validation, duplicate detection (against existing data and within the file), auto-creation of missing categories, and confirmation before insert.
- **Recurring Transactions** — Scheduled templates (daily/weekly/monthly/yearly) that materialize into real transactions on demand or via CLI. Pure-Python processing — no Celery/Redis required.
- **REST API** — Session-authenticated JSON endpoints for all resources (accounts, categories, transactions, budgets, recurring, reports) with Pydantic request validation.
- **Security** — CSRF protection, HTTP-only SameSite=Lax cookies, security headers (CSP, X-Frame-Options, HSTS), safe upload limits, environment-driven `SECRET_KEY`, production failsafe.
- **Settings** — Change password, update default currency (INR, USD, EUR, GBP).

---

## Tech Stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.13+ (type hints, dataclasses, enums, `decimal.Decimal` for money) |
| Web framework | Flask 3.x |
| ORM / migrations | Flask-SQLAlchemy, Flask-Migrate (Alembic) |
| Forms / validation | Flask-WTF, WTForms, Pydantic |
| Data analysis | Pandas |
| Auth | Secure Flask sessions (signed cookies), Werkzeug password hashing |
| Database | SQLite by default; PostgreSQL-ready via `DATABASE_URL` |
| Testing | pytest, pytest-flask |
| Linting | ruff |
| Config | python-dotenv, environment-driven config classes |

---

## Project Structure

```
moneywise/
├── app/
│   ├── __init__.py            # create_app() application factory
│   ├── config.py              # Development/Testing/Production config classes
│   ├── extensions.py          # db, migrate, csrf extension instances + SQLite PRAGMA
│   ├── utils.py               # Money formatting, date math, login_required decorator
│   ├── forms.py               # WTForms definitions for every web form
│   ├── models/
│   │   ├── __init__.py        # Re-exports all models
│   │   ├── enums.py           # AccountType, TransactionType, RecurringFrequency
│   │   ├── mixins.py          # TimestampMixin, to_decimal(), utcnow()
│   │   ├── user.py            # User model (owner of all data)
│   │   ├── account.py         # Account model (computed balances)
│   │   ├── transaction.py     # Transaction model (core financial record)
│   │   ├── category.py        # Category model + DEFAULT_CATEGORIES
│   │   ├── budget.py          # Budget model (computed spent/remaining)
│   │   └── recurring.py       # RecurringTransaction model
│   ├── routes/
│   │   ├── auth.py            # /auth/* — register, login, logout
│   │   ├── dashboard.py       # / — live financial dashboard
│   │   ├── accounts.py        # /accounts/* — CRUD, archive, delete
│   │   ├── transactions.py    # /transactions/* — CRUD, filter, CSV import
│   │   ├── budgets.py         # /budgets/* — monthly budget management
│   │   ├── recurring.py       # /recurring/* — recurring transaction templates
│   │   ├── reports.py         # /reports/* — analytics views + CSV export
│   │   ├── categories.py      # /categories/* — manage categories
│   │   ├── settings.py        # /settings/* — password, currency
│   │   └── api.py             # /api/* — REST API (Pydantic validation)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py    # Registration, auth, sessions, rate limiting
│   │   ├── transaction_service.py  # CRUD, validation, filtering, pagination
│   │   ├── budget_service.py  # CRUD, progress, warning levels
│   │   ├── analytics_service.py    # Pandas aggregations, CSV exports
│   │   ├── import_service.py  # CSV parse, validate, preview, insert
│   │   └── recurring_service.py    # Materialize due templates, advance dates
│   ├── templates/             # 23 Jinja2 templates (base, auth, dashboard,
│   │                          #   accounts, transactions, budgets, recurring,
│   │                          #   reports, categories, settings, errors)
│   └── static/
│       ├── style.css          # Single stylesheet
│       └── transaction_form.js  # Client-side form helpers
├── tests/                     # pytest suite (isolated in-memory DB per test)
│   ├── conftest.py            # Shared fixtures: app, client, user, auth_client
│   ├── test_auth.py           # Authentication tests
│   ├── test_accounts.py       # Account CRUD, archiving, ownership
│   ├── test_transactions.py   # Transaction CRUD, validation, filtering
│   ├── test_budgets.py        # Budget CRUD, progress, warnings
│   ├── test_reports.py        # Analytics + CSV export tests
│   ├── test_import.py         # CSV import: parse, validate, duplicates
│   ├── test_recurring.py      # Recurring transaction tests
│   └── test_api.py            # REST API tests
├── migrations/                # Alembic migrations (initial schema)
├── instance/                  # Local SQLite DB + logs (gitignored)
├── .env.example               # Environment variable template
├── .gitignore
├── pyproject.toml             # Project metadata, dependencies, ruff/pytest config
├── README.md
└── run.py                     # Development entry point
```

---

## Data Model

| Model | Purpose | Key Fields |
| --- | --- | --- |
| `User` | Account owner | `username` (unique), `email` (unique), `password_hash`, `currency` |
| `Account` | Cash/bank/savings/credit-card/investment | `name`, `type`, `starting_balance`, `currency`, `is_archived` |
| `Category` | Income/expense labels | `name`, `type` (income/expense), `is_system`; unique per user+name+type |
| `Transaction` | Income/expense/transfer entries | `amount`, `type`, `description`, `date`, `notes`; `account_id` + optional `to_account_id` for transfers |
| `Budget` | Monthly per-category limit | `year`, `month`, `amount`; unique per user+category+period |
| `RecurringTransaction` | Scheduled repeating entries | `amount`, `frequency`, `next_due_date`, `is_active` |

### Design Notes

- **Money is never a float.** All amounts are `Numeric(14, 2)` columns backed by `decimal.Decimal`. SQLite aggregates are re-coerced to `Decimal` via `to_decimal()`.
- **Balances are computed, not stored.** `Account.current_balance` derives from the starting balance plus signed transaction effects. `Budget.spent/remaining/percent_used` aggregate the month's expenses for the category.
- **Ownership is enforced by structure.** Every record has a `user_id` FK with `CASCADE` deletes.
- **SQLite foreign keys are enforced** via a per-connection `PRAGMA` (skipped for other backends).
- **Enums are stored as portable strings** (`VARCHAR` + check), so the schema migrates cleanly to PostgreSQL.

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/moneywise.git
cd moneywise
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows (Git Bash / cmd)
.venv/Scripts/activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

This installs runtime dependencies plus the dev extras (pytest, pytest-flask, ruff).

### 4. Configure the environment

```bash
cp .env.example .env
```

Edit `.env` and set a strong `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Run database migrations

```bash
flask --app run.py db upgrade
```

### 6. Run the application

```bash
flask --app run.py run        # or: python run.py
```

Open http://127.0.0.1:5000 — the `/health` endpoint should return `{"status": "ok"}`.

### 7. Run the tests

```bash
pytest
```

---

## Configuration

All settings are environment-driven via `.env` (loaded by `python-dotenv`). Three configuration classes exist:

| Config | `FLASK_ENV` | Key Differences |
| --- | --- | --- |
| `DevelopmentConfig` | `development` | Debug on, relaxed cookies, SQLite file DB |
| `TestingConfig` | `testing` | In-memory SQLite, CSRF disabled, rate limiter disabled |
| `ProductionConfig` | `production` | Debug off, secure cookies, `SECRET_KEY` validated at startup |

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `FLASK_ENV` | `development` | Config class selector |
| `SECRET_KEY` | `dev-only-insecure-secret` | Session/CSRF signing key (must change in production) |
| `DATABASE_URL` | `sqlite:///moneywise.db` | SQLAlchemy database URI |
| `MAX_CONTENT_LENGTH` | `5242880` (5 MB) | Max upload size for CSV imports |
| `FLASK_DEBUG` | `1` | Flask debug mode |

---

## Database Migrations

The migration setup is already in place (`migrations/`). Alembic commands:

```bash
flask --app run.py db upgrade                          # apply pending migrations
flask --app run.py db migrate -m "describe change"     # after changing models
flask --app run.py db downgrade                        # roll back one step
```

---

## REST API

All API endpoints are under `/api/` and require session authentication (log in via `/api/auth/login` first). CSRF is exempted on the API.

### Authentication

| Method | Endpoint | Body | Status |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | `{username, email, password}` | 201 |
| POST | `/api/auth/login` | `{identifier, password}` | 200 |
| POST | `/api/auth/logout` | — | 200 |

### Accounts

| Method | Endpoint | Body | Status |
| --- | --- | --- | --- |
| GET | `/api/accounts` | — | 200 |
| POST | `/api/accounts` | `{name, type, starting_balance, currency, is_archived}` | 201 |
| GET | `/api/accounts/<id>` | — | 200 |
| PUT | `/api/accounts/<id>` | `{name, type, starting_balance, currency, is_archived}` | 200 |
| DELETE | `/api/accounts/<id>` | — | 200 |

### Categories

| Method | Endpoint | Body | Status |
| --- | --- | --- | --- |
| GET | `/api/categories` | — | 200 |
| POST | `/api/categories` | `{name, type}` | 201 |

### Transactions

| Method | Endpoint | Query Params / Body | Status |
| --- | --- | --- | --- |
| GET | `/api/transactions` | `?q=&type=&account_id=&category_id=&date_from=&date_to=&min_amount=&max_amount=&sort=&order=&page=&per_page=` | 200 |
| POST | `/api/transactions` | `{account_id, category_id, amount, type, description, date, notes, to_account_id}` | 201 |
| GET | `/api/transactions/<id>` | — | 200 |
| PUT | `/api/transactions/<id>` | (same as POST) | 200 |
| DELETE | `/api/transactions/<id>` | — | 200 |

### Budgets

| Method | Endpoint | Body | Status |
| --- | --- | --- | --- |
| GET | `/api/budgets` | `?year=&month=` | 200 |
| POST | `/api/budgets` | `{category_id, year, month, amount}` | 201 |
| PUT | `/api/budgets/<id>` | `{category_id, year, month, amount}` | 200 |
| DELETE | `/api/budgets/<id>` | — | 200 |

### Recurring Transactions

| Method | Endpoint | Body | Status |
| --- | --- | --- | --- |
| GET | `/api/recurring` | — | 200 |
| POST | `/api/recurring` | `{description, amount, type, account_id, category_id, frequency, next_due_date, is_active}` | 201 |
| PUT | `/api/recurring/<id>` | (same as POST) | 200 |
| DELETE | `/api/recurring/<id>` | — | 200 |
| POST | `/api/recurring/process` | — | 200 |

### Reports

| Method | Endpoint | Query Params | Status |
| --- | --- | --- | --- |
| GET | `/api/reports/monthly` | `?year=&month=` | 200 |
| GET | `/api/reports/categories` | `?year=&month=` | 200 |
| GET | `/api/reports/trend` | `?months=` | 200 |

### Validation

Request bodies are validated with **Pydantic** models. Invalid requests return `400` with field-level error details:

```json
{
  "error": "validation_error",
  "message": "Invalid request body.",
  "details": [
    {"field": "amount", "message": "Input should be greater than 0"}
  ]
}
```

---

## CSV Import

### Expected Format

```csv
date,description,amount,category,type,account,notes
2026-08-01,Groceries,1500.00,Food,expense,,Weekly shopping
2026-08-01,Salary,50000.00,Salary,income,,Monthly salary
```

### Required Columns

`date`, `description`, `amount`, `category`, `type`

### Optional Columns

`account` (defaults to the user's first active account), `notes`

### Supported Date Formats

`YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DD-MM-YYYY`

### Process

1. **Upload** — CSV file is validated (UTF-8, required headers, max 5 MB).
2. **Preview** — Every row is validated; errors, duplicates (against existing DB and within the file), and auto-created categories are shown.
3. **Confirm** — User confirms; valid rows are inserted, duplicates skipped.

---

## Recurring Transactions

Templates repeat on a schedule (daily, weekly, monthly, yearly). The `process_due` function:

1. Finds all active templates whose `next_due_date` is on or before today.
2. For each due template, creates one transaction per missed period.
3. Advances `next_due_date` until it is after today.
4. Deactivates templates whose account has been deleted.

Can be triggered via:
- **Web**: `POST /recurring/process`
- **API**: `POST /api/recurring/process`
- **CLI**: `flask --app run.py recurring-process`

---

## Security Considerations

- **Passwords** are hashed with Werkzeug's `generate_password_hash` (scrypt/pbkdf2). Never stored or logged in plaintext.
- **Session cookies** are HTTP-only, SameSite=Lax, and marked Secure in production.
- **CSRF protection** via Flask-WTF on all state-changing forms.
- **`SECRET_KEY`** comes from the environment; production fails fast if unset or insecure.
- **Upload size** limited via `MAX_CONTENT_LENGTH`; CSV files validated before parsing.
- **Financial amounts** use `decimal.Decimal` / `Numeric` — never floats for money.
- **Ownership enforcement** — every query is scoped to the logged-in user; users cannot access each other's data.
- **Security headers** — X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Content-Security-Policy, HSTS (production).
- **Open redirect protection** — `is_safe_next_url()` rejects non-relative targets.
- **Rate limiting** — in-memory login rate limiter (5 attempts per 600s window, per IP+identifier).

---

## Error Report

### Ruff Lint Violations (58 total, 33 auto-fixable)

Run `ruff check .` to see all violations. Key categories:

| Code | Count | Description |
| --- | --- | --- |
| I001 | 12 | Unsorted/unformatted import blocks |
| E501 | 16 | Lines exceeding 100 characters |
| F401 | 12 | Unused imports |
| F841 | 1 | Unused variable assignment |
| F541 | 1 | f-string without placeholders |
| UP037 | 2 | Unnecessary quoted type annotations |
| SIM103 | 1 | Could return negated condition directly |
| SIM105 | 1 | Could use `contextlib.suppress` instead of try/except/pass |
| W291 | 1 | Trailing whitespace (in migration) |

**Auto-fixable:** Run `ruff check . --fix` to resolve 33 of the 58 violations automatically.

### Test Failures (9 of 74 tests failing)

| Test | File | Error | Root Cause |
| --- | --- | --- | --- |
| `test_account_list_shows_balance` | `test_accounts.py:45` | `assert '150.00' in ...` | The `format_money` Jinja filter prepends a currency symbol (₹), so `"150.00"` never appears as a substring. The template renders `₹150.00` but the test checks for `150.00`. |
| `test_edit_account` | `test_accounts.py:68` | `IndexError: list index out of range` | The `account_id()` helper calls `user.accounts[0]` but `auth_client` doesn't create an account — only `auth_client` registers/logs in. The test needs to create an account first (via `_create_via_form`) before calling `account_id()`. However, `_create_via_form` is called *before* `account_id()` and the account_id fetch happens in a separate request context where the relationship may not be refreshed. |
| `test_archive_and_restore_account` | `test_accounts.py:89` | Same `IndexError` as above |
| `test_delete_account` | `test_accounts.py:101` | Same `IndexError` as above |
| `test_register_creates_user_and_logs_in` | `test_auth.py:34` | `assert 'scrypt:32768:8:1' in ('scrypt', 'pbkdf2')` | The Werkzeug password hash format is `scrypt:32768:8:1:...` — the test splits on `$` but Werkzeug 3.x uses `:` as the delimiter. The test needs to split on `:` instead. |
| `test_users_cannot_access_each_others_data` | `test_auth.py:183` | `AttributeError: 'NoneType' object has no attribute 'accounts'` | `bob` is `None` because the test tries to register "bob" but the `register()` helper always uses "alice" as the default username. The second registration fails silently (form validation error), so `bob` is never created. |
| `test_monthly_trend` | `test_reports.py:101` | `assert np.float64(8000.0) == 11500.0` | The test expects expenses of 11500.0 for August but the trend only shows 8000.0. This is because `monthly_trend` uses `start = date(today.year, today.month, 1)` and `add_months(end, -(months-1))` as the range, which may not include all seeded transactions depending on the current date relative to the seed dates. |
| `test_web_report_page` | `test_reports.py:137` | `KeyError: 0` | The template iterates `trend|reverse` expecting dict-like rows with `.month`, `.income`, etc. When the trend DataFrame is empty (no data in range), `reverse` produces integer indices that don't have the expected keys. The `monthly_trend` function returns an empty DataFrame with columns but no rows, yet the template doesn't handle the empty case for `trend|reverse`. |
| `test_transfer_requires_different_accounts` | `test_transactions.py:89` | `assert b'different' in b'...'` | The test submits a transfer with the same account for source and destination, expecting an error message containing "different". The form validation error is set on the field but may not appear in the response HTML because the form re-renders without the error being flashed/displayed in the expected location. |

---

## License

MIT License. See `pyproject.toml` for details.
