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
| GET | `/api/upcoming?days=90` | `{today, monthly_committed_cents, items}`. Other features that need projected bills call this endpoint on the backend directly; the database API at :6005 serves stored rows only and has no dependency on the backend. |
| GET/POST | `/api/disputes` | POST `{bill_id, reason}` creates a dispute and drafts letter v1 via the AI guard. |
| GET/PUT/DELETE | `/api/disputes/<id>` | PUT `{status}`. |
| GET | `/api/disputes/<id>/drafts` | |
| POST | `/api/disputes/<id>/regenerate` | `{edited_letter?, feedback?}`, stores version N + 1. |
| POST | `/api/chat` | `{message}` -> `{reply, op, preview, fallback}`. When the turn produces a proposal, `preview` also carries `message_id` and `suggestion_id`, and a `pending` row is written to `suggestions`. Writes `chat_messages` and `suggestions` only; never touches bills/payments/disputes directly. |
| POST | `/api/chat/apply` | `{op, entity, id, fields, message_id?}` -> executes through the services layer, so an applied proposal gets the same validation and status recompute a manual edit does. |
| GET | `/api/chat/history` | |
| GET | `/api/chat/suggestions` | Query `status` (`pending`/`applied`/`rejected`/`failed`). Lists AI proposals awaiting a decision. |
| POST | `/api/chat/suggestions/<id>/approve` | Claims the row atomically (`pending` -> `applied`), then applies it; on failure the row becomes `failed` with `error` set and nothing is changed. |
| POST | `/api/chat/suggestions/<id>/reject` | Rejects a pending proposal, or dismisses a failed one. Recorded in the chat transcript so the model can adapt. |
| POST | `/api/handoff/recurring` | See `contracts-inbound.md`. |
| POST | `/api/suggestions` | See `contracts-inbound.md`. |
| GET | `/health` | `{ok, today, db_api, transactions_api, ollama}`. |

Reads are pure: every GET above computes `status` with `engine/status.derive_status` and never writes it back, so reading a bill has no side effects on :6005. The `status` column stored in the database is a cache, refreshed only where a write already happens — bill create/update/cancel and payment create/update/delete. Other features reading `:6005/bills` directly should treat that column as last-written; read `:5005/api/bills` when the status needs to be current.

## Reading projected bills

Stored bill rows come from the database API: `GET :6005/bills`. Projections (next occurrences, monthly-committed totals) come from the backend: `GET :5005/api/upcoming`, because the date engine lives in the backend, not the database container. The earlier `:6005/upcoming` passthrough was removed in PR #31 so the database container does not depend on the backend. Calling the backend for projections is the one declared exception to reading other features' data through their DB API.

## HTML fragments (`/ui/*`)

Thirty Jinja fragment routes — 15 GET and 15 POST — all under the `/ui` prefix. They render the same engine output as the JSON routes above.

**GET (render a fragment):** `/ui/bills`, `/ui/calendar`, `/ui/timeline?days=`, `/ui/disputes?bill_id=`, `/ui/disputes-tab`, `/ui/chat`, `/ui/suggestions`, `/ui/modal`, `/ui/toast?text=`, `/ui/handoff/subscription`, and five form fragments: `/ui/bills/new-form`, `/ui/bills/<id>/edit`, `/ui/bills/<id>/cancel-form`, `/ui/bills/<id>/dispute-form`, `/ui/bills/<id>/payment-form`.

**POST (write, then return the refreshed fragment):** `/ui/bills`, `/ui/bills/<id>/edit`, `/ui/bills/<id>/confirm`, `/ui/bills/<id>/cancel`, `/ui/bills/<id>/delete`, `/ui/payments`, `/ui/disputes`, `/ui/disputes/<id>/status`, `/ui/disputes/<id>/regenerate`, `/ui/disputes/<id>/delete`, `/ui/chat`, `/ui/chat/apply`, `/ui/suggestions/<id>/approve`, `/ui/suggestions/<id>/reject`, `/ui/suggestions/<id>/suggest`.

The frontend is built and these are fully wired. Row actions are a disclosure menu rather than four inline buttons (PR #103), and modal confirm/cancel posts over HTMX. `/ui/calendar` and `/ui/timeline` remain callable and tested but are no longer rendered by the single-page layout (PR #109). A write route returns 422 with an error fragment on invalid input, never a 500.

## AI calls

Exactly two: `POST {OLLAMA_URL}/api/chat` with `DRAFT_MODEL` for dispute letters, and with `CHAT_MODEL` for the chat assistant. Both go through `sophia/backend/ai/guard.py`, which validates the JSON response, retries once with the validation error appended to the prompt, and falls back to a templated response (`fallback: true`) if the second attempt also fails. Dispute drafts get one code-enforced amendment: a direct-debit bill's steps must mention removing the payment authority; a card bill's steps must mention cancelling from the app's account page.
