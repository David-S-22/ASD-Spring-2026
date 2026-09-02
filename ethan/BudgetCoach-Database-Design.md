# Budget Coach Database Design

## Purpose of this document

This is a **living design document** for the Budget Coach database microservice. It explains what each table is for, how the tables relate to each other, and the business meaning behind those relationships.

This file should be **actively updated whenever the schema, table purposes, field meanings, or table relationships change**.

## Database role in the system

The Budget Coach database service is a Flask application that owns the Budgets feature's SQLite schema and exposes it through HTTP CRUD endpoints. Its job is to:

- store budget data for each month
- store category-level budget rules
- store expected future spending items
- store AI-generated coaching proposals and decision history

This service should **not** contain budgeting calculations, frontend logic, or AI prompting logic. It is the persistence layer for the feature.

## Core design idea

The schema should be centred around **one monthly budget record**. That parent budget then has:

- many category budget lines
- many planned future spending events
- many AI coaching proposals

So the overall model is:

`budget -> budget lines + planned events + coach proposals`

## Canonical table definitions

These are the current written definitions that implementation should follow:

- `budgets (id PK, month, declared_income, status)`
- `budget_lines (id PK, budget_id FK -> budgets.id, category_id, category, warn_at, hard_cap)`
- `planned_events (id PK, budget_id FK -> budgets.id, date, label, category, est_low, est_high, source, status)`
- `coach_proposals (id PK, budget_id FK -> budgets.id, proposal_json, rationale, status, decided_at)`

## Current agreed design decisions

These decisions are now part of the intended implementation unless they are later revised:

1. all money values are stored as integers
2. all primary keys use GUID values
3. `month` uses `YYYY-MM`
4. there is only one budget per month
5. budget lines should use categories from the transactions service, storing the transaction `category_id` plus the resolved category name
6. deleting a budget should cascade delete linked `budget_lines`, `planned_events`, and `coach_proposals`
7. all fields may be null for now except primary keys and foreign keys

## Table: `budgets`

### Purpose

`budgets` stores the top-level budget for a single month.

One row means:

> "This is the user's budget for a specific month."

### Main fields

- `id`
- `month`
- `declared_income`
- `status`
- `created_at`
- `updated_at`

### Field meaning

- `id`: primary key and unique identifier for the monthly budget
- `month`: the month this budget applies to, such as `2026-09`
- `declared_income`: the user's income for that month
- `status`: lifecycle state such as `draft`, `active`, or `closed`
- `created_at` / `updated_at`: audit fields for CRUD and reporting

### What this table is used for

This table is the **anchor** for the entire feature. It is used to:

- create a new monthly budget
- load the user's current budget
- separate one month's budget from another
- provide the parent record for all category lines, planned events, and coach proposals

### Recommended rules

- only one budget per month
- `declared_income` is stored as an integer amount
- `month` uses the `YYYY-MM` format

## Table: `budget_lines`

### Purpose

`budget_lines` stores the category-level budget rules inside a monthly budget.

One row means:

> "For this budget, this category has a warning level and a hard cap."

### Main fields

- `id`
- `budget_id`
- `category_id`
- `category`
- `warn_at`
- `hard_cap`
- `created_at`
- `updated_at`

### Field meaning

- `id`: primary key and unique identifier for the budget line
- `budget_id`: foreign key linking the line to a row in `budgets`
- `category_id`: category identifier from the transactions service
- `category`: resolved spending category name from the transactions service, such as groceries or transport
- `warn_at`: threshold where the app should begin warning the user
- `hard_cap`: maximum intended amount for the category
- `created_at` / `updated_at`: audit fields

### What this table is used for

This table is used to:

- define category budgets for a month
- compare actual spending against target limits
- drive progress bars and warning colours in the UI
- support AI suggestions about reallocating budget amounts

### Relationship

`budgets` -> `budget_lines` is **one-to-many**.

That means:

- one monthly budget can contain many categories
- each budget line belongs to exactly one monthly budget

### Recommended rules

- category ids should be unique within one budget
- `warn_at` is stored as an integer amount
- `hard_cap` is stored as an integer amount
- `warn_at <= hard_cap`

