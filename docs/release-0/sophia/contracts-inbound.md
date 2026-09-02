# Inbound contracts (dated 22 Aug 2026)

Assumptions this feature makes about other students' services, written down so a mismatch is a one-file diff.

## 1. Transactions service (Janelle, :6003)

> **Port note (30 Aug):** Janelle's #59 deployed her containers on
> 3001/5001/6001, which collides with the student-1 convention block; the
> team is settling which allocation wins. Bills addresses her DB API by
> container name via `TRANSACTIONS_DB_API_URL` (e.g.
> `http://transactions-db:6001`), so whichever port the team lands on is a
> one-variable change here, not a code change.

Assumed contract: `GET /transactions?merchant=&since=` returning a list of rows with `date`, `merchant`, `description`, `amount`, `category_id`, `ai_confidence`. The field shape is Janelle's call as the data owner; `sophia/backend/fixtures/transactions_stub.json` is the worked example Bills currently codes against. `sophia/backend/clients/transactions.py` normalises every row through one `_normalise()` function, so a differing real contract is a one-function change. When `TRANSACTIONS_DB_API_URL` is unset, or the real service errors, the client falls back to `sophia/backend/fixtures/transactions_stub.json` (~25 rows across the seed merchants) and reports `source="stub"`.

## 2. Recurring-bill handoff

`POST /api/handoff/recurring` — body `{source: "transactions", merchant, intent: "end"|"change_amount"|"create", amount?, effective_from?, note?}` — returns `200 {preview, apply_url: "/api/chat/apply", ui_url: "http://localhost:3005/?handoff=<id>#bills"}`. Nothing is applied by this call; the caller (or the user, via `ui_url`) still has to POST the returned `preview.op` to `apply_url`.

Simpler deep link for a plain nudge into chat: `http://localhost:3005/?message=<urlencoded>#bills`.

**Deep-link shape (changed 3 Sep).** The parameter travels in the **query** and the hash is a bare `#bills`. The shared shell routes its tabs on an exact hash match — `tabs.find(t => t.dataset.page === location.hash.slice(1)) || tabs[0]` (`shared/frontend/public/index.html`, added by #113) — so the previous `#chat?handoff=<id>` sliced to `chat?handoff=<id>`, matched no tab and fell back to **Home**: the link opened the app but never reached Bills. Verified in a real browser against the running shell. There is no `chat` page in the shell at all, so `#chat` could never work there; Bills owns Ask Tally, and `app.js` routes on the query parameter once Bills has loaded. The old `#bills?confirm=` / `#chat?` forms are still honoured by `app.js` for standalone use, so existing links and screenshots do not break.

This endpoint deliberately stays a `POST` (decision D2): it returns a preview plus `apply_url`, and nothing is written until the confirmed preview is applied.

## 3. Bill suggestions from alerts (Feature 4)

Link handoff: `GET http://localhost:3005/handoff/subscription?...` with the parameters below. Bills opens its normal add-bill form prefilled from the parameters; nothing is created until the user saves it. Saved bills carry `source="f4_handoff"` and `confirmed_at=NULL`, so they show a "Confirm this?" prompt in the bills table until confirmed.

| Param | Required | Type | Notes |
|---|---|---|---|
| `source` | yes | `f4` | |
| `alert_id` | yes | int | shown on the preview; lets him mark the alert handled |
| `merchant` | yes | string | |
| `amount` | yes | decimal dollars | the typical amount observed; Bills converts to cents |
| `cadence` | yes | `weekly` / `fortnightly` / `monthly` | if unsure send `monthly` + `confidence=low` |
| `first_seen` | yes | `YYYY-MM-DD` | first occurrence in the evidence |
| `last_seen` | yes | `YYYY-MM-DD` | most recent; Bills projects `next_billing_date` from this + cadence |
| `occurrences` | yes | int | how many charges the pattern rests on; shown on the preview |
| `confidence` | no | `high` / `low` | wording only |
| `evidence` | no | comma-separated ints | his transaction refs, shown as "based on N charges" |
| `return_url` | no | url | back to his alerts |

`next_billing_date` is deliberately not a parameter — he sends what he observed, Bills computes what happens next.

The earlier `POST /api/suggestions` — body `{source: "alerts", alert_id, merchant, amount, cadence, last_seen, occurrences}`, returning `201 {bill_id, status, confirm_url: "http://localhost:3005/?confirm=<id>#bills"}` — still exists and creates the bill immediately; the link above is the preferred handoff because nothing is written until the user saves the prefilled form.
