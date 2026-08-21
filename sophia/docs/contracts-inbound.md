# Inbound contracts (dated 22 Aug 2026)

Assumptions this feature makes about other students' services, written down so a mismatch is a one-file diff.

## 1. Transactions service (Janelle, :6001)

Assumed contract: `GET /transactions?merchant=&since=` returning a list of rows with `date`, `merchant`, `description`, `amount`, `category_id`, `ai_confidence`. `sophia/backend/clients/transactions.py` normalises every row through one `_normalise()` function, so a differing real contract is a one-function change. When `TRANSACTIONS_DB_API_URL` is unset, or the real service errors, the client falls back to `sophia/backend/fixtures/transactions_stub.json` (~25 rows across the seed merchants) and reports `source="stub"`.

## 2. Recurring-bill handoff

`POST /api/handoff/recurring` — body `{source: "transactions", merchant, intent: "end"|"change_amount"|"create", amount?, effective_from?, note?}` — returns `200 {preview, apply_url: "/api/chat/apply", ui_url: "http://localhost:3005/#chat?handoff=<id>"}`. Nothing is applied by this call; the caller (or the user, via `ui_url`) still has to POST the returned `preview.op` to `apply_url`.

Simpler deep link for a plain nudge into chat: `http://localhost:3005/#chat?message=<urlencoded>`.

## 3. Bill suggestions from alerts

`POST /api/suggestions` — body `{source: "alerts", alert_id, merchant, amount, cadence, last_seen, occurrences}` — returns `201 {bill_id, status, confirm_url: "http://localhost:3005/#bills?confirm=<id>"}`. Creates the bill immediately with `source="f4_handoff"` and `confirmed_at=NULL`, so it shows a "Confirm this?" prompt in the bills table until the user confirms it.
