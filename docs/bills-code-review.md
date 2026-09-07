# Bills feature — code review

Reviewer: Claude (Cowork session for Soph), 2026-09-02, against `main` @ `3164ce8`.
Scope: the Bills feature only — `sophia/frontend`, `sophia/backend`, `sophia/database` — with
emphasis on the Ask Tally chat seam, per the handover plan. Findings marked **[verified]** were
reproduced against a running stack (backend + database + frontend, Ollama stubbed) rather than
inferred from reading.

## Architecture (as found)

The plan assumed a JS SPA with a client cache; the reality is simpler and changes where the bugs
live. The Bills frontend is a static shell (`sophia/frontend/index.html` + `app.js`) over
**HTMX**: every view is server-rendered HTML from `sophia/backend/routes/fragments.py` (`/ui/*`),
and every write route re-renders the bills table, timeline, and calendar as out-of-band swaps.
There is **no client-side cache to invalidate** — "the table updates" means "the response carried
a fresh `#bills-table` fragment", which the existing `/ui/chat/apply` route already does.

The chat is not tool-calling in the usual sense. `services/chat.py:send_message` asks a small
Ollama model (`qwen2.5:3b`) for a single JSON object (`op/entity/id/fields/question/say`),
validated by `ai/schemas.py:validate_chat_response` with one retry (`ai/guard.py`). A returned op
becomes a **preview card** in the chat panel (Confirm / "Keep it"); only `/ui/chat/apply` (or
`/api/chat/apply`) writes. So an approve-before-apply seam already exists — the defects below are
about what that seam lets through, what it tells the user, and what it tells the model afterwards.

Layers: frontend nginx (`:3005`/`:80`) → backend Flask (`:5005`, routes → services → engine) →
bills-db Flask+SQLite (`:6005`, thin validated CRUD). The shared shell (`:3000`) swaps the whole
Bills document into its `#content`, sharing one DOM — OOB swaps still work there **[verified]**.

---

## Critical

### C1. Chat apply bypasses service-layer validation — one bad date bricks the whole Bills tab **[verified]**
`sophia/backend/services/chat.py:200-215` (`apply`): bill create/update/delete call
`bills_db.create_bill / update_bill / delete_bill` (the raw DB client) directly, while the manual
edit path goes through `services/bills.py` (`_clean_payload`: required fields, `amount_cents`
integer coercion, **ISO date validation**) plus `_persist_status_if_drifted`. The DB API
(`sophia/database/app.py:_validate_bill`) checks enums and integer types but **not date format**.

Reproduced: `POST /api/chat/apply` with `fields={"next": "early September"}` returns 200 and
stores `next_billing_date="early September"`; from then on `row_to_bill`'s
`date.fromisoformat` raises, and `/ui/bills`, `/ui/timeline`, `/ui/calendar`, `/api/bills` all
500 until the row is manually repaired. A model paraphrasing a date — exactly what a 3B model
does — can take the tab down. The chat docstring says apply uses "the same CRUD calls a manual
edit uses"; it uses the same *client*, one layer below the checks.

Fix: route chat apply through `bills_service.create_bill / update_bill / delete_bill` (and
`payments_service` for payments), so chat writes obey exactly the invariants manual edits do.
Side benefit: status-cache sync happens on chat writes too.

### C2. The assistant claims changes are done that were never applied — and is never told the outcome **[verified]**
Three mutually reinforcing defects, `services/chat.py` + `ai/chat_prompt.py`:

- The prompt never tells the model its ops are *proposals*. The few-shot `say` values read as
  completed/in-progress actions ("Marking Spotify as ending…", "Adding Disney Plus…"), so the live
  model says "Deleted Netflix — it's gone" while the delete sits unconfirmed in a preview card.
- "Keep it" (reject) is client-side only (`app.js` `dismiss-preview` → `card.remove()`); no
  request is made, nothing is recorded. The model's own "deleted it" message stays in
  `_recent_history` uncorrected — asked "did you delete it?", it says yes while the row is still
  in the table (reproduced end-to-end).
