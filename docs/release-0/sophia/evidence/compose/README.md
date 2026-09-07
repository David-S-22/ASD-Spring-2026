# Docker Compose verification — 22 Aug 2026

> **Dates.** The captures here are stamped 21 Aug **UTC** (`compose-ps.txt` says
> so explicitly; the `Date:` headers in `ui-write-routes.txt` run from "Fri, 21 Aug
> 2026 18:56:52 GMT" to "18:58:29 GMT"). That is 22 Aug in Sydney, which is the date on this heading.
> Both are correct; they are not two different runs.
>
> **Superseded in part.** `pytest-283-passed.txt` and `compose-ps-2026-09-07.txt`
> in this directory, and `../ci-summary-2026-09-07.txt`, are the current numbers.
> `pytest-283-passed.txt` is the full suite output — 283 passed, 91% coverage,
> Python 3.13.2 at `ffb625f`, matching Sophia-CI run 145 on 3.12.
> `compose-ps-2026-09-07.txt` is a fresh `docker compose up -d --build` of the whole
> team stack: 17 services up (16 built, `ollama` pulled), all five frontends and
> four of five backends 200 through the shared shell on `:3000`. The one 404 is
> Bills' own backend root, which registers no `/` route (`/health` and `/api/bills`
> are 200 through the same path); three non-Bills backends have no `/health`
> endpoint, recorded as an observation outside this feature's scope.
> Everything below is the 22 Aug record and is kept as history.

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

`ui-write-routes.txt` — eleven `/ui/*` write routes curled form-encoded, the
way HTMX actually sends them: add/edit/cancel/delete/confirm a bill, record
a payment, create/status/regenerate a dispute (**create and regenerate** are
the real Ollama calls, not mocked; `status` is a plain database update that
never reaches the model), send a chat message and apply its preview, plus a
validation failure (422 + error fragment) and three `/api/*` routes hit with
a form body (400 JSON, never 500).

**This was every write route on 22 Aug; it is 11 of 15 now.** Four arrived
later and have no transcript here: `POST /ui/disputes/<id>/delete` (#106) and
`POST /ui/suggestions/<id>/approve`, `/reject` and `/suggest` (#105).

**Correction (7 Sep).** An earlier version of this file said the
exclude_from_plan/next-month calendar work was "visible in the apply
response" as `Plan for September` / `Set aside up to $697`, and that the
timeline's top row read `Home internet` / `Overdue` / `$79.00`. Those strings
appear in none of the four capture files. The transcript records status lines
and headers only — the apply response is logged as `HTTP/1.1 200 OK` with
`Content-Length: 13989` and `HX-Trigger: {"toast": "Done \u2014 change
saved."}` (the em dash is JSON-escaped in the capture), and the body itself was
never saved. The underlying behaviour is
real and covered by the test suite; it was simply never evidenced *here*, so
the claim has been withdrawn rather than restated.

`four-cases.txt` — after an independent curl sweep found two leftover
500s (a bad calendar month, and a chat/apply fields key outside the
per-entity whitelist), a second `docker compose down -v && docker compose
up -d --build` and four more curls confirm both are fixed: `/api/*` returns
400 JSON, `/ui/*` returns 422 with the error fragment, never a 500.

Containers were left running after this pass, per instruction, for a
click-through in the browser.
