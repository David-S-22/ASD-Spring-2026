# Budget Coach AI Chat Implementation Plan

## 1. Purpose

This document lays out a practical plan for implementing the **Chat with Tally (AI)** feature for Budget Coach, plus the surrounding changes needed to make it reliable, assessable for Interim 0, and consistent with patterns already used elsewhere in the repository.

This plan is intentionally based on the current Budget Coach architecture in `ethan/`, while borrowing proven ideas from:

- `sophia/backend/routes/chat.py`
- `sophia/backend/services/chat.py`
- `sophia/backend/ai/chat_prompt.py`
- `sophia/backend/ai/ollama_client.py`
- `sophia/backend/ai/schemas.py`
- `sophia/backend/templates/chat_panel.html`
- `sophia/backend/templates/suggestion_card.html`
- `janelle/backend/services/chat_service.py`
- `janelle/backend/services/ollama_service.py`
- `sophia/agentic_loop/README.md`

The goal is **not** to copy those implementations directly. The goal is to reuse the best ideas while fitting the already-established Budget Coach frontend, backend, database, and shared-shell patterns.

## 2. What the AI chat must achieve

For Interim 0, the AI chat should do four things well:

1. answer budget questions about the currently selected month
2. turn plain-English user requests into one structured proposed change
3. require explicit user approval before any change is applied
4. produce clear evidence of AI-mode, prompt engineering, and agentic workflow use

The AI chat should behave like a **budget-specific assistant**, not a general chatbot.

## 2.1 Explicit Interim 0 alignment

This feature plan must satisfy the **guidelines and marking rubric**, not just produce a technically working chat box.

That means the implementation must visibly support:

1. **AI-Mode integration** using Ollama and an approved open-source model
2. **Agentic workflow evidence** showing Plan → Act → Observe → Adapt
3. **Prompt engineering and context management evidence**
4. **Integrated working software** across frontend, backend/API, and database services
5. **Docker Compose integration** within the shared group system
6. **GitHub Actions validation** through the existing Budgets workflow
7. **Technical report evidence** including screenshots, architecture explanation, workflow explanation, and known limitations

## 3. Current Budget Coach baseline

Budget Coach already has the non-AI budgeting core in place:

- month-based budget selection
- budget line CRUD
- planned event CRUD
- summary calculations
- projected warning and over-cap states
- other-expenses view
- live affordability check
- shared shell integration
- Docker and CI integration

That means the AI feature can be added as a **thin orchestration layer** over working existing functionality, rather than inventing a second path for writing data.

## 4. Recommended design principles

The implementation should follow these rules.

### 4.1 Propose first, apply second

Follow the same high-level idea seen in Sophia's bills chat and Janelle's transaction chat:

- the first AI step creates a structured **proposal**
- the user reviews the proposal
- only an explicit accept action performs the real write

Budget Coach should never let model output directly mutate `budgets`, `budget_lines`, or `planned_events`.

### 4.2 Keep the AI output shape strict

Use the same general pattern as:

- `sophia/backend/ai/schemas.py`
- `janelle/backend/services/ollama_service.py`

The model should return JSON only, and the backend should validate it with hand-written deterministic checks. No proposal should reach the user if the response shape is invalid or incoherent.

### 4.3 Reuse the normal CRUD paths

Match the discipline already visible in:

- `sophia/backend/services/chat.py`
- `janelle/backend/services/chat_service.py`

Applying a proposal should call the same Budget Coach CRUD code paths already used by the existing frontend forms. The AI flow should never become a hidden second implementation of budget writes.

### 4.4 Stay month-aware

The chat must use the selected month as its operating context. Any proposed edit should target the active budget only, and planned events must continue obeying the month restriction already implemented.

### 4.5 Keep the current frontend style

Budget Coach already uses a simple fetch-driven dashboard in `ethan/frontend/public/index.html`. The AI panel should follow that same style rather than switching to HTMX fragments just for the chat.

