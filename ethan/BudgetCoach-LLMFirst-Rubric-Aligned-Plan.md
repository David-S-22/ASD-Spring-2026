# Budgets Tally — LLM-First, Rubric-Aligned Implementation Plan

## Purpose

This plan guides the transition of the Budgets feature's Tally chat from a mostly deterministic responder to an **LLM-first, agentic workflow**, while staying aligned with the **Release 1 brief**, **marking rubric**, and the integrated group application requirements.

This is not just a chat-refactor plan. It is a **Release 1 implementation and evidence plan** for the Budgets feature.

## Non-negotiable rubric constraints

The implementation must keep the following true at all times:

1. **Budgets remains part of the integrated group application**
   - The feature must remain functional inside the shared app.
   - Loss of integration risks zero for Working Software.

2. **Frontend access stays backend-mediated**
   - The Budgets frontend must access MCP and RAG **through the Budgets backend/API**.
   - The frontend must not call shared MCP or shared RAG directly.

3. **Shared MCP and RAG remain non-containerised**
   - `docker-compose.yml` must continue to run the containerised microservices only.
   - AI mode, MCP, RAG, and the shared agentic loop must remain outside Docker Compose.

4. **Release 0 functionality and AI mode must continue to work**
   - Existing Budgets behavior must remain operational after Release 1 changes.

5. **Budgets must preserve visible MCP and RAG demonstrations**
   - At least one successful Budgets MCP interaction must remain visible through the frontend/backend.
   - At least one successful Budgets RAG grounded response must remain visible through the frontend/backend.

6. **Grounded responses must remain rubric-compliant**
   - RAG responses must include citations and confidence.
   - If relevant context is unavailable, Budgets must show an insufficient-context response.

7. **CI/CD expectations must remain intact**
   - Budgets CI must retain MCP/RAG integration in code.
   - MCP and RAG must remain disabled during CI/CD execution.

## Target architecture

### High-level goal

Make Tally **LLM-first for user-facing conversation**, while keeping deterministic code as a **calculation, validation, and fallback layer**.

### Required interaction boundary

Frontend -> Budgets backend/API -> shared MCP / shared RAG / local AI model

### Agentic workflow

The Budgets feature should continue to expose and follow:

1. **Observe**
   - gather budget snapshot
   - gather recent chat history
   - gather UI context
   - gather open proposal state
   - gather MCP or RAG evidence if required

2. **Plan**
   - classify the intent
   - choose the execution path
   - decide whether exact deterministic calculations are required
   - decide whether MCP or RAG is needed

3. **Act**
   - run any deterministic calculations
   - call MCP and/or RAG if required
   - build the LLM prompt/context
   - generate the reply or proposal

4. **Adapt**
   - validate the result
   - retry or downgrade if invalid
   - store proposal/revision state
   - persist workflow metadata for later turns and evidence

## Deterministic logic policy

The aim is **not** to remove deterministic code entirely. The aim is to stop using deterministic code as the main conversational voice.

### Deterministic logic should be used for

1. **Exact budget calculations**
   - affordability before/after math
   - remaining room before warning/cap
   - projected spend changes
   - proposal target calculations

2. **Validation of LLM output**
   - verify numeric claims
   - verify warning/cap claims
   - verify proposal direction and plausibility
   - verify referenced category/line consistency

3. **Hard fallback**
   - invalid model output after retry
   - unsafe or contradictory budget claims
   - situations where an exact answer is required and the model cannot be trusted

### Deterministic logic should not be the default for

1. general coaching
2. explanation and rewording
3. conversational follow-up
4. grounded synthesis of MCP or RAG evidence
5. proposal phrasing and adaptation

## MCP and RAG integration policy

### MCP

Use MCP when the user needs **transaction evidence** or structured tool output.

Typical MCP uses:

- show relevant transactions for a category
- explain why a category is under pressure using recent spending
- support a budget conversation with transaction evidence

MCP must continue to:

- be called by the backend
- return a structured tool result
- remain visible in the Budgets UI and stored response metadata

### RAG

Use RAG when the user needs **grounded coaching**, **source-backed guidance**, or **citations/confidence**.

Typical RAG uses:

- what should I focus on this month?
- give grounded advice with sources
- what guidance applies to this budget situation?

RAG must continue to:

- be called by the backend
- return or support grounded responses
- surface citations and confidence
- surface insufficient-context behavior when retrieval is weak

## Workstreams

This work must proceed in two parallel workstreams.

