# Inbound contracts (first written 22 Aug 2026, revised through 7 Sep 2026)

Assumptions this feature makes about other students' services, written down so a mismatch is a one-file diff.

## 1. Transactions service (Janelle, `transactions-db` :6001)

> **Port note (30 Aug):** Janelle's #59 deployed her containers on
> 3001/5001/6001, which collides with the student-1 convention block; the
> team is settling which allocation wins. Bills addresses her DB API by
> container name via `TRANSACTIONS_DB_API_URL` (e.g.
> `http://transactions-db:6001`), so whichever port the team lands on is a
> one-variable change here, not a code change. **Compose does not set that
> variable** for `bills-backend` (only `PORT`, `BILLS_DB_API_URL`,
> `FRONTEND_ORIGIN`, `OLLAMA_URL`), so the composed stack always runs on the
> stub and `/health` reports `transactions_api` unset; going live is adding
> the one variable.

Assumed contract: `GET /transactions?merchant=&since=` returning a list of rows with `date`, `merchant`, `description`, `amount`, `category_id`, `ai_confidence`. The field shape is Janelle's call as the data owner; `sophia/backend/fixtures/transactions_stub.json` is the worked example Bills currently codes against. `sophia/backend/clients/transactions.py` normalises every row through one `_normalise()` function, so a differing real contract is a one-function change. When `TRANSACTIONS_DB_API_URL` is unset, or the real service errors, the client falls back to `sophia/backend/fixtures/transactions_stub.json` (~25 rows across the seed merchants) and reports `source="stub"`.

**Checked 7 Sep against Janelle's actual service:** `GET /transactions` serialises `shared/backend/dto.py`'s `Transaction` — `id`, `amount`, `merchant`, `date`, `description`, `category_id`. There is no `ai_confidence` (`_normalise()` would carry it as `None`), and `date` is a `datetime`, which `jsonify` emits as an HTTP-date string rather than the `YYYY-MM-DD` the stub uses, so `_normalise()` needs a date parse before the live path is usable. Neither has been exercised: the composed stack runs on the stub (port note above).

## 2. Recurring-bill handoff

`POST /api/handoff/recurring` — body `{source: "transactions", merchant, intent: "end"|"change_amount"|"create", amount?, effective_from?, note?}` — returns `200 {preview, apply_url: "/api/chat/apply", ui_url: "http://localhost:3005/?handoff=<id>#bills"}`. Nothing is applied by this call; the caller (or the user, via `ui_url`) still has to POST the returned `preview.op` to `apply_url`.

**What the route actually enforces (checked 7 Sep): nothing.** `source` is never read; an unknown or missing `intent` falls through to the `create` branch; a missing `merchant` still returns 200 with a preview whose `say` is `"None for None"`. This endpoint never returns 400 or 422 — validation happens only when the preview is applied. And `ui_url`'s `handoff=<id>` is not resolvable: the id is derived from intent and merchant, never stored, and `app.js` only scrolls the Ask Tally panel into view when it sees the parameter, so a user opening that link cannot apply the preview from it — the caller must POST `preview.op` to `apply_url` itself. Both are R1 items.

Simpler deep link for a plain nudge into chat: `http://localhost:3005/?message=<urlencoded>#bills`.

**Deep-link shape (changed 3 Sep).** The parameter travels in the **query** and the hash is a bare `#bills`. The shared shell routes its tabs on an exact hash match — `tabs.find(t => t.dataset.page === location.hash.slice(1)) || tabs[0]` (`shared/frontend/public/index.html`, added by #77 and given that routing line by #113) — so the previous `#chat?handoff=<id>` sliced to `chat?handoff=<id>`, matched no tab and fell back to **Home**: the link opened the app but never reached Bills. Verified in a real browser against the running shell. There is no `chat` page in the shell at all, so `#chat` could never work there; Bills owns Ask Tally, and `app.js` routes on the query parameter once Bills has loaded. The old `#bills?confirm=` / `#chat?` forms are still honoured by `app.js` for standalone use, so existing links and screenshots do not break.

This endpoint deliberately stays a `POST` (decision D2): it returns a preview plus `apply_url`, and nothing is written until the confirmed preview is applied.

## 3. Bill suggestions from alerts (Feature 4)

Link handoff: `GET http://localhost:3005/handoff/subscription?...` with the parameters below. Bills opens its normal add-bill form prefilled from the parameters; nothing is created until the user saves it. Saved bills carry `source="f4_handoff"` and `confirmed_at=NULL`, so they show an "Added from Spending Alerts — keep it?" prompt in the bills table until confirmed. (The copy was "Confirm this?" until 2 Sep; it was reworded because it never said where the row had come from.)

| Param | Required | Type | Notes |
|---|---|---|---|
| `source` | yes | `f4` | |
| `alert_id` | no | int | accepted but not read: nothing displays it and omitting it does not 422 |
| `merchant` | yes | string | |
| `amount` | yes | decimal dollars | the typical amount observed; Bills converts to cents |
| `cadence` | yes | `weekly` / `fortnightly` / `monthly` | if unsure send `monthly` + `confidence=low` |
| `first_seen` | yes | `YYYY-MM-DD` | first occurrence in the evidence |
| `last_seen` | yes | `YYYY-MM-DD` | most recent; Bills projects `next_billing_date` from this + cadence |
| `occurrences` | yes | int (≥ 1) | how many charges the pattern rests on; drives the "based on N charges" banner |
| `confidence` | no | `high` / `low` | wording only |
| `evidence` | no | comma-separated ints | accepted but not read; the banner counts `occurrences`, not these refs |
| `return_url` | no | url | back to his alerts |

`next_billing_date` is deliberately not a parameter — he sends what he observed, Bills computes what happens next.

**Verified 7 Sep** against the running stack, with the full required set
(`source=f4&alert_id=77&merchant=GymCo&amount=24.99&cadence=monthly&first_seen=2026-05-19&last_seen=2026-08-19&occurrences=4`):
200 from all three entry points — `:5005/ui/handoff/subscription`,
`:3005/handoff/subscription` and `:3000/bills-frontend/handoff/subscription`.
The form comes back prefilled with `source=f4_handoff`, `name`/`merchant` GymCo,
`amount` 24.99, and `next_billing_date` **2026-09-19** — computed from `last_seen`
plus the cadence, not sent by the caller — above an evidence banner reading
"based on 4 charges from 2026-05-19 to 2026-08-19". Omitting a required
parameter (or sending a non-finite, negative or non-numeric amount, an unknown
cadence, a bad date, `first_seen` after `last_seen`, or `occurrences` < 1)
returns 422 with the error fragment from `:5005/ui/handoff/subscription`, which
is what `screenshots/r0-15-handoff-422.png` captures. Through nginx (`:3005`, or
the shell on `:3000`) the page itself always loads 200 — the frontend's nginx has
no `/handoff/` location, so the request falls through to `index.html`, and
`app.js` then fetches the fragment from `/bills-backend/ui/handoff/subscription`;
the 422 arrives on that inner request and renders in place.

The earlier `POST /api/suggestions` — body `{source: "alerts", alert_id, merchant, amount, cadence, last_seen, occurrences}`, where `amount` is **integer cents** (unlike the link's decimal dollars), `source`, `alert_id` and `occurrences` are accepted but unread, and the row is created with `next_billing_date = last_seen`, `source="f4_handoff"` — returning `201 {bill_id, status, confirm_url: "http://localhost:3005/?confirm=<id>#bills"}` — still exists and creates the bill immediately; the link above is the preferred handoff because nothing is written until the user saves the prefilled form.
