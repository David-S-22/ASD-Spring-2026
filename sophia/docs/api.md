# Bills backend API (:5005)

Base URL in compose: `http://bills-backend:5005`. Locally: `http://localhost:5005`.

## JSON API (`/api/*`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/bills` | Query `type`, `status`. Each row enriched with `status`, `status_label`, `next_occurrence`, `usual_range`, `monthly_equivalent_cents`. |
| POST | `/api/bills` | Creates a bill. |
| GET/PUT/DELETE | `/api/bills/<id>` | |
| GET | `/api/bills/<id>/payments` | |
| POST | `/api/bills/<id>/confirm` | Sets `confirmed_at` to `DEMO_TODAY`. |
| POST | `/api/payments` | Recomputes and stores the owning bill's status. |
| PUT/DELETE | `/api/payments/<id>` | Same recompute. |
| GET | `/api/timeline?days=30..180` | `{today, days, items:[{date, bill_id, name, merchant, amount, amount_cents, display_amount, kind, within_30_days}]}`. `display_amount` is exact for `kind=actual`, whole-dollar for `kind=predicted`. |
| GET | `/api/calendar/<YYYY-MM>` | Usual/extra breakdown for one month. |
| GET | `/api/calendar?from=YYYY-MM&months=6` | Breakdown for a run of months. |
| GET | `/api/upcoming?days=90` | `{today, monthly_committed_cents, items}`. This is what the database API's `GET /upcoming` proxies to. |
| GET/POST | `/api/disputes` | POST `{bill_id, reason}` creates a dispute and drafts letter v1 via the AI guard. |
| GET/PUT/DELETE | `/api/disputes/<id>` | PUT `{status}`. |
| GET | `/api/disputes/<id>/drafts` | |
| POST | `/api/disputes/<id>/regenerate` | `{edited_letter?, feedback?}`, stores version N + 1. |
| POST | `/api/chat` | `{message}` -> `{reply, op, preview, fallback}`. Writes only `chat_messages`; never touches bills/payments/disputes directly. |
| POST | `/api/chat/apply` | `{op, entity, id, fields}` -> executes through the normal CRUD routes. |
| GET | `/api/chat/history` | |
| POST | `/api/handoff/recurring` | See `contracts-inbound.md`. |
| POST | `/api/suggestions` | See `contracts-inbound.md`. |
| GET | `/health` | `{ok, today, db_api, transactions_api, ollama}`. |

## HTML fragments (`/ui/*`)

Jinja fragments rendered for HTMX: `GET /ui/bills`, `GET /ui/calendar`, `GET /ui/timeline?days=`, `GET /ui/disputes?bill_id=`, `GET /ui/chat`, `GET /ui/modal`, `GET /ui/toast?text=`. These render the same engine output as the JSON routes above; the frontend build (a later PR) wires the interactive bits (row action buttons, modal confirm/cancel) that are currently inert placeholders in the templates.

## AI calls

Exactly two: `POST {OLLAMA_URL}/api/chat` with `DRAFT_MODEL` for dispute letters, and with `CHAT_MODEL` for the chat assistant. Both go through `sophia/backend/ai/guard.py`, which validates the JSON response, retries once with the validation error appended to the prompt, and falls back to a templated response (`fallback: true`) if the second attempt also fails. Dispute drafts get one code-enforced amendment: a direct-debit bill's steps must mention removing the payment authority; a card bill's steps must mention cancelling from the app's account page.