### Workstream A — Chat architecture evolution

Goal: make Tally LLM-first without losing correctness.

### Workstream B — Rubric-visible evidence preservation

Goal: preserve and strengthen the Budgets Release 1 evidence needed for marking, report, showcase, and Q&A.

Neither workstream is optional.

## Step-by-step implementation plan

## Phase 0 — Rubric lock and demonstration lock

### Objective

Protect the Release 1 requirements before further chat refactoring.

### Tasks

1. Lock one explicit Budgets **MCP demo path** in the UI/backend.
2. Lock one explicit Budgets **RAG demo path** in the UI/backend.
3. Lock one explicit **insufficient-context RAG validation case**.
4. Confirm Budgets still works through the integrated group app.
5. Confirm Budgets still routes through backend/API only.

### Done when

- Budgets still has a clear MCP interaction
- Budgets still has a clear grounded RAG interaction
- insufficient-context behavior is preserved as a testable scenario

## Phase 1 — Introduce planner-driven routing

### Objective

Move routing decisions into an explicit planner instead of scattered branch logic.

### Tasks

1. Add a planner that decides:
   - intent
   - execution path
   - whether deterministic facts are required
   - whether MCP is needed
   - whether RAG is needed
2. Record planner decisions in the existing workflow payload.
3. Preserve explicit `mcp` and `rag` mode overrides.

### Done when

- each Budgets turn has a traceable execution plan
- planner metadata is stored in the response/workflow payload

### Status

**Completed**

- explicit execution plan added
- `execution_path` / `execution_reason` metadata added
- explicit MCP/RAG override behavior preserved

## Phase 2 — Make auto mode selectively LLM-first

### Objective

Shift `auto` routing away from deterministic-default behavior.

### Tasks

1. Make `auto` prefer Ollama for non-exact coaching and explanation turns.
2. Keep exact numeric flows deterministic for now.
3. Keep MCP and RAG explicit modes intact.
4. Keep deterministic skip/testing controls usable during development.

### Done when

- some `auto` turns route to Ollama by default
- exact numeric paths still remain safe

### Status

**Completed, expanded beyond the first slice**

- overspending/pressure-style auto path prefers Ollama
- affordability and budget-line explanation flows now prefer Ollama with backend-computed facts
- proposal-sensitive paths still remain deterministic for now

## Phase 3 — Refactor deterministic replies into computation helpers

### Objective

Separate computation from wording.

### Tasks

1. Extract deterministic helpers that return structured facts instead of user-facing prose:
   - affordability facts
   - threshold room/overshoot
   - before/after totals
   - category/line resolution
   - proposal target values
2. Ensure these helpers are reusable by both deterministic fallback and LLM context builders.

### Done when

- deterministic logic can be reused as machine-readable context
- exact calculations are no longer tied to large reply-generating functions

## Phase 4 — Build intent-specific computed context packs

### Objective

Give the model reliable structured facts instead of forcing it to infer everything from a flat summary.

### Tasks

1. Build an **affordability context pack**:
   - target line/category
   - requested amount
   - actual/planned/projected
   - warn/cap
   - remaining income before/after
   - over-warning / over-cap flags

2. Build a **tracking/pressure context pack**:
   - top pressure lines
   - exact threshold room
   - whether pressure comes from actual or planned spend

3. Build a **proposal revision context pack**:
   - active proposal
   - current thresholds
   - user feedback direction
   - allowed revision boundaries

4. Build a **grounded guidance context pack**:
   - RAG retrieval
   - citations
   - confidence / insufficient-context hints

5. Build an **MCP evidence context pack**:
   - tool scope
   - result count
   - preview rows
   - totals

### Done when

- Ollama has precise backend-generated facts for high-risk intents
- the model no longer has to invent core budget arithmetic

## Phase 5 — Tighten proposal gating

### Objective

Stop the LLM from turning ordinary budget questions into threshold-change proposals.

### Tasks

1. Allow proposal mode only when the user explicitly asks for:
   - a suggestion
   - a change
   - an adjustment
   - making room
   - a revision of an existing suggestion

2. Force affordability / tracking / explanation questions toward:
   - `advice`, or
   - `clarify`

3. Keep proposal creation reviewable and non-destructive.

### Done when

- plain affordability questions stop spawning nonsense proposals
- proposal mode becomes an explicit user-driven action

## Phase 6 — Strengthen prompts and few-shot examples

### Objective

Teach the model better behavior for Budgets-specific chat patterns.

### Tasks

