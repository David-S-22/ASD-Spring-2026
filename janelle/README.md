# Transactions service

Janelle's feature is a three-service transaction manager with an HTMX user
interface, a Flask API, and SQLite persistence. It supports transaction and
category CRUD, filtering and pagination, category-correction history, and an
Ollama-backed assistant for transaction queries and guarded changes.

## Project structure

| Path | Purpose |
|---|---|
| `frontend/` | nginx container that serves `public/index.html`, exposes `/health`, and proxies `/transactions-backend/*` to the backend. |
| `backend/` | Flask API and Jinja/HTMX UI fragments. It proxies transaction and category requests to the database, runs the AI workflow, and notifies the anomalies service after a transaction is created. |
| `backend/prompts/` | JSON-only planner prompt used by the transaction assistant. |
| `backend/services/` | Ollama planning, trusted transaction operations, MCP and RAG clients, the MCP-or-database transaction read source, request orchestration, and the bounded Plan -> Act -> Observe -> Adapt runner. |
| `backend/templates/` | Transaction table, forms, pagination, chat panel, preview, clarification, and result fragments. |
| `database/` | Flask-SQLAlchemy API backed by SQLite, including models, validation, filtering, startup seed data, and category-correction records. |
| `scripts/test/` | Standard-library HTTP helpers plus endpoint, live AI workflow, and database NFR probes. |
| `test/` | pytest coverage for the frontend contract, backend routes, database behavior, planner guardrails, and agent workflow. |

## Run with Docker Compose

From the repository root:

```powershell
docker compose up --build -d ollama transactions-db transactions-backend transactions-frontend
```

Open `http://localhost:3001`. The service endpoints are:

| Service | URL |
|---|---|
| Frontend | `http://localhost:3001` |
| Backend | `http://localhost:5001` |
| Database API | `http://localhost:6001` |
| Ollama | `http://localhost:11434` |

Each transaction service exposes `GET /health`. The backend health body also
reports which integration modes are switched on, without any network call:

```json
{"ok": true, "container": "transactions-backend", "modes": {"ai": "enabled", "mcp": "enabled", "rag": "enabled"}}
```

`mcp` and `rag` read `disabled` when `MCP_ENABLED` or `RAG_ENABLED` is
`false`. Compose passes both through `${MCP_ENABLED:-true}` and
`${RAG_ENABLED:-true}`, so they can be turned off without editing the file:

```powershell
$env:MCP_ENABLED = "false"; $env:RAG_ENABLED = "false"
docker compose up --build -d --no-deps transactions-db transactions-backend transactions-frontend
```

The backend reaches the shared MCP server (port `8000`) and RAG server
(port `5003`) on the host through `host.docker.internal`. Compose persists SQLite data
in the `transactions_data` volume and ensures the configured
`qwen2.5:3b` model is available in Ollama.

## User and API behavior

The frontend loads Jinja fragments from the backend through nginx. The UI
provides:

- transaction search, category and date-range filters, and page-size controls;
- forms for creating transactions and categories;
- an "Ask Tally" panel for transaction questions and guarded changes.

The backend exposes transaction and category CRUD at `/transactions` and
`/categories`, with item routes under `/<id>`. The chat workflow uses:

| Endpoint | Purpose |
|---|---|
| `POST /chat` | Plan a read, create, update, or delete request. |
| `POST /chat/category` | Accept or replace a proposed category. |
| `POST /chat/apply` | Apply a server-issued write preview after confirmation. |
| `GET /mcp/tools` | Diagnostic list of MCP tools visible to the backend. `503 mcp_disabled` when MCP is off, `502 mcp_unavailable` when the server cannot be reached. |
| `POST /rag/refresh` | Rebuild the `transactions-records` RAG collection. `503 rag_disabled` when RAG is off, `502 rag_unavailable` when the server cannot be reached. |

The database API also exposes
`POST /transactions/<id>/category-correction` and
`GET /category-corrections`. Transaction list queries support `search_text`,
`merchant`, `date_from`, `date_to`, `since`, `category_id`, `min_amount`,
and `max_amount`.

## AI workflow and safeguards

