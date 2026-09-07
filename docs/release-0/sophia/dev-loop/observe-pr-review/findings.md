<!-- Source: the session's output note `41026_bills-pr-review-vs-spec.md` in my local notes, 29 Aug 2026. Copied whole; only machine paths, other people's names and references to tools outside this repository are neutralised. -->

# 41026 — Bills merged-PR self-audit vs spec, criteria and team agreements

**Run:** 29 Aug 2026, ~1:30 pm AEST · **Head:** `b0751bc` ("Feat: Setting up savings frontend (#55)", merged 29 Aug 13:09 AEST) · teammates are pushing actively, so every "current state" claim below is as-of this SHA.
**PR set reviewed** (every squash merge on `main` authored by Sophia Nguyen since `73178a4`, 23 Aug):

| PR | SHA | Title |
|---|---|---|
| #47 | `71e063c` | Bills docs: README merge status, contracts ports, projected-bills read |
| #49 | `cdd23bf` | Bills: Feature 4 link handoff (GET /handoff/subscription) and deep links |
| #50 | `41b9e05` | Bills tests: handoff routes, transactions contract, service validation branches |
| #51 | `5ccfc5d` | Sophia-CI: container health smoke test after build |
| #52 | `3da70ab` | Bills: review-readiness cleanups |

Not in the review set: **#56** (`refactor/bills-pure-reads`, B2 pure reads) — still an open draft, unmerged at head. Where it fixes a finding below, that is said.

**Sources used, ranked:**
1. the project specification PDF — primary; quotes below are from the sibling `.txt` extraction, which is text-complete for every section quoted (pages 13, 17–18 extract as headings only — those are the architecture *diagrams*; no requirement below leans on them).
2. **Superseded 31 Aug 2026: the Release 0 rubric was found on the assignment page itself (never in the mirror — it lives on the assignment, not a module page); this "no rubric exists" finding is wrong, and the ten criteria are audited in 41026_R0-rubric-evidence-audit.** Original finding: **No Release 0 rubric / marking-criteria document exists in the the subject's published materials mirror** — searched `the subject materials` (all folders incl. the Week 6 showcase folder) for rubric/criteria/marking/assessment. The Week 6 folder holds only the sample-architecture page; `Assessment overview.md` defers to "the subject information". Dimension B is therefore skipped, per the review rules — no criteria were invented.
3. `~/notes/41026_release0-brief.md` — secondary map only. One difference noticed vs primary: none material; the brief paraphrases faithfully (its `student-N.yml` and 10-record claims match the spec verbatim).
4. Team agreements — **no 41026 team charter document exists in the local notes** (all charter hits are 31272, the other subject). The documented agreements used instead, each cited where applied: 41026_registration-form-submitted (signed 21 Aug — feature allocation and topic; **note: the form as filed contains no port table**, see D-3 below), 41026_ci-contracts-and-architecture_chat-takeaways, 41026_shared-dtos_chat-takeaways, 41026_poc-and-shared-shell_chat-takeaways, and the per-service requirements decision recorded in 2026-08-22_reqs-split-per-service.

Strongest compliance points first: every individually-marked spec obligation in §2.2 is MET on head — three containerised microservices, full CRUD through both frontend and backend, all five tables seeded past the ten-record minimum, an approved-model Ollama flow that is local-only, a versioned Plan→Act→Observe→Adapt dispute loop, a personal CI workflow that builds and health-checks the containers, and 26 merged PRs of clean history. Everything found below is evidence-freshness, declared-deviation wording, or team-level integration — nothing in the five PRs weakened a spec obligation.

---

## A. Spec compliance table (per-student obligations)

Verdicts judge the **current `sophia/**` tree at head**; the PR column says how the review set contributed.

