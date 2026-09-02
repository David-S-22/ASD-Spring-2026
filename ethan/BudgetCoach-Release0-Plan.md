# Budget Coach Release 0 Plan

## 1. Purpose

This document turns the Release 0 brief into a practical implementation plan for the **Budget Coach** feature. It focuses on what still needs to be built so the feature is not just present in isolation, but integrated into the shared team application and assessable under the Release 0 marking criteria.

## 2. What is already in place

The `ethan` folder already has a basic service scaffold:

- `ethan/frontend` contains a minimal nginx-based frontend container template.
- `ethan/backend` contains a minimal Flask backend container template.
- `ethan/database` contains a minimal Flask database container template.
- `ethan/test` contains basic pytest health-route tests.
- `docker-compose.yml` already includes `budgets-frontend`, `budgets-backend`, and `budgets-db`.
- `.github/workflows/budgets-ci.yml` already runs Budgets tests and container build/health checks.

This means the container and CI foundation exists, but the actual **Budget Coach feature** is still largely unimplemented.

## 3. What still needs to be done

To satisfy the feature brief and the Release 0 rubric, the following work remains.

### 3.1 Frontend microservice

Build a working frontend for Budget Coach with:

- a monthly budget editor
- category rows showing `warn_at` and `hard_cap`
- spending progress bars per category
- a week-ahead planner for upcoming spending
- a chat box for plain-English budget requests
- proposal cards that require explicit user acceptance before any AI-suggested change is saved
- links from the shared HTMX landing page into the Budget Coach frontend

### 3.2 Backend/API microservice

Build the real backend logic for:

- CRUD endpoints for budgets
- CRUD endpoints for budget lines
- CRUD endpoints for planned events
- coach proposal generation and accept/reject handling
- budget calculations in normal code
- chat-to-structured-operation conversion using AI
- cross-feature API integration with the Statement API
- a validation endpoint other features can call, such as "would this purchase put me over budget?"

### 3.3 Database microservice

Implement the SQLite-backed database API for:

- `budgets`
- `budget_lines`
- `planned_events`
- `coach_proposals`

The database service must expose CRUD via HTTP and remain the only owner of its SQLite file and schema.

### 3.4 AI integration

Implement AI-Mode with Ollama and approved open-source models:

- use an approved LLM for coaching advice
- use an approved LLM for chat intent parsing
- validate all AI outputs against a strict JSON schema
- record rejected suggestions and reuse that feedback in later prompts
- document prompt assets and context management choices for the report

### 3.5 Integration and evidence

Complete the integration items needed for assessment:

- connect the feature to the team's shared frontend entry point
- ensure Docker Compose runs the Budgets feature with the group system
- ensure GitHub Actions remain green
- capture screenshots, terminal logs, workflow runs, and prompt records for the technical report
- prepare a clear demo script for the showcase video

## 4. Release 0 interpretation for Budget Coach

To score well, Budget Coach must be delivered as an **integrated feature** rather than a standalone prototype.

### 4.1 Minimum viable Release 0 outcome

Budget Coach should demonstrate all of the following:

1. A user can open the Budget Coach UI from the shared index.
2. A user can create, read, update, and delete budget data through the Budgets frontend, backend, and database services.
3. The backend reads transaction history from another team's **Statement API** rather than from another team's SQLite database.
4. The backend can call Ollama with an approved model and return structured coaching or structured proposed edits.
5. AI-generated changes are never auto-applied; the user must explicitly accept them.
6. The feature runs through the shared Docker Compose configuration.
7. The Budgets GitHub Actions workflow proves the feature still builds and passes validation.

If any of these are missing, the feature risks losing marks under working software, AI integration, Docker Compose integration, DevOps, and project setup.

## 5. Proposed architecture

## 5.1 Frontend

Recommended responsibilities:

- Render the Budget Coach dashboard.
- Fetch budget summaries from the backend API.
- Render progress bars using backend-calculated values.
- Submit create/update/delete actions to the backend.
- Show AI proposals as pending cards.
- Allow the user to accept or reject each proposal.

Suggested pages or sections:

- monthly overview
- budget lines editor
- planned events editor
- coach insights panel
- budget chat panel

HTMX is a good fit if the team is already using server-rendered fragments elsewhere. If the repo is moving toward simple HTML plus fetch calls, match the existing team pattern instead of inventing a new frontend stack.

## 5.2 Backend/API

Recommended responsibilities:

- Expose frontend-facing endpoints.
- Own budgeting calculations.
- Aggregate data from:
  - Budgets database API
  - Statement API from the transactions feature
  - Ollama AI service