The repo examples are useful for behavior and contracts, but the Budget Coach UI should remain consistent with its current architecture.

## 5. Feature scope for Interim 0

The AI chat should be delivered in phases.

### 5.1 Phase 1: advice-only questions

Support questions like:

- "Where am I overspending most?"
- "Can I still afford to eat out this month?"
- "Which categories are close to warning?"
- "What should I cut back on?"

This phase proves:

- Ollama integration
- prompt construction from live budget data
- month-aware coaching output

### 5.2 Phase 2: proposal generation

Support natural-language requests that become one structured proposed action:

- create a budget line
- update a budget line
- delete a budget line
- create a planned event
- update a planned event
- cancel a planned event

This phase proves:

- human-in-the-loop safety
- schema validation
- integration with existing CRUD endpoints

### 5.3 Phase 3: proposal acceptance and rejection

Support:

- accept proposal
- reject proposal
- optional rejection reason

This phase proves:

- coach proposal lifecycle
- stored AI decision history
- feedback loop for later prompts

### 5.4 Phase 4: starter-budget and coaching extensions

If time permits before submission:

- first-run starter-budget generation from transactions
- coaching proposals that recommend reallocations
- rejection reasons influencing the next suggestion

This is valuable, but not the first priority after basic chat correctness.

## 5.5 Minimum rubric-complete AI scope

To align strongly with the marking criteria, the minimum chat-AI deliverable should be:

1. a working chat panel reachable from the shared app
2. a backend route that calls Ollama successfully
3. one approved model clearly identified in config and documentation
4. strict schema validation and safe fallback behavior
5. at least one end-to-end proposal flow from chat → review card → accept/reject
6. clear evidence of the agentic loop and prompt/context decisions

Anything less than that risks the feature appearing only partially complete under the AI integration and agentic workflow criteria.

## 6. What should be added to the database layer

The existing `coach_proposals` table is close, but the AI chat needs a little more support around it.

### 6.1 Keep `coach_proposals` as the approval anchor

Continue using `coach_proposals` for reviewable AI changes.

Recommended proposal JSON shape:

```json
{
  "proposal_type": "chat_edit",
  "target_type": "budget_line",
  "operation": "update",
  "target_id": 12,
  "fields": {
    "warn_at": 15000,
    "hard_cap": 20000
  },
  "preview": {
    "title": "Update Groceries budget line",
    "rows": [
      {"label": "Warn at", "old": "$130", "new": "$150"},
      {"label": "Hard cap", "old": "$180", "new": "$200"}
    ]
  }
}
```

This mirrors the preview discipline seen in Sophia and Janelle, but adapted to Budget Coach entities.

### 6.2 Add a `chat_messages` table

Recommended new table:

- `chat_messages (id, budget_id, role, content, proposal_id, created_at)`

Why it is worth adding:

- keeps a durable chat transcript for the active month
- gives the backend recent history for prompts
- gives the report/demo a clear AI evidence trail
- separates chat conversation from proposal decisions

Suggested meaning:

- `role`: `user` or `assistant`
- `content`: visible message text
- `proposal_id`: nullable link when an assistant message produced a proposal

This is not strictly required for CRUD correctness, but it is strongly recommended for a proper AI chat experience and for submission evidence.

### 6.3 Extend proposal decision tracking slightly if needed

The current table already has:

- `status`
- `rejection_reason`
- `decided_at`

That is likely enough. If anything is added, keep it minimal:

- optional `applied_at`
- optional `applied_result_json`

Only add these if the acceptance flow needs them for debugging or evidence.

## 7. Backend/API implementation plan

## 7.1 Add an AI package under `ethan/backend`

Recommended files:

- `ethan/backend/ai/__init__.py`
- `ethan/backend/ai/ollama_client.py`
- `ethan/backend/ai/chat_prompt.py`
- `ethan/backend/ai/schemas.py`
- `ethan/backend/ai/guard.py`

