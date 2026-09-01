# Shared terminal agentic loop (Plan → Act → Observe → Adapt)

A terminal-driven review workflow for the group application. Each run picks a
review target, collects evidence from the repository, sends it through a
local LLM, and ends with a **human review-and-adapt step** whose decision is
recorded. Every run writes a machine- and human-readable record to
`reports/` — the Agentic Loop Workflow Record the Release 0 report requires.

By team decision (31 Aug) the shared loop is **file-based and deliberately
barebones**: two Python files, evidence read from the repository, no probing
of running services. Each student adds their own review modes through the
extension point below. Live-probing collectors (database row counts over
HTTP, endpoint latency sweeps, CI run conclusions) exist as a worked example
of the extension point and are kept as individual work, not on `main`.

## What it reviews

| Mode | Evidence collected (OBSERVE) | Models |
|---|---|---|
| Architecture | Compose service inventory and dependency edges, student directory layout, required directories (`.github/workflows/`, `docs/`, `shared/`, `ai-services/`, `scripts/`), shared `index.html` entry point | qwen2.5:0.5b + llama3.1:8b review |

Ports and services are read from `docker-compose.yml` at run time — nothing
is hardcoded, so the review follows whatever the team settles on. Student
directories are derived (any root directory containing `backend/`), not
listed in code.

## The loop stages

- **PLAN** — the review target is chosen and the externalised prompt files
  for that mode are loaded from `prompts/<family>/`.
- **OBSERVE** — evidence is collected from the repository.
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

The whole engine is two files, ~265 lines, readable top to bottom:

**`main.py` (~205 lines)** — everything except the record. In order:
`read_prompt` and `call_model` (one OpenAI-compatible call to ollama;
failures are returned as strings, never raised); `collect_architecture`
(the OBSERVE evidence: compose services/ports/dependency edges via PyYAML,
derived student directories, required-directory check); the `MODES` dict
(one entry per review mode); `run_review` (the four stages in sequence,
each printed as a `[mode][STAGE]` banner and recorded); `adapt` (the
accept / reject / edit prompt — closes cleanly if input ends); and `main`
(a numbered menu built from `MODES`).

**`record.py` (~55 lines)** — accumulates each reviewed mode and rewrites
the three `reports/` files after every completed mode, so a crash cannot
lose the record.

## Extending the loop (per-student review modes)

Adding a mode does not require touching the engine flow:

1. Add prompt files under `prompts/<your-family>/` — these are your own
   criterion-5 prompt assets (`implementation/system_prompt.txt`,
   `implementation/task_prompt.txt`, `review/review_prompt.txt`).
2. Write a collect function in `main.py` returning `(ok, evidence_text)`
   for whatever your mode reviews.
3. Add one entry to the `MODES` dict. The menu numbers itself.

The parked live-probing modes (database, endpoints, devops) are a complete
worked example of this pattern.

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
  evidence (real HTTP requests, database row checks). By the same team
  decision the shared loop is file-based; the live-probing collectors are
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