- Enforce validation and workflow rules.
- Translate accepted frontend actions into database API calls.

The backend should never read another team's database directly. It must call the other feature's API only.

## 5.3 Database API

Recommended responsibilities:

- Own the SQLite schema.
- Expose CRUD endpoints over HTTP.
- Return JSON DTOs only.
- Perform no AI logic.
- Keep data rules simple and explicit.

## 6. Data model plan

### 6.1 `budgets`

Suggested fields:

- `id` as the primary key
- `month` such as `2026-09`
- `declared_income`
- `status` such as `draft`, `active`, `closed`
- `created_at`
- `updated_at`

Rules:

- one budget per month
- `id` uses an integer primary key
- `declared_income` should be stored as an integer amount
- `month` should use the `YYYY-MM` format

### 6.2 `budget_lines`

Suggested fields:

- `id` as the primary key
- `budget_id` as a foreign key to `budgets.id`
- `category_id` using the transactions service category identity
- `category`
- `warn_at`
- `hard_cap`
- `created_at`
- `updated_at`

Rules:

- `warn_at <= hard_cap`
- `id` uses an integer primary key
- `warn_at` and `hard_cap` should be stored as integer amounts
- category ids should be unique within a budget
- budget lines should be selected from the transactions service categories rather than free-typed

### 6.3 `planned_events`

Suggested fields:

- `id` as the primary key
- `budget_id` as a foreign key to `budgets.id`
- `date`
- `label`
- `category`
- `est_low`
- `est_high`
- `source` with values like `user` or `predicted`
- `status` with values like `planned`, `confirmed`, `cancelled`
- `created_at`
- `updated_at`

Rules:

- `id` uses an integer primary key
- `est_low <= est_high`
- `est_low` and `est_high` should be stored as integer amounts
- each planned event belongs to a budget through `budget_id`
- category values are free text, but should align with existing budget lines for the same budget
- source and status should be constrained to known values

### 6.4 `coach_proposals`

Suggested fields:

- `id` as the primary key
- `budget_id` as a foreign key to `budgets.id`
- `proposal_json`
- `rationale`
- `status` with values `proposed`, `accepted`, `rejected`
- `rejection_reason`
- `decided_at`
- `created_at`

Rules:

- `id` uses an integer primary key

Rules:

- accepted proposals should be traceable to the applied change
- rejected proposals should preserve the user reason for later prompts
- the table should store proposal data separately from the real budget tables so AI suggestions are reviewable before application

## 7. API plan

## 7.1 Backend-facing frontend endpoints

Suggested initial endpoints:

- `GET /budget/current`
- `POST /budget`
- `PATCH /budget/<id>`
- `DELETE /budget/<id>`
- `GET /budget/<id>/lines`
- `POST /budget/<id>/lines`
- `PATCH /budget-lines/<id>`
- `DELETE /budget-lines/<id>`
- `GET /budget/<id>/planned-events`
- `POST /budget/<id>/planned-events`
- `PATCH /planned-events/<id>`
- `DELETE /planned-events/<id>`
- `POST /coach/generate`
- `POST /coach/proposals/<id>/accept`
- `POST /coach/proposals/<id>/reject`
- `POST /chat/interpret`
- `POST /validation/purchase-impact`

## 7.2 Database API endpoints

The backend should call the Budgets database microservice over HTTP for:

- budgets CRUD
- budget lines CRUD
- planned events CRUD
- coach proposals CRUD

Keep the database API resource-oriented and narrow. The backend should own orchestration and cross-service logic.

## 8. AI implementation plan

## 8.1 Coaching flow

Goal:

- produce advice plus structured suggested reallocations for the current budget

Inputs to the coaching prompt:

- current month
- income
- budget lines
- actual spending by category
- planned events
- prior rejected proposal reasons

Expected output:

- strict JSON object with:
  - summary advice
  - detected overspend or risk areas
  - suggested budget changes
  - rationale

Implementation rules:

- validate response against a schema before use
- if schema validation fails, surface an explicit error
- store valid suggestions in `coach_proposals`
- only apply changes after user acceptance

## 8.2 Chat flow

Goal:

- convert plain-English instructions into exactly one structured operation

Examples:

- create budget line
- update budget line
- delete budget line
- create planned event
- update planned event
- delete planned event

Expected output:

- strict JSON with:
  - `operation_type`
  - `target_resource`
  - `fields`
  - `user_confirmation_message`

Rules:

- do not directly apply the AI result
- show it back to the user as a proposal
- apply it only after acceptance

## 8.3 Special delete-category workflow

If the user tries to delete a category that already has spending this month:

