# Bills — development-loop run records

The run record for the development loop under `prompts/bills/`: one folder
per stage, each holding the terminal record of the session that ran that
stage's prompt, and — for the two Observe stages — the findings the session
produced. It mirrors what `sophia/agentic_loop/` already keeps for the
review loop (a terminal transcript and a run record per mode), so the
report's Agentic Loop Workflow Record can cite both loops the same way.

| Stage | Prompt | Run | What it did | `terminal.txt` source | findings |
|---|---|---|---|---|---|
| Plan | `prompts/bills/plan/release0_plan_prompt.txt` | 22 Aug 2026 | Plan-only: read the repo, design the feature and the shared shell; no files created | transcript `7a4fc3b7` (the v3 issue of the prompt; the v4 text on file was written later that day) | — |
| Act | `prompts/bills/act/r0_improvements_task_prompt.txt` | 28 Aug 2026 | Verify the improvement plan, then Tier A in four PRs (#47, #49, #50, #51) | transcript `cb34a49a` (opened 26 Aug, PRs merged 28 Aug) | — |
| Act | `prompts/bills/act/b2_pure_reads_task_prompt.txt` | 29 Aug 2026 | B2: reads stop writing the cached status (#56), plus a test-suite consolidation assessment | transcript `9fdd41a4` | — |
| Observe | `prompts/bills/observe/pr_review_prompt.txt` | 29 Aug 2026 | Read-only review of the merged Bills PRs against the spec, criteria and team agreements | transcript `d241321a` | `observe-pr-review/findings.md` |
| Adapt | `prompts/bills/adapt/audit_fixes_task_prompt.txt` | 30 Aug 2026 | Re-verify the audit findings, then fix them in dependency order (#68, #69, #71, #75) | transcript `c097cc16` | — (the fixes are the record) |
| Observe | `prompts/bills/observe/rubric_gaps_audit_prompt.txt` | 31 Aug 2026 | Rubric evidence audit, then close the gaps: the agentic loop (#78, #88), its sample run (#82), shell evidence (#89, #91) | transcript `7f61b4db` (the audit and the loop's draft PR; the PRs merged 1 Sep after a further session) | `observe-rubric-audit/findings.md` |

Folders: `plan/`, `act-r0-improvements/`, `act-b2-pure-reads/`,
`observe-pr-review/`, `adapt-audit-fixes/`, `observe-rubric-audit/`.

## What a development loop's terminal record is

A review loop's terminal record is the loop's own stdout. A development
loop's terminal record is three things, all of which already exist: the
prompt as it was issued, the tool calls it drove — every command run, file
read, file written, in order, with the points where the session stopped and
waited for a decision — and the pull requests it produced, which GitHub
timestamps independently of anything written here. Each `terminal.txt`
above is that, condensed from the session transcript: the prompt verbatim,
one line per tool call, each phase gate as it happened with the reply given,
and the closing summary verbatim. Tool outputs longer than ten lines are
elided, machine paths are shown as `~/…` or repo-relative, and other
people's names are replaced. The header of each file states the session id,
its start and end, and the `main` commit the session started from. Nothing
in these files was reconstructed; where a stage's prompt on file differs
from the text actually issued, the header says so.

The later Observe → Adapt cycle on the Ask Tally chat — the 2 Sep code
review and the fixes it produced in #105, #106, #108, #109 and #120 — is
already fully committed at `docs/bills-code-review.md`, with its status
banner recording what became of each finding.
