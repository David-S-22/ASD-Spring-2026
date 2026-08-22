# Schema adoption

Additive columns/tables this feature introduced to the bills schema, for anyone reviewing or extending it.

- `bills.end_date` — nullable date; a bill/subscription with an end_date stops projecting occurrences and is reported as "paid, Ended {date}" once it's passed.
- `bills.source` — flags where a bill came from: `manual`, `f3_handoff`, `f4_handoff`, or `chat`. **Flagged loudest**: `f4_handoff` rows are created with `confirmed_at=NULL` and surface a "Confirm this?" prompt until the user acts on them.
- `bills.confirmed_at` — nullable date; distinct from `created_at`, marks when the user actually confirmed a bill (used for the "barely using" chat question and the confirm-prompt above).
- `chat_messages` — new table backing the Ask Tally chat history and its audit trail (`op_json`, `applied`).
- `bills.exclude_from_plan` (decision D, added 22 Aug 2026) — `INTEGER NOT NULL DEFAULT 0`; seeded `1` for Rent only. The calendar card's month breakdown is the *only* consumer that filters on it (bills with it set never enter that particular `month_breakdown()` call); the chat "total" answer and `/api/upcoming`'s `monthly_committed_cents` keep including everything, unfiltered. Never matched on the bill's name — it's an explicit flag, not a "Rent" string check.