1. Ask which category should absorb those records.
2. Ask what to do with the freed budget:
   - spread across the rest of this month
   - add to next month's budget
   - set aside

This is important because it is explicitly called out in the feature description and is likely to be examined in the demo.

## 9. Cross-feature integration plan

The feature description already makes an important design choice: **transaction history comes from the Statement API**.

This should be implemented and documented as a clear architecture rule:

- Budget Coach does not read another feature's SQLite file.
- Budget Coach does not query another feature's tables directly.
- Budget Coach only consumes transaction data through the other team's public API.

Needed work:

1. Identify the exact statement-service endpoint for transaction history.
2. Agree a response shape with the teammate owning that service.
3. Build a backend adapter client in the Budgets backend.
4. Handle unreachable-service and malformed-response failures explicitly.

## 10. Docker and Compose plan

The current compose entries are placeholders. They now need to support the real app.

Required updates likely include:

- real backend and database dependencies
- environment variables for:
  - database API URL
  - Statement API URL
  - Ollama base URL
  - selected model names
- optional shared network naming only if the team is already standardising it
- mounted data volume for the Budgets SQLite file

Compose should be able to start:

- Budgets frontend
- Budgets backend
- Budgets database
- shared AI services
- other team services needed for integration

## 11. GitHub Actions plan

The existing `budgets-ci.yml` should evolve from scaffold validation into feature validation.

Recommended stages:

1. install backend, database, and test dependencies
2. run targeted tests
3. optionally run integration tests that mock the Statement API and Ollama responses
4. build Budgets containers
5. bring up Budgets services
6. run endpoint smoke tests

Recommended test coverage:

- backend CRUD endpoint tests
- database API CRUD endpoint tests
- validation rule tests
- AI response schema validation tests
- accept/reject proposal workflow tests

## 12. Detailed implementation plan

This section breaks the work into implementation parts so the feature can be built in a sensible order and demonstrated at every stage.

### Part 1: lock the contracts first

**Goal**

Define the shapes of the data and API calls before building logic, so the frontend, backend, and database services can progress without rework.

**What to do**

1. Define the DTOs for budgets, budget lines, planned events, and coach proposals.
2. Define request and response JSON for create, read, update, and delete actions.
3. Define the backend-to-database API contract.
4. Define the Statement API contract Budget Coach depends on.
5. Define the exact JSON schema expected back from Ollama for coaching and chat interpretation.

**Instructions**

- Create one short contract note or table for each resource.
- Keep field names consistent across frontend, backend, database, tests, and prompts.
- Decide now which fields are required, optional, computed, or AI-generated.
- Identify validation rules early, especially `warn_at <= hard_cap` and `est_low <= est_high`.
- Confirm the transaction categories and date formats expected from the Statement API.

**Output of this step**

- stable JSON shapes
- stable field names
- agreement on external dependencies before implementation starts

### Part 2: build the database microservice

**Goal**

Implement the Budgets database service as the single owner of Budget Coach persistence.

**What to do**

1. Add the persistence layer and create the SQLite schema.
2. Implement models for `budgets`, `budget_lines`, `planned_events`, and `coach_proposals`.
3. Add CRUD endpoints for each resource.
4. Add validation and relationship rules.
5. Add tests for database routes and expected failure cases.

**Instructions**

- Start with the `budgets` table, then add `budget_lines`, then `planned_events`, then `coach_proposals`.
- Enforce foreign keys and uniqueness where needed, especially category uniqueness within a budget.
- Return JSON responses only; do not put frontend or AI logic in this service.
- Keep route responsibilities narrow: this service stores and returns data, nothing more.
- Add tests for both happy paths and invalid input, such as negative amounts or missing fields.

**Output of this step**

- real Budgets database API
- working SQLite schema
- tested CRUD foundation

### Part 3: build backend budgeting logic

**Goal**

Turn the backend into the orchestration layer that calculates budget state and coordinates with other services.

**What to do**

1. Add a backend service layer for budget calculations.
2. Add an HTTP client for the Budgets database API.
3. Add an HTTP client for the Statement API.
4. Implement backend CRUD endpoints that call the database API.
5. Implement computed summary endpoints for the frontend.
6. Implement the cross-feature purchase-impact validation endpoint.

**Instructions**

- Put all spending maths here, not in the AI prompt and not in the database service.
- Fetch transaction history through the Statement API only, never through direct database access.
- Compute totals by category, warning-state flags, cap breaches, remaining budget, and planned-event impact.
- Create a summary endpoint that gives the frontend one joined view of the month instead of forcing many small calls.
- Make errors explicit when the Statement API is unavailable or returns invalid data.

