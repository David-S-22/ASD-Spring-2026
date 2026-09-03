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
    assert 'id="budget-income-dialog"' in index_html
    assert 'id="budget-income-form"' in index_html
    assert 'id="budget-income-input"' in index_html
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
    assert 'id="chat-history"' in index_html
    assert 'id="proposal-history"' in index_html
    assert 'id="coach-proposals-list"' in index_html
    assert 'id="chat-form"' in index_html
    assert 'id="chat-input"' in index_html
    assert 'id="reset-chat-button"' in index_html
    assert 'id="show-rejected-proposals"' in index_html
    assert "data-edit-budget-line" in index_html
    assert "data-delete-budget-line" in index_html
    assert "data-edit-planned-event" in index_html
    assert "data-cancel-planned-event" in index_html
    assert "data-edit-income-summary" in index_html
    assert 'id="other-expenses-panel"' in index_html
    assert "Week Ahead" in index_html
    assert "Can I afford?" in index_html
    assert "Chat with Tally (AI)" in index_html
    assert "Show other expenses" in index_html
    assert "data-quick-add-budget-line" in index_html
    assert "const pageRoot = document.querySelector('.budgets-page');" in index_html
    assert "function isPageActive()" in index_html
    assert "async function readApiJson(response, requestMessage, unexpectedMessage)" in index_html
    assert "function shiftMonthValue(value, delta)" in index_html
    assert 'id="budget-month-input"' in index_html
    assert 'id="budget-month-display"' in index_html
    assert "function openBudgetMonthPicker()" in index_html
    assert "function renderPlannedEvents(summary)" in index_html
    assert "function setBudgetIncomeFormVisible(isVisible)" in index_html
    assert "function startEditingBudgetIncome()" in index_html
    assert "async function saveBudgetIncome(event)" in index_html
    assert index_html.index("async function saveBudgetIncome(event)") < index_html.index("async function startEditingPlannedEvent(eventId)")
    assert "function updatePlannedEventImpactWarning()" in index_html
    assert "function monthDateBounds(value)" in index_html
    assert "function syncPlannedEventDateConstraints()" in index_html
    assert "Planned event dates must stay inside " in index_html
    assert "function affordabilityOutcome(category, amountCents)" in index_html
    assert "function updateAffordabilityPreview()" in index_html
    assert "function renderChatMessages(messages)" in index_html
    assert "function renderCoachProposals(summary)" in index_html
    assert "function proposalLineLabel(summary, operation)" in index_html
    assert "function mergeCoachProposal(summary, proposal)" in index_html
    assert "function visibleCoachProposals(summary)" in index_html
    assert "function loadChatHistory(budgetId)" in index_html
    assert "function resetChatHistory()" in index_html
    assert "function sendChatMessage(event)" in index_html
    assert "function applyCoachProposal(proposalId)" in index_html
    assert "function rejectCoachProposal(proposalId)" in index_html
    assert "chatMessagesByBudgetId" in index_html
    assert "data-chat-chip" in index_html
    assert "data-apply-proposal" in index_html
    assert "data-reject-proposal" in index_html
    assert "Suggested budget change" in index_html
    assert "that budget line" in index_html
    assert "Show rejected" in index_html
    assert "coach-columns" in index_html
    assert "coach-column + .coach-column" in index_html
    assert "proposal-history" in index_html
    assert "summary-card-button" in index_html
    assert "summary-card-edit-icon" in index_html
    assert "max-height: 31rem;" in index_html
    assert "overflow-y: auto;" in index_html
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
    assert "/budgets-backend/api/chat" in index_html
    assert "/budgets-backend/api/coach-proposals/" in index_html
    assert "Tally returned an unexpected response." in index_html
    assert "Tally is unavailable right now. Please try again." in index_html
    assert "/summary" in index_html
    assert "/chat-messages" not in index_html
