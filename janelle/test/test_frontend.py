from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_loads_transaction_rows_with_htmx():
    index = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")
    page = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "transactions_page.jinja"
    ).read_text(encoding="utf-8")

    assert "htmx.org@2.0.10" in index
    assert 'hx-get="/transactions-backend/ui/transactions/page"' in index
    assert 'id="transactions-table"' in page
    assert 'id="transactions"' in page
    assert (
        'hx-get="/transactions-backend/ui/transactions?page=1"'
        in page
    )
    assert 'hx-trigger="load, transactionsChanged from:body"' in page
    assert 'hx-include="#transaction-filters, #transactions-page-size"' in page
    assert 'hx-swap="outerHTML"' in page
    assert "<th>ID</th>" not in page
    assert 'colspan="5"' in page


def test_transaction_table_has_page_size_and_navigation_controls():
    table = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "transactions_table.jinja"
    ).read_text(encoding="utf-8")

    assert 'id="transactions-page-size"' in table
    assert 'name="page_size"' in table
    assert "{% for size in page_sizes %}" in table
    assert '<option value="{{ size }}"' in table
    assert 'id="previous-transactions-page"' in table
    assert 'aria-label="Previous page"' in table
    assert "&larr;" in table
    assert 'id="next-transactions-page"' in table
    assert 'aria-label="Next page"' in table
    assert "&rarr;" in table
    assert "Page {{ page }} of {{ total_pages }}" in table
    assert table.count(
        'hx-include="#transaction-filters, #transactions-page-size"'
    ) == 3


def test_transaction_page_has_search_category_and_date_filters():
    page = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "transactions_page.jinja"
    ).read_text(encoding="utf-8")

    assert 'id="transaction-filters"' in page
    assert 'id="transaction-search"' in page
    assert 'type="search"' in page
    assert 'name="search"' in page
    assert 'placeholder="Search transactions"' in page
    assert 'id="transaction-category-filter"' in page
    assert 'name="category_id"' in page
    assert "All categories" in page
    assert "{% for category in categories %}" in page
    assert 'id="transaction-date-filter"' in page
    assert 'name="date_range"' in page
    assert "All dates" in page
    assert "Last 7 days" in page
    assert "Last 30 days" in page
    assert "Last 90 days" in page
    assert "This month" in page
    assert "This year" in page
    assert 'hx-target="#transactions-table"' in page
    assert 'hx-include="#transactions-page-size"' in page


def test_transaction_pagination_uses_compact_single_row_layout():
    index = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")
    pagination_styles = index.split(
        ".transactions-pagination {",
        1,
    )[1].split(".transaction-form-screen", 1)[0]
    mobile_styles = index.split("@media (max-width: 700px)", 1)[1]

    assert "flex-wrap: nowrap;" in pagination_styles
    assert "width: 4.5rem !important;" in pagination_styles
    assert ".transactions-pagination," not in mobile_styles
    assert ".transactions-page-details," not in mobile_styles
    assert ".transactions-page-count {" in mobile_styles
    assert "display: none;" in mobile_styles


def test_add_transaction_button_loads_jinja_form_with_htmx():
    page = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "transactions_page.jinja"
    ).read_text(encoding="utf-8")

    assert 'id="add-transaction-button"' in page
    assert 'type="button"' in page
    assert 'hx-get="/transactions-backend/ui/transactions/new"' in page
    assert 'hx-target="#transactions-content"' in page
    assert 'hx-swap="outerHTML"' in page
    assert "+ Add transaction" in page


def test_transaction_form_contains_required_fields_and_htmx_actions():
    form = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "transaction_form.jinja"
    ).read_text(encoding="utf-8")

    assert 'id="add-transaction-form"' in form
    assert 'hx-post="/transactions-backend/ui/transactions"' in form
    assert 'hx-target="#transactions-content"' in form
    assert 'hx-swap="outerHTML"' in form
    assert 'hx-disabled-elt="#save-transaction-button"' in form
    assert "Back to transactions" in form
    assert 'hx-get="/transactions-backend/ui/transactions/page"' in form
    assert 'id="transaction-date"' in form
    assert 'name="date"' in form
    assert 'type="date"' in form
    assert 'id="transaction-amount"' in form
    assert 'name="amount"' in form
    assert 'type="number"' in form
    assert 'step="0.01"' in form
    assert 'id="transaction-merchant"' in form
    assert 'name="merchant"' in form
    assert 'id="transaction-description"' in form
    assert 'name="description"' in form
    assert 'id="transaction-category"' in form
    assert 'name="category_id"' in form
    assert 'id="save-transaction-button"' in form
    assert form.count("required") == 5


def test_frontend_places_ask_tally_below_the_transaction_table():
    page = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "transactions_page.jinja"
    ).read_text(encoding="utf-8")
    panel = (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "chat_panel.jinja"
    ).read_text(encoding="utf-8")

    assert 'id="transaction-chat-panel"' in page
    assert 'hx-get="/transactions-backend/ui/chat"' in page
    assert page.index('id="transactions"') < page.index(
        'id="transaction-chat-panel"'
    )
    assert ">Ask Tally</h2>" in panel
    assert "What did I spend at Woolworths in August?" in panel
    assert "Show my biggest purchases in August" in panel
    assert "How much did eating out cost me last week?" in panel
    assert 'placeholder="Ask about your transactions..."' in panel
    assert panel.count("hx-on::before-request") == 3
    assert (
        "document.getElementById('transaction-chat-input').value = ''"
        in panel
    )
    assert "Biggest purchases" in (
        REPOSITORY_ROOT
        / "janelle"
        / "backend"
        / "templates"
        / "chat_result.jinja"
    ).read_text(encoding="utf-8")


def test_frontend_proxies_only_to_backend():
    nginx = (
        REPOSITORY_ROOT / "janelle" / "frontend" / "nginx.conf"
    ).read_text(encoding="utf-8")

    assert "location /transactions-backend/" in nginx
    assert "proxy_pass http://transactions-backend:5001/;" in nginx
    assert "transactions-db" not in nginx


def test_shared_shell_proxies_transactions_backend_through_frontend():
    nginx = (
        REPOSITORY_ROOT / "shared" / "frontend" / "nginx.conf"
    ).read_text(encoding="utf-8")
    location_start = nginx.index("location /transactions-backend/")
    location_end = nginx.index("\n    }", location_start)
    transactions_location = nginx[location_start:location_end]

    assert "proxy_pass ${TRANSACTIONS_FRONTEND_URL};" in transactions_location


def test_compose_sets_twenty_second_database_timeout():
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "DATABASE_TIMEOUT_SECONDS: 20" in compose


def test_compose_configures_pr4_chat_services():
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    transactions_backend = compose.split("\n  transactions-backend:", 1)[1].split(
        "\n  transactions-db:",
        1,
    )[0]
    assert "OLLAMA_URL: http://ollama:11434" in transactions_backend
    assert "CHAT_MODEL: qwen2.5:3b" in transactions_backend
    assert "AI_TIMEOUT_SECONDS: 90" in transactions_backend
    assert "ollama:" in transactions_backend
    assert "condition: service_healthy" in transactions_backend
