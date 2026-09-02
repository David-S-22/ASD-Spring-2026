from pathlib import Path


def test_budgets_frontend_contains_overview_screen():
    index_html = Path("ethan/frontend/public/index.html").read_text(encoding="utf-8")

    assert "Budget overview" in index_html
    assert 'id="budget-month-select"' in index_html
    assert 'id="previous-budget-month-button"' in index_html
    assert 'id="next-budget-month-button"' in index_html
    assert 'id="show-add-budget-line-button"' in index_html
    assert 'id="budget-line-form"' in index_html
    assert "data-edit-budget-line" in index_html
    assert "data-delete-budget-line" in index_html
    assert 'id="other-expenses-panel"' in index_html
    assert "Show other expenses" in index_html
    assert "data-quick-add-budget-line" in index_html
    assert "const pageRoot = document.querySelector('.budgets-page');" in index_html
    assert "function isPageActive()" in index_html
    assert "function shiftMonthValue(value, delta)" in index_html
    assert 'id="budget-month-input"' in index_html
    assert 'id="budget-month-display"' in index_html
    assert "function openBudgetMonthPicker()" in index_html
    assert "String(line.id) === String(lineId)" in index_html
    assert "No budget has been created for this month yet." in index_html
    assert "parseMoneyInputToCents" in index_html
    assert 'step="0.01"' in index_html
    assert "/budgets-backend/api/budgets" in index_html
    assert "/api/transaction-categories" in index_html
    assert "/budgets-backend/api/budget-lines/" in index_html
    assert "/summary" in index_html
