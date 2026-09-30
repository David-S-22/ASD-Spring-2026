# Shared terminal agentic loop (Plan → Act → Observe → Adapt)

A terminal review workflow for the group application. Each run picks a
review target, collects evidence, sends it through two local LLMs, and ends
with a human accept / reject / edit step. Every run writes the run record
(`reports/report.json`, `report.md`, `run-view.md`) the reports require.

Two Python files: `main.py` (the loop and the collectors) and `record.py`
(the run record). One `collect` function and three prompt files per mode.

## Modes

| Mode | OBSERVE evidence | Asserts (one PASS/FAIL line each) |
|---|---|---|
| Architecture | `docker-compose.yml` services, ports and dependency edges; student directories; required directories; shared `index.html` | Read from files, nothing running |
| MCP validation | Live, read-only. Lists tools and the `search_transactions` schema; calls it unfiltered, then filtered by the first row's merchant and month, then with a merchant that cannot exist | Tool registered with `start_date`, `end_date`, `merchant`; result is a list of rows with `id`, `date`, `merchant`, `amount`; every row matches the filters and the impossible merchant returns 0 rows; under 3000 ms |
| RAG validation | Live, read-only. `GET /health`; builds a question from one real `transactions-records` chunk; `POST /retrieve` (`k=3`) on `transactions-records` and `transactions` for that question and a fixed unanswerable one | Both collections present; seeded question under `RAG_INSUFFICIENT_ABOVE` with a `category_id` and the seed's merchant as best chunk; unanswerable question above the threshold; guide best chunk `doc_type` markdown |

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

## Run

```
pip install -r agentic_loop/requirements.txt
python -m agentic_loop.main
```

Run from the repository root. Needs `ollama` up for real model output
(`docker compose up -d ollama`). The validation modes also need the shared
servers on the host: `python ai-services/mcp-server/server.py` (8000) and
`python ai-services/rag-server/server.py` (5003), with `transactions-db`
running and the Transactions backend started once so `transactions-records`
is populated. Anything missing is recorded as a failure, not a crash.

`reports/` is gitignored. Committed samples: `docs/release-0/agentic-loop/`
(architecture) and `docs/release-1/agentic-loop/` (MCP and RAG).

## Environment variables

Loaded from an optional root `.env`. Defaults suit a host terminal.

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | ollama OpenAI-compatible endpoint |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` | Implementation model |
| `OLLAMA_REVIEW_MODEL` | `llama3.1:8b` | Review model |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | Shared MCP server |
| `RAG_SERVER_URL` | `http://localhost:5003` | Shared RAG server |
| `RAG_INSUFFICIENT_ABOVE` | `1.2` | Best distance above this is insufficient (same as the Transactions backend) |
| `LOOP_HTTP_TIMEOUT` | `30` | Seconds per MCP or RAG call |

## Adding a mode

1. Add `prompts/<family>/implementation/system_prompt.txt`,
   `implementation/task_prompt.txt`, `review/review_prompt.txt`.
2. Write a collect function in `main.py` returning `(ok, evidence_text)`.
3. Add one entry to `MODES`. The menu numbers itself.

The MCP and RAG modes are the worked example; the engine did not change.

## Lab traceability

Same Plan → Act → Observe → Adapt workflow, stage banners, externalised
prompts, two-model review and three report files as the Labs 04–05
reference ([asd-labs](https://github.com/Georges034302/asd-labs)).
Deliberate deviations: two files instead of a 16-file package (team
decision, 31 Aug); live evidence only for the two shared AI servers, with
student database and endpoint collectors kept as individual work; no direct
SQLite access, data is reached through each service's API.
