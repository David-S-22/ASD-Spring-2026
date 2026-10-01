# Budget Coach Release 1 Implementation Plan

## 1. Purpose

This plan turns the **Release 1** brief into a concrete delivery plan for the
**Budget Coach** feature in `ethan\`. The goal is to keep the existing
containerised Budgets frontend, backend/API, and database services working,
while extending them to integrate with the team's **shared local MCP server**,
**shared local RAG server**, and **shared local agentic loop**.

This plan is intentionally scoped around the Budgets slice and the files it
already owns, while calling out the small shared-repo changes needed to make
the Budgets feature assessable under the Release 1 rubric.

## 2. Release 1 outcome for Budgets

Budget Coach is Release 1 complete when all of the following are true:

1. `budgets-frontend`, `budgets-backend`, and `budgets-db` still run through
   the shared `docker-compose.yml`.
2. Existing Release 0 budgeting behaviour still works:
   - budget CRUD
   - budget-line CRUD
   - planned-event CRUD
   - summary calculations
   - current AI chat / proposal flow where still applicable
3. The Budgets frontend can trigger at least one **MCP** interaction through
   `budgets-backend`.
4. The Budgets frontend can trigger at least one **RAG** interaction through
   `budgets-backend`.
5. RAG answers shown in the Budgets UI include:
   - grounded answer text
   - source citations
   - confidence category
   - explicit insufficient-context handling when relevant context is missing
6. The Budgets backend remains the only frontend-facing integration point; the
   frontend never talks directly to MCP or RAG services.
7. Budgets participates in the shared agentic loop's new **MCP validation** and
   **RAG validation** modes.
8. The Ethan CI workflow keeps the integration code present but disables MCP
   and RAG during CI execution.
9. The Budgets contribution provides enough screenshots, logs, run outputs, and
   commit traceability for the report and showcase.

## 3. Current Budgets baseline

The `ethan\` area already provides a strong Release 0 base:

- `ethan\frontend\public\index.html` already contains the Budget Coach UI,
  coach panel, proposal history, and fetch-driven interaction model.
- `ethan\backend\app.py` already exposes frontend-facing routes for budget
  data, proposals, chat, and health checks.
- `ethan\backend\chat_service.py` already contains orchestration logic for
  budget-specific assistant behaviour and proposal generation.
- `ethan\backend\db_api.py` already proxies the Budgets database API.
- `ethan\database\app.py` and `ethan\database\models.py` already persist
  budgets, budget lines, planned events, proposals, and chat messages.
- `.github\workflows\Ethan-ci.yml` already tests and compose-checks the Budgets
  services.
- `docker-compose.yml` already runs `budgets-frontend`, `budgets-backend`, and
  `budgets-db`.

This means Release 1 should be built as an **extension of the existing coach
panel and orchestration flow**, not as a separate parallel feature.

## 4. Design approach

### 4.1 Keep the existing microservice boundaries

The Budgets services remain:

- **Frontend:** UI rendering and user interaction only
- **Backend/API:** orchestration, validation, integration with other services
- **Database API:** persistence only

MCP, RAG, and the shared agentic loop must remain **outside Docker Compose**
and **outside `ethan\` service ownership**, but Budgets must integrate with
them through the backend.

### 4.2 Use the coach panel as the Release 1 entry point

The simplest and safest Release 1 path is to treat the existing **Tally / coach
panel** as the single Budgets entry point for:

- tool-style MCP interactions
- grounded RAG responses
- proposal previews and acceptance/rejection
- evidence capture through stored chat records

### 4.3 Route by intent inside the backend

The Budgets frontend should keep posting user requests to the Budgets backend.
The backend should decide whether a message is:

- a deterministic local budget question
- an MCP tool request
- a RAG grounded-response request
- a proposal-generation request

This avoids splitting the frontend into multiple incompatible AI flows.

## 5. Required Budgets workstreams

## 5.1 Backend/API work

### A. Configuration

Update `ethan\backend\config.py` to support shared local services:

- `MCP_SERVER_URL`
- `RAG_SERVER_URL`
- `MCP_ENABLED`
- `RAG_ENABLED`
- request timeout settings for MCP and RAG

These must default safely so CI can disable MCP/RAG without breaking the
backend.

### B. Shared-service clients

Add small backend client modules, for example:

- `ethan\backend\mcp_client.py`
- `ethan\backend\rag_client.py`

Responsibilities:

- make HTTP requests to the shared local MCP/RAG servers
- validate response shape
- raise explicit service errors on timeouts, invalid responses, or unavailable
  services
- avoid silent fallback behaviour

### C. Orchestration routes

Extend `ethan\backend\app.py` with Release 1 orchestration routes. Two viable
patterns:

**Option 1: dedicated routes**

- `POST /api/budgets/<budget_id>/mcp-tools/<tool_name>`
- `POST /api/budgets/<budget_id>/grounded-chat`

**Option 2: unified chat route**

- keep `POST /api/chat`
- let the backend decide whether to answer through deterministic logic, MCP, or
  RAG

For Budget Coach, **Option 2** is the better fit because it preserves the
existing coach UI and proposal flow.

### D. Context assembly

Extend the Budgets backend to package the context needed by MCP and RAG:

- active budget id and month
- declared income
- summary totals
- budget lines
- planned events
- current unresolved proposals
- recent chat history

Most of this data already exists through:

- `summary_service`
- `db_api`
- existing chat/proposal endpoints

### E. Response handling

Standardise the Release 1 backend response shape to support:

- `message`
- `mode` (`deterministic`, `mcp`, `rag`)
- `tool_result` for MCP
- `citations` for RAG
- `confidence`
- `insufficient_context`
- `proposal`
- `response_source`

This keeps the frontend update small and predictable.

## 5.2 MCP integration work

The Budgets feature should support at least one real tool-style path through
the shared MCP server.

Recommended Budgets MCP use cases:

1. **Budget summary lookup**
2. **Affordability check**
3. **Structured budget adjustment suggestion**
4. **Proposal creation using a shared tool contract**

Recommended minimum implementation:

- Budgets backend sends a structured request to the shared MCP server
- MCP server returns a valid tool result
- Budgets frontend displays the result in the coach panel
- The interaction is persisted in chat history for evidence

Preferred Budgets tool result structure:

```json
{
  "tool_name": "check_affordability",
  "ok": true,
  "result": {
    "decision": "affordable",
    "explanation": "Dinner at $35 keeps Dining under the warning threshold.",
    "remaining_after_purchase": 4200
  }
}
```

## 5.3 RAG integration work

The Budgets feature should support grounded coaching answers generated through
the shared local RAG service.

Recommended RAG inputs:

- active budget month and id
- budget summary snapshot
- budget lines and planned events
- optional project/reference material if included in the shared RAG corpus

Required RAG outputs:

- answer text
- citations
- confidence category
- insufficient-context handling

Preferred response structure:

```json
{
  "answer": "Dining is closest to its warning threshold this month.",
  "citations": [
    {"label": "Budget summary", "source": "budget:42:summary"},
    {"label": "Planned event: Friday dinner", "source": "planned-event:81"}
  ],
  "confidence": "high",
  "insufficient_context": false
}
```

If the RAG server cannot ground the response, the backend must return a clear,
non-fabricated insufficient-context result and the frontend must show it
explicitly.

## 5.4 Frontend work

Update `ethan\frontend\public\index.html` to display Release 1 behaviour while
keeping the current UI structure.

### Frontend changes

1. Keep the current coach panel and send flow.
2. Display whether a response came from:
   - deterministic budget rules
   - MCP tool result
   - RAG grounded response
3. Render RAG citations under the reply.
4. Render the confidence category clearly.
5. Render insufficient-context responses explicitly.
6. Keep proposal cards and accept/reject flows working.
7. Preserve existing month-based behaviour and summary refresh logic.

### Frontend evidence hooks

The UI should make it easy to capture screenshots of:

- a successful MCP interaction
- a successful grounded RAG interaction
- an insufficient-context response
- proposal history
- normal Release 0 budget behaviour still working

## 5.5 Database work

The database microservice should remain persistence-only, but store enough
evidence to support Release 1 reporting.

Review and extend the existing `chat_messages` support in:

- `ethan\database\models.py`
- `ethan\database\app.py`

Recommended persistence additions if not already fully stored:

- `mode`: `deterministic`, `mcp`, `rag`
- `response_source`
- `plan_json`
- `observation_json`
- `stage_trace`
- optional citation metadata

The key rule is to keep the database as a **log/evidence store**, not as the
place where MCP/RAG orchestration happens.

## 5.6 Docker Compose and local configuration work

Update the Budgets section of `docker-compose.yml` so the backend can reach the
shared local services without containerising them.

Recommended Budgets backend environment additions:

- `MCP_SERVER_URL=http://host.docker.internal:<mcp-port>`
- `RAG_SERVER_URL=http://host.docker.internal:<rag-port>`
- `MCP_ENABLED=true`
- `RAG_ENABLED=true`

