<!-- Source: the session's output note `41026_R0-rubric-evidence-audit.md` in my local notes, 31 Aug 2026. Copied whole; only machine paths, other people's names and references to tools outside this repository are neutralised. -->

# Release 0 rubric evidence audit — 31 Aug 2026

Read-only audit of head `4dbb4d6` against the ten-criterion marking rubric
recovered from the assignment page on 31 Aug. Supersedes the
41026_bills-pr-review-vs-spec finding that "no R0 rubric exists" — the
rubric lives on the assignment page, not in any module the the subject's published materials mirror
covers. Suite re-run on head this morning: **159 passed / 88% coverage**
(matches `sophia/README.md:150` and `evidence/pytest-159-passed.txt`).

Deadlines: freeze Wed 2 Sep · video Thu 3 Sep · showcase Fri 4 Sep (all
attend or 0) · group PDF `group21.pdf` Sun 6 Sep 23:59.

## Phase 0 state

- Head `4dbb4d6`, unchanged since 30 Aug. Working tree clean (`.vs/` untracked only).
- All three merged fixes confirmed on head: `math.isfinite` guard at
  `sophia/backend/routes/fragments.py:236`; `OLLAMA_URL: http://ollama:11434`
  + `depends_on: [bills-db, ollama]` in the bills-backend compose block
  (docker-compose.yml:72–77); README 159/88% + evidence txt present.
- `docs/bills-screenshots-final` branch: content fully merged via squash #75
  (`4dbb4d6`); remote branch just not deleted. No open PR.
- **Screenshot set is COMPLETE** — 16 files in
  `docs/release-0/sophia/screenshots/`: r0-01…r0-11 (incl. the once-blocked
  r0-02), r0-06b/06c, r0-13/14/15. Only r0-12 absent (impossible — no shared
  home page). **Phase 5 is not needed.**
- Agentic material search (`agentic|PAOA|PLAN|OBSERVE|ADAPT` repo-wide):
  **zero hits on main.** No `agentic_loop/`, no root `prompts/`, `scripts/`
  is a bare `.gitkeep`. The only agentic work anywhere is [teammate]'s draft
  PR #67 (`aiden/feat/agentic-model`) — see below. One prompt file exists
  outside sophia/: `david/backend/prompts/system_prompt.txt` (savings).
- `shared/` contains **only `backend/dto.py`**. No index.html, no CSS.
- Fifth student: `student-3/` is an empty `.gitkeep`; no compose services,
  no workflow. Compose integrates 4 of 5 features (janelle=transactions,
  sophia=bills, aiden=anomalies, david=savings) + ollama.

## Per-criterion verdicts

| # | Criterion | Verdict | Evidence checked |
|---|---|---|---|
| 1 | Project Setup | **PARTIAL — team** | Structure ✓ (per-name student dirs — deviation from `student-x/`, declared in report §5), `ai-services/` ✓ populated, 4 workflows ✓, compose ✓, ollama AI-Mode ✓, bills seeds ✓. Missing: **shared containerised `index.html`** (`shared/` = dto.py only), shared CSS theme, `scripts/` empty, `student-3/` empty. |
| 2 | Service Implementation | **MET (mine) / PARTIAL (group)** | Bills 3-container slice operational in the group compose (blocks at docker-compose.yml:55–87); 4 of 5 features integrated; student-3 absent. |
| 3 | AI-Mode Integration | **MET (mine)** | Shared `ollama` compose service, approved models (`llama3.1:8b`, `qwen2.5:0.5b` — the two `OLLAMA_PULL_MODELS` pulls); callable from frontend via chat + dispute UI; `sophia/backend/ai/*`; 7 real-call JSONs in `evidence/ai/`. |
| 4 | Agentic AI Workflow | **NOT MET — team; nothing in repo** | Zero PAOA hits on main. Report §6's PAOA table describes the *product's* runtime loop, not a dev-workflow loop demonstrated in the terminal. PR #67 is a runtime HTTP endpoint (no terminal demo, no human adapt, no run record) — does not satisfy it either. Phase 2 port is the fix. |
| 5 | Prompt Eng. & Context Mgmt | **PARTIAL (mine)** | Artefacts exist (inventory below) but the report draft documents almost none of them. local notes-only artefacts earn nothing until cited. Phase 6 fixes. |
| 6 | DevOps & GitHub Actions | **MET (mine)** | `Sophia-CI.yml`: 2 jobs (test, docker-health), path-filtered; **72 runs / 69 success** as of 31 Aug (report says 59/56 "as of 29 Aug" — stale); run 33309346244 verified success on main 30 Aug. Naming deviation (`Sophia-CI.yml` vs `student-5.yml`) declared in §5. Group: 5th workflow missing. |
| 7 | Docker Compose Integration | **PARTIAL — team** | One shared compose builds/runs 13 services across 4 features + ollama. Missing: student-3 services and the containerised shared entry point the assignment names for crit 1. |
| 8 | Working Software | **MET (mine)** | Full CRUD via frontend → backend → db-api; 159 tests; #73 restored every modal write; screenshots r0-01…06c; curl transcripts in `evidence/compose/`. |
| 9 | Technical Report | **PARTIAL (mine)** | 13 sections drafted; section-by-section gaps below + claim table below. |
| 10 | Project Demonstration | **NOT MET yet — team** | No video exists (due Thu 3 Sep). Must show feature, AI-Mode, CI/CD + deployment in ≤10 min. |

