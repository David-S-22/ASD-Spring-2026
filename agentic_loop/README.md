# Shared terminal agentic loop (Plan → Act → Observe → Adapt)

A terminal review workflow for the group application. Each run picks a
review target, collects evidence, sends it through two local LLMs, and ends
with a human accept / reject / edit step. Every run writes the run record
(`reports/report.json`, `report.md`, `run-view.md`) the reports require.

By team decision (31 Aug) the shared loop started **file-based and deliberately
barebones**. For Release 1 it now has one shared file-based mode, the original
shared MCP/RAG live-validation modes, plus Budgets live-validation modes that
probe Ethan's running backend and RAG service over HTTP. Each student still
adds their own review modes through the extension point below.

Two Python files: `main.py` (the loop and the collectors) and `record.py`
(the run record). One `collect` function and three prompt files per mode.

## Modes

| Mode | OBSERVE evidence | Asserts (one PASS/FAIL line each) |
|---|---|---|
| Architecture | `docker-compose.yml` services, ports and dependency edges; student directories; required directories; shared `index.html` | Read from files, nothing running |
| MCP validation | Live, read-only. Lists tools and the `search_transactions` schema; calls it unfiltered, then filtered by the first row's merchant and month, then with a merchant that cannot exist | Tool registered with `start_date`, `end_date`, `merchant`; result is a list of rows with `id`, `date`, `merchant`, `amount`; every row matches the filters and the impossible merchant returns 0 rows; under 3000 ms |
| RAG validation | Live, read-only. `GET /health`; builds a question from one real `transactions-records` chunk; `POST /retrieve` (`k=3`) on `transactions-records` and `transactions` for that question and a fixed unanswerable one | Both collections present; seeded question under `RAG_INSUFFICIENT_ABOVE` with a `category_id` and the seed's merchant as best chunk; unanswerable question above the threshold; guide best chunk `doc_type` markdown |
| Budgets MCP validation | Live Budgets `/health`, selected budget id/month, summary totals, MCP-backed `/api/chat` response source, tool name, result count, preview rows | Budgets backend reachable; response source is `mcp`; tool preview present |
| Budgets RAG validation | Live Budgets `/health`, selected budget id/month, RAG `/health` collections, RAG-backed `/api/chat` response source, confidence, insufficient-context flag, citations | Budgets backend reachable; response source is `rag`; citations/confidence present |

The validation probes seed themselves from live data, so they keep working
when the seed data changes. Neither calls `/refresh` or writes anything. An
unreachable server makes the collector return `(False, reason)`; the run
records the OBSERVE failure and continues. A single failed `/retrieve` is
recorded on its own line (`retrieve failed: HTTP <code>`) and the mode
continues.

## Stages

- **PLAN** — target chosen, prompts loaded from `prompts/<family>/`.
- **OBSERVE** — the mode's collector gathers evidence.
- **ACT** — implementation model writes a finding; review model critiques it.
- **ADAPT** — the human accepts, rejects, or edits; the decision is recorded.

## How to run

The architecture mode needs nothing running — it reads the repository.

The shared MCP and RAG validation modes need:
- host MCP server reachable on `MCP_SERVER_URL` (default `http://localhost:8000/mcp`)
- host RAG server reachable on `RAG_SERVER_URL` (default `http://localhost:5003`)
- `transactions-db` running, with the Transactions backend started at least once so `transactions-records` is populated

The Budgets MCP and RAG modes need:
- `budgets-backend` reachable on `BUDGETS_BACKEND_URL` (default `http://127.0.0.1:5006`)
- host RAG server reachable on `BUDGETS_RAG_URL` (default `http://127.0.0.1:5003`)
- at least one Budgets record available through `/api/budgets`

For real model output ollama must also be up (`docker compose up -d ollama`;
the models are the two `ai-services` already pulls, ~5 GB on first start). If
the model is unreachable the run still completes and records the failure as
part of the run record.

```
pip install -r agentic_loop/requirements.txt
python -m agentic_loop.main
```

Run from the repository root.

`reports/` is gitignored. Committed samples: `docs/release-0/agentic-loop/`
(architecture) and `docs/release-1/agentic-loop/` (MCP and RAG).

For repeatable Budgets terminal evidence outside the loop, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\ethan\test-budgets-endpoints.ps1
```

## Engine walkthrough

The whole engine is two files:

- **`main.py`** — prompts, model calls, evidence collectors, mode registry,
  and the Plan → Observe → Act → Adapt runtime.
- **`record.py`** — accumulates each reviewed mode and rewrites the three
  `reports/` files after every completed mode.

## Extending the loop

1. Add prompt files under `prompts/<family>/`:
   - `implementation/system_prompt.txt`
   - `implementation/task_prompt.txt`
   - `review/review_prompt.txt`
2. Write a collect function in `main.py` returning `(ok, evidence_text)`.
3. Add one entry to the `MODES` dict.

The Budgets MCP and RAG modes are working live-probing examples of this
pattern.

## Environment variables

Loaded from an optional root `.env`. Defaults suit a host terminal.

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | ollama OpenAI-compatible endpoint |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` | Implementation model |
| `OLLAMA_REVIEW_MODEL` | `llama3.1:8b` | Review model |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | Shared MCP server |
| `RAG_SERVER_URL` | `http://localhost:5003` | Shared RAG server |
| `RAG_INSUFFICIENT_ABOVE` | `1.2` | Best distance above this is insufficient |
| `LOOP_HTTP_TIMEOUT` | `30` | Seconds per MCP or RAG call |
| `BUDGETS_BACKEND_URL` | `http://127.0.0.1:5006` | Base URL for Ethan's Budgets backend during Budgets validation |
| `BUDGETS_RAG_URL` | `http://127.0.0.1:5003` | Base URL for the shared host RAG server during Budgets RAG validation |
| `BUDGETS_VALIDATION_BUDGET_ID` | unset | Optional specific Budgets id to validate instead of the first budget |

## Lab traceability

Same Plan → Act → Observe → Adapt workflow, stage banners, externalised
prompts, two-model review and three report files as the Labs 04–05
reference ([asd-labs](https://github.com/Georges034302/asd-labs)).

Deliberate deviations:
- two files instead of a 16-file package (team decision, 31 Aug)
- file-based architecture evidence plus targeted live shared-service probes
- no direct SQLite access; data is reached through each service's API
