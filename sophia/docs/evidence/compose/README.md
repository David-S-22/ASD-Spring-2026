# Docker Compose verification — 22 Aug 2026

`compose-down.txt`, `compose-ps.txt`, `curl-endpoints.txt` are the baseline
verification from the prior PR (services build/start/health, before this
addendum's frontend write-path work existed). `up.txt` and
`ui-write-routes.txt` below are new, from this addendum.

Docker Desktop's daemon was down for most of this addendum's work (checked
repeatedly) but came up before the final verification pass, so this is a
real run, not a substitute.

```
docker compose down -v
docker compose up -d --build
```

`up.txt` — `docker compose ps`, and health checks for all three services
(`:6005/health`, `:5005/health`, `:3005/`, `:3005/api/bills`).

`ui-write-routes.txt` — every `/ui/*` write route curled form-encoded, the
way HTMX actually sends them: add/edit/cancel/delete/confirm a bill, record
a payment, create/status/regenerate a dispute (the last two are real
Ollama calls, not mocked), send a chat message and apply its preview, plus
a validation failure (422 + error fragment) and three `/api/*` routes hit
with a form body (400 JSON, never 500). The exclude_from_plan/next-month
calendar work is visible in the apply response: `Plan for September` /
`Set aside up to $697`, and the timeline's top row is `Home internet`
tagged `Overdue` at `$79.00` (cents, not a rounded estimate).

`four-cases.txt` — after an independent curl sweep found two leftover
500s (a bad calendar month, and a chat/apply fields key outside the
per-entity whitelist), a second `docker compose down -v && docker compose
up -d --build` and four more curls confirm both are fixed: `/api/*` returns
400 JSON, `/ui/*` returns 422 with the error fragment, never a 500.

Containers were left running after this pass, per instruction, for a
click-through in the browser.