### Paste-able team lines (criteria 1, 4, 7, 10)

- **C1/C7:** "The rubric's Project Setup and Compose criteria want a shared
  *containerised* HTMX `index.html` routing to all five frontends, referenced
  from docker-compose.yml — `shared/` currently has only `dto.py`. It also
  wants `scripts/` non-empty and student-3's services in compose. Who owns
  the home page container, and can we get it in before Wed freeze?"
- **C4:** "Criterion 4 wants a Plan→Act→Observe→Adapt workflow *demonstrated
  in the terminal and logged in the technical report*, reviewing the DB,
  implementation, architecture and DevOps pipeline. Nothing in the repo does
  this today ([teammate]'s #67 is a runtime endpoint, which is great for AI-Mode
  but isn't a terminal demo). I have a working terminal loop from Lab 4/5
  I can port as a shared `agentic_loop/` — offering it as a draft PR."
- **C10:** "Video due Thu: 10 min max, must cover each assigned feature,
  AI-Mode, and the CI/CD workflow + deployment steps. All members attend
  Fri or the group gets 0 — please confirm availability."

## Report-sections claim table

Every checked claim in 41026_R0-report_sophia-sections:

| Claim | Note line | Verdict | Correct value |
|---|---|---|---|
| Ports 3005/5005/6005, `Sophia-CI.yml` | 4 | true | — |
| "159/88 assumes nan-guard PR merges" | 12–13 | stale | merged as #68; numbers verified on head |
| F5-FR11 seeds: bills 12 | 33 | true | 12 |
| F5-FR11 seeds: payments "40+" | 33 | **wrong** | **38** (`seed.py PAYMENTS`) |
| F5-FR11 seeds: disputes 10, drafts 13 | 33 | true | — |
| F5-FR11 seeds: chat_messages "28" | 33 | **wrong** | **10** (`seed.py CHAT_MESSAGES`) |
| NFR9 "82 tests, 1.3 s" | 49 | stale | 159 tests / ~5 s local |
| "Ollama runs host-side… switch at R1 is one line" | 63 | stale | switch happened at R0 (#69); keep as dated decision + add outcome sentence |
| §4 diagram "Ollama (host) :11434" | 111 | stale | ollama is a compose service; host-gateway is fallback only |
| §5 path filter incl. `shared/**` | 134 | true | verified in workflow |
| §5 coverage 88% | 136 | true | — |
| §5 "59 runs, 56 successful (29 Aug)" | 140 | stale | **72 / 69** at 31 Aug; refresh at freeze |
| §6 "159 passing" | 148 | true | — |
| §6 "reaches Ollama on the host through host-gateway" | 152 | **stale/wrong** | compose `ollama` service via `OLLAMA_URL=http://ollama:11434`; host-gateway fallback |
| §7 "159 passed in 3.45s" | 179 | true (count) | 5.07 s today; timing cosmetic |
| §7 evidence files ui-write-routes.txt, four-cases.txt | 190 | true | both exist |
| §7 seven AI JSONs | 192 | true | 7 files |
| §8 run 33309346244 success on main 30 Aug | 200 | true | verified via gh api |
| §9 compose env "OLLAMA_URL=host.docker.internal" | 247 | **wrong** | `http://ollama:11434` since #69 |
| §9 compose env "DRAFT_MODEL, CHAT_MODEL, DEMO_TODAY" | 247 | **wrong** | not in compose; they are `config.py` defaults (lines 10–13) |
| [SCREENSHOT 1–11] markers | various | true | files exist for all |
| [SCREENSHOT 12] | 261 | known-missing | r0-12 impossible; §11 fallback stands |
| r0-13/14/15 exist but no markers | — | **gap** | add markers 13/14/15 (handoff prefill, deep-link confirm, 422 banner) |
| §13 "13 commits from 14 PRs" | 305 | stale | **32 commits / 32 merged PRs** on main by Sophia |
| §12 contribution log ends 22 Aug | 279–285 | thin | missing 26–30 Aug (B2, audit, #68/#69/#71/#73/#75) |

Also: `sophia/README.md:174` says "29 in total" PRs — now 32 (repo-side; fix
in a later evidence pass, not Phase 6 which is local notes-only).

## Criterion 5 artefact inventory

| Artefact | Where | Referenced in report? |
|---|---|---|
| Runtime prompt modules | `sophia/backend/ai/chat_prompt.py`, `dispute_prompt.py`, `schemas.py`, `guard.py` | Indirectly (§6 PAOA table); paths not named |
| Real-call evidence | `docs/release-0/sophia/evidence/ai/` (7 JSONs + README) | §7 ✓ |
| Versioned Claude Code prompt series | local notes: `41026_release0_claude-code-prompt`, `…bills-r0-improvements…`, `…bills-b2-pure-reads…`, `…bills-pr-review…`, `…bills-audit-fixes…`, `41026_r0-rubric-gaps_claude-code-prompt` | **No — zero mentions** |
| Self-audit note | 41026_bills-pr-review-vs-spec | No |
| PR trail (32 merged, gated draft workflow) | GitHub | Partially (§13, stale) |
| Lab 4/5 prompt files (to be ported) | `Code\enrolment-app-open-ai\prompts\**` | Will become `prompts/<family>/` in Phase 2 |

Phase 6 adds the criterion-5 subsection citing these by path with short excerpts.

## Criterion 9 section walk (assignment list vs the 13 drafted sections)

Present: FR/NFR ✓ · feature plan ✓ · risk plan ✓ · individual architecture ✓
· workflow description ✓ · implementation summary ✓ · testing evidence ✓ ·
Actions evidence ✓ (stale counts) · Compose evidence ✓ (stale env claims) ·
screenshots ✓ · known issues ✓ · contribution log ✓ (thin) · commit log ✓ (stale).

Missing or not mine:
- **Data design (conceptual / ERD / logical / physical)** — absent → Phase 4.
- **Agentic Loop Workflow Record** (shared-loop contribution, own prompt
  assets, review record) — absent → Phases 2/3/6.
- **Criterion-5 prompt-artefact subsection** — absent → Phase 6.
- PAOA diagram of the dev workflow — group section ([teammate]'s), doesn't exist anywhere.
- Showcase video URL — pending (video Thu).
- Group sections (overview, Agile plan, backlog, repo structure, integrated
  + Compose + DevOps architecture, student-yml descriptions ×5) — [teammate]'s;
  not audited beyond noting my §5 covers only my own workflow.

## PR #67 (read-only)

Draft, branch `aiden/feat/agentic-model`, updated 30 Aug. Adds
`aiden/backend/services/agent_api.py` (183 lines): a two-pass runtime check —
implementation model flags a suspicious transaction, review model verifies —
triggered from the frontend (dummy-transaction button), logged via app logger.

**The model mismatch I suspected does not exist in the PR's current state**:
its compose diff *does* add `qwen2.5:3b` to `OLLAMA_PULL_MODELS` (and points
`OLLAMA_IMPLEMENTATION_MODEL` at it). Note there is no `setup-ollama.sh`; the
pull list lives in the compose env consumed by `ai-services/entrypoint.sh`.
Remaining real concerns, only on a clean volume: ~2 GB extra pull, and the
healthcheck (`healthcheck.sh` requires *every* listed model present) may
outlive `start_period: 60s` — [teammate]'s own diff carries a TODO saying the
health params are "messing with the health of the container". Since
anomalies-backend gates on `ollama: service_healthy`, a slow first pull can
keep his backend from starting.

**Criterion 4 verdict on #67: does not satisfy it.** It is a runtime HTTP
endpoint inside the product — no terminal demonstration, no human
review/adapt stage, no logged run record for the report, and it reviews
transactions, not the database/implementation/architecture/DevOps pipeline
the criterion names. It is good criterion-3 material for anomalies.

## Surviving work plan

| Phase | What | Est. |
|---|---|---|
| 2 | Port terminal agentic loop (`agentic_loop/`, `prompts/`, 4 collectors incl. new devops, ADAPT stage, run recorder, README) → draft PR | 3–4 h |
| 3 | Run all modes vs the live group app, capture transcript + reports + terminal screenshots to `docs/release-0/agentic-loop/sample-run/` | 1–1.5 h |
| 4 | Data design section (conceptual/ERD/logical/physical, Bills only) → local notes | ~45 min |
| 5 | **Skipped — set already complete** (16 files; only r0-12 impossible) | 0 |
| 6 | Report corrections (claim table), insert data design, Agentic Loop Workflow Record, criterion-5 subsection; reconcile known-issues; supersede-line in the pr-review note | 1–1.5 h |
