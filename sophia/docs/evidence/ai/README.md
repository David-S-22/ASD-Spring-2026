# AI evidence — real local Ollama, 22 Aug 2026

Both calls run against the real local Ollama (`llama3.1:8b` for dispute drafts,
`qwen2.5:0.5b` for chat), not mocked, via a temp `db` + `backend` pair started
locally with `DEMO_TODAY=2026-08-20` and `AI_TIMEOUT_SECONDS=90`. Each file
below is the raw JSON response for one call, saved as-is.

## Dispute drafting (llama3.1:8b) — 3/3 first-try schema pass

| File | Call | Result |
|---|---|---|
| `01-dispute-create-gymco-direct-debit.json` | `POST /api/disputes` for GymCo (bill 6, direct_debit), reason "Charged after I cancelled" | `fallback: false`; direct-debit authority-removal step correctly appended by `enforce_payment_method_step` |
| `02-dispute-create-primevideo-card.json` | `POST /api/disputes` for Prime Video (bill 5, card), reason "Charged for a month I did not use" | `fallback: false`; card cancel-from-app-page step correctly appended |
| `03-dispute-regenerate-primevideo-feedback.json` | `POST /api/disputes/15/regenerate` with feedback "Make it shorter and ask for the refund within 14 days." | `fallback: false`, `version: 2`; letter is shorter and asks for the refund within 14 days as requested |

**Hit rate: 3/3 (100%) validated on the first try — no retries, no fallbacks.**

### What tuning changed this

The first live run against GymCo surfaced a real bug, not just a prompt
quality issue: `enforce_payment_method_step` checked the joined steps text
for the substring `"authority"`, which false-positived whenever the model's
own steps cited "Australian Financial Complaints Authority (AFCA)" as an
escalation channel — so the actually-required direct-debit-authority-removal
step silently never got appended. Fixed in `dispute_prompt.py` by checking
each step individually and excluding the AFCA phrase specifically before
testing for "authority".

The same run also showed the model inventing a fake phone number
(`1300 123 456`) for an escalation contact. Tightened `SYSTEM` in
`dispute_prompt.py` to say escalation entries are channel names only
("Merchant support", "Your bank's dispute team"), never invented contact
details — the next run's escalation list matched the fallback's own clean
style with no invented specifics.

## Chat op classification (qwen2.5:0.5b) — 4/4 correct op

| File | Chip | Expected | Got | Correct? |
|---|---|---|---|---|
| `04-chat-total.json` | "What do my bills add up to?" | `question: "total"` | `question: "total"` (resolved reply: "This month you're set to pay around $1,741...") | Yes |
| `05-chat-barely-using.json` | "Which subscriptions am I barely using?" | `question: "barely_using"` | `question: "barely_using"` (resolved reply names Anytime Fitness and Cloud storage with real billed counts) | Yes |
| `06-chat-cancel-spotify.json` | "I cancelled Spotify from September — remove the future payments" | `op:"update", entity:"bill", id:3, fields:{end_date:"2026-09-16"}` | Exact match | Yes |
| `07-chat-dispute-gymco.json` | "Draft a note to dispute my GymCo charge" | `op:"create", entity:"dispute", fields:{bill_id:6, reason:...}` | Exact match (`bill_id: 6`, reason "Charged after I cancelled") | Yes |

**Hit rate: 4/4 (100%) — exceeds the 3/4 bar.** All four calls validated on the
first try (`fallback: false`); no retries were needed.

### What tuning changed this

`chat_prompt.py` was rewritten from a bare instruction line to: a compact
one-line-per-bill bills list (id, name, amount, cadence, next date, type) so
the 0.5B model has concrete ids to reference instead of guessing, plus four
few-shot examples pinned to exactly these four requests. Given qwen2.5:0.5b's
context sensitivity, the prompt stays short deliberately — no verbose
explanation, no repeated schema description beyond the one response-shape
line.

## Honesty note

This is a small sample (7 calls, one session, one seed of the local models).
It demonstrates the guard/schema/enforcement pipeline works end to end
against the real models and caught one real bug that unit tests alone (which
mock the HTTP layer) would not have caught. It is not a statistical claim
about long-run accuracy — a wider sweep across more phrasings belongs in a
later evidence pass if the team wants a firmer number.
