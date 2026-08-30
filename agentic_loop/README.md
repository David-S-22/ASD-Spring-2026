# Shared terminal agentic loop (Plan → Act → Observe → Adapt)

A terminal-driven review workflow for the group application. Each run picks a
review target, collects real evidence from the running app and the
repository, sends it through a local LLM, and ends with a **human
review-and-adapt step** whose decision is recorded. Every run writes a
machine- and human-readable record to `reports/` — the Agentic Loop Workflow
Record the Release 0 report requires.

Offered to the team as the shared loop; each student's prompt assets live
under `prompts/` and each student can add their own collectors and prompt
files.

## What it reviews

| Mode | Evidence collected (OBSERVE) | Models |
|---|---|---|
| Database | Every `*-db` service in `docker-compose.yml`: health route, list route, row counts vs the 10-row seed minimum — over HTTP, never by opening another feature's SQLite file | qwen2.5:0.5b |
| Endpoints | Every `*-backend` service: `/health` plus the documented GET `/api/*` and `/ui/*` routes for bills, with status + latency (the NFR timing evidence) | qwen2.5:0.5b |
| Architecture | Compose service inventory and dependency edges, student directory layout, required directories (`.github/workflows/`, `docs/`, `shared/`, `ai-services/`, `scripts/`), shared `index.html` entry point | qwen2.5:0.5b + llama3.1:8b review |
| DevOps | Workflow files, student mapping, jobs per workflow, latest run conclusion on `main` (when `gh` is installed) | qwen2.5:0.5b + llama3.1:8b review |

Ports are parsed from `docker-compose.yml` at run time — nothing is
hardcoded, so the loop follows whatever port assignments the team settles on.
An unreachable service is recorded as evidence, not treated as an error.

## The loop stages

- **PLAN** — the review target is chosen and the externalised prompt files
  for that mode are loaded from `prompts/<family>/`.
- **OBSERVE** — the collector gathers live evidence from the running app /
  the repository.
- **ACT** — the implementation model produces a finding; architecture and
  devops modes add a second, stronger review model.
- **ADAPT** — the human accepts, rejects, or edits the finding at the
  terminal; the decision (and any edit) goes into the run record.

## How to run

Prerequisites: the group app and ollama are up (`docker compose up -d`) and
the models are pulled (first start does this automatically; ~5 GB).

```
pip install -r agentic_loop/requirements.txt
python -m agentic_loop.main
```

Run it from the repository root. Each run writes `reports/report.json`,
`reports/report.md` and `reports/run-view.md` (gitignored; a committed
sample lives at `docs/release-0/agentic-loop/sample-run/`).

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