**Output of this step**

- working backend orchestration layer
- reusable budget calculations
- frontend-ready summary responses

### Part 4: implement starter-budget generation

**Goal**

Generate the first realistic budget from transaction history so the feature is useful from the first run.

**What to do**

1. Detect when the user has no current-month budget.
2. Pull recent transactions from the Statement API.
3. Group spending by category.
4. Produce starter `warn_at` and `hard_cap` values.
5. Save the starter budget through the Budgets database API.

**Instructions**

- Choose a simple baseline rule, such as using recent spending plus a safety margin.
- Keep the first version deterministic and explainable rather than overly clever.
- Store the generated budget as a normal budget so the user can edit it immediately.
- Document the starter-budget logic in the report because it shows design reasoning beyond raw CRUD.

**Output of this step**

- automatic first-run budget creation
- realistic default budget values

### Part 5: implement coaching AI flow

**Goal**

Use Ollama and an approved model to produce budget advice and structured proposed reallocations.

**What to do**

1. Add an Ollama client wrapper in the backend.
2. Create a coaching prompt template.
3. Build a strict response schema for coaching output.
4. Validate AI output before using it.
5. Store valid coaching suggestions as `coach_proposals`.
6. Add accept and reject actions for those proposals.

**Instructions**

- Send only the context the model actually needs: month, budget lines, spend totals, planned events, and prior rejection reasons.
- Require JSON output and reject anything that does not match the schema exactly.
- Store both the proposal payload and the rationale so it can be shown in the UI and report.
- When a user rejects a proposal, save the reason and include it in future coaching prompts.
- Do not let the model mutate data directly; it can only propose changes.

**Output of this step**

- working coaching endpoint
- stored AI proposals
- clear human approval workflow

### Part 6: implement chat interpretation AI flow

**Goal**

Let the user describe budget changes in plain English, while keeping control over what is actually saved.

**What to do**

1. Create a chat interpretation prompt template.
2. Define a schema for exactly one structured operation at a time.
3. Convert the model result into a proposal card rather than applying it directly.
4. Handle category-delete follow-up questions when spending already exists.
5. Apply the change only after user confirmation.

**Instructions**

- Limit the model to one operation per request so the UI and backend stay predictable.
- Convert ambiguous requests into follow-up questions instead of guessing.
- For delete-category operations with current-month spend, enforce the two required follow-ups from the feature brief.
- Reuse the same proposal storage approach as coaching where possible, so the audit trail is consistent.
- Test invalid, vague, and conflicting inputs, not just clean examples.

**Output of this step**

- safe natural-language budget editing
- user-approved application of AI-suggested actions

### Part 7: build the frontend experience

**Goal**

Create a working Budget Coach UI that exposes CRUD, summaries, planning, and AI proposal review.

**What to do**

1. Build the dashboard shell.
2. Add a monthly summary section with income, totals, and status indicators.
3. Build the budget-line editor.
4. Build the planned-events editor.
5. Build the coach insights panel.
6. Build the chat input and proposal review flow.
7. Connect the UI to backend endpoints.

**Instructions**

- Start with simple layouts and get the data flow working before polishing appearance.
- Render progress bars from backend-computed values, with amber above warning and red above cap.
- Make create, update, and delete actions obvious and easy to demonstrate.
- Show AI suggestions as pending cards with accept and reject actions.
- Preserve enough detail in the UI to explain what the AI suggested and why.

**Output of this step**

- working user-facing Budget Coach microservice
- demonstrable CRUD and AI flows

### Part 8: integrate with the shared team application

**Goal**

Make sure the feature is assessable as part of the group application rather than as an isolated student service.

**What to do**

1. Link Budget Coach from the shared HTMX index.
2. Apply the shared team theme or styling conventions.
3. Wire real service URLs into Docker Compose.
4. Confirm the backend can reach the Statement API and Ollama service in compose.
5. Confirm other features can call the purchase-impact endpoint.

**Instructions**

- Treat integration as a feature requirement, not a final cleanup step.
- Use service names in compose for internal communication between containers.
- Verify the team entry point can navigate to the Budgets frontend container.
- Document the cross-feature API-only rule in both code and report material.
- Work with the teammate owning the Statement API early, because this dependency can block the demo.

**Output of this step**

- integrated group-ready feature
- no risk of being marked as non-integrated work

### Part 9: strengthen Docker and CI

**Goal**

Make the feature reliable in the repository's shared DevOps workflow.

**What to do**