This structure should follow the same separation of concerns shown in `sophia/backend/ai/`.

Responsibilities:

- `ollama_client.py`: POST to Ollama chat API
- `chat_prompt.py`: build prompt messages from budget context
- `schemas.py`: validate AI output shapes
- `guard.py`: retry once on invalid AI JSON, then return a safe fallback

## 7.2 Add a chat service

Recommended new file:

- `ethan/backend/chat_service.py`

Responsibilities:

- load current budget summary and related entities
- load recent chat history
- call the AI guard
- distinguish between:
  - advice response
  - proposal response
- store assistant/user chat messages
- store proposals in `coach_proposals`
- apply accepted proposals through existing CRUD pathways

This should mirror the orchestration style in `sophia/backend/services/chat.py`, but use Budget Coach data and entities.

## 7.3 Add backend routes

Recommended routes:

- `POST /api/chat`
- `GET /api/chat/history?budget_id=<id>`
- `POST /api/chat/proposals/<proposal_id>/accept`
- `POST /api/chat/proposals/<proposal_id>/reject`
- `GET /api/chat/proposals?budget_id=<id>&status=proposed`

Optional:

- `POST /api/chat/retry-last`

These routes belong in `ethan/backend/app.py`.

### `POST /api/chat`

Input:

```json
{
  "budget_id": 3,
  "message": "Raise groceries to 150 to 200"
}
```

Output for advice:

```json
{
  "reply": "Groceries is still under cap but projected to hit warning this month.",
  "proposal": null,
  "fallback": false
}
```

Output for proposal:

```json
{
  "reply": "I've suggested updating Groceries. Review it before saving.",
  "proposal": {
    "id": 18,
    "status": "proposed",
    "preview": {
      "title": "Update Groceries budget line",
      "rows": [
        {"label": "Warn at", "old": "$130", "new": "$150"},
        {"label": "Hard cap", "old": "$180", "new": "$200"}
      ]
    }
  },
  "fallback": false
}
```

## 7.4 Reuse existing write services for proposal application

When a user accepts a proposal:

- load the proposal row
- validate that it is still `proposed`
- validate that its target still exists and is still coherent
- apply through the same CRUD wrappers already used by manual UI actions
- mark the proposal as `accepted`

When a user rejects a proposal:

- set status to `rejected`
- store optional `rejection_reason`
- record `decided_at`

This should be as close as possible to the preview-then-apply pattern used in:

- `sophia/backend/services/chat.py`
- `janelle/backend/services/chat_service.py`

## 7.5 Add stale-proposal protection

Borrow the spirit of Janelle's preview checks.

Before applying a proposal:

- reload the current target
- compare against the preview assumptions when possible
- if the row changed meaningfully, refuse the apply and tell the user the proposal is stale

This prevents accepting AI suggestions that no longer match the current budget state.

## 8. Database API additions

Recommended new database API support in `ethan/database/app.py` and `ethan/database/models.py`:

- CRUD for `chat_messages`
- existing `coach_proposals` CRUD reused for proposal rows
- optional query filters by `budget_id` and `status`

Suggested endpoints:

- `GET /budgets/<budget_id>/chat-messages`
- `POST /budgets/<budget_id>/chat-messages`
- `GET /budgets/<budget_id>/coach-proposals?status=proposed`

The database API should remain persistence-only:

- no prompt logic
- no Ollama calls
- no budget maths

## 9. Frontend implementation plan

The frontend should replace the current placeholder AI panel in `ethan/frontend/public/index.html`.

### 9.1 Chat panel layout

Recommended UI elements:

- message history area
- 3 to 4 prompt chips for common questions
- text input
- send button
- loading indicator
- proposals area below the chat

Good starter chips:

- "Where am I overspending most?"
- "Can I still afford to eat out this month?"
- "Create a groceries budget of $150-$200"
- "Add dinner on Friday for about $40"

