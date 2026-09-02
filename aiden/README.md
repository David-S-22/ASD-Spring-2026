# Anomaly Detection Service

An AI-assisted transaction anomaly-detection feature, split into three
containerised services (frontend, backend, database) with a dedicated test
suite. Each service is a small Flask/nginx app that runs independently via
Docker Compose.

## Project structure

### `frontend/`

The user-facing layer. An **nginx** container that serves a single-page
`public/index.html` and reverse-proxies API calls under `/anomalies-backend/`
to the backend service.

- `public/index.html` — HTMX-driven UI listing anomalies, with buttons to create
  a dummy anomaly and check a dummy transaction. Includes toast notifications.
- `nginx.conf` — templated nginx config (`${PORT}`, `${ANOMALIES_BACKEND_URL}`)
  that proxies backend requests.
- `Dockerfile` — builds on `nginx:alpine`, exposes port `3004`.

### `backend/`

The application/logic layer. A **Flask** app exposing the anomaly-detection API
and orchestrating the AI agent.

- `app.py` — Flask routes: index, `/anomalies` (render list), `/check-transaction`
  (enqueue a transaction for asynchronous review; a background worker runs it
  through the agent and persists flagged anomalies), `/dummy-anomaly`, and `/fact`.
- `review_queue.py` — in-process queue and background worker that perform the slow
  LLM review off the request thread and persist any anomaly.
- `services/` — external integrations:
  - `agent_api.py` — the skeptical anomaly-detection agent; prompts the model,
    parses/validates JSON findings, and builds context from prior user-reviewed
    anomalies.
  - `ollama_api.py` — thin OpenAI-compatible client wrapper (cached singleton)
    for the Ollama model.
  - `anomalies_api.py` / `transaction_api.py` — HTTP clients for the database and
    transaction services.
- `templates/` — Jinja fragments (`anomalies.jinja`) returned to HTMX.
- `helpers.py` — (de)serialisation and env helpers.
- `Dockerfile` / `requirements.txt` — service image and dependencies.

### `database/`

The persistence layer. A **Flask + SQLAlchemy** app exposing a REST CRUD API for
anomalies backed by SQLite.

- `models.py` — the `Anomaly` SQLAlchemy model and its `to_dto()` mapping.
- `app.py` — `anomalies` blueprint with GET/POST/PATCH/DELETE routes (including
  delete-by-transaction), JSON error handling, and `setup_database()`.
- `helpers.py` — field-setting and parsing helpers.
- `Dockerfile` / `requirements.txt` — service image and dependencies.

### `test/`

The automated test suite (pytest).

- `test_backend.py` — exercises backend routes, mocking the database service by
  redirecting `requests` to an in-memory test client via `responses`.
- `test_database.py` — CRUD tests against an in-memory SQLite database.
- `conftest.py` — shared fixtures. `requirements.txt` — test dependencies.

## Development processes

### Static type checking (mypy)

Type checking is enforced with **mypy**, configured in `mypy.ini`
(Python 3.13, `check_untyped_defs = True`, `mypy_path = ..` so the shared package
resolves).

### Testing (pytest)

Unit tests run without any live services — the database uses an in-memory SQLite
DB and the backend intercepts outbound HTTP.

### CI/CD

GitHub Actions workflow `.github/workflows/aiden-ci.yml` runs on pull requests to
`main` (and manual dispatch) when `aiden/**` or `shared/**` change. It has two jobs:

- **test** — installs the backend, database, and test requirements, runs mypy
  (annotating issues inline), then runs pytest.
- **build-health** — brings up the three containers via `docker compose`, then
  curls each service's health endpoint (frontend `3004`, backend `5004`,
  database `6004`) and tears the containers down afterwards.

### Running locally

The services are designed to run together via Docker Compose (see the repository
root `docker-compose` configuration), which wires the frontend, backend, and
database containers together along with the shared model package.
