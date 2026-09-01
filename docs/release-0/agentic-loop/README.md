# Agentic loop — committed sample runs

Two runs of the terminal Plan → Act → Observe → Adapt loop against the live
group app, seventeen hours apart. They are kept side by side deliberately:
the first observed a gap, the team shipped a fix, and the second re-observed
the same thing and found it closed. That is the loop doing its job, rather
than a description of the loop doing its job.

| Directory | Captured | Loop | Modes | Decisions |
|---|---|---|---|---|
| [`sample-run/`](sample-run/) | 31 Aug 2026, 02:33 | the full 16-file version, before the barebones rewrite | DB, Endpoints, Architecture, DevOps | 1 rejected, 3 edited |
| [`sample-run-2026-09-01/`](sample-run-2026-09-01/) | 1 Sep 2026, 14:02 | `sophia/agentic_loop/`, the rebuilt four-mode version | Architecture, Database, Endpoints, DevOps | 1 rejected, 3 edited |

Each directory holds the terminal transcript, the run record in three forms
(`report.json`, `report.md`, `run-view.md`) and dark-terminal screenshots.
The 31 Aug directory is left exactly as it was captured.

## What changed between the two runs

### The shared entry point — observed, fixed, re-observed

On 31 Aug the architecture mode reported:

> compose defines **13 services** … `index.html` **MISSING** — no shared
> containerised entry point routing to the five frontends

That gap was one of the group-level items going into the report. Aiden's
[#77](https://github.com/David-S-22/ASD-Spring-2026/pull/77) added
`shared/frontend/**` and a `shared-frontend` service on `:3000`.

On 1 Sep the same mode reported:

> Compose defines **14 services** … `shared-frontend:3000` …
> Shared frontend index.html present: **True**

Four new dependency edges appear with it — `shared-frontend` to each of the
four feature frontends — which is what makes the shell a real entry point
rather than a fifth unconnected container.

### The `/health` finding got sharper, not just repeated

On 31 Aug two database services could not be probed at all:

> savings-db (:6002): **UNREACHABLE** — service not running or no /health route
> transactions-db (:6001): **UNREACHABLE** — service not running or no /health route

The collector could not tell "not running" from "no route" and said so. On
1 Sep, with the whole stack up, the ambiguity resolves:

> anomalies-db (:6004): health **404**; /anomalies has 0 rows
> savings-db (:6002): health **404**; list route /savings 404
> transactions-db (:6001): health **404**; /transactions has 3 rows

The services are running. They return 404 on `/health` because the route does
not exist. The same holds on the backends: `anomalies-backend`,
`savings-backend` and `transactions-backend` all return 404 on `/health`,
where `bills-backend` returns 200.

**Current status:** still open, and it matters beyond tidiness — compose
healthchecks and the CI smoke checks both depend on `/health`. Raised with
the team; not fixed at the time of writing.

### Other movement

| Observation | 31 Aug | 1 Sep |
|---|---|---|
| Compose services | 13 | 14 |
| `transactions-db` rows | unreachable | 3 (below the 10-row minimum) |
| `bills-db` rows | 13 | 12 — a clean reseed; the extra row on 31 Aug came from manual testing |
| `janelle-ci.yml` jobs | `[build-health]` | `[build-health, test]` |
| Student→workflow mapping | literal `student ?` placeholders | derived from each workflow's `paths:` filters |
| Database services | 4 of the 5 the spec expects | unchanged — `student-3` still has none |

## The two loops are not the same program

The 31 Aug run used the full 16-file engine, which the team later voted down
as over-engineered; that version survives on `feat/agentic-loop` as
individual work. The shared loop was rewritten barebones
([#78](https://github.com/David-S-22/ASD-Spring-2026/pull/78)) and reviews
files only.

The 1 Sep run used `sophia/agentic_loop/` — the rebuilt four-mode version
([#88](https://github.com/David-S-22/ASD-Spring-2026/pull/88)), which extends
the shared workflow rather than replacing it. Same four stages, same `MODES`
extension point, flat modules instead of an engine.

So the two runs are not a controlled before/after of one program. What is
being compared is what each run **observed about the group app**, and on that
the comparison holds: the same repository, the same collectors, the same
models, seventeen hours apart.

## On the ADAPT decisions

Every finding in both runs was either rejected or corrected. None was
accepted as written.

The implementation model (`qwen2.5:0.5b`) contradicted its own evidence in
all four modes on 1 Sep — claiming required directories were unlisted when
the evidence said `none`, calling correct dependency edges wrong, and listing
the same routes as simultaneously healthy and failed. The review model
(`llama3.1:8b`) caught each one and recommended dropping it.

That is worth stating plainly rather than hiding: a 0.5b model at this
context length is not reliable, and the run record shows exactly where the
human stage did the work. The corrections recorded under each `edited`
decision are written from the collected evidence, which is the part that is
trustworthy — the collectors are deterministic and their output is in the
record next to the finding they contradict.