This follows the friendly discoverability seen in `sophia/backend/templates/chat_panel.html`.

### 9.2 Proposal cards

Proposal cards should show:

- title
- field-by-field before/after rows
- short rationale
- warning text if relevant
- Accept button
- Reject button

This should visually follow the clarity of `sophia/backend/templates/suggestion_card.html`, but stay within the existing Budget Coach panel style and JavaScript architecture.

### 9.3 Frontend behavior

On send:

1. read the active `budget_id`
2. POST the message to `/budgets-backend/api/chat`
3. append the user message locally
4. append the assistant reply
5. render any returned proposal card
6. refresh the monthly summary if a proposal is accepted

On accept:

1. POST to `/budgets-backend/api/chat/proposals/<id>/accept`
2. refresh the summary, budget lines, planned events, affordability options, and proposal list
3. add a short assistant/system message confirming the change

On reject:

1. POST to `/budgets-backend/api/chat/proposals/<id>/reject`
2. optionally collect a short reason in a small popup
3. refresh the proposal list
4. optionally trigger one adaptive reply from the AI

## 10. Prompt design plan

The prompt should be kept compact and structured, following the principle shown in `sophia/backend/ai/chat_prompt.py`: short instructions, explicit JSON shape, few-shot examples, and only the minimum useful context.

### 10.1 System instructions

The prompt should tell the model:

- you are Tally, a budgeting assistant
- operate only on the provided month
- never claim a change is already saved
- return JSON only
- ask for missing details instead of inventing them
- produce at most one proposed action at a time

### 10.2 Context injected per turn

Include:

- selected month
- declared income
- totals summary
- budget lines with ids, categories, warn/cap, actual, planned, projected
- planned events summary
- unresolved proposal rejections if relevant
- last few chat messages

Do not dump more than necessary. Keep it compact.

### 10.3 Response shapes

Recommended advice shape:

```json
{
  "mode": "advice",
  "say": "Dining is projected to hit its warning amount because of two planned events.",
  "question": null,
  "proposal": null
}
```

Recommended proposal shape:

```json
{
  "mode": "proposal",
  "say": "I've suggested updating Dining. Review it before saving.",
  "question": null,
  "proposal": {
    "target_type": "budget_line",
    "operation": "update",
    "target_id": 7,
    "fields": {"warn_at": 8000, "hard_cap": 12000},
    "rationale": "Dining is tracking higher than the current limits."
  }
}
```

Recommended clarification shape:

```json
{
  "mode": "clarify",
  "say": "Do you want me to change the warning amount, the hard cap, or both for Groceries?",
  "question": {
    "kind": "missing_detail",
    "field": "scope"
  },
  "proposal": null
}
```

## 10.4 Prompt engineering artefacts required for submission

The rubric expects evidence of prompt engineering and context management, so the following should exist as inspectable artefacts in the repo:

- the actual prompt builder source file
- the response schema validator source file
- a short explanation of what context is injected and why
- one or more example prompts and example validated responses for the report

This should be treated as a required deliverable, not optional polish.

## 11. Validation rules the backend must enforce

The AI layer should not be trusted with domain correctness.

The backend must validate:

- target entity type is supported
- referenced ids are integers and exist
- budget line category rules are respected
- planned event dates stay inside the parent budget month
- money fields are integers in cents before persistence
- `warn_at <= hard_cap`
- `est_low <= est_high`
- delete actions are blocked or clarified when downstream data would become inconsistent

If validation fails:

- do not create a proposal
- return a safe assistant reply asking the user to rephrase or clarify

## 12. Suggested step-by-step build order

### Step 1: backend configuration and Ollama client

Add config entries for:

- `OLLAMA_URL`
- `CHAT_MODEL`
- `COACH_MODEL`
- `AI_TIMEOUT_SECONDS`

Mirror the structure already used in other features.

### Step 2: database support for chat history

Add:

- `ChatMessage` model
- CRUD endpoints
- tests

