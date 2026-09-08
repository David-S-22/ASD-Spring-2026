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
| `backend/services/` | Ollama planning, trusted transaction operations, request orchestration, and the bounded Plan -> Act -> Observe -> Adapt runner. |
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

Each transaction service exposes `GET /health`. Compose persists SQLite data
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

The database API also exposes
`POST /transactions/<id>/category-correction` and
`GET /category-corrections`. Transaction list queries support `q`,
`merchant`, `date_from`, `date_to`, `since`, `category_id`, `min_amount`,
and `max_amount`.

## AI workflow and safeguards

The planner prompt is `backend/prompts/chat_prompt.txt`. The configured model
can plan one transaction operation and request deterministic calculations
such as count, sum, average, or largest purchases. Trusted application code
validates and grounds the model output before reading data or preparing a
write.

The workflow is bounded to at most two Plan -> Act -> Observe -> Adapt
iterations. Reads are calculated from database rows by application code.
Creates, updates, and deletes never write during planning: they return a
before/after preview, require explicit confirmation, and are matched to
server-held request state. Confirmed updates and deletes use a stored row
version to reject stale previews, and every attempted write is checked
against the resulting database state.

Each response includes an `agent` object containing the request ID, planner
model, workflow status, and, when enabled, a stage trace with iteration,
status, summary, and duration.

### Logging

When `AGENT_LOG_ENABLED=true`, the backend emits one structured `AI_WORKFLOW`
JSON record for every stage and one completion record for every cycle. The
records include request ID, phase, model, iteration, stage, status, duration,
and safe error type. User messages, prompts, transaction values, and model
response bodies are deliberately excluded.

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

The database process reads `PORT` and `DB_PATH`; Compose uses port `6001` and
`/app/data/transactions.db`. The frontend reads `PORT`; Compose uses `3001`.

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
