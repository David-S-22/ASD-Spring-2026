# Bills List & Dispute Assistant

Owner: Sophia Nguyen, Student 5.

## What this feature does

Tracks recurring bills and subscriptions, projects when they'll next charge,
shows a month-by-month "what to set aside" calendar, tracks paid/due/overdue
status per bill, drafts dispute letters for charges that look wrong, and
answers plain-language questions about the bills through a small chat
assistant ("Ask Tally"). Nothing writes to the database without an explicit
user action: chat replies with a preview card, and only `POST
/api/chat/apply` actually executes a change, through the same CRUD routes a
manual edit would use. Disputes are drafts only — there is no send
integration.

## Run it

### Docker Compose (from the repo root)

```
docker compose build bills-frontend bills-backend bills-db
docker compose up -d
```

Then open `http://localhost:3005`. `docker compose down` to stop.

### Local, without Docker

Three processes, each from the repo root so `sophia` resolves as a package:

```
DB_PATH=./bills.db PORT=6005 python sophia/database/app.py
BILLS_DB_API_URL=http://localhost:6005 PORT=5005 python -m sophia.backend.app
```

The frontend is static files; open `sophia/frontend/index.html` directly, or
serve the folder with any static file server, once `nginx.conf`'s proxy
targets are pointed at wherever the backend is actually running (the
Dockerized frontend proxies through nginx; a bare static-file server won't
proxy `/api/` or `/ui/`, so hitting the backend directly on `:5005` is
easiest for local iteration).

Architecture diagrams:
[individual architecture](../docs/architecture/r0-d1-individual-architecture.png),
[compose topology](../docs/architecture/r0-d2-docker-compose-architecture.png),
[dispute loop](../docs/architecture/r0-d3-paoa-dispute-loop.png),
[chat loop](../docs/architecture/r0-d4-paoa-chat-loop.png).

## Ports and env vars

| Service | Port | Key env vars |
|---|---|---|
| `bills-frontend` | 3005 | — (static + nginx proxy) |
| `bills-backend` | 5005 | `PORT`, `BILLS_DB_API_URL` (default `http://bills-db:6005`), `FRONTEND_ORIGIN` (default `http://localhost:3005`), `TRANSACTIONS_DB_API_URL` (optional; unset → stub), `OLLAMA_URL` (default `http://host.docker.internal:11434`), `DRAFT_MODEL` (`llama3.1:8b`), `CHAT_MODEL` (`qwen2.5:0.5b`), `DEMO_TODAY` (default `2026-08-20`), `AI_TIMEOUT_SECONDS` (default `90`) |
| `bills-db` | 6005 | `PORT`, `DB_PATH` (default `./bills.db`) |

`DEMO_TODAY` is parsed once in `sophia/backend/config.py`; nothing under
`sophia/backend/engine/` ever calls `date.today()` or `datetime.now()` —
every engine function takes `today` as an explicit argument.

Compose sets only `PORT`, `BILLS_DB_API_URL` and `FRONTEND_ORIGIN` for the
backend — the AI and demo-clock values are in-container defaults from
`config.py`. Anyone running the backend bare on a machine without Docker
Desktop should set `OLLAMA_URL=http://localhost:11434`; the demo clock stays
`DEMO_TODAY=2026-08-20` by default and is overridable per environment.

## The two AI calls

Exactly two, both through `sophia/backend/ai/guard.py`: validate the JSON
response against a hand-written schema (`ai/schemas.py`, no jsonschema/
pydantic), retry once with the validation error appended to the prompt on
failure, and fall back to a templated response (`fallback: true`) if the
second attempt also fails. Neither call ever raises out to the route.