### Step 3: AI prompt, schema, and guard

Add:

- prompt builder
- response validators
- fallback handling

Test invalid JSON, missing keys, and hallucinated fields.

### Step 4: `POST /api/chat`

Ship the advice-only version first.

That proves:

- monthly context loading
- Ollama reachability
- safe fallback behavior

### Step 5: proposal creation

Support the simplest proposal types first:

1. create budget line
2. update budget line
3. create planned event

These map neatly onto the existing UI and data model.

### Step 6: proposal accept/reject

Implement:

- accept
- reject
- rejection reason
- refresh behavior

### Step 7: frontend chat panel

Replace the placeholder with:

- history
- input
- prompt chips
- proposal cards

### Step 8: adaptive follow-up after rejection

Borrow the same broad idea as Sophia's adapt step:

- once a proposal is rejected, either
  - store that and wait for the next user message, or
  - optionally run one short adaptive assistant response

For Interim 0, storing the rejection reason is more important than a complex automatic follow-up.

### Step 9: coaching proposal mode

After command interpretation works, add proactive recommendations such as:

- reduce Dining by $20
- increase Groceries warning range
- move discretionary room from Entertainment to Transport

These should still land as reviewable proposals.

## 12.1 Where the agentic workflow appears in this implementation

The chat feature should explicitly demonstrate the required **Plan → Act → Observe → Adapt** loop.

Recommended mapping:

1. **Plan**
   - build the prompt from the selected month's summary, budget lines, planned events, recent chat messages, and any relevant rejection history
   - ask the model for either advice or one structured proposal

2. **Act**
   - return advice to the user, or create a reviewable proposal row
   - on user acceptance, execute the proposal through the normal CRUD path

3. **Observe**
   - reload the current budget summary after proposal acceptance or rejection
   - record whether the proposal was accepted, rejected, or failed as stale/invalid
   - capture what effect the action had on warning states, caps, and remaining income

4. **Adapt**
   - if the proposal is rejected, store the rejection reason
   - include that rejection outcome in later prompt context
   - if the result is stale or invalid, return a corrective reply rather than silently failing

This should not only exist in code; it should also be shown in the report and demo.

## 12.2 Evidence needed to prove the agentic loop

For Interim 0, the feature should produce concrete evidence for each stage:

| Stage | Evidence to capture |
|---|---|
| Plan | prompt builder source, example context payload, screenshot/log of a chat request |
| Act | proposal card screenshot, accept/reject action, backend route description |
| Observe | updated summary after apply, recorded proposal status, health/result output |
| Adapt | rejection reason storage, follow-up response, explanation in report |

## 13. Testing plan

## 13.1 Backend tests

Add tests for:

- advice responses
- proposal responses
- fallback when Ollama is unavailable
- invalid model JSON
- unsupported target types
- missing detail clarification
- accept proposal applies exactly one write
- reject proposal stores reason and decision time
- stale proposal refusal

Take testing inspiration from:

- `janelle/test/test_chat.py`
- `sophia/test/test_chat_apply_service_path.py`
- `sophia/test/test_chat_proposal_honesty.py`

## 13.2 Database tests

Add tests for:

- `chat_messages` CRUD
- proposal status transitions
- rejection reason storage
- applied proposal persistence rules

## 13.3 Frontend tests

Extend the current static frontend regression to assert presence of:

- chat panel
- chat form
- proposal list
- accept/reject actions
- chip prompts

If time allows, add one small backend route test that proves the returned payload shape expected by the frontend.

## 14. Docker, compose, and environment changes

If Ollama is already part of the shared compose stack, Budget Coach should reuse it rather than defining its own AI container.

Needed changes may include:

- backend config wiring for Ollama URL and chosen model names
- compose environment variables for the Budgets backend
- health reporting that includes AI availability

Recommended:

- add Ollama status to `ethan/backend/app.py` health output
- document which approved model Budget Coach uses for:
  - chat interpretation
  - coaching advice

