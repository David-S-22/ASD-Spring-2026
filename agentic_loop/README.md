# Shared terminal agentic loop (Plan → Act → Observe → Adapt)

A terminal-driven review workflow for the group application. Each run picks a
review target, collects evidence from the repository, sends it through a
local LLM, and ends with a **human review-and-adapt step** whose decision is
recorded. Every run writes a machine- and human-readable record to
`reports/` — the Agentic Loop Workflow Record the Release 0 report requires.

By team decision (31 Aug) the shared loop is **file-based**: the evidence it
collects comes from files in the repository, not from probing running
services. The engine is the shared part; each student adds their own review
modes through the extension point below. Live-probing collectors (database
row counts over HTTP, endpoint latency sweeps, CI run conclusions) exist as
a worked example of the extension point and are kept as individual work, not
on `main`.

## What it reviews

| Mode | Evidence collected (OBSERVE) | Models |
|---|---|---|
| Architecture | Compose service inventory and dependency edges, student directory layout, required directories (`.github/workflows/`, `docs/`, `shared/`, `ai-services/`, `scripts/`), shared `index.html` entry point | qwen2.5:0.5b + llama3.1:8b review |

Ports and services are read from `docker-compose.yml` at run time — nothing
is hardcoded, so the review follows whatever the team settles on.

## The loop stages

- **PLAN** — the review target is chosen and the externalised prompt files
  for that mode are loaded from `prompts/<family>/`.
- **OBSERVE** — the collector gathers evidence from the repository.
- **ACT** — the implementation model produces a finding; a second, stronger
  review model then reviews it.
- **ADAPT** — the human accepts, rejects, or edits the finding at the
  terminal; the decision (and any edit) goes into the run record.

## How to run

The architecture mode needs nothing running — it reads the repository. For
real model output ollama must be up (`docker compose up -d ollama`; the
models are the two `ai-services` already pulls, ~5 GB on first start). If the
model is unreachable the run still completes and records the failure as part
of the run record.

```
pip install -r agentic_loop/requirements.txt
python -m agentic_loop.main
```

Run it from the repository root. Each run writes `reports/report.json`,
`reports/report.md` and `reports/run-view.md` (gitignored; a committed
sample lives at `docs/release-0/agentic-loop/sample-run/`).

## Engine walkthrough

The engine is three files, readable top to bottom in about 240 lines:

**`main.py` (~75 lines)** — the terminal shell. Resolves the repo root,
loads `.env` if one exists, builds the mode config, prompt registry, AI
runner and run recorder, then loops on a numbered menu. A menu choice maps
to a mode key; `run_mode` does the rest. Choice 5 runs every configured mode
in sequence; 0 exits.

**`core/orchestrator.py` (~107 lines)** — the loop itself. `run_mode` walks
one mode through the four stages, printing a `[mode][STAGE]` banner and
recording each step:

1. PLAN — announce the target, load the mode's prompt files from
   `prompts/<family>/` (which files is config, not code:
   `config/review_config.py`).
2. OBSERVE — call the mode's collector from the `COLLECTORS` dict. A
   collector is a function `(app_dir, repo_root) -> (ok, evidence_text)`.
   Collectors are deterministic code, so the evidence layer is exact and
   unit-testable; only the interpretation layer is probabilistic.
3. ACT — send system + task prompts and the evidence to the implementation
   model (`core/ai_runner.py`, an OpenAI-compatible client pointed at
   ollama), then hand its output to the review model for a second pass.
4. ADAPT — `_adapt()` shows the finding at the terminal and asks
   accept / reject / edit. The decision and any edit or rejection reason go
   into the run record (`core/recorder.py`), which writes the
   `reports/` files at the end of the run.

**`collectors/compose.py` (~57 lines)** — the address book. PyYAML
`safe_load` on `docker-compose.yml` plus small dict walks: service names,
first published host port per service, `depends_on` edges. It does not
validate the file (docker does that) — it tells collectors what exists so
nothing is hardcoded.

The remaining files are small and single-purpose: `core/prompt_registry.py`
(20 lines, reads prompt files), `core/reporter.py` (20 lines, menu and
result printing), `core/recorder.py` (113 lines, accumulates the run and
writes the three report files), `config/review_config.py` (which prompt
files each mode uses).

## Extending the loop (per-student review modes)

Adding a mode does not require touching or understanding the engine:

1. Add prompt files under `prompts/<your-family>/` — these are your own
   criterion-5 prompt assets.
2. Optionally add a collector (~70–90 lines) returning
   `(ok, evidence_text)` for whatever your mode reviews.
3. Register the mode: one entry each in `config/review_config.py`,
   the orchestrator's `COLLECTORS` dict, and the menu.

The parked live-probing modes (database, endpoints, devops) are a complete
worked example of this pattern.

## Lab traceability

The loop is a port of the reference implementation from Labs 04–05
([asd-labs](https://github.com/Georges034302/asd-labs)): same package
layout, same filenames, same roles — Lab 04 defines the engine, collectors,
pipelines and externalised prompts; Lab 05 adds the DevOps mode and the
three `reports/` files.

Known deviations from the labs, both deliberate:

- **Evidence scope.** The labs' db and endpoints collectors gather live
  evidence (real HTTP requests, database row checks). By team decision
  (31 Aug) the shared loop is file-based; the live-probing collectors are
  parked as individual work and can return as an R1 proposal.
- **Database access.** The lab db collector opens the SQLite file
  directly. The parked port reads each student's database API over HTTP
  instead, respecting service data ownership.

## Environment variables

There is no `.env` in the repo; a root-level `.env` is loaded if you create
one. Defaults suit a host-side terminal talking to the compose-published
ollama port:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint of the ollama service |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` | Implementation model |
| `OLLAMA_REVIEW_MODEL` | `llama3.1:8b` | Review model |

Both defaults are models `ai-services` already pulls — no extra downloads.
