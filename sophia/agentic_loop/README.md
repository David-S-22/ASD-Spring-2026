# Bills extended agentic loop

A terminal Plan → Act → Observe → Adapt review loop over the group app, with
four review modes. This is my individual, extended counterpart to the shared
loop in [#78](https://github.com/David-S-22/ASD-Spring-2026/pull/78): the same
four-stage workflow and the same `MODES` extension point, but where the shared
loop reviews files only, the service modes here observe the running system.

Run it from the repository root:

```
python -m sophia.agentic_loop.main
```

## The four modes

| Mode | What it observes |
|---|---|
| Architecture | Compose services and host ports, dependency edges, derived student directories, required-directory check, shared entry point |
| Database | Row counts over HTTP from every `*-db` service compose defines, against the ten-row seed minimum |
| Endpoints | Status and latency for every `*-backend` health route, plus the thirteen documented Bills GET routes |
| DevOps | Workflow files, their jobs, which student directory each watches, and the latest run conclusion on `main` via `gh` |

Ports are parsed from `docker-compose.yml` at run time, never hardcoded, so
the loop keeps working when the team moves a port. A service that does not
answer is recorded as a finding, not raised as an error — "unreachable" and
"empty" are different observations with different causes.

Only GET routes are swept. The loop never writes to another feature.

## Why it lives here, and why the prompts are duplicated

The shared loop is the team's and lives at the repository root; this one is my
individual work and lives entirely inside `sophia/`. Nothing outside `sophia/`
is created, imported at start-up, or written to.

The prompt assets under `prompts/` are deliberately a separate set from the
root `prompts/`. Sharing them would make this loop depend on the shared one
being merged first; keeping them here means it runs either way. That is a
choice, not an oversight.

## Layout

```
main.py            the menu, the four stages, the ADAPT prompt
collect.py         the four collect functions -- no model calls, no writes
record.py          writes reports/report.json, report.md, run-view.md
prompts/<family>/  implementation/ and review/ prompts per mode
reports/           run output, self-ignoring
```

`main.py` names two roots separately, which matters because this package sits
two levels down rather than at the repository root:

```python
FEATURE_ROOT = Path(__file__).resolve().parent   # prompts, reports
REPO_ROOT    = FEATURE_ROOT.parent.parent        # compose, workflows, students
```

Collapsing them into one — as the root version's
`Path(__file__).parent.parent` does correctly for its own location — would
resolve to `sophia/` here and silently point every collector at the wrong
tree. `main()` checks `REPO_ROOT / "docker-compose.yml"` at start-up and exits
with a readable message rather than producing empty evidence.

## Configuration

All optional; the defaults match the team's compose file.

| Variable | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` (implementation stage) |
| `OLLAMA_REVIEW_MODEL` | `llama3.1:8b` (review stage) |

The model is called over plain HTTP with `requests`, so there is no SDK
dependency — `requests` and `PyYAML` are the only requirements, both already
in `sophia/requirements.txt`.

## Tests

`sophia/test/test_loop_collect.py` and `sophia/test/test_loop_record.py` cover
the deterministic parts: host-port parsing in all three compose forms, the
architecture collector against a fixture repository, the workflow parser, and
the record writer. No model calls, no sockets, no Docker — they run in CI with
the rest of the Bills suite.

## Adding a mode

Add prompt files under `prompts/<family>/` and one entry to `MODES` in
`main.py`. The menu numbers itself.
