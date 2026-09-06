# AI evidence — real local Ollama, re-captured 7 Sep 2026

Seven calls against the real local Ollama, not mocked: `llama3.1:8b` for dispute
drafts, **`qwen2.5:3b`** for chat. Each file beside this one is the raw JSON
response for one call, saved as-is.

These were re-captured on 7 Sep. The original 22 Aug set ran on **`qwen2.5:0.5b`**,
which stopped being the chat model on 1 Sep (PR #94, `CHAT_MODEL` default →
`qwen2.5:3b`), so that evidence no longer described the shipping system. The
dispute model is unchanged.

Two other things changed with the re-capture, and both are visible in the files:

- **Run against the composed stack**, not a temp `db` + `backend` pair. `bills-backend`
  reaches Ollama at the composed service `http://ollama:11434` (compose overrides
  `config.py`'s `host.docker.internal` default), with `DEMO_TODAY=2026-08-20` and
  `AI_TIMEOUT_SECONDS=90` as before.
- **Chat proposals no longer apply themselves.** Since PR #105 a proposal lands as a
  `pending` row in the new `suggestions` table and waits for a decision, so the chat
  previews now carry `message_id` and `suggestion_id`, and the replies say the change
  was *suggested* rather than made. That is why 06 and 07 read differently from the
  22 Aug capture — the wording is the fix, not a regression.

## Dispute drafting (`llama3.1:8b`) — 3/3 schema pass, no fallbacks

| File | Call | Result |
|---|---|---|
| `01-dispute-create-gymco-direct-debit.json` | `POST /api/disputes` for GymCo (bill 6, direct_debit), reason "Charged after I cancelled" | `fallback: false`, 23.3s. Direct-debit authority-removal step correctly appended by `enforce_payment_method_step` as the last of 6 steps |
| `02-dispute-create-primevideo-card.json` | `POST /api/disputes` for Prime Video (bill 5, card), reason "Charged for a month I did not use" | `fallback: false`, 23.7s. Card cancel-from-app-page step correctly appended as the last of 7 |
| `03-dispute-regenerate-primevideo-feedback.json` | `POST /api/disputes/12/regenerate` with feedback "Make it shorter and ask for the refund within 14 days." | `fallback: false`, `version: 2`, 14.1s. Letter goes 252 → 154 characters and asks for the refund within 14 days, as asked |

**3/3 validated with no fallback.** The saved responses record `fallback: false` but
not an attempt count, so this is "no fallback was needed", not a first-try claim.

### What tuning changed this (22 Aug, still applies)

The first live run against GymCo surfaced a real bug, not a prompt-quality issue:
`enforce_payment_method_step` checked the joined steps text for the substring
`"authority"`, which false-positived whenever the model's own steps cited
"Australian Financial Complaints Authority (AFCA)" as an escalation channel — so the
actually-required direct-debit-authority-removal step silently never got appended.
Fixed in `dispute_prompt.py` by checking each step individually and excluding the
AFCA phrase specifically before testing for "authority". The 7 Sep re-capture
confirms the fix still holds: `01` cites AFCA-style escalation channels *and* still
gets its authority-removal step.

The same run also showed the model inventing a fake phone number (`1300 123 456`).
`SYSTEM` was tightened to say escalation entries are channel names only. The
re-capture's escalation lists contain no invented contact details.

## Chat op classification (`qwen2.5:3b`) — 4/4 correct op

| File | Message | Expected op | Got | Correct? |
|---|---|---|---|---|
| `04-chat-total.json` | "What do my bills add up to?" | `question: "total"` | `op: null`, reply "August is set to cost around $1,695. Your ongoing monthly total across all bills is $1,731.95." | Yes |
| `05-chat-barely-using.json` | "Which subscriptions am I barely using?" | `question: "barely_using"` | `op: null`, names Anytime Fitness (7 billings, $17.50/mo) and Cloud storage (4, $2.99/mo) | Yes |
| `06-chat-cancel-spotify.json` | "I cancelled Spotify from September — remove the future payments" | `op:"update", entity:"bill", id:3, fields:{end_date:…}` | `op:"update"`, `entity:"bill"`, `id:3` — **but `end_date: 2026-10-16`, which is wrong; see below** | Op yes, field no |
| `07-chat-dispute-gymco.json` | "Draft a note to dispute my GymCo charge" | `op:"create", entity:"dispute", fields:{bill_id:6, reason:…}` | Exact match (`bill_id: 6`, reason "Charged after I cancelled") | Yes |

**4/4 on op classification, `fallback: false` on all four.** 14.0s / 4.6s / 6.0s /
6.9s; the first is a cold-ish start, the rest are the steady state.

The replies in `04` and `05` are produced by deterministic code once the model has
classified the question, not written by the model. `04` names two different figures
on purpose: `$1,695` is the calendar-month estimate and `$1,731.95` is the ongoing
monthly rate the page header shows. `05`'s counts come from the seed, which is why it
says seven billings where the 22 Aug capture said six — the seed grew, the model did
not change its answer.

### The one thing that is wrong, stated plainly

`06` returns `end_date: 2026-10-16`. The correct value is **`2026-09-16`**: Spotify's
`next_occurrence` is 16 Sep, and `chat_prompt.py:38` carries *this exact message* as a
few-shot example pinned to `{"end_date": "2026-09-16"}`. The model is being shown the
right answer for the identical sentence and still returns a date a month late.

It is consistent, not a one-off. Six repeats of the same call:

| Run | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| `end_date` | **2026-09-16** | 2026-10-16 | 2026-10-16 | 2026-10-16 | 2026-10-16 | 2026-10-16 |

**5 of 6 wrong.** `op`, `entity` and `id` were right in all six, and `fallback` was
false in all six — so the guard and schema layer did their job; the model simply
picked the wrong month. The committed `06` file is the majority (wrong) result, kept
deliberately rather than re-rolled until it looked good.

Worth recording alongside the 1 Sep model A/B, which chose `qwen2.5:3b` over
`qwen2.5:0.5b` on add-bill reliability (0.5b blew the 90s timeout on 3 of 6 runs and
returned `"fields": null`). This is the counter-example: on the Spotify case 0.5b was
3/3 correct and 3b is 1/6. The choice was still right on balance — a wrong date the
user reviews and rejects is recoverable, a timeout is not, and nothing is written
until the user approves the suggestion — but "3b is better" is not true field-by-field,
and this file is the evidence.

### What tuning changed this

`chat_prompt.py` was rewritten from a bare instruction line to a compact
one-line-per-bill list (id, name, amount, cadence, next date, type) so the model has
concrete ids to reference instead of guessing, plus few-shot examples. It now carries
six, including the bill-create example added in PR #100 and a `BILL_FIELDS` block
naming the fields a create needs — the schema description the earlier, shorter prompt
deliberately omitted when it was tuned for 0.5b's context sensitivity.

## Honesty note

Small sample: 7 calls plus a 6-run repeat, one session, one seed, one pull of each
local model. It demonstrates the guard/schema/enforcement pipeline works end to end
against the real models, caught one real bug that unit tests alone (which mock the
HTTP layer) would not have caught, and — in `06` — shows where the pipeline correctly
does *not* save you: a well-formed answer that validates and is still wrong. It is
not a statistical claim about long-run accuracy. A wider sweep across more phrasings
belongs in a later evidence pass.
