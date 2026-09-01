from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_loads_transaction_rows_with_htmx():
    index = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")

    assert "htmx.org@2.0.10" in index
    assert 'id="transactions"' in index
    assert 'hx-get="/transactions-backend/transactions"' in index
    assert 'hx-trigger="load"' in index
    assert 'hx-swap="innerHTML"' in index
    assert "<th>ID</th>" not in index
    assert 'colspan="5"' in index


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
