# Agentic loop — committed sample runs

Three runs of the terminal Plan → Act → Observe → Adapt loop against the live
group app. The first two are kept side by side deliberately: the first
observed a gap, the team shipped a fix, and the second re-observed the same
thing and found it closed. That is the loop doing its job, rather than a
description of the loop doing its job. The third is the reference capture,
taken against the composed `ollama` service with the endpoint recorded.

| Directory | Captured | Loop | Modes | Decisions |
|---|---|---|---|---|
| [`sample-run/`](sample-run/) | 31 Aug 2026, 02:33 | the full 16-file version, before the barebones rewrite | DB, Endpoints, Architecture, DevOps | 1 rejected, 3 edited |
| [`sample-run-2026-09-01/`](sample-run-2026-09-01/) | 1 Sep 2026, 14:02 | `sophia/agentic_loop/`, the rebuilt four-mode version | Architecture, Database, Endpoints, DevOps | 1 rejected, 3 edited |
| [`sample-run-2026-09-01-composed/`](sample-run-2026-09-01-composed/) | 1 Sep 2026, 16:38 | `sophia/agentic_loop/`, rewritten prompts, pinned endpoint | Architecture, Database, Endpoints, DevOps | 4 edited |

Each directory holds the terminal transcript and the run record in three forms
(`report.json`, `report.md`, `run-view.md`); the first two also hold
dark-terminal screenshots. The 31 Aug directory is left exactly as it was
captured.

## Which ollama each run used

The two earlier runs reached a **host-installed Ollama**, not the composed
`ollama` service. On Windows `localhost` resolves to both `127.0.0.1` and
`::1`; a desktop Ollama install held the IPv4 socket, so Docker's port proxy
could bind only IPv6, and `requests` resolves IPv4 first. Nothing failed and
nothing in the output said which instance answered, because both served the
same two registered models — `qwen2.5:0.5b` and `llama3.1:8b`.

The 16:38 run is the first taken against the composed service, after quitting
the desktop app and restarting `ollama` so the proxy re-bound IPv4. Its record
carries the endpoint and the model list that endpoint served, and the
transcript ends with `docker exec ollama ollama ps` as the cross-check from
the container's side. `qwen2.5:3b` appears in that list and is held only by
the container, which is what makes the run self-identifying rather than
self-asserting.

The two earlier runs remain valid observations of the group app — the
collectors read compose, the workflows and the live HTTP services, none of
which depends on which Ollama answered. What changes is only the claim that
can be made about the model host, and it is stated here rather than left
implied.

## What changed between the 31 Aug and 1 Sep runs

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

So the 31 Aug and 1 Sep runs are not a controlled before/after of one program.
What is being compared is what each run **observed about the group app**, and
on that the comparison holds: the same repository, the same collectors, the
same models, seventeen hours apart.

The third run shares the 1 Sep run's program, so those two *are* comparable as
software — they differ only in the prompts and the pinned endpoint.

## On the ADAPT decisions

Every finding in all three runs was either rejected or corrected. None was
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

### What the rewritten prompts changed, and what they did not

Before the 16:38 run the prompts were rewritten against the failure taxonomy
the earlier runs exposed. The largest defect had been caused by the prompts
themselves: each task prompt offered a menu of candidate problems — "a missing
required directory, a dependency edge that looks wrong" — and the
implementation model returned the menu as its findings. On 1 Sep at 14:02 the
architecture finding was headed *Missing required directories* while the
evidence read `Missing required directories: none`. The menus are gone; each
task prompt now asks direct questions, and the shared persona forbids
reporting a value as its opposite or placing one item in two contradictory
categories.

Architecture improved measurably: the fabricated and inverted claims are gone
and the run at 16:38 answered the service count, the entry point and the edge
check correctly. Database, endpoints and devops still fail at `qwen2.5:0.5b`,
but they now fail by omission and miscounting rather than by confident
invention, which is the less misleading failure and the one the review stage
catches more reliably.

The prompts are not the binding constraint on those three. Running the
identical prompts against `qwen2.5:3b` produced a correct database finding,
including the distinction between a service below the seed minimum and one
whose list route did not answer, and found the health-route failures that
`qwen2.5:0.5b` missed entirely. The default stays `qwen2.5:0.5b`; the residual
errors are a demonstrated model-capacity limit rather than an untuned prompt.

The four corrections recorded under the `edited` decisions state the answer
the evidence supports, without describing what the model got wrong. That is
deliberate. An earlier draft of these decisions quoted the findings' wording
and went stale the moment the run was repeated, because the model's output
varies between runs while the collectors' evidence does not. Anchoring the
decision in the evidence makes it re-verifiable; every claim in the four was
checked against the collected evidence before the run was committed.
