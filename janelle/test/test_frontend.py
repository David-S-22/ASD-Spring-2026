from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_loads_transaction_rows_with_htmx():
    index = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")

    assert "htmx.org@2.0.10" in index
    assert 'id="transactions"' in index
    assert 'hx-get="/transactions-backend/ui/transactions"' in index
    assert 'hx-trigger="load, transactionsChanged"' in index
    assert 'hx-swap="innerHTML"' in index
    assert "<th>ID</th>" not in index
    assert 'colspan="5"' in index


def test_frontend_has_add_transaction_screen_and_back_button():
    index = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")

    assert 'id="add-transaction-button"' in index
    assert 'onclick="showAddTransactionScreen()"' in index
    assert 'id="transaction-form-screen"' in index
    assert 'onclick="showTransactionList()"' in index
    assert "Back to transactions" in index
    assert 'id="transaction-date"' in index
    assert 'id="transaction-amount"' in index
    assert 'id="transaction-merchant"' in index
    assert 'id="transaction-description"' in index
    assert 'id="transaction-category"' in index
    assert 'id="save-transaction-button"' in index


def test_frontend_loads_categories_and_posts_transaction_to_backend():
    index = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")

    assert "fetch('/transactions-backend/categories')" in index
    assert "fetch('/transactions-backend/transactions'" in index
    assert "method: 'POST'" in index
    assert "headers: {'Content-Type': 'application/json'}" in index
    assert "body: JSON.stringify(payload)" in index
    assert "amount: Number(formData.get('amount'))" in index
    assert "category_id: Number(formData.get('category_id'))" in index
    assert "document.getElementById('transactions')" in index
    assert "'transactionsChanged'" in index
    assert "transactions-db" not in index


def test_frontend_proxies_only_to_backend():
    nginx = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "nginx.conf"
    ).read_text(encoding="utf-8")

    assert "location /transactions-backend/" in nginx
    assert "proxy_pass http://transactions-backend:5001/;" in nginx
    assert "transactions-db" not in nginx


def test_compose_sets_twenty_second_database_timeout():
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "DATABASE_TIMEOUT_SECONDS: 20" in compose
