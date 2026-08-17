"""REST API tests (Phase 11)."""

from __future__ import annotations

import json

from app.models import Account, Category, Transaction, TransactionType, User
from conftest import make_account


def _post_json(client, path, data):
    return client.post(path, json=data)


def _api_login(client, identifier="alice", password="password123"):
    return client.post(
        "/api/auth/login",
        json={"identifier": identifier, "password": password},
    )


def _register_api(client, username="alice", email="alice@example.com"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": "password123"},
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_api_register_and_login(client):
    response = _register_api(client)
    assert response.status_code == 201
    assert response.get_json()["user"]["username"] == "alice"

    client.post("/api/auth/logout")
    response = _api_login(client)
    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == "alice@example.com"


def test_api_login_rejects_bad_credentials(client):
    _register_api(client)
    client.post("/api/auth/logout")
    response = _api_login(client, password="wrong")
    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_credentials"


def test_api_register_conflict(client):
    _register_api(client)
    response = _register_api(client, email="other@example.com")
    assert response.status_code == 409


def test_api_requires_auth(client):
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/transactions").status_code == 401
    assert client.post("/api/accounts", json={}).status_code == 401
    assert client.get("/api/reports/monthly").status_code == 401


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_api_account_crud(client):
    _register_api(client)

    created = client.post(
        "/api/accounts",
        json={"name": "Savings", "type": "savings", "starting_balance": "1000.50"},
    )
    assert created.status_code == 201
    account = created.get_json()["account"]
    assert account["name"] == "Savings"
    assert account["starting_balance"] == 1000.5
    account_id = account["id"]

    listed = client.get("/api/accounts")
    assert listed.status_code == 200
    assert len(listed.get_json()["accounts"]) == 1

    updated = client.put(
        f"/api/accounts/{account_id}",
        json={"name": "High Yield", "type": "savings",
              "starting_balance": "2000.00", "currency": "USD"},
    )
    assert updated.status_code == 200
    assert updated.get_json()["account"]["name"] == "High Yield"
    assert updated.get_json()["account"]["currency"] == "USD"

    deleted = client.delete(f"/api/accounts/{account_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/accounts/{account_id}").status_code == 404


def test_api_account_validation_errors(client):
    _register_api(client)
    response = client.post("/api/accounts", json={"name": "", "type": "nonsense"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "validation_error"
    assert body["details"]


def test_api_cannot_see_other_users_accounts(client):
    _register_api(client, username="alice")
    client.post("/api/auth/logout")
    _register_api(client, username="bob", email="bob@example.com")

    with client.application.app_context():
        alice = User.query.filter_by(username="alice").first()
        alice_account = make_account(alice, name="Secret")
        alice_account_id = alice_account.id

    response = client.get(f"/api/accounts/{alice_account_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def _seed_transaction_data(client):
    """Returns (account_id, category_id) via the API."""
    _register_api(client)
    account = client.post(
        "/api/accounts", json={"name": "Bank", "type": "bank"}
    ).get_json()["account"]
    categories = client.get("/api/categories").get_json()["categories"]
    food = next(c for c in categories if c["name"] == "Food")
    return account["id"], food["id"]


def test_api_transaction_crud(client):
    account_id, food_id = _seed_transaction_data(client)

    created = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": food_id,
            "amount": "250.50",
            "type": "expense",
            "description": "Groceries",
            "date": "2026-08-10",
        },
    )
    assert created.status_code == 201
    txn = created.get_json()["transaction"]
    assert txn["amount"] == 250.5
    assert txn["category_name"] == "Food"
    txn_id = txn["id"]

    fetched = client.get(f"/api/transactions/{txn_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["transaction"]["description"] == "Groceries"

    updated = client.put(
        f"/api/transactions/{txn_id}",
        json={
            "account_id": account_id,
            "category_id": food_id,
            "amount": "300.00",
            "type": "expense",
            "description": "Groceries+",
            "date": "2026-08-11",
        },
    )
    assert updated.status_code == 200
    assert updated.get_json()["transaction"]["amount"] == 300.0

    assert client.delete(f"/api/transactions/{txn_id}").status_code == 200
    assert client.get(f"/api/transactions/{txn_id}").status_code == 404


def test_api_transaction_transfer(client):
    account_id, _ = _seed_transaction_data(client)
    savings = client.post(
        "/api/accounts", json={"name": "Savings", "type": "savings"}
    ).get_json()["account"]

    created = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "to_account_id": savings["id"],
            "amount": "500.00",
            "type": "transfer",
            "description": "To savings",
            "date": "2026-08-12",
        },
    )
    assert created.status_code == 201
    assert created.get_json()["transaction"]["to_account_name"] == "Savings"


def test_api_transaction_validation(client):
    account_id, _ = _seed_transaction_data(client)
    # Transfer without a destination.
    response = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "amount": "10.00",
            "type": "transfer",
            "description": "Bad",
            "date": "2026-08-01",
        },
    )
    assert response.status_code == 400
    # Expense without a category.
    response = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "amount": "10.00",
            "type": "expense",
            "description": "Bad",
            "date": "2026-08-01",
        },
    )
    assert response.status_code == 400
    # Negative amount.
    response = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "amount": "-5.00",
            "type": "expense",
            "description": "Bad",
            "date": "2026-08-01",
        },
    )
    assert response.status_code == 400