Also keep:

- existing Budgets service names
- existing ports
- existing database connection
- existing Ollama settings if still used for other local logic

Do **not** add MCP, RAG, or the shared agentic loop as services in
`docker-compose.yml`.

## 5.7 Ethan CI workflow work

Update `.github\workflows\Ethan-ci.yml` so the Budgets code retains MCP/RAG
integration while disabling those modes in CI.

Recommended workflow environment settings:

- `MCP_ENABLED=false`
- `RAG_ENABLED=false`

Add or update tests so the backend still starts cleanly when:

- MCP is disabled
- RAG is disabled
- host-local shared services are unavailable

The goal is to prove that the Budgets feature stays buildable and testable in
CI while preserving Release 1 integration code for local execution.

## 5.8 Agentic loop work

Extend the shared `agentic_loop\` with Budgets-specific evidence paths for the
new Release 1 validation modes.

Required additions:

1. **MCP validation mode**
   - checks that Budgets can trigger a valid MCP tool request
   - captures the returned tool result

2. **RAG validation mode**
   - checks that Budgets can trigger a grounded response
   - captures citations and confidence
   - captures insufficient-context behaviour when no relevant context exists

Expected outputs:

- terminal output
- agentic loop run records
- report-ready excerpts or screenshots

## 5.9 Documentation and report evidence work

The Budgets contribution needs explicit Release 1 evidence in the report.

Prepare:

- updated Budgets repository structure summary
- Budgets slice within the overall Release 1 architecture diagram
- Budgets MCP + RAG interaction flow diagram
- screenshots of frontend MCP and RAG interactions
- backend/API request and response examples
- terminal validation output
- Docker Compose evidence
- Ethan workflow run link or log
- identifiable Budgets commits
- known issues / limitations for Budgets local execution

## 6. Implementation phases

## Phase 1 - Stabilise the Budgets baseline

Objective: protect Release 0 behaviour before adding Release 1 features.

Tasks:

1. Review existing Budgets tests and add missing coverage for:
   - budget summary route
   - chat route
   - proposal apply/reject flow
2. Confirm all current frontend budget workflows still behave as expected.
3. Confirm `Ethan-ci.yml` passes before Release 1 changes begin.

Done when:

- the Release 0 Budgets feature is green and stable
- the team has a safe baseline to extend

## Phase 2 - Add backend config and shared-service clients

Objective: make `budgets-backend` capable of reaching local MCP/RAG services.

Tasks:

1. Add new config values in `ethan\backend\config.py`.
2. Add `mcp_client.py`.
3. Add `rag_client.py`.
4. Add explicit error handling and tests for unavailable services.

Done when:

- the backend can be configured locally for MCP/RAG
- CI can disable those integrations cleanly

## Phase 3 - Add MCP orchestration

Objective: deliver at least one valid frontend -> backend -> MCP -> frontend
flow.

Tasks:

1. Define the Budgets MCP request/response contract.
2. Add backend orchestration in `ethan\backend\app.py` and/or
   `ethan\backend\chat_service.py`.
3. Persist MCP interaction records in chat history.
4. Render the tool result in the coach panel.
5. Add tests for success and error cases.

Done when:

- a Budgets user can trigger a valid MCP request from the UI
- the result is visible and logged

## Phase 4 - Add RAG orchestration

Objective: deliver grounded Budgets answers with citations and confidence.

Tasks:

1. Define the Budgets RAG request/response contract.
2. Build the context payload from the current budget summary.
3. Add backend orchestration and response validation.
4. Add frontend rendering for citations, confidence, and
   insufficient-context.
5. Add tests for grounded and insufficient-context outcomes.

Done when:

- the UI shows a grounded Budgets answer
- citations and confidence are visible
- insufficient-context is explicit

## Phase 5 - Compose and CI integration

Objective: ensure Release 1 works locally without breaking CI.

Tasks:

1. Update the Budgets backend environment in `docker-compose.yml`.
2. Update `.github\workflows\Ethan-ci.yml` for disabled MCP/RAG execution.
3. Add or adjust tests for integration flags.
4. Verify the Budgets services still build and start.

Done when:

- local compose execution can reach shared local services
- CI remains green with MCP/RAG disabled

## Phase 6 - Agentic loop and validation evidence

Objective: produce criterion-ready evidence for Budgets.

Tasks:

1. Add Budgets evidence collection for MCP validation mode.
2. Add Budgets evidence collection for RAG validation mode.
3. Capture sample outputs.
4. Update `ethan\test-budgets-endpoints.ps1` or equivalent scripts for
   repeatable validation.

Done when:

- terminal validation is repeatable
- evidence exists for the report and showcase

## Phase 7 - Report packaging and demo preparation

Objective: make the Budgets work easy to mark.

Tasks:

1. Capture screenshots, logs, and workflow links.
2. Prepare Budgets architecture and interaction diagrams.
3. Write Budgets-specific known issues and limitations.
4. Map evidence explicitly to the rubric criteria.
5. Prepare a short demo path:
   - show Release 0 budget flow still works
   - show one MCP interaction
   - show one grounded RAG response
   - show one insufficient-context response
   - show CI evidence

Done when:

- the Budgets contribution is easy to defend in the showcase and report

## 7. File-level change map

### Budgets-owned files likely to change

- `ethan\backend\config.py`
- `ethan\backend\app.py`
- `ethan\backend\chat_service.py`
- `ethan\backend\db_api.py`
- `ethan\frontend\public\index.html`
- `ethan\database\app.py`
- `ethan\database\models.py`
- `ethan\test\test_backend.py`
- `ethan\test\test_frontend.py`
- `ethan\test\test_database.py`
- `ethan\test-budgets-endpoints.ps1`
- `.github\workflows\Ethan-ci.yml`
- `docker-compose.yml`

### Shared files likely to change outside `ethan\`

- `agentic_loop\main.py`
- `agentic_loop\README.md`
- prompt assets under `prompts\`
- report evidence locations under `docs\` if the team stores committed samples

## 8. Rubric coverage map

| Release 1 criterion | Budgets plan coverage |
|---|---|
| Project setup and architecture | keep Budgets microservices intact, add MCP/RAG configuration, document architecture and interaction flow |
| Student feature microservices | preserve frontend/backend/db behaviour and Release 0 functionality |
| MCP server integration | add frontend -> backend -> shared MCP path with valid tool result |
| RAG integration and grounded responses | add grounded answers with citations, confidence, and insufficient-context |
| Shared agentic loop | add Budgets evidence for MCP and RAG validation modes |
| DevOps and GitHub Actions | update Ethan workflow with MCP/RAG disabled in CI |
| Docker Compose deployment | configure Budgets backend to reach host-local MCP/RAG without containerising them |
| Integrated working software | preserve end-to-end Budgets behaviour inside the shared app |
| Technical report and project evidence | capture logs, screenshots, diagrams, commit traceability, and known issues |
| Demonstration and Q&A | prepare a defendable Budgets demo and explanation path |

## 9. Risks and controls

| Risk | Impact | Control |
|---|---|---|
| Shared MCP contract changes late | Budgets integration breaks | define a small stable contract early and mock it in tests |
| Shared RAG response shape is inconsistent | frontend rendering becomes brittle | validate responses strictly in the backend before returning them |
| CI accidentally depends on local-only services | Ethan workflow fails in GitHub Actions | keep MCP/RAG behind explicit enable flags |
| Frontend grows too complex | bugs in coach panel | preserve the existing panel and extend response rendering surgically |
| Evidence is captured too late | marks lost despite working code | collect screenshots, logs, and sample outputs during each phase |

## 10. Recommended delivery order

Deliver in this order:

1. stabilise current Budgets tests
2. add config flags and MCP/RAG client modules
3. implement one MCP flow end to end
4. implement one RAG flow end to end
5. render citations/confidence/insufficient-context in the coach panel
6. update Compose and Ethan CI
7. extend validation scripts and agentic loop
8. capture evidence and package for the report

This sequence gives the fastest path to a demonstrable Release 1 Budgets
feature while reducing the risk of breaking the existing Release 0 slice.

## 11. Immediate next-step plan after MCP/RAG browser verification

**Current state:** the Budgets coach panel now works end to end for:
- standard Ollama chat
- deterministic budget coaching
- MCP transaction retrieval
- RAG grounded responses with citations and confidence

The latest polish pass also fixed the main RAG presentation issue by giving the
grounded-answer prompt formatted currency values and explicit week-ahead planned
spend context.

### What the next step is

The next step is to **turn the working feature into assessable Release 1 evidence
and finish the remaining shared validation gap**.

That breaks into two tracks:

1. **Evidence packaging**
   - capture screenshots of the Budgets chat chips
   - capture one successful MCP result in the UI
   - capture one successful RAG result in the UI
   - save `/health` output and terminal proof that host MCP/RAG services are running
   - keep one example showing citations/confidence clearly

2. **Shared agentic-loop completion**
   - add a Budgets-focused MCP validation mode to the shared agentic loop
   - add a Budgets-focused RAG validation mode to the shared agentic loop
   - make those modes emit evidence that can be referenced in the report/demo

### Why this is the right next step

The core Budgets implementation is now working, so the biggest remaining mark
risk is no longer software failure inside `ethan\`; it is **missing validation
coverage and missing report/demo evidence**. In other words, the app is close to
"working software" marks already, but it still needs the proof and shared-loop
story needed for full Release 1 coverage.

### Recommended execution order

1. Capture the UI/API evidence while the current working state is fresh.
2. Add or update a simple Budgets validation script if repeatable terminal proof is needed.
3. Implement the shared agentic-loop MCP mode for Budgets.
4. Implement the shared agentic-loop RAG mode for Budgets.
5. Store the final screenshots/logs/output snippets in the location the group will use for the report/showcase.

### Concrete deliverables from this next step

- screenshots showing:
  - MCP chip and response
  - RAG chip and response
  - citations/confidence visible in the Budgets coach panel
- terminal or saved output for:
  - Budgets `/health`
  - shared MCP server running
  - shared RAG server running
- shared agentic-loop evidence for:
  - MCP validation mode
  - RAG validation mode

### Files likely to change in this phase

- `ethan\test-budgets-endpoints.ps1`
- `agentic_loop\main.py`
- `agentic_loop\README.md`
- prompt assets under `prompts\`
- optionally a committed evidence location if the team wants reusable report assets

## 12. Contextual MCP/RAG integration plan for the existing Budgets page

### Objective

Move Budgets from **working AI chat modes** to **context-aware budgeting help**
without creating a new page or breaking the current coach panel.

The goal is that MCP and RAG feel attached to:

- budget summary cards
- pressured budget lines
- week-ahead planned events
- Tally's existing coach suggestions

rather than feeling like separate manual chat commands.

### Product direction

Keep the current Budgets page and coach panel, but make the AI flows more
contextual in three ways:

1. **Category-linked coach actions**
   - add actions beside each relevant budget line, such as:
     - `Show transactions`
     - `Why is this under pressure?`
     - `Get grounded advice`
   - these actions should pass the category and month context to the existing
     backend chat flow so the user does not need to type the right question

2. **Week-ahead-linked actions**
   - add actions on planned events such as:
     - `How will this affect my budget?`
     - `Show similar spending`
     - `What should I watch out for?`
   - use deterministic logic first for direct impact questions, MCP for related
     historical transactions, and RAG for grounded budgeting guidance

3. **Coach-led suggestions**
   - let Tally surface contextual prompts based on the selected month's actual
     pressure points
   - examples:
     - `Transport is near warning. Show the transactions behind it`
     - `Dining has week-ahead pressure. Get grounded advice`
   - this preserves the chat panel while making it proactive

### UX implementation approach

#### A. Budget-line contextual actions

Add compact action buttons or links inside each rendered budget-line card.

Minimum action set:

- **MCP:** `Show transactions`
- **RAG:** `Get grounded advice`
- **Deterministic:** `Why is this under pressure?`

Expected behaviour:

- clicking an action posts to the existing Budgets backend
- the request includes the active budget id and a category-aware prompt or
  action hint
- the resulting answer appears:
  - in the chat history for auditability
  - and optionally in a lightweight inline details panel near the budget line

#### B. Planned-event contextual actions

Add action hooks to each week-ahead planned event card.

Recommended actions:

- `Can I still afford this?`
- `Show similar spending`
- `Get grounded advice`

These should bind the selected event's category and estimated range into the
chat/backend context rather than requiring free-text entry.

#### C. Inline result rendering

For better integration, do not rely on the chat stream alone.

Preferred render targets:

- MCP transaction previews directly below the selected category or event
- RAG guidance summary directly below the selected category or event
- citations as inline source pills or a compact list near the advice

The chat history should still record the same interaction for evidence and
traceability.

### Backend/API changes needed

The existing unified `/api/chat` route can remain the backend entry point, but
the backend should accept richer structured hints so it can treat these as
contextual interactions rather than generic free-text.

Recommended additions:

- optional `target_category`
- optional `target_budget_line_id`
- optional `target_planned_event_id`
- optional `ui_action`

These can be used by `chat_service.py` to:

- build a more explicit deterministic explanation
- send category-specific MCP requests
- build category/event-specific RAG prompts

### RAG tuning required for contextual use

Before contextual RAG is demo-ready, tighten the output rules so the answer:

1. separates **current spend** from **week-ahead planned spend**
2. clearly identifies whether the pressure is from:
   - current actual spending
   - planned events
   - warning threshold proximity
   - hard-cap proximity
3. avoids mixing multiple categories unless:
   - it ranks them explicitly, or
   - the user asked for broader month-wide guidance

This is the main remaining answer-quality gap for contextual RAG use.

### Why this improves the rubric

This tighter integration improves marking strength by making it easier to show:

- frontend + backend MCP interactions as part of the actual Budgets workflow
- frontend + backend RAG interactions as part of the actual Budgets workflow
- stronger integrated working software evidence
- a clearer and more defendable demo path

It also makes screenshots more meaningful because the AI output will be tied to
the visible budget data the user is interacting with.

## 13. Outstanding work needed to fully close the original plan

### A. Final functional work still outstanding

1. **RAG answer-quality tuning**
   - refine prompt/output rules so advice no longer confuses current spend and
     planned spend
   - make category ranking deterministic enough for month-pressure questions

2. **Contextual Budgets-page integration**
   - add inline actions on budget lines
   - add inline actions on planned events
   - optionally add inline rendering of MCP/RAG results
   - keep chat history as the canonical audit trail

3. **One clean insufficient-context example**
   - preserve or create a reliable example for the rubric/demo showing that RAG
     declines when guidance is genuinely inadequate

### B. Evidence and packaging still outstanding

1. capture final screenshots of:
   - contextual MCP usage
   - contextual RAG usage
   - citations/confidence
   - normal Release 0 budgeting still working

2. rerun and store:
   - `ethan\test-budgets-endpoints.ps1`
   - Budgets MCP validation mode in `agentic_loop`
   - Budgets RAG validation mode in `agentic_loop`

3. prepare report/demo assets:
   - Budgets architecture note
   - Budgets MCP/RAG interaction flow summary
   - known issues / limitations
   - rubric-to-evidence mapping

### C. Recommended execution order from here

1. finish the final RAG wording/ranking pass
2. implement contextual MCP/RAG entry points on the existing Budgets page
3. verify the contextual flows in the browser
4. rerun validation scripts and shared loop modes
5. capture the final report/showcase evidence

## 14. Highest-mark path through the remaining work

To maximise the original task and rubric outcome, the remaining work should aim
for the following final demonstration state:

1. **Release 0 stability still visible**
   - budgets, summary cards, planned events, proposals, and normal coaching all
     still work

2. **MCP visibly integrated into the page**
   - the user can trigger a contextual transaction lookup from a pressured
     category or planned event

3. **RAG visibly integrated into the page**
   - the user can trigger contextual grounded advice from the same page element
   - the response shows citations and confidence clearly

4. **Shared validation evidence exists**
   - terminal validation script output saved
   - agentic-loop MCP/RAG outputs saved

5. **Report/demo mapping is explicit**
   - every major rubric point has a corresponding screenshot, log, or run
     output

If implemented this way, the Budgets slice does not just technically satisfy
Release 1 — it shows the integration in a way that is easier for markers to
understand and reward.

## 15. Plan to make Tally context RAG-assisted and MCP-backed

### Objective

Improve Tally's answer consistency by changing how chat context is built:

1. use **RAG retrieval** to supply grounded guidance context before Ollama
   answers broader coaching questions
2. use **MCP transaction retrieval** as the chat layer's transaction-evidence
   source instead of relying on the current direct local transaction-summary
   assembly for all natural-language context
3. keep **deterministic budget maths** in place for exact affordability,
   thresholds, and proposal calculations until MCP-backed summary parity is
   proven

This should be treated as a **chat-context migration**, not a full rewrite of
the Budgets calculation engine.

### Why change the current context building

The current system already works, but the chat layer still has two weaknesses:

1. **Ollama answers are only as good as the prompt context**
   - without retrieved guidance, month-wide coaching answers can drift in tone,
     category ranking, or explanation quality

2. **transaction context is assembled differently from the shared AI stack**
   - Budgets summary maths is currently built through `summary_service.py`,
     which pulls transaction data from `transactions_api`
   - MCP is already stronger for showing concrete transaction evidence and
     aligns better with the shared Release 1 integration story

### Target architecture

Split Tally orchestration into three complementary layers:

1. **Deterministic layer**
   - exact affordability
   - exact warning/hard-cap checks
   - proposal maths

2. **MCP evidence layer**
   - relevant transactions for a category, period, or contextual action
   - structured transaction search results used to enrich chat context

3. **RAG guidance layer**
   - retrieved budgeting guidance chunks used to enrich Ollama prompts for
     coaching/explanation questions

In practice, Tally should answer from a composed context bundle:

- current deterministic budget snapshot
- relevant MCP transaction evidence
- relevant RAG guidance
- recent chat history
- optional UI context (`target_category`, `target_budget_line_id`,
  `target_planned_event_id`, `ui_action`)

### Scope recommendation

The safest scope is:

- **switch natural-language transaction context to MCP first**
- **add RAG to Ollama prompt-building for suitable question types**
- **do not immediately replace deterministic calculations or
  `summary_service.py` for canonical totals**

That still satisfies the goal of making the AI context more shared-stack-driven
without risking regression in exact budget behaviour.

### Implementation plan

#### Phase A - Introduce a unified chat-context builder

Create a dedicated context-building path in `ethan\backend\chat_service.py`
that returns a structured bundle for any chat turn.

Suggested shape:

```json
{
  "summary": {},
  "mcp_transactions": [],
  "rag_guidance": [],
  "history": [],
  "context_hints": {}
}
```

Responsibilities:

- centralise chat-context assembly in one place
- decide when MCP retrieval is needed
- decide when RAG retrieval is needed
- keep deterministic summary data available for exact maths and fallback logic

Files likely to change:

- `ethan\backend\chat_service.py`
- optionally a new helper such as `ethan\backend\chat_context.py`
- `ethan\test\test_backend.py`

#### Phase B - Route transaction-evidence retrieval through MCP

Replace the chat layer's direct use of locally assembled transaction context
for natural-language answers with MCP retrieval.

Recommended MCP retrieval triggers:

- budget-line contextual `Show transactions`
- planned-event `Show similar spending`
- questions about "recent purchases", "transactions", or "what is driving"
  category pressure
- month-pressure coaching where the top pressured category is identified first
  and then evidenced through MCP

Recommended MCP output normalisation:

- consistent transaction row structure
- top N rows
- total matched spend
- matched category label
- date range used
- any MCP/tool status metadata needed for auditability

Important constraint:

- keep `summary_service.py` for totals/ranking during the first migration
  phase
- use MCP as the **transaction evidence source for chat context**, not yet the
  sole budgeting source of truth

#### Phase C - Add RAG retrieval into Ollama prompt-building

For suitable chat turns, retrieve guidance from the shared RAG server before
calling Ollama.

Recommended trigger types:

- "what should I focus on"
- "why is this risky"
- "what should I watch out for"
- "what does this mean"
- contextual grounded-advice actions

Recommended flow:

1. build the deterministic budget snapshot
2. identify the main target category/event for the question
3. retrieve RAG guidance for that question and context
4. retrieve MCP transactions if transaction evidence would improve the answer
5. build an Ollama prompt that clearly separates:
   - current actual spend
   - planned/week-ahead spend
   - transaction evidence
   - retrieved guidance
6. require the model to answer only from that provided context

Prompt rules should explicitly forbid:

- inventing uncited guidance
- mixing actual and planned spend without labelling them
- broadening to extra categories unless explicitly ranking them

Files likely to change:

- `ethan\backend\chat_service.py`
- `ethan\backend\ai\chat_prompt.py`
- `ethan\backend\ai\grounded_prompt.py`
- `ethan\test\test_backend.py`

#### Phase D - Add mode-aware orchestration rules

Refine routing so each question type uses the right combination of systems:

| Question type | Deterministic | MCP | RAG | Ollama |
|---|---|---|---|---|
| Exact affordability | required | optional evidence | no | optional wording only |
| Category pressure explanation | required ranking | yes | optional | yes |
| Transaction lookup | no | required | no | no/minimal |
| Grounded coaching advice | summary context | optional | required | yes |
| Planned-event guidance | required impact maths | optional | yes | yes |

This avoids the common failure mode where one AI path tries to answer
everything.

#### Phase E - Add parity checks before any deeper MCP migration

If the project still wants transaction context to come from MCP more broadly,
add a shadow-validation step first.

Suggested validation:

- compare top category spend totals inferred from MCP query results against
  current `summary_service.py` outputs for the same month
- compare matched transaction counts for sample categories
- log mismatches in test/dev mode

Only after that parity is stable should the team consider replacing more of the
current summary assembly path with MCP-derived transaction aggregation.

### Validation plan

1. **Unit/integration tests**
   - questions that should trigger RAG-assisted Ollama
   - questions that should trigger MCP evidence retrieval
   - questions that must remain deterministic
   - contextual budget-line and planned-event actions using the new context
     bundle

2. **Prompt-quality checks**
   - verify responses cleanly separate actual spend from planned spend
   - verify month-pressure answers cite the correct primary category
   - verify RAG does not broaden scope unexpectedly

3. **Failure-mode checks**
   - MCP unavailable
   - RAG unavailable
   - RAG returns weak/no results
   - MCP returns no matching transactions

4. **Evidence/report checks**
   - one example of MCP-backed transaction evidence
   - one example of RAG-assisted coaching
   - one example showing deterministic maths remained correct

### Review of impact

#### Expected benefits

1. **More consistent coaching answers**
   - Ollama will answer from retrieved guidance instead of only a freeform
     summary prompt

2. **Stronger Release 1 integration story**
   - Tally will more visibly use both shared services as part of normal budget
     interaction

3. **Better evidence and explainability**
   - MCP results justify "why" a category is under pressure
   - RAG guidance justifies "what to do about it"

4. **Cleaner system separation**
   - deterministic = exact maths
   - MCP = evidence
   - RAG = grounded guidance
   - Ollama = natural-language synthesis

#### Main risks

1. **Latency increases**
   - a single chat turn may need summary build + MCP + RAG + Ollama

2. **More failure surfaces**
   - Tally can now be affected by MCP availability and RAG availability more
     often

3. **Potential mismatch between MCP evidence and local summary maths**
   - if MCP query filters differ from `transactions_api`, users may see
     confusing discrepancies

4. **Over-reliance on AI routing**
   - if too many queries are forced through RAG+Ollama, exact answers may get
     worse instead of better

#### Mitigations

- keep deterministic routing for exact financial questions
- keep local summary maths as the first canonical ranking source initially
- use MCP for evidence enrichment first, then validate parity before deeper
  migration
- degrade cleanly when MCP or RAG is unavailable

### Recommendation

This plan is **worth implementing**, but the best version is a staged one:

1. add **RAG-assisted prompt context** for coaching/explanation questions
2. shift **chat transaction evidence** to MCP
3. keep **deterministic/local summary maths** as the canonical numeric layer
   until MCP parity is proven

That gives better answer consistency and stronger shared-service integration
without risking the reliability of the Budgets feature.