## Table: `planned_events`

### Purpose

`planned_events` stores expected or future spending that has not happened yet but should still affect the user's budget outlook.

One row means:

> "This upcoming or predicted spending item should be considered when forecasting the month."

### Main fields

- `id`
- `budget_id`
- `date`
- `label`
- `category`
- `est_low`
- `est_high`
- `source`
- `status`
- `created_at`
- `updated_at`

### Field meaning

- `id`: primary key and unique identifier for the planned event
- `budget_id`: foreign key linking the event to the relevant monthly budget
- `date`: expected date of the event
- `label`: short human-readable description
- `category`: the budget category affected by the event
- `est_low`: lower end of the expected cost range
- `est_high`: upper end of the expected cost range
- `source`: where the event came from, such as `user` or `predicted`
- `status`: lifecycle state such as `planned`, `confirmed`, or `cancelled`
- `created_at` / `updated_at`: audit fields

### What this table is used for

This table is used to:

- let the user add upcoming spending to the month
- let the system store predicted future spending
- improve the budget forecast before money is actually spent
- give the AI richer context when generating advice

### Relationship

`budgets` -> `planned_events` is **one-to-many**.

That means:

- one monthly budget can have many future or predicted spending items
- each planned event belongs to exactly one monthly budget

### Logical relationship to `budget_lines`

There may not need to be a direct foreign key from `planned_events` to `budget_lines`, but there is still an important business relationship:

- the `category` on a planned event should normally match a category in `budget_lines`
- the backend uses that category to decide which budget line is affected

So even without a direct FK, a planned event still has a meaningful link to one category rule in the same budget.

### Recommended rules

- `est_low` is stored as an integer amount
- `est_high` is stored as an integer amount
- `est_low <= est_high`
- `source` should be constrained to known values
- `status` should be constrained to known values

## Table: `coach_proposals`

### Purpose

`coach_proposals` stores AI-generated advice and suggested changes in a way that the user can review before anything is applied.

One row means:

> "The AI recommends this change for this monthly budget, and here is the user's decision on it."

### Main fields

- `id`
- `budget_id`
- `proposal_json`
- `rationale`
- `status`
- `rejection_reason`
- `decided_at`
- `created_at`

### Field meaning

- `id`: primary key and unique identifier for the proposal
- `budget_id`: foreign key linking the proposal to a monthly budget
- `proposal_json`: structured proposed change payload
- `rationale`: explanation of why the AI suggested the change
- `status`: state such as `proposed`, `accepted`, or `rejected`
- `rejection_reason`: why the user rejected the suggestion
- `decided_at`: when the user accepted or rejected it
- `created_at`: when the proposal was generated

### What this table is used for

This table is used to:

- store AI coaching suggestions before they are applied
- support the accept/reject review flow
- preserve an audit trail of AI decisions
- feed rejection feedback into later prompts

### Relationship

`budgets` -> `coach_proposals` is **one-to-many**.

That means:

- one budget can have many coaching proposals over time
- each proposal belongs to exactly one monthly budget

### Logical relationship to other tables

`coach_proposals` usually refers to changes that affect `budget_lines` or `planned_events`, but it should not replace those tables.

The intended design is:

- the AI generates a proposal
- the proposal is stored in `coach_proposals`
- the user reviews it
- the backend applies the real change to `budget_lines` or `planned_events` only after approval

This separation is important because the AI should **suggest**, not directly mutate production data.

### Recommended rules

- `status` should be constrained to `proposed`, `accepted`, or `rejected`
- `rejection_reason` should only be present when the status is `rejected`
- `decided_at` should only be set once a decision is made

## Enum values and meanings

These fields should behave like controlled enums even if they are initially stored as strings in Flask/SQLite models.

### `budgets.status`

Suggested values:

- `draft`: the monthly budget exists but is still being prepared or edited
- `active`: the budget is the live budget for that month
- `closed`: the month is finished and the budget is no longer being actively changed

Meaning:

This field tells the system where the monthly budget is in its lifecycle. It matters for frontend behaviour, edit permissions, and later reporting.

### `planned_events.source`

Suggested values:

- `user`: the planned event was entered directly by the user
- `predicted`: the planned event was created by system logic or AI prediction

Meaning:

This field explains where the planned event came from. It is useful for auditability and for presenting the event differently in the UI.

### `planned_events.status`

Suggested values:

- `planned`: the event is expected but has not happened yet
- `confirmed`: the event has been confirmed by the user or converted into a more certain item
- `cancelled`: the event is no longer expected to happen

Meaning:

This field tells the system whether the event should still affect forecasts. For example, `planned` and `confirmed` may still count toward forecast pressure, while `cancelled` should not.

### `coach_proposals.status`

Suggested values:

- `proposed`: the AI suggestion exists and is waiting for user review
- `accepted`: the user approved the suggestion and the backend may apply or has applied it
- `rejected`: the user declined the suggestion

Meaning:

This field controls the review workflow. It is the key rule that separates AI suggestions from real data changes.

## `proposal_json` purpose and example

### Why `proposal_json` exists

`proposal_json` exists because the AI should not directly mutate real budget data. Instead, the AI produces a structured proposal that can be:

- stored
- displayed to the user
- accepted or rejected
- applied later by backend logic
- audited in the report or logs

This keeps the system safe and explainable. The proposal is the suggested change, not the change itself.

### Example meaning

If the user asks:

> "Update groceries to 150-200 and add a dinner out this Friday for about 40 to 60"

the AI should not immediately write to `budget_lines` or `planned_events`. It should instead produce a proposal payload that describes the intended actions.

### Example `proposal_json`

```json
{
  "proposal_type": "chat_edit",
  "operations": [
    {
      "action": "update_budget_line",
      "target": {
        "budget_id": "4e1f4a2c-2dc4-4df6-b525-2bc9db9159b2",
        "category": "groceries"
      },
      "fields": {
        "warn_at": 15000,
        "hard_cap": 20000
      }
    },
    {
      "action": "create_planned_event",
      "target": {
        "budget_id": "4e1f4a2c-2dc4-4df6-b525-2bc9db9159b2"
      },
      "fields": {
        "date": "2026-09-04",
        "label": "Dinner out",
        "category": "eating out",
        "est_low": 4000,
        "est_high": 6000,
        "source": "user",
        "status": "planned"
      }
    }
  ],
  "user_confirmation_message": "Update groceries to 150-200 and add a planned dinner out for 40-60?",
  "reasoning_summary": "Groceries was adjusted directly from the request, and the planned event was added so the forecast includes expected discretionary spending."
}
```

### What this example means

- the AI is proposing two actions
- nothing has been applied yet
- the user can review the proposal first
- if accepted, the backend converts the operations into real writes to `budget_lines` and `planned_events`
- if rejected, the proposal remains in `coach_proposals` with status `rejected`

## Relationship summary

### Direct table relationships

1. `budgets` -> `budget_lines` = one-to-many
2. `budgets` -> `planned_events` = one-to-many
3. `budgets` -> `coach_proposals` = one-to-many

### Logical business relationships

1. `planned_events.category` should align with a category in `budget_lines` for the same budget
2. `coach_proposals.proposal_json` may describe changes to `budget_lines` or `planned_events`
3. accepted proposals may result in writes to other tables, but proposals remain separate records for auditability

## Meaning of the schema as a whole

The schema models the month like this:

- `budgets` = the month-level budget container
- `budget_lines` = the category rules inside that month
- `planned_events` = the upcoming spending signals affecting that month
- `coach_proposals` = the AI's advice and change suggestions for that month

In plain English:

> one month has many budget categories, many expected spending items, and many AI-generated suggestions about how the month should be adjusted

## Recommended implementation notes

Before implementing the Flask models, the following decisions should remain part of the design:

1. include `id` on every table
2. include `created_at` and `updated_at` where ongoing edits matter
3. add `budget_id` to `planned_events`
4. keep the database service focused on persistence and validation only
5. keep calculations and AI orchestration in the backend/API service

## Change management note

Whenever the schema changes, this document should be updated to reflect:

- added or removed fields
- new validation rules
- changed table purposes
- changed relationships
- new status values or enum meanings
- changes to how proposals are applied