The planner prompt is `backend/prompts/chat_prompt.txt`. The configured model
can plan one transaction operation and request deterministic calculations
such as count, sum, average, or the largest and smallest purchases. Trusted
application code validates and grounds the model output before reading data
or preparing a write. Two groundings override the planner outright: a bare
month name ("in August") always becomes that whole month, and a ranking
question is always answered from the end of the range the wording asks for,
so "cheapest" cannot come back ranked by "largest".

The workflow is bounded to at most two Plan -> Act -> Observe -> Adapt
iterations. Reads are calculated from database rows by application code.
Creates, updates, and deletes never write during planning: they return a
before/after preview, require explicit confirmation, and are matched to
server-held request state. Confirmed updates and deletes use a stored row
version to reject stale previews, and every attempted write is checked
against the resulting database state.

Each response includes an `agent` object containing the request ID, planner
model, workflow status, the MCP tool calls the request made, and, when
enabled, a stage trace with iteration, status, summary, and duration.

### MCP read path

`backend/services/transaction_source.py` is the one seam every transaction
read passes through. When `MCP_ENABLED=true`, a read plan fetches its rows by
calling `search_transactions` on the shared MCP server instead of the
database. Validated plan filters are mapped onto tool arguments:

| Plan filter | Tool argument |
|---|---|
| `date_from`, or `since` when no `date_from` | `start_date` |
| `date_to` | `end_date` |
| `category_id` | `category_name`, resolved through the request's category lookup |
| `merchant`, `search_text`, `min_amount`, `max_amount` | the same names |

A `dates` list makes one call per date with `start_date` and `end_date` set to
that day, capped at seven dates, and the rows are merged and de-duplicated by
id exactly as the database path does. Returned rows pass the same
`transaction_row` validation as database rows, so a malformed row fails safely
with the existing invalid-response error. A result over 500 rows is truncated
and the reply says so.

Two reads never use the tool. Point lookups of `GET /transactions/<id>` are
not searches, and write previews and confirmed writes ask for the row version
that the tool does not return, so both stay on the database API.

If the MCP server is unreachable, `MCP_FALLBACK_TO_DATABASE=true` serves the
read from the database and records the fallback; with the fallback off the
read fails with `503 mcp_unavailable`. Set
`MCP_TOOL_SUPPORTS_EXTENDED_FILTERS=false` when the deployed tool only accepts
dates and a category: the merchant, text and amount filters are then applied
to the returned rows with the database API semantics, and the recorded call
lists them under `residual_filters`.

`POST /chat` reports what happened in `agent.tools`, one entry per invocation:

```json
{"server": "http://host.docker.internal:8000/mcp", "tool": "search_transactions",
 "arguments": {"start_date": "2026-08-01", "end_date": "2026-08-31"},
 "residual_filters": [], "status": "succeeded", "rows": 4, "truncated": false,
 "duration_ms": 912.4, "error": null}
```

`status` is `succeeded`, `fallback_database`, `failed`, or `skipped_disabled`.
The safe ACT trace summary names the tool or the fallback. Creates, category
selections, and confirmations report an empty list.

### RAG-grounded category suggestion

When a Tally create has no category in the message and `RAG_ENABLED=true`,
`backend/services/category_grounding.py` asks
`backend/services/rag_answer.py` for a grounded suggestion before the
Release 0 correction vote runs. The question is built from the merchant and
description only. The steps are:

1. Two `POST /retrieve` calls on the shared RAG server: the records
   collection (`RAG_RECORDS_COLLECTION`, `RAG_TOP_K` results) and the guide
   collection (`RAG_GUIDE_COLLECTION`, `RAG_GUIDE_TOP_K` results). If either
   call fails there is no partial grounding.
2. Results are merged by distance and anything farther than `RAG_LOW` is
   dropped. With nothing left the result is `insufficient` and no model call
   is made.
3. Ollama (`RAG_MODEL`, temperature 0) is asked to choose exactly one live
   category name using only the numbered context and to cite it as `[n]`.
   The reply is matched exactly against live category names; markers that
   point outside the context, or at a record whose `category_id` disagrees
   with the chosen category, are discarded.
