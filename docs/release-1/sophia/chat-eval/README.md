# Ask Tally chat evaluation harness (Release 1)

The night of 1 Oct 2026 fixed nine chat misses by hand: type a query, read the reply, patch a rule, re-run everything. This folder is that loop as a harness, so a fix cannot land while it breaks another phrasing.

## Pieces

| Piece | Where | What it does |
|---|---|---|
| Corpus | `sophia/eval/chat_queries.yaml` | One entry per phrasing with the **route** it must take (`total`, `upcoming`, `barely_using`, `tool`, `grounded`, `proposal`, `ask_back`) and a few must/must-not substrings or the card title. Every fix adds its phrasing here first. |
| Route field | `/api/chat` → `route`, `suggestion_title` | The code path that produced the reply, named by the code, so a harness scores routing instead of prose. |
| Route matrix (CI) | `sophia/test/test_chat_route_matrix.py` | Drives every corpus entry through the chat with adversarial classifier outputs (plain, wrong tag, wrong bill id, invented field, null amount). No model, no network. Proves the code rules decide regardless of what qwen2.5:3b says. 114 cases on 1 Oct. |
| Live sweep | `python -m sophia.eval.chat_sweep --runs 3 --base http://localhost:3000/bills-backend` | Posts each query to the running stack N times with the real model, scores route and expectations, writes `sweep-<stamp>.md/.json` here. Catches the nondeterminism the matrix cannot guess. Reseed `bills_data` afterwards: proposals stay pending. |
| Agentic loop | `sophia/eval/chat_eval_workflow.js` | Generate paraphrases per intent (Sonnet) → live sweep (code) → diagnose failures and propose the smallest rule (Opus) → **gate**: full corpus matrix + whole suite must stay green before a rule is accepted. Run with Claude Code's Workflow tool when the stack is free. |

## Why routes, not text

A small model's prose varies run to run; the route does not have to. Nine of the ten misses on 1 Oct were the model saying something the code then trusted (an `upcoming` tag on "Which bill is overdue?", Prime Video's id for a Spotify update, an invented `disputed` field). The matrix makes each of those a named adversarial case and runs every phrasing against all of them.

## Evidence in this folder

- `matrix-2026-10-01.txt`: the matrix run that found three further gaps before anyone typed them (a trusted `total` tag on an overdue question, "What will I pay in the next 3 weeks?" depending on the tag, "Add Netflix" falling into RAG), then 114/114 after the rules.
- `suite-2026-10-01.txt`: the whole Bills suite after the harness landed.
- `sweep-*.md`: live sweeps (added when the stack is free; never during a demo).

## Adding a phrasing

1. Add the entry to `chat_queries.yaml` with the route and any substrings or title.
2. Run the matrix; if it fails, the fix goes in `services/chat.py` as a rule, never as a prompt tweak.
3. Run the live sweep once the stack is free; attach the report here.