def test_api_transaction_filters(client):
    account_id, food_id = _seed_transaction_data(client)
    for i, amount in enumerate(["100.00", "200.00", "300.00"]):
        client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "category_id": food_id,
                "amount": amount,
                "type": "expense",
                "description": f"Txn {i}",
                "date": f"2026-08-0{i + 1}",
            },
        )

    response = client.get(
        f"/api/transactions?type=expense&min_amount=150&max_amount=350"
    )
    body = response.get_json()
    assert body["total"] == 2
    assert [t["amount"] for t in body["transactions"]] == [300.0, 200.0]


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_api_budget_crud(client):
    _, food_id = _seed_transaction_data(client)
    created = client.post(
        "/api/budgets",
        json={"category_id": food_id, "year": 2026, "month": 8, "amount": "10000.00"},
    )
    assert created.status_code == 201
    budget = created.get_json()["budget"]
    assert budget["amount"] == 10000.0
    assert budget["status"] == "ok"
    budget_id = budget["id"]

    listed = client.get("/api/budgets?year=2026&month=8")
    assert listed.status_code == 200
    assert len(listed.get_json()["budgets"]) == 1

    updated = client.put(
        f"/api/budgets/{budget_id}",
        json={"category_id": food_id, "year": 2026, "month": 8, "amount": "15000.00"},
    )
    assert updated.get_json()["budget"]["amount"] == 15000.0

    assert client.delete(f"/api/budgets/{budget_id}").status_code == 200


def test_api_budget_duplicate_conflict(client):
    _, food_id = _seed_transaction_data(client)
    client.post(
        "/api/budgets",
        json={"category_id": food_id, "year": 2026, "month": 8, "amount": "100.00"},
    )
    response = client.post(
        "/api/budgets",
        json={"category_id": food_id, "year": 2026, "month": 8, "amount": "200.00"},
    )
    assert response.status_code == 400
    assert "already exists" in response.get_json()["message"]


# ---------------------------------------------------------------------------
# Recurring
# ---------------------------------------------------------------------------


def test_api_recurring_crud_and_process(client):
    account_id, food_id = _seed_transaction_data(client)
    created = client.post(
        "/api/recurring",
        json={
            "description": "Netflix",
            "amount": "499.00",
            "type": "expense",
            "account_id": account_id,
            "category_id": food_id,
            "frequency": "monthly",
            "next_due_date": "2026-08-01",
        },
    )
    assert created.status_code == 201
    recurring_id = created.get_json()["recurring"]["id"]

    processed = client.post("/api/recurring/process")
    assert processed.status_code == 200
    assert processed.get_json()["created"] == 1

    with client.application.app_context():
        assert Transaction.query.count() == 1

    assert client.delete(f"/api/recurring/{recurring_id}").status_code == 200


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_api_monthly_report(client):
    account_id, food_id = _seed_transaction_data(client)
    client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": food_id,
            "amount": "200.00",
            "type": "expense",
            "description": "Food",
            "date": "2026-08-05",
        },
    )
    response = client.get("/api/reports/monthly?year=2026&month=8")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total_expenses"] == 200.0
    assert body["spending_by_category"]["Food"] == 200.0


def test_api_category_report(client):
    account_id, food_id = _seed_transaction_data(client)
    client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": food_id,
            "amount": "50.00",
            "type": "expense",
            "description": "Snack",
            "date": "2026-08-06",
        },
    )
    response = client.get("/api/reports/categories?year=2026&month=8")
    assert response.status_code == 200
    assert response.get_json()["spending_by_category"]["Food"] == 50.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_api_404_is_json(client):
    _register_api(client)
    response = client.get("/api/nonexistent")
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_api_unknown_route_is_json_for_api_prefix(client):
    response = client.get("/api/whatever")
    assert response.status_code == 404
    assert response.is_json


def test_api_rejects_invalid_json(client):
    _register_api(client)
    response = client.post(
        "/api/accounts", data="not json", content_type="application/json"
    )
    assert response.status_code == 400