4. Confidence is deterministic and combines two signals. The retrieval
   band comes from the distances: `high` when the best distance is below
   `RAG_HIGH` and at least two documents survived, `medium` below
   `RAG_MEDIUM`, otherwise `low`. The model's own certainty then gates that
   band: the request asks Ollama for `logprobs`, the log probabilities of
   the category-name tokens (before the first `[`) are summed into
   `model_probability`, and a `high` band needs at least `RAG_PROB_HIGH`
   while a `medium` band needs at least `RAG_PROB_MEDIUM`, each failure
   dropping one step. A server that returns no log probabilities leaves
   `model_probability` as `null` and keeps the distance band. An answer with
   no surviving marker is downgraded one further step, flagged `uncited`,
   and cites the surviving records that agree with it. An answer that is not a live category (or `NONE`),
   or one with no supporting record, falls back to a majority vote over the
   surviving records' `category_id` (guide chunks do not vote), downgraded one
   step and flagged `derived_from_votes`. With no records to vote over the
   result is `insufficient`.

The two collections hold different things. `transactions` is server-owned
and ingested from `ai-services/rag-server/sources/transactions/categories.md`.
`transactions-records` is backend-owned: `backend/services/rag_corpus.py`
builds one document per transaction (`tx-<id>`) and one per category
correction (`corr-<id>`) with scalar metadata (`kind`, `transaction_id`,
`date`, `merchant`, `category`, `category_id`, `category_type`, `amount`),
so a refresh is a whole-collection, idempotent replacement.

`category_selection` in `POST /chat` and `POST /chat/category` carries
`grounding`:

```json
{"status": "grounded", "answer": "Fitness", "confidence": "high",
 "insufficient_context": false, "uncited": false, "derived_from_votes": false,
 "citations": [
   {"marker": 1, "id": "tx-7", "collection": "transactions-records",
    "source": "transaction 7", "excerpt": "Transaction 7 on 2026-06-24: ...",
    "distance": 0.31, "category_id": 31, "category": "Fitness",
    "date": "2026-06-24", "merchant": "Anytime Fitness Ultimo", "amount": 17.5},
   {"marker": 2, "id": "transactions_categories.md_2", "collection": "transactions",
    "source": "categories.md", "excerpt": "Fitness: ...", "distance": 0.52}],
 "retrieved": 9, "survivors": 3, "best_distance": 0.31, "model_probability": 0.93,
 "model": "qwen2.5:3b",
 "thresholds": {"insufficient_above": 1.2, "high_below": 0.6, "medium_below": 0.9,
                "probability_high_at_least": 0.8, "probability_medium_at_least": 0.5}}
```

`status` is one of:

| Status | Meaning | Suggestion source | Reply |
|---|---|---|---|
| `grounded` | Context supported a live category; always has at least one citation. | The grounded answer. | "I suggest {name}. Use {name}, or choose another category." |
| `insufficient` | Nothing similar enough was retrieved; no citations. | The Release 0 correction vote still runs and may pre-select the dropdown. | "I couldn't find past transactions or notes similar enough to suggest a category. Choose a category to continue." |
| `unavailable` | Any `RAGError`, including the HTTP 500 the server returns for a collection that does not exist yet; carries the safe `error` code. | Release 0 correction vote, then the planner's category. | Release 0 text. |
| `disabled` | `RAG_ENABLED=false`. The `grounding` key is omitted so the Release 0 payload is byte-identical. | Release 0. | Release 0 text. |

In the Ask Tally card, a grounded or insufficient suggestion shows a
confidence chip (`HIGH`, `MEDIUM`, `LOW`, or `INSUFFICIENT`). A grounded one
lists its sources under "Based on:", labelling transaction records
(`[1] transaction 7 · 24 Jun 2026 · Anytime Fitness Ultimo · $17.50 · Fitness`)
differently from guide chunks (`[2] guide categories.md: "..."`). The one-click
"Accept suggestion" button appears only for `high` or `medium` confidence, or
for a Release 0 correction-vote suggestion; a `low` suggestion is pre-selected
in the dropdown instead. `disabled` and `unavailable` render the Release 0
markup.

The records collection is refreshed three ways, each logged as `RAG_REFRESH`:
on a background thread at process start when `RAG_REFRESH_ON_START=true`
(up to ten attempts three seconds apart, because the RAG server may still be
ingesting its own sources), on a background thread after a confirmed create
when `RAG_REFRESH_AFTER_WRITE=true`, and on demand via `POST /rag/refresh`,
which returns `{"feature", "total", "kinds": {"transaction", "correction"},
"duration_ms"}`. Background refresh failures are logged and never change a
write result. The startup thread is started from `python -m backend`, not on
import, so the test client never opens a socket.

