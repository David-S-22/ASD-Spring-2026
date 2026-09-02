from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_budgets_frontend_contains_overview_screen():
    index_html = (
        REPOSITORY_ROOT / "ethan" / "frontend" / "public" / "index.html"
    ).read_text(encoding="utf-8")

    assert "<h1>Budgets</h1>" in index_html
    assert 'id="budget-month-select"' in index_html
    assert 'id="previous-budget-month-button"' in index_html
    assert 'id="next-budget-month-button"' in index_html
    assert 'id="show-add-budget-line-button"' in index_html
    assert 'id="budget-line-dialog"' in index_html
    assert 'id="budget-line-form"' in index_html
    assert 'id="show-add-planned-event-button"' in index_html
    assert 'id="planned-event-dialog"' in index_html
    assert 'id="planned-event-form"' in index_html
    assert 'id="planned-events-list"' in index_html
    assert 'id="affordability-panel"' in index_html
    assert 'id="affordability-form"' in index_html
    assert 'id="affordability-category"' in index_html
    assert 'id="affordability-amount"' in index_html
    assert 'id="affordability-result"' in index_html
    assert 'id="coach-panel"' in index_html
    assert "data-edit-budget-line" in index_html
    assert "data-delete-budget-line" in index_html
    assert "data-edit-planned-event" in index_html
    assert "data-cancel-planned-event" in index_html
    assert 'id="other-expenses-panel"' in index_html
    assert "Week Ahead" in index_html
    assert "Can I afford?" in index_html
    assert "Chat with Tally (AI)" in index_html
    assert "Show other expenses" in index_html
    assert "data-quick-add-budget-line" in index_html
    assert "const pageRoot = document.querySelector('.budgets-page');" in index_html
    assert "function isPageActive()" in index_html
    assert "function shiftMonthValue(value, delta)" in index_html
    assert 'id="budget-month-input"' in index_html
    assert 'id="budget-month-display"' in index_html
    assert "function openBudgetMonthPicker()" in index_html
    assert "function renderPlannedEvents(summary)" in index_html
    assert "function updatePlannedEventImpactWarning()" in index_html
    assert "function monthDateBounds(value)" in index_html
    assert "function syncPlannedEventDateConstraints()" in index_html
    assert "Planned event dates must stay inside " in index_html
    assert "function affordabilityOutcome(category, amountCents)" in index_html
    assert "function updateAffordabilityPreview()" in index_html
    assert "Projected warning" in index_html
    assert "budget-progress-fill projected" in index_html
    assert "String(line.id) === String(lineId)" in index_html
    assert "No budget has been created for this month yet." in index_html
    assert "parseMoneyInputToCents" in index_html
    assert 'step="0.01"' in index_html
    assert "/budgets-backend/api/budgets" in index_html
    assert "/api/transaction-categories" in index_html
    assert "/budgets-backend/api/budget-lines/" in index_html
    assert "/budgets-backend/api/planned-events/" in index_html
    assert "/summary" in index_html