1. **Dispute drafting** (`ai/dispute_prompt.py`, `DRAFT_MODEL`): given the
   bill, its last 6 payments, the reason, and the payment method (or "not
   recorded"), drafts `{letter_text, steps, escalation,
   payment_method_note}`. Code-enforced on top of the model's output
   (`enforce_payment_method_step`): a direct-debit bill's steps must mention
   removing the payment authority; a card bill's steps must mention
   cancelling from the app's account page.
2. **Chat** (`ai/chat_prompt.py`, `CHAT_MODEL`): given a compact bills list
   (id, name, amount, cadence, next date, type) and four few-shot examples,
   classifies the message into `{op, entity, id, fields, question, say}`.
   `question` resolves in code (`total`, `barely_using`, `upcoming`); `op`
   becomes a preview card the user must confirm before anything is written.
   Kept deliberately short — `qwen2.5:0.5b`'s accuracy degrades fast with
   long context.

## Date engine rules

- **Actual vs predicted vs overdue**: an occurrence is `actual` if a payment
  for that bill exists within ±3 days of it, `overdue` if its current cycle
  (`current_cycle_due`) is strictly before today with no matching payment —
  `timeline()`'s forward-only window otherwise drops these entirely, so
  `project()`'s normal walk is topped up with one synthetic occurrence per
  bill for this case — else `predicted`. The `Predicted` tag itself is
  hidden inside the first 30 days of the timeline (an imminent charge reads
  as expected, not speculative); `Overdue` always shows, at the real cents
  amount rather than a rounded estimate, since it's a real unpaid charge.
- **Usual vs extra** (calendar breakdown): a bill already billing before the
  month and still active is "usual" — it contributes `expected_per_month ×
  usual_range` to the month's low/high, plus an `extra_occurrence` line for
  any occurrences beyond that base count. A bill with no prior occurrence
  that bills at least once this month is a "starts" line. A bill whose
  `end_date` falls in this month counts its occurrences as usual and adds a
  zero-cost "ends" note; the month after, it contributes nothing.
- **Status**: `paid` / `due` / `overdue`, derived from the latest occurrence
  at or before `today` and whether a payment covers it — see
  `sophia/backend/engine/status.py` for the exact rules and labels. Month
  arithmetic (`add_months`) is computed directly from the anchor date, never
  by repeatedly stepping — this matters for 31st-anchored monthly bills,
  where re-adding a step from an already-clamped date drifts (28 Feb + 1
  month is 31 Mar from the anchor, not 28 Mar from re-adding a month to 28
  Feb).

## Money formatting convention

Integer cents everywhere internally. `format_actual` renders exact amounts
("$1,100.00"); `format_estimate`/`format_estimate_single` round to whole
dollars, half rounding up, and collapse an equal lo/hi range to a single
figure ("$379–415", or "$379" when lo == hi).

## Inbound contracts

See `docs/release-0/sophia/contracts-inbound.md` (dated 22 Aug 2026) for the two inbound
handoff endpoints (`POST /api/handoff/recurring`, `POST /api/suggestions`)
and the transactions-service contract this feature assumes.

## Schema adoption

See `docs/release-0/sophia/schema-adoption.md` for the four additive schema items
(`end_date`, `source`, `confirmed_at`, `chat_messages`) and why each exists.

## Testing and evidence

```
python -m pytest sophia/test -q --cov=sophia/backend --cov-report=term
```

108 passed; coverage 81% across `sophia/backend` (measured 28 Aug 2026).

Covers the engine (dates, projection, calendar, status, money), the database
API (temp SQLite per test, seed row counts, CRUD round-trips, cascade
delete), the backend routes (monkeypatched
`bills_db` client, no network), the AI guard and schemas (mocked HTTP,
retry-then-fallback, direct-debit/card step injection, unreachable-Ollama
fallback), and the `/ui/*` HTML fragments (a real `sophia/database` instance
in a background thread against a temp seeded SQLite file, verbatim-copy and
`$`-formatting assertions).

`docs/release-0/sophia/evidence/ai/` holds raw JSON from real local Ollama calls (not
mocked) — dispute drafts for a direct-debit bill and a card bill plus a
regenerate-with-feedback call (3/3 first-try schema pass), and all four
chat chips (4/4 correct op), with an honest note on what tuning changed and
what this small sample does and doesn't demonstrate.
`docs/release-0/sophia/evidence/compose/` holds the `docker compose`
verification run and the curl transcripts of the `/ui/*` write routes.
Diagrams are in `docs/architecture/` and app screenshots in
`docs/release-0/sophia/screenshots/` (see the README there). Per the spec's
repository layout, nothing under `sophia/` is documentation.

## Pull requests

All Bills PRs are merged to `main` — 21 in total, each squash-merged after
review:

- Scaffold #6, #7 · engine #8 · DB API #13 · backend #10 · frontend #11 ·
  AI #12
- Defect fixes: #14, #15, #16, #17, #18, #31
- Docs, layout, polish: #19, #24, #25, #26, #27, #30, #33
- Requirements split: #34

Actions evidence — Sophia-CI run on `main`:
<https://github.com/David-S-22/ASD-Spring-2026/actions/runs/32573962576>

## Workflow note

The team's workflow doc names this feature's CI file `student-5.yml`; it's
named `Sophia-CI.yml` here instead, to match the existing `David-CI.yml`
naming convention already in the repo.