- Apply outcomes are only partially recorded: success writes a generic "Done — change saved." row
  (`chat.py:apply` tail), but a *failed* apply (e.g. deleting an id that doesn't exist) raises
  before any history write — the failure is shown to the user as an error fragment and is
  invisible to the model forever.

This is the reported Bug B (and most of Bug A's *perceived* behaviour — see H1). Fix: proposal
language in the prompt and reply UI; record approve/reject/failure outcomes into `chat_messages`
so the model's next turn reflects reality; never render "done" wording for a pending proposal.

## High

### H1. Validator accepts an op with no entity (or no id/fields) — the change silently evaporates **[verified]**
`ai/schemas.py:validate_chat_response` checks each key independently: `{"op":"create",
"entity":null, "fields":{...}}` passes, but `chat.py:_build_preview` requires both `op` and
`entity`, so it returns `None` — no preview card, no error, while `say` still promises the change.
Same for `op:"update"/"delete"` with `id:null` (the preview renders, and apply then fails with a
raw 404 — see M3). For the user this *is* "the AI said it created the bill but the table never
updated". Small models drop keys routinely; the validator should enforce coherence (create needs
entity+fields; update/delete need entity+id) so the guard's retry/fallback machinery — which
already exists — kicks in instead.

Note the mechanical refresh path is **not** broken: on Confirm, `/ui/chat/apply` returns the
bills table + timeline + calendar as OOB swaps and the table updates without a reload, verified
standalone (:3005) and inside the shared shell (:3000 equivalent). Bug A's fix is honesty +
coherence, not cache plumbing.

### H2. Preview cards show nothing about what will be applied
`templates/chat_reply.html`: the card is two bare buttons. For a delete it does not name the
bill; for an update it shows no before/after; for a create, none of the field values — the user
approves whatever the model happened to emit, sight unseen. Combined with H3 this is how a
hallucinated amount or a wrong-id delete gets applied. The approve/reject surface needs a
human-readable summary and field-level detail (diff for updates, the doomed row for deletes).

### H3. Prompt invites hallucinated field values on create (Bug C)
`ai/chat_prompt.py:BILL_FIELDS` instructs that a create "needs" the full field list and gives no
instruction for the missing-information case, so "add Netflix" yields invented amount/date/
cadence. No few-shot example asks a follow-up question. There's also no deterministic backstop:
if the model invents plausible values, nothing downstream can tell. Fix at three levels: prompt
("only use values the user explicitly provided; if amount, cadence, or first billing date are
missing, set op null and ask"), a few-shot example of asking, and a backend check that refuses to
turn an under-specified create into an appliable proposal (the service-layer required-fields
check from C1 is the last line).

### H4. No idempotency or duplicate guard on chat creates
`chat.py:apply` create path inserts unconditionally; asking twice (or re-Confirming after a
confused exchange, or the model re-proposing after a retry) yields duplicate rows. The Confirm
button is also not disabled while its request is in flight (`hx-disabled-elt` is only on the chat
send button), so a double-click can double-create. Minimum: disable on click + a same-name/
same-amount pending check at proposal time; the suggestions store (planned) gives a natural
place to mark a proposal consumed once applied.

## Medium

### M1. Failed apply leaves no trace in chat history (model side)
Subsumed by C2 but worth its own line for tests: `apply()` writes history only on success. A
tool-result contract should record failure ("bill not found") the model can see.

### M2. `_raise_for_status` can surface raw HTML as an error message
`clients/bills_db.py:_raise_for_status`: for a 4xx whose body isn't JSON (e.g. Flask's HTML 404
for `/bills/None` when the model emits a non-int id — reachable via `_coerce_id` passing strings
through), `message = response.text` puts an HTML document into a `ServiceError` that the UI then
renders into a fragment/toast. Truncate/normalise non-JSON bodies.

### M3. `/ui/chat/apply` parses `fields` with a bare `json.loads`
`routes/fragments.py:chat_apply`: malformed `fields` raises `ValueError` → generic 500 handler.
Harmless today (htmx JSON-stringifies `hx-vals` objects — checked against the vendored
`htmx-2.0.4.min.js`), but a one-line `try/except → ServiceError(400)` makes the contract honest.

### M4. Demo clock vs DB clock skew (Sydney-relevant)
The backend runs on `DEMO_TODAY=2026-08-20`; the DB stamps `created_at` with **real UTC now**
(`database/app.py:_now_date`). Two effects: (a) any newly created bill has
`created_at > DEMO_TODAY`, so `projection._within` drops occurrences that fall before its
`created_at` — a bill added "next charge 3 Sep" on real-day 5 Sep is in the table but missing
from the timeline/calendar; (b) `_now_date` uses UTC, so anything created before ~10am in
Australia/Sydney is stamped with *yesterday's* date, off-by-one for every date comparison above.
Least-surprise fix: stamp `created_at` from the caller (backend, on the demo clock) or default it
server-side from the request payload the way `status`/`source` already work.

### M5. Whitelist lets chat set `amount_cents` directly, in unconverted units
`chat.py:BILL_FIELD_WHITELIST` includes `amount_cents`; the dollars→cents conversion only runs
for the alias key `amount`. A model that emits `amount_cents: 15` for a $15 bill (the exact drift
the file's own comment describes) stores 15 cents silently. Since the prompt asks for dollars,
`amount_cents` should be dropped from the chat whitelist (or converted when it plainly looks like
dollars — but dropping is the honest, narrow move).

## Low

### L1. No auth anywhere; permissive CORS on both Flask apps; sequential ids
`CORS(app)` unrestricted on backend and DB API; the DB API is also published on host port 6005,
so anything on the machine can bypass even the backend's checks. Fine for a uni demo, worth one
line in the README so nobody mistakes it for deployable.

### L2. `/api/chat/history` is dead code for the UI
The panel deliberately opens clean (documented in `fragments.py:_render_chat_panel`); the JSON
history route is unused by any client. Keep or cull, but its existence suggests state the UI
doesn't actually show — cheap confusion for the next reader.

### L3. Accessibility is largely good; two nits
The table region, row menus and modal focus handling are careful (and commented). Nits: the chat
preview card's buttons have no accessible relationship to the message they confirm (a screen
reader hears "Confirm" with no object — H2's summary text fixes this for free), and toasts are
not in an `aria-live` region so outcomes are announced to no one.

### L4. Test suite is strong; gaps map exactly to the bugs above
234 tests pass, and the UI-write and fragment suites are unusually well-argued. Missing: any test
that an op-without-entity response yields an honest reply (H1), that chat updates reject bad
dates (C1 — today the test would fail, correctly), delete tool-result contract on missing ids,
and any record of reject outcomes (C2). These arrive with the fixes.

---

## Summary ranking

| # | Sev | One line |
|---|-----|----------|
| C1 | Critical | Chat apply skips service validation; bad date from chat 500s the whole tab |
| C2 | Critical | Model claims unapplied/rejected/failed changes as done; outcomes never recorded |
| H1 | High | Validator passes incoherent ops; change evaporates silently ("table didn't update") |
| H2 | High | Approve/reject card shows no detail of what it applies |
| H3 | High | Prompt demands full fields, never asks — hallucinated creates (Bug C) |
| H4 | High | No duplicate/in-flight guard on chat creates |
| M1–M5 | Medium | Failure not recorded; HTML in errors; bare json.loads; clock skew; amount_cents unit trap |
| L1–L4 | Low | No auth/CORS (demo); dead history route; a11y nits; test gaps |

The three reported bugs map to: Bug A → H1 + C2 (perception; the OOB refresh itself works),
Bug B → C2 + M1 + M2, Bug C → H3 + C1 + H2. The suggestions window closes C2/H2 structurally
and gives H4 a place to live.