### Logging

When `AGENT_LOG_ENABLED=true`, the backend emits one structured `AI_WORKFLOW`
JSON record for every stage and one completion record for every cycle. The
records include request ID, phase, model, iteration, stage, status, duration,
and safe error type. User messages, prompts, transaction values, and model
response bodies are deliberately excluded.

The same switch emits one `MCP_TOOL` record per tool invocation, including
the `fallback_database`, `failed`, and `skipped_disabled` outcomes, and one
`MCP_TOOLS_LISTED` record per `GET /mcp/tools` call:

```json
{"event": "MCP_TOOL", "request_id": "...", "phase": "initial", "iteration": 1,
 "stage": "ACT", "server": "http://host.docker.internal:8000/mcp",
 "tool": "search_transactions",
 "arguments": {"start_date": "2026-08-01", "merchant": "Woolworths"},
 "residual_filters": [], "status": "succeeded", "rows": 4, "truncated": false,
 "duration_ms": 912.4, "error": null}
```

`arguments` only ever carries filter values from the validated plan, and
`error` is a safe code, so no user text, prompt, or model output reaches the
record.

Grounded category suggestions emit one `RAG_GROUNDING` record per attempt
(including `disabled` and `unavailable`) and every records refresh emits one
`RAG_REFRESH` record:

```json
{"event": "RAG_GROUNDING", "request_id": "...", "phase": "initial", "iteration": 1,
 "stage": "ACT", "collections": ["transactions-records", "transactions"],
 "retrieved": 9, "survivors": 3, "best_distance": 0.31, "model_probability": 0.93,
 "confidence": "high", "status": "grounded", "derived_from_votes": false, "uncited": false,
 "citations": 2, "model": "qwen2.5:3b", "duration_ms": 1480.2, "error": null}
{"event": "RAG_REFRESH", "trigger": "startup", "collection": "transactions-records",
 "total": 42, "kinds": {"transaction": 38, "correction": 4},
 "duration_ms": 312.7, "status": "succeeded", "error": null}
```

Neither record carries document text, excerpts, the merchant, the
description, or the user's message; `citations` is a count.

`AGENT_TRACE_ENABLED` independently controls whether the safe stage trace is
returned in API responses.

## Data model

The SQLite service owns three tables:

- `categories` with case-insensitive unique names and optional `need`, `want`,
  or `saving` types;
- `transactions` with date, merchant, description, amount, category, and
  created/updated timestamps;
- `category_corrections`, which records the previous and user-selected
  category for a transaction.

On first startup, a completely empty database is populated with demo
categories, transactions, and correction history. Later startups preserve
existing data and do not reseed it.

## Configuration

