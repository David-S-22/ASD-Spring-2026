# Shared terminal agentic loop (Plan → Act → Observe → Adapt)

A terminal-driven review workflow for the group application. Each run picks a
review target, collects evidence from the repository (architecture mode) or
from the two shared servers (MCP and RAG validation modes), sends it through
a local LLM, and ends with a **human review-and-adapt step** whose decision
is recorded. Every run writes a machine- and human-readable record to
`reports/` — the Agentic Loop Workflow Record the Release 0 report requires.

By team decision (31 Aug) the shared loop is **file-based and deliberately
barebones**: two Python files, evidence read from the repository, no probing
of running services. Each student adds their own review modes through the
extension point below. Live-probing collectors (database row counts over
HTTP, endpoint latency sweeps, CI run conclusions) exist as a worked example
of the extension point and are kept as individual work, not on `main`.
Release 1 (criterion 5 of the brief: the loop 'extended with MCP and RAG
validation modes') adds two live-probing validation modes for the shared MCP
and RAG servers in `validate.py`; the architecture mode stays file-based and
the record format is unchanged.

## What it reviews

| Mode | Evidence collected (OBSERVE) | Models |
|---|---|---|
| Architecture | Compose service inventory and dependency edges, student directory layout, required directories (`.github/workflows/`, `docs/`, `shared/`, `ai-services/`, `scripts/`), shared `index.html` entry point | qwen2.5:0.5b + llama3.1:8b review |
| MCP validation | `MCP_SERVER_URL` (default `http://localhost:8000/mcp`): registered tools with their required arguments (a successful listing is the liveness check), the read-only smoke calls registered in `validate.SMOKE_CALLS` (tools without an entry are listed, not called), two boundary probes (`no_such_tool`, and the first registered tool with a required argument called with `{}`) | qwen2.5:0.5b + llama3.1:8b review |
| RAG validation | `RAG_SERVER_URL` (default `http://localhost:5003`): `/health` collections, one benchmark question per `validate.RAG_BENCHMARKS` entry whose collection exists (others print "collection listed, no benchmark registered"), an off-topic probe on the first collection that answered compared with its on-topic distance, an unknown-feature probe (a 4xx is a rejection; a 5xx is recorded as a server error) | qwen2.5:0.5b + llama3.1:8b review |

Ports and services are read from `docker-compose.yml` at run time — nothing
is hardcoded, so the review follows whatever the team settles on. Student
directories are derived (any root directory containing `backend/`), not
listed in code.

## The loop stages

- **PLAN** — the review target is chosen and the externalised prompt files
  for that mode are loaded from `prompts/<family>/`.
- **OBSERVE** — evidence is collected (files for the architecture mode; live
  probes of the two shared servers for the MCP and RAG modes).
- **ACT** — the implementation model produces a finding; a second, stronger
  review model then reviews it.
- **ADAPT** — the human accepts, rejects, or edits the finding at the
  terminal; the decision (and any edit) goes into the run record.

## How to run

The architecture mode needs nothing running. The MCP and RAG modes probe the
two shared servers: `docker compose up -d` first (the smoke calls read
transactions-db :6001 and, after #141, anomalies-db :6004 through the MCP
server), then `python ai-services/rag-server/server.py`, then
`python ai-services/mcp-server/server.py`. A server that is down is recorded
as `UNREACHABLE` in the OBSERVE evidence and the run still completes all four
stages; `ok=False` is reserved for loop misconfiguration (for example
`fastmcp` not installed — `pip install -r agentic_loop/requirements.txt`).
The RAG mode calls the RAG server directly because it validates that server;
feature backends do not — they reach retrieval only through the MCP
`retrieve_context` tool (team decision 13 Sep). The RAG mode validates
retrieval (collections, chunks, distances), not grounded answers, which each
backend produces. The run record lands in `reports/` like the other modes;
captures of Release 1 runs are committed separately. For real model output
ollama must be up (`docker compose up -d ollama`; the models are the two
`ai-services` already pulls, ~5 GB on first start). If the model is
unreachable the run still completes and records the failure as part of the
run record.

```
pip install -r agentic_loop/requirements.txt
python -m agentic_loop.main
```

Run it from the repository root. Each run writes `reports/report.json`,
`reports/report.md` and `reports/run-view.md` (gitignored; a committed
sample lives at `docs/release-0/agentic-loop/sample-run/`).

## Engine walkthrough

The whole engine is three files (`validate.py` holds the two live
collectors), readable top to bottom:

**`main.py` (~205 lines)** — everything except the record. In order:
`read_prompt` and `call_model` (one OpenAI-compatible call to ollama;
failures are returned as strings, never raised); `collect_architecture`
(the OBSERVE evidence: compose services/ports/dependency edges via PyYAML,
derived student directories, required-directory check); the `MODES` dict
(one entry per review mode); `run_review` (the four stages in sequence,
each printed as a `[mode][STAGE]` banner and recorded); `adapt` (the
accept / reject / edit prompt — closes cleanly if input ends); and `main`
(a numbered menu built from `MODES`).

**`validate.py` (~212 lines)** — the two live collectors, read top to
bottom: the registries (`SMOKE_CALLS`, `BOUNDARY_PROBES`, `RAG_BENCHMARKS`),
then the shared formatters `_shape`/`_one_line`; the MCP half —
`_timed_call`, `_probe_mcp`, `_format_mcp`, `collect_mcp` — lists the
server's tools and runs the registered smoke calls and boundary probes; the
RAG half — `_retrieve`, `_format_benchmark`, `_format_rag`, `collect_rag` —
runs one benchmark question per registered collection. Both `collect_mcp`
and `collect_rag` always return `(ok, evidence)`: a server that cannot be
reached is honest `UNREACHABLE` evidence, not a crash; a boundary probe the
server refuses is `rejected`, one it accepts instead is flagged
`NOT rejected` (that is itself a finding, not a pass). Add your own feature
with one registry line in your own PR — a smoke call,
`SMOKE_CALLS["get_transactions_with_confirmed_anomalies"] = {}`, or a
benchmark, `RAG_BENCHMARKS["savings"] = "advice about how to generate
savings advice"` — no engine edit, no test edit.

**`record.py` (~55 lines)** — accumulates each reviewed mode and rewrites
the three `reports/` files after every completed mode, so a crash cannot
lose the record.

## Extending the loop (per-student review modes)

Adding a mode does not require touching the engine flow:

1. Add prompt files under `prompts/<your-family>/` — these are your own
   criterion-5 prompt assets (`implementation/system_prompt.txt`,
   `implementation/task_prompt.txt`, `review/review_prompt.txt`).
2. Write a collect function in `main.py` (or `validate.py` for a live probe)
   returning `(ok, evidence_text)` for whatever your mode reviews.
3. Add one entry to the `MODES` dict. The menu numbers itself.

### Joining the MCP and RAG validation modes (no new mode needed)

- `SMOKE_CALLS["<tool name as registered>"] = {<arguments>}` — one read-only
  call per tool; tools without an entry are listed but not called; tools not
  registered on the server are ignored; each call has 10 s. Example:
  `"get_transactions_with_confirmed_anomalies": {}`.
- `RAG_BENCHMARKS["<sources folder name>"] = "<one question your backend
  really asks>"` — runs only when `/health` lists that collection. Example:
  `"savings": "advice about how to generate savings advice"`.
- Edit your own line in your own PR (it is a shared file). Tests are beside
  the module: `python -m pytest agentic_loop/test_validate.py -q`, run by
  Sophia-CI on every `agentic_loop/**` and `prompts/**` change; they do not
  depend on the registry contents, so adding a line needs no test edit.

`validate.py` is the worked example of a live-probing collector; the parked
R0 collectors (database, endpoints, devops) remain individual work.

## Lab traceability

The loop is an interpretation of the Labs 04–05 reference implementation
([asd-labs](https://github.com/Georges034302/asd-labs)): the same
Plan → Act → Observe → Adapt workflow, stage banners, externalised prompts,
two-model review, and the three `reports/` files Lab 05 defines.

Known deviations from the labs, all deliberate:

- **Engine size.** The labs' engine spans a 16-file package (config,
  registry, collectors, pipelines, reporter). The team judged that
  over-engineered for our purpose (31 Aug); this version condenses it to
  two files with the same observable behaviour and stages.
- **Evidence scope.** The labs' db and endpoints collectors gather live
  evidence (real HTTP requests, database row checks). By the 31 Aug decision
  the architecture mode is file-based; the Release 1 MCP and RAG validation
  modes probe the two shared servers because the brief asks the loop to
  validate them — the R1 return of live collectors this paragraph
  anticipated.
- **Database access.** The lab db collector opens the SQLite file
  directly. The parked port reads each student's database API over HTTP
  instead, respecting service data ownership.

## Prompt families

| Family | Used by | Files |
|---|---|---|
| `prompts/architecture/` | mode 1, Architecture | `implementation/system_prompt.txt`, `implementation/task_prompt.txt`, `review/review_prompt.txt` |
| `prompts/mcp/` | mode 2, MCP validation (`validate.collect_mcp`) | same three |
| `prompts/rag/` | mode 3, RAG validation (`validate.collect_rag`) | same three |
| `prompts/bills/` | Bills Release 0 session prompts, filed by stage (not a loop mode) | see `prompts/bills/README.md` |

Task prompts ask direct questions and cap replies at 80 words; the Release 0
runs showed that menu-style prompts make `qwen2.5:0.5b` echo the menu as
findings.

## Environment variables

There is no `.env` in the repo; a root-level `.env` is loaded if you create
one. Defaults suit a host-side terminal talking to the compose-published
ollama port:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint of the ollama service |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` | Implementation model |
| `OLLAMA_REVIEW_MODEL` | `llama3.1:8b` | Review model |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | MCP validation endpoint |
| `RAG_SERVER_URL` | `http://localhost:5003` | RAG validation endpoint |

Both defaults are models `ai-services` already pulls — no extra downloads.
The MCP mode needs `fastmcp==4.0.3` and the RAG mode `requests==2.34.2`, both
pinned in `agentic_loop/requirements.txt`.