The report should explicitly name the selected approved model and explain why it was chosen.

## 15. Agentic workflow and evidence plan

Interim 0 also cares about the AI development and review workflow, not just the feature itself.

Budget Coach should prepare evidence for:

- prompts used for the feature
- validation and fallback strategy
- human approval gate
- example transcript of a proposal being accepted or rejected
- Plan → Act → Observe → Adapt narrative

Use the mindset shown in `sophia/agentic_loop/README.md`:

- keep evidence explicit
- record what the AI observed
- record what changed
- keep outputs inspectable rather than implied

Suggested evidence artefacts for `ethan/`:

- one short AI architecture note
- one prompt asset document or prompt source file reference
- one screenshot of:
  - advice reply
  - proposal card
  - accepted change reflected in the dashboard

## 15.1 Recommended report mapping to the rubric

The final write-up for this feature should explicitly address the marking criteria rather than assuming the evidence speaks for itself.

Recommended mapping:

| Rubric area | Budget Coach AI chat evidence |
|---|---|
| Project Setup | `ethan/` service structure, compose integration, shared shell route, CI workflow |
| Service Implementation | working frontend chat panel, backend chat endpoints, database-backed proposal/chat storage |
| AI-Mode Integration | Ollama call path, selected approved model, fallback behavior |
| Agentic AI Workflow | Plan → Act → Observe → Adapt explanation with example run |
| Prompt Engineering and Context Management | prompt builder, schema validation, rejection-feedback context |
| DevOps and GitHub Actions | Budgets workflow passing after chat changes |
| Docker Compose Integration | chat working through the composed stack |
| Working Software | live advice + proposal acceptance/rejection flow |
| Technical Report | screenshots, architecture, prompt evidence, known issues |
| Project Demonstration | demo of chat question, proposal, approval, and resulting budget change |

## 15.2 Known limitations section to prepare in advance

The report should honestly note likely Interim 0 limitations such as:

- only one proposal handled at a time
- compact recent-history window rather than unlimited context
- fallback response when Ollama is unavailable or emits invalid JSON
- limited supported action types in the first release
- no autonomous writes without user approval by design

These are acceptable limitations if they are clearly documented and justified.

## 16. Recommended minimum deliverable for Interim 0

To satisfy Interim 0 strongly without over-scoping, the minimum high-value AI deliverable should be:

1. AI advice for budget questions
2. AI proposal generation for create/update budget-line requests
3. reviewable proposal cards
4. accept/reject workflow
5. stored proposal history and chat history
6. Ollama-backed integration documented and demonstrated

If those are working, Budget Coach will have:

- real AI-mode integration
- strong evidence for prompt engineering and context management
- a clear agentic loop story
- a safe, assessable human-in-the-loop design

## 17. Recommended next implementation sequence

The next work should be tackled in this order:

1. add backend AI config and Ollama client
2. add `chat_messages` persistence
3. implement advice-only `/api/chat`
4. implement structured proposal generation
5. implement accept/reject/apply flow
6. replace the frontend AI placeholder with the real chat panel
7. add evidence and screenshots for the report

That order gives the fastest path to a demonstrable Interim 0 outcome while minimising risk.

## 18. Definition of done for Interim 0

This chat feature should only be considered ready for Interim 0 when all of the following are true:

1. the Budgets frontend shows a working chat panel inside the shared application
2. the Budgets backend successfully calls Ollama with an approved model
3. advice responses work against the selected budget month
4. at least one proposal type can be created from natural language
5. the user can accept or reject the proposal before any data is changed
6. accepted proposals update the real budget data through existing CRUD logic
7. proposal and chat history are persisted or otherwise demonstrable
8. targeted tests cover the chat path and proposal workflow
9. Docker Compose and the Budgets workflow still pass
10. the report/demo artefacts exist for AI integration, prompt design, and the agentic loop
