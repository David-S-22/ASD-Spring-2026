# Bills — session prompts by Plan → Act → Observe → Adapt stage

The prompts that drove the Release 0 work on `sophia/**` (Feature 5, Bills
List & Dispute Assistant), filed under the stage each one performs, in the
same `prompts/<family>/` layout the agentic loop uses.

| Stage | File | Run | What it did |
|---|---|---|---|
| Plan | `plan/release0_plan_prompt.txt` | 22 Aug 2026 | Plan-only: read the repo, design the feature and the shared shell; no files created |
| Act | `act/r0_improvements_task_prompt.txt` | 28 Aug 2026 | Verify the improvement plan, then Tier A in four PRs (#47, #49, #50, #51) |
| Act | `act/b2_pure_reads_task_prompt.txt` | 29 Aug 2026 | B2: reads stop writing the cached status (#56), plus a test-suite consolidation assessment |
| Observe | `observe/pr_review_prompt.txt` | 29 Aug 2026 | Read-only review of the merged Bills PRs against the spec, criteria and team agreements |
| Adapt | `adapt/audit_fixes_task_prompt.txt` | 30 Aug 2026 | Re-verify the audit findings, then fix them in dependency order (#68, #69, #71, #75) |
| Observe | `observe/rubric_gaps_audit_prompt.txt` | 31 Aug 2026 | Rubric evidence audit, then close the gaps: the agentic loop (#78, #88), its sample run (#82), shell evidence (#89, #91) |

## How to read them

Each file opens with a five-line header — stage, run date, purpose,
outcome — then the prompt itself. The prompts are condensed from the
session originals for readability: the wording is the original's, but the
machine-specific setup, the note-keeping steps, and the stop-and-wait
choreography are summarised in the header rather than reproduced. That
choreography is the context-management practice the prompts share:

- **Verify before implementing.** Every prompt opens with a read-only
  phase that re-checks the plan's claims against the repository as it is
  *now*, produces a claim-by-claim table, and stops. Nothing is written
  until the results are reviewed and the next phase is explicitly
  unlocked.
- **Scoped, gated phases.** Work is split into branches and PRs of one
  concern each, in dependency order; a phase whose precondition is unmet
  is skipped and reported, never forced.
- **Hard scope rules.** Only `sophia/**`, the three `bills-*` compose
  blocks, `Sophia-CI.yml` and `docs/release-0/sophia/**` may change;
  problems elsewhere are listed for the team, never fixed. `git diff
  --stat` is checked before every commit.
- **Push and merge gates.** No push without an explicit instruction; PRs
  open as drafts; nothing is merged by the agent.
- **Decisions are pinned.** Settled decisions (D1–D3, port allocations,
  gated adoptions) are restated at the top of each prompt so they are not
  reopened mid-session.