| # | Requirement (verbatim, §) | Verdict | Evidence |
|---|---|---|---|
| A1 | "Developing and maintaining one frontend microservice … one backend/API microservice … one database microservice." (§2.2) | **MET** | `sophia/frontend` (nginx + HTMX, :3005), `sophia/backend` (Flask, :5005), `sophia/database` (Flask + SQLite, :6005); each has a `Dockerfile`; compose services `bills-frontend/-backend/-db`. |
| A2 | "Implementing CRUD operations through the frontend and backend microservices." (§2.2) | **MET** | Backend JSON: `GET/POST /api/bills`, `GET/PUT/DELETE /api/bills/<id>` (`routes/bills.py`), payments `POST/PUT/DELETE`, disputes full CRUD (`routes/disputes.py`). Frontend HTML: `POST /ui/bills`, `/ui/bills/<id>/edit`, `/ui/bills/<id>/delete`, payments, disputes, cancel, confirm (`routes/fragments.py`). |
| A3 | "Populating each database table with a minimum of ten (10) records." (§2.2, §2.4) | **MET** | `sophia/database/seed.py`: bills **12**, payments **38**, disputes **10**, dispute_drafts **13**, chat_messages **10**. Disputes and chat_messages sit exactly at the minimum — compliant, zero margin; two extra rows each is cheap insurance (~10 min). |
| A4 | "Frontend → Backend/API → Ollama → LLM workflow", "Local only" (§4.2 R0 row); "Use only approved open-source LLMs" (§4.6) | **MET** | Two AI calls via `sophia/backend/ai/guard.py`; models `llama3.1:8b` (Llama) and `qwen2.5:0.5b` (Qwen), both approved §4.1. No MCP/RAG anywhere in `sophia/`. #49 moved model/URL config from compose env to `config.py` defaults — behaviour-preserving (defaults equal the old compose values). Ollama itself runs on the host via `extra_hosts: host.docker.internal` — see C-1 team gap. |
| A5 | "Demonstrate the Plan → Act → Observe → Adapt Agentic AI workflow." (§2.2) | **MET** | Dispute drafts versioned (`dispute_drafts.version`, seeds carry v1→v2 pairs), `/api/disputes/<id>/regenerate` feeds user edits into the next draft (Observe→Adapt); chat op preview → confirm → `/api/chat/apply` (Plan→Act). |
| A6 | "Implementing and maintaining their own CI/CD workflow." (§2.2) | **MET** | `.github/workflows/Sophia-CI.yml`: `test` job (pytest + coverage over `sophia/backend`) then `docker-health` job (#51) — compose build of the three bills images, `up -d`, `/health` curl on :6005 and :5005 (body-checked `"ok":true` since #52) and `/` on :3005, logs on failure, `down -v` always. Triggers on PR + push to main for `sophia/**`, the workflow file, and `shared/**`. |
| A7 | "student-5.yml – Build and validate Student 5 microservices." (§7.3 Release 0) | **PARTIAL — declared deviation** | The workflow is named `Sophia-CI.yml`, not `student-5.yml`. Team-conventional: `David-CI.yml` and `aiden-ci.yml` sit beside it. What it *does* matches the quoted purpose exactly. Needs the justification sentence (below) in the report. |
| A8 | "Store each student's assigned frontend, backend/API, database, testing, and Docker artefacts in their designated student-x/ directory." (§7.1) | **PARTIAL — declared deviation** | Folder is `sophia/`, not `student-5/`. Team-conventional: `david/`, `aiden/`, `janelle/` (renames merged as PRs #7, #32; `student-3/` is a leftover `.gitkeep` — team tidy-up, not Bills). Content-wise the folder holds exactly the artefact set the line lists. |
| A9 | "Commit changes regularly using meaningful commit messages." / "Develop features using separate Git branches." / "Merge changes into the main branch using Pull Requests." (§7.2) | **MET** | 26 Sophia PRs squash-merged to main (#6–#34 set + #47–#52). Review-set messages sampled: all imperative, scoped, specific (e.g. "fix: rename the table's next_billing key, guard empty dispute drafts, stop toast and scroll listener leaks"). Every merge came through a branch + PR. |
| A10 | "Be accessible from the unified project home page." (§2.4); "Providing a unified home page (index.html) that links to all individual frontend features." (§2.3, *team* list) | **NOT MET — team-level gap, not a Bills PR defect** | At head no unified home page exists: `shared/` contains only `backend/dto.py`; [teammate]'s `david/frontend/index.html` (#55, merged today) is a "Hello World" on :3002 with no links. What Bills did instead: full standalone shell at :3005; offered `theme.css` as the shared-CSS donor (22 Aug chat, "I'll create the shared.css file"); `#bills`/`#chat` deep links and `/handoff/…` (#49) are integration surface ready for the shell when it exists. |
| A11 | "Applying a consistent CSS theme and user interface across the entire application." (§2.3, *team* list) | **NOT MET — team-level** | No `shared/` stylesheet at head; Bills vendors its own `theme.css` + `bills.css`, which the team agreed to treat as the donor. Bills' obligation ends at offering it — done, in writing, 22 Aug. |
| A12 | "Store the integrated home page, shared CSS, JavaScript, assets, and common configuration in the shared/ directory." / "Store the shared AI services in the ai-services/ directory." / "Store project build, testing, and deployment scripts in the scripts/ directory." (§7.1) | **NOT MET — team-level** | `shared/` = dto.py only; `ai-services/` and `scripts/` are `.gitkeep`s. Consequence of the empty `ai-services/`: Ollama is not containerised anywhere, so §6.3 "All frontend, backend, database, and AI services shall be containerised" is unmet at team level. Bills' mitigation is documented (`host.docker.internal` + `OLLAMA_URL` default). |
| A13 | "Maintain pre-testing and post-testing evidence for the assigned microservices." (§2.2) | **PARTIAL / ambiguous — tutor question** | Evidence exists (`docs/release-0/sophia/evidence/`: ai/, compose/, pytest output) but "pre-testing and post-testing" is undefined for R0 — the spec only gives it concrete meaning in §7.3 Release 2 ("pre-commit pytest validation … post-commit AI-assisted unit testing"). Ambiguous — declare the interpretation (pytest before merge, CI run after) and ask. Also the pytest evidence file is stale — finding a-1. |

## Findings by tier

### (a) Genuine gaps in my work — fix before Sunday

1. **Every committed test/coverage number is stale after #50.** Head reality (suite run today on `b0751bc`): **147 passed, 86% coverage**. Stale claims: `sophia/README.md:142` — "108 passed; coverage 81% across `sophia/backend` (measured 28 Aug 2026)" (written by #47, outdated the moment #50 merged the same day); `docs/release-0/sophia/evidence/pytest-108-passed.txt` (stale in name and content); screenshot `r0-07-pytest.png` (22 Aug, shows the old count). A marker who runs the suite sees the mismatch immediately. **Fix: merging draft #56 already corrects the README line (its suite will be 155/88%); rename/regenerate the evidence txt and retake r0-07 after that merge. ~20 min on top of #56.**
2. **The Actions evidence URL predates the workflow it evidences.** `sophia/README.md:176` cites run `32573962576` (22 Aug) — before #50's tests existed and before #51 replaced the `build` job with `docker-health`. The report's "GitHub Actions workflow execution evidence" should show the workflow as submitted. **Fix: after #56 merges, take the fresh Sophia-CI run-on-main URL (~5 min; also closes the open thread from 2026-08-28_bills-tier-a).**
3. **Screenshot set is 7/13 and all predate the reviewed PRs.** Last commit to `docs/release-0/sophia/screenshots/` is 22 Aug 21:22; missing per that folder's own README: r0-02 (add-bill toast), r0-05/r0-06 (dispute draft v2, sent), r0-08/r0-09 (Actions), r0-10/r0-11 (compose ps, health). The handoff prefill form, evidence note, and deep-link behaviour (#49) exist in no screenshot. **Fix: one capture session on the final build, ~45–60 min; add one shot of the prefilled handoff form — it is the feature's best integration evidence.**
4. **Minor defect (new, found in #49's diff):** `_parse_handoff_subscription` (`sophia/backend/routes/fragments.py:224`) accepts `amount=nan`/`inf` — `float()` parses them, the `< 0` check passes for NaN, and `round(amount * 100)` then raises → unhandled 500 instead of the friendly 422 every other bad input gets. Cosmetic robustness on an inbound-facing route. **Fix: `math.isfinite()` guard + one test, ~15 min. Candidate for the known-issues list if not fixed.**

### (b) Declared deviations — need only their justification sentence in the report

1. **Folder `sophia/` vs §7.1 "their designated student-x/ directory"** (quote in A8). Team-wide convention, merged via reviewed PRs (#7, #32).
2. **Workflow `Sophia-CI.yml` vs §7.3 "student-5.yml"** (quote in A7). Same convention (`David-CI.yml`, `aiden-ci.yml`).
3. **Raw `sqlite3` vs the team's Flask-SQLAlchemy adoption** — team decision 22 Aug (41026_ci-contracts-and-architecture_chat-takeaways: "Flask-SQLAlchemy is in — [teammate] proposed it (10:57 am, pinned), [teammate] said add it (10:58)… no more raw SQL for anyone using it; tables must be registered as models"). Bills' deferral is Soph's recorded decision, 26 Aug (2026-08-26_bills-r0-improvement-plan: "D1 = SQLAlchemy in R1"). Deviation is declared, not silent — needs the sentence.
4. **Projections read from the backend, not the DB API** — the one declared exception to reading through DB APIs, already documented by #47 in `docs/release-0/sophia/api.md` ("Calling the backend for projections is the one declared exception…"). No further action.
5. **`POST /api/suggestions` retained beside the preferred link handoff** — deliberate (decision D2, documented by #47 in `contracts-inbound.md`: "This endpoint deliberately stays a `POST`… nothing is written until the confirmed preview is applied"). No further action.

### (c) Team-level gaps — not attributable to Bills; list under known issues, don't absorb

1. **No unified home page, no shared CSS** (A10–A12) — the single biggest marked gap for everyone ("Be accessible from the unified project home page" is on *each* feature). Bills' integration surface is ready and documented; the shell remains unbuilt and, since [teammate]'s soft claim ("if it's not done by the time I get to it", 22 Aug), undated.
2. **Ollama not containerised / `ai-services/` empty** (§6.3, §7.1) — affects all five features equally.
3. **`janelle/` is a `.gitkeep`** — no transactions service exists; Bills runs on its stub by design (`source="stub"` fallback, documented in `contracts-inbound.md`). Worth one report sentence so the stub reads as resilience, not absence.
4. **`student-3/` leftover `.gitkeep`, `scripts/` empty** — repo tidiness vs §7.1.
5. **No rubric/criteria document published for the subject** — the 26 Aug open action "check whether the rubric says anything about consistency" cannot be completed against the mirror; nothing to check exists. If a rubric PDF circulates elsewhere, it never reached the subject's published materials.

### (d) Charter / agreement notes

- **No 41026 team charter exists** (searched the whole local notes; every charter document is 31272's — different team, not used, per the review rules). The "charter" for this audit = signed registration form + the four convo takeaways + the 22 Aug requirements decision.
- **Dependency ownership: compliant.** Agreement (2026-08-22_reqs-split-per-service: "no more shared root `requirements.txt`; each student owns their dependency files"). Root `requirements.txt` is gone from the repo (#54, [teammate]'s); Sophia-CI installs `sophia/requirements.txt`; both bills Dockerfiles COPY their own service `requirements.txt`. Nothing in the Bills stack resolves a shared dependency file.
- **JSON-over-HTTP stays the contract: compliant.** Agreement (41026_shared-dtos_chat-takeaways: "Bills does not import `shared/backend/dto.py`… each feature's HTTP JSON is the actual contract"). Verified at head: zero imports of `shared/` anywhere under `sophia/`. #51 adding `shared/**` to Sophia-CI's trigger paths is watching, not adopting — consistent with the gate.
- **Ports 3005/5005/6005: compliant, but fix the provenance.** The signed registration form **contains no port table** — the allocation lives in the chat takeaways (shell :3000/:5000/:6000; [teammate]'s DB corrected to :6003 by #47) and Bills' own docs, and compose matches (3005/5005/6005). If the report says "ports per the registration form", soften to "per the team's port convention".
- **Scope: all five PRs clean.** Union of files touched: `sophia/**`, `docs/release-0/sophia/**`, `.github/workflows/Sophia-CI.yml`, and one `docker-compose.yml` hunk (#49) confined to the `bills-backend` environment block. Nothing outside the agreed writable set (<earlier session notes>).
- **Unratified proposal, correctly not relied on:** "changes to `shared/` via PR, tag consumers, no self-merge" was proposed 23 Aug, never ratified — no PR in the set assumes it, and no deviation is claimed against it.
- **Still open with the team** (carried, not new): `Transaction` DTO `date` field typed `datetime` vs the ISO-string ask; [teammate] absent from both decisions about her data.

## Sentences ready for the report (paste and adapt)

> **Folder and workflow naming.** The repository uses per-student folders named by first name (`sophia/`, `david/`, `aiden/`, `janelle/`) and per-student workflow files (`Sophia-CI.yml`) in place of the spec's `student-x/` and `student-5.yml`. The mapping is recorded in the feature-allocation table; the content and purpose of each artefact follows §7.1 and §7.3 exactly. This was a deliberate team convention adopted at repository setup and applied consistently by all members.

> **Persistence layer.** The team adopted Flask-SQLAlchemy on 22 August; the Bills services retain raw `sqlite3` for Release 0 and migrate in Release 1. The Bills schema predates the adoption decision, is fully covered by tests (147 passing), and deferring the rewrite kept the pre-freeze window for integration work; the migration is scheduled as Release 1 work.

> **AI configuration.** The Bills backend reaches the Ollama runtime on the host through Docker's `host-gateway`; model selection (`llama3.1:8b` for dispute drafting, `qwen2.5:0.5b` for chat) and the demo clock default in `sophia/backend/config.py` and are overridable per environment. Both models are approved families under §4.1, and Release 0 AI calls are local-only per §4.2.

> **Transactions dependency.** The Transactions service was not yet available at Release 0; the Bills client reads it through the documented HTTP contract and falls back to a seeded stub (reported as `source="stub"`) when the service is absent, so the feature demonstrates the full flow independently and switches to the live service by setting one environment variable.

> **Projections exception.** Stored bill rows are read from the Bills database API; projections come from the backend because the date engine lives there — the one declared exception to reading feature data through its database API, made to keep the database container free of business logic and of any dependency on the backend (PR #31).

## Open tutor questions

1. What does "pre-testing and post-testing evidence" (§2.2) mean for Release 0, given §7.3 only defines pre/post-commit testing for Release 2? (Current interpretation: pytest evidence before merge + CI execution evidence after.)
2. Is the first-name folder / `Sophia-CI.yml` naming acceptable as a declared deviation, or should Release 1 rename to `student-x/` / `student-N.yml`?
3. Is a rubric or criteria breakdown for Release 0 published anywhere beyond the spec's deliverable lists? Nothing exists published for the subject.
4. Does the Week 6 showcase require the video *and* a live demo, or does the video substitute? (Carried from the brief; showcase is Fri 4 Sep.)

---
*Method note: every verdict above was taken from the head tree or the squash diffs (`git show`), not from PR descriptions; the suite was re-run on head to measure, not quoted. Review performed read-only — no branches, commits, pushes, or PR comments.*