1. Update Dockerfiles with real dependencies and startup commands.
2. Add any required environment variables to compose and workflow definitions.
3. Expand `budgets-ci.yml` from health checks to feature validation.
4. Add integration tests or smoke tests for key endpoints.
5. Keep the workflow focused on Budgets-owned paths and dependencies.

**Instructions**

- Keep the CI workflow small but meaningful: run tests, build containers, and verify core routes.
- Add tests that cover the acceptance flow, schema validation, and critical CRUD paths.
- Mock Ollama and Statement API calls in tests unless the team already has a stable integration environment.
- Use compose-based checks to prove the feature runs in containers, not just from local Python.

**Output of this step**

- stronger proof for DevOps and Docker criteria
- better protection against integration regressions

### Part 10: capture report and showcase evidence

**Goal**

Collect all evidence while building, instead of leaving documentation until the end.

**What to do**

1. Capture screenshots of the UI and CRUD flows.
2. Capture terminal evidence of compose startup and the agentic loop.
3. Save prompt assets used for coaching and chat interpretation.
4. Save workflow run evidence from GitHub Actions.
5. Prepare architecture diagrams and contribution records.
6. Draft the demonstration sequence for the 10-minute showcase.

**Instructions**

- Save evidence as soon as a step works; do not rely on recreating it later.
- Make sure the demo includes frontend use, backend/API behavior, AI behavior, Docker Compose, and CI.
- Keep one short record of the Plan -> Act -> Observe -> Adapt cycle with real prompts and outputs.
- Record known limitations honestly so the report still looks complete if stretch goals remain unfinished.

**Output of this step**

- report-ready artefacts
- demo-ready feature narrative

## 13. Recommended working order

If you want the shortest path to a working Release 0 feature, build in this order:

1. contracts
2. database service
3. backend calculations and summary endpoints
4. starter-budget generation
5. coaching AI flow
6. chat interpretation AI flow
7. frontend
8. group integration
9. CI and compose hardening
10. report evidence and showcase preparation
## 14. Agentic AI workflow plan

The Release 0 brief requires a visible **Plan -> Act -> Observe -> Adapt** loop.

A practical Budget Coach version could be:

1. **Plan**  
   The backend prepares the monthly budget context, spending totals, planned events, and user feedback history.
2. **Act**  
   The backend asks the LLM for coaching advice or a structured proposed change.
3. **Observe**  
   The backend validates the JSON, compares it with current budget data, and presents the result to the user.
4. **Adapt**  
   The user accepts or rejects the suggestion, and rejection reasons are stored for the next prompt cycle.

This loop should be shown:

- in the implementation
- in terminal or workflow evidence
- in the technical report diagram

## 15. Risks and controls

| Risk | Impact | Control |
|---|---|---|
| Statement API not ready or unstable | Budget coaching cannot calculate realistic spending | Agree early on a fallback mock contract for tests and local development |
| Ollama output is not valid JSON | AI features become unreliable | Enforce schema validation and keep prompts narrow |
| CRUD works locally but not in compose | Integration marks are lost | Test via Docker Compose early, not only with local Flask runs |
| Feature is built but not linked from shared index | Feature may be treated as non-integrated | Prioritise shared-entry integration before polish |
| Too much time spent on AI polish | Core CRUD and integration may remain incomplete | Finish end-to-end CRUD and compose first, then improve prompts |

## 16. Report and demo checklist

To support the technical report and showcase, collect evidence for:

- repository structure
- Budgets architecture diagram
- integrated architecture diagram
- Docker Compose architecture diagram
- DevOps pipeline diagram
- Agentic workflow diagram
- workflow YAML explanation
- passing GitHub Actions runs
- passing Docker Compose run
- frontend screenshots
- backend endpoint evidence
- database CRUD evidence
- Ollama/LLM evidence
- prompt assets
- known issues and limitations
- commit history
- contribution logs
- showcase video URL

## 17. Recommended definition of done

Budget Coach is ready for Release 0 when:

- all three Budgets services are implemented beyond health-check stubs
- CRUD works end-to-end through frontend -> backend -> database API
- transaction history is read from the Statement API
- at least one approved LLM flow works through Ollama
- AI proposals require acceptance before persistence
- shared Docker Compose starts the integrated feature
- Budgets CI passes
- screenshots, logs, and diagrams are ready for the report

## 18. Immediate next build targets

If implementation starts now, the best order is:

1. build the Budgets database schema and CRUD API
2. build the Budgets backend orchestration endpoints and calculations
3. connect the Statement API
4. add Ollama prompt + schema validation
5. build the frontend editor, planner, and proposal flow
6. integrate with shared index, compose, and report evidence