1. Update the system prompt to say:
   - exact numbers come from supplied facts
   - do not invent thresholds or category mappings
   - do not create proposals for plain affordability checks
   - explain follow-ups like "what" instead of starting a new action

2. Retune few-shot examples:
   - affordability -> advice
   - explanation -> advice
   - explicit adjustment -> proposal
   - vague follow-up -> clarify or explain
   - grounded coaching -> cited answer

### Done when

- model responses are less proposal-happy
- follow-up turns are more stable and explainable

## Phase 7 — Add semantic validation

### Objective

Validate correctness, not just JSON shape.

### Tasks

1. Keep JSON/schema validation.
2. Add post-generation validation for:
   - money values
   - cap/warning claims
   - category references
   - proposal plausibility
3. Retry once with a targeted correction prompt if validation fails.
4. Fall back to deterministic wording only if still invalid/unsafe.

### Done when

- invalid but well-formed model output no longer reaches the user unchanged

## Phase 8 — Narrow deterministic final responses to fallback-only where safe

### Objective

Use deterministic final wording only where truly necessary.

### Tasks

1. Migrate more exact-answer paths to:
   - deterministic computation + LLM explanation
   rather than
   - deterministic final prose
2. Keep deterministic final replies only for:
   - failed model retries
   - unsafe exact answers
   - unresolved critical ambiguity

### Done when

- user-facing replies are mostly Ollama-driven
- deterministic logic still protects correctness behind the scenes

## Phase 9 — Preserve and capture Release 1 evidence

### Objective

Make sure the implementation earns marks, not just improves design.

### Tasks

1. Capture Budgets MCP frontend/backend evidence.
2. Capture Budgets RAG grounded-response frontend/backend evidence.
3. Capture Budgets insufficient-context evidence.
4. Capture terminal validation for local MCP/RAG interactions.
5. Capture Docker Compose deployment evidence showing Budgets backend connection config.
6. Capture CI evidence with MCP/RAG disabled.
7. Ensure report-ready examples exist for:
   - OLLAMA-first chat
   - MCP result
   - RAG grounded answer
   - insufficient-context case
   - proposal review flow

### Done when

- the Budgets feature has report/showcase-ready evidence for Release 1

## Phase 10 — Report and showcase support

### Objective

Make the final implementation easy to defend in the report and Q&A.

### Tasks

1. Record the final Budgets interaction flows in concise architecture language.
2. Keep examples of:
   - backend-mediated MCP
   - backend-mediated RAG
   - grounded response with citations/confidence
   - insufficient-context case
   - LLM-first but validated affordability/coaching
3. Document known issues and remaining limitations honestly.

### Done when

- the Budgets contribution is easy to explain, defend, and evidence in the report/demo

## Testing checkpoints between implementation stops

At each pause point, report which of these are complete:

1. planner/routing changes
2. new tests passing
3. live Budgets container rebuilt and verified
4. MCP path preserved
5. RAG path preserved
6. insufficient-context behavior preserved
7. existing Release 0 Budgets behavior preserved

## Current completed steps

As of now, the following have been completed:

1. **Planner-driven routing introduced**
2. **LLM-first auto routing expanded across overspending, affordability, and line-explainer flows**
3. **Routing tests updated and passing**
4. **Computed affordability and pressure fact packs added to the Ollama prompt**
5. **Current-month defaulting and dynamic month-status behaviour completed**

Current verified test result:

- `85 passed` across the current Budgets targeted backend, frontend, and database tests after the expanded routing and month-state fixes

## Current biggest remaining gaps relative to the rubric

1. MCP and RAG evidence must stay clearly demonstrable in Budgets
2. insufficient-context validation must be explicitly preserved and evidenced
3. CI/report/showcase evidence still needs to be produced
4. shared-agentic-loop-facing validation compatibility must remain intact
5. proposal-sensitive and remaining exact-answer paths still need to move from deterministic-first to LLM-first with computed facts where safe

## Definition of done

This plan is complete when:

1. Budgets auto mode is **mostly LLM-first**
2. Deterministic code is used mainly for **computation, validation, and fallback**
3. Budgets still exposes clear **MCP** and **RAG** frontend/backend interactions
4. RAG responses still show **citations**, **confidence**, and **insufficient-context** handling
5. Budgets remains integrated and operational in the full group application
6. Docker Compose still works with MCP/RAG remaining non-containerised
7. CI still works with MCP/RAG disabled
8. Budgets has sufficient evidence for the report, showcase, and Q&A