Compose supplies production-ready defaults. The backend reads:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5001` | Backend port. |
| `TRANSACTIONS_DB_URL` | `http://transactions-db:6001` | Database service base URL. |
| `DATABASE_TIMEOUT_SECONDS` | `20` | Database HTTP timeout. |
| `ANOMALIES_BACKEND_URL` | `http://anomalies-backend:5004` | Anomaly review service URL. |
| `ANOMALIES_TIMEOUT_SECONDS` | `10` | Anomaly notification timeout. |
| `OLLAMA_URL` | `http://ollama:11434` | Ollama base URL. |
| `CHAT_MODEL` | `qwen2.5:3b` | Planner model. |
| `AGENT_MAX_ITERATIONS` | `2` | Agent iteration limit, clamped to one or two. |
| `AGENT_TRACE_ENABLED` | `true` | Include safe workflow traces in responses. |
| `AGENT_LOG_ENABLED` | `true` | Emit structured workflow logs. |
| `AGENT_REQUEST_TTL_SECONDS` | `900` | Lifetime of pending category and preview state. |
| `AI_TIMEOUT_SECONDS` | `90` | Ollama request timeout. |
| `MCP_ENABLED` | `true` | MCP mode switch. CI sets `false`. |
| `MCP_SERVER_URL` | `http://host.docker.internal:8000/mcp` | Shared MCP server. |
| `MCP_TIMEOUT_SECONDS` | `30` | Per MCP tool call timeout. |
| `MCP_ALLOWED_TOOLS` | `search_transactions` | Comma-separated tool allow list. |
| `MCP_FALLBACK_TO_DATABASE` | `true` | Read from the database when MCP is unreachable. |
| `MCP_TOOL_SUPPORTS_EXTENDED_FILTERS` | `true` | Send the merchant, text, and amount filters to the tool instead of applying them to the returned rows. |
| `RAG_ENABLED` | `true` | RAG mode switch. CI sets `false`. |
| `RAG_SERVER_URL` | `http://host.docker.internal:5003` | Shared RAG server. |
| `RAG_RECORDS_COLLECTION` | `transactions-records` | Backend-owned collection of transaction and correction documents. |
| `RAG_GUIDE_COLLECTION` | `transactions` | Server-owned collection ingested from `sources/transactions/`. |
| `RAG_TOP_K` | `6` | Records retrieved per suggestion. |
| `RAG_GUIDE_TOP_K` | `3` | Guide chunks retrieved per suggestion. |
| `RAG_TIMEOUT_SECONDS` | `15` | Per `/retrieve` and `/refresh` call timeout. |
| `RAG_REFRESH_ON_START` | `true` | Refresh the records collection at startup. |
| `RAG_REFRESH_AFTER_WRITE` | `true` | Refresh the records collection after a confirmed create. |
| `RAG_HIGH` | `0.6` | Best distance below this, with two or more survivors, is `high` confidence. |
| `RAG_MEDIUM` | `0.9` | Best distance below this is `medium` confidence. |
| `RAG_LOW` | `1.2` | Best distance up to this is `low` confidence. Documents farther than this are not used as context; if none remain the result is insufficient context. |
| `RAG_MODEL` | `qwen2.5:3b` | Model used for the grounded category choice. |
| `RAG_LOGPROBS` | `true` | Ask Ollama for per-token log probabilities and gate the confidence band on the answer's probability. |
| `RAG_PROB_HIGH` | `0.8` | Minimum joint probability of the category-name tokens to keep a `high` band; below it the band drops to `medium`. |
| `RAG_PROB_MEDIUM` | `0.5` | Minimum probability to keep a `medium` band; below it the band drops to `low`. |

The three distance thresholds must satisfy
`0 < RAG_HIGH < RAG_MEDIUM < RAG_LOW`, and the two probability thresholds
`0 < RAG_PROB_MEDIUM < RAG_PROB_HIGH <= 1`. An invalid combination logs one
warning and falls back to the defaults.

The database process reads `PORT` and `DB_PATH`; Compose uses port `6001` and
`/app/data/transactions.db`. When a transaction is deleted, the database also
removes the associated anomaly by calling the anomalies database, reading
`ANOMALIES_DB_URL` (default `http://anomalies-db:6004/anomalies`) and
`ANOMALIES_TIMEOUT_SECONDS` (default `10`). This cleanup is best-effort: a
failure to reach the anomalies database is logged and never fails the delete.
The frontend reads `PORT`; Compose uses `3001`.

## Tests and probes

Install the Python dependencies and run the automated suite from the
repository root:

```powershell
python -m pip install -r janelle\backend\requirements.txt -r janelle\database\requirements.txt -r janelle\test\requirements.txt
python -m pytest janelle\test -q
```

With the services running, the endpoint probe checks health, frontend proxying,
list endpoints, category CRUD, transaction CRUD, and validation, then removes
its synthetic records:

```powershell
python janelle\scripts\test\janelle_endpoint_smoke.py
```

The live AI probe checks that planning does not write, confirmation performs
exactly one verified write, and cleanup succeeds:

```powershell
python janelle\scripts\test\janelle_ai_workflow_probe.py
```

The NFR probe runs against a temporary SQLite database and enforces the local
sequential and parallel transaction-read baselines:

```powershell
python janelle\scripts\test\janelle_nfr_probe.py
```

Each probe accepts `--output <path>` to save its JSON report. Release 0
results, workflow logs, and supporting material are documented in
[`docs/release-0/janelle/README.md`](../docs/release-0/janelle/README.md).
