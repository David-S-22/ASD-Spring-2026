// Ask Tally chat evaluation loop for Claude Code's Workflow tool.
// Launch with: Workflow({ scriptPath: "sophia/eval/chat_eval_workflow.js", args: { base: "http://localhost:3000/bills-backend", runs: 2 } })
// Needs the stack, the MCP and RAG host servers and Ollama running; never run it during a demo (it writes chat rows and proposals; reseed bills_data afterwards).
export const meta = {
  name: 'tally-chat-eval-loop',
  description: 'Generate paraphrases per Ask Tally intent, sweep them against the live stack, diagnose failures into rules, and gate every rule on the full corpus matrix and suite',
  phases: [
    { title: 'Generate', detail: 'Sonnet writes paraphrases per intent from the corpus', model: 'sonnet' },
    { title: 'Sweep', detail: 'Sonnet runs chat_sweep against the live stack and reports failures', model: 'sonnet' },
    { title: 'Diagnose', detail: 'Opus classifies each failure and proposes the smallest rule, gated on matrix + suite', model: 'opus' },
  ],
}

const REPO = 'C:\\Users\\Sophia.Nguyen\\OneDrive - WiseTech Global Pty Ltd\\Documents\\SPRING 2026\\30-Projects\\Tally'
const BASE = (args && args.base) || 'http://localhost:5005'
const RUNS = (args && args.runs) || 2

const CONTEXT = `
Repo ${REPO} (Git Bash from the repo root; python is .venv/Scripts/python; pytest with -p no:cacheprovider). Corpus: sophia/eval/chat_queries.yaml (route per phrasing). Matrix: sophia/test/test_chat_route_matrix.py (adversarial classifier outputs, no model). Sweep: python -m sophia.eval.chat_sweep --base ${BASE} --runs ${RUNS} (live model; writes docs/release-2/sophia/chat-eval/sweep-*.md). Routing lives in sophia/backend/services/chat.py (_model_turn and the word rules: CHANGE_VERB, QUESTION_START, TOTAL_WORDS, BARELY_WORDS, DUE_WORDS, PAY_WORDS, CHARGE_WORDS, FUTURE_WORDS, DISPUTE_VERB). Norms: the LLM never computes dates or totals; a question is never a change; nothing is written without a click; the chat works with MCP/RAG off; fixes are code rules, never prompt tweaks; David's style bar (no inline comments, one-line docstrings, no thin wrappers). Do not commit or push.`

const GEN_SCHEMA = { type: 'object', properties: { entries: { type: 'array', items: { type: 'object', properties: { message: { type: 'string' }, route: { type: 'string' }, title: { type: 'string' } }, required: ['message', 'route'] } } }, required: ['entries'] }
const SWEEP_SCHEMA = { type: 'object', properties: { report_path: { type: 'string' }, passed: { type: 'integer' }, total: { type: 'integer' }, failures: { type: 'array', items: { type: 'object', properties: { message: { type: 'string' }, expected_route: { type: 'string' }, got_route: { type: 'string' }, reply: { type: 'string' }, failures: { type: 'array', items: { type: 'string' } } }, required: ['message', 'expected_route', 'got_route', 'reply', 'failures'] } } }, required: ['report_path', 'passed', 'total', 'failures'] }
const DIAG_SCHEMA = { type: 'object', properties: { accepted_rules: { type: 'array', items: { type: 'string' } }, rejected: { type: 'array', items: { type: 'object', properties: { failure: { type: 'string' }, why: { type: 'string' } }, required: ['failure', 'why'] } }, matrix: { type: 'string' }, suite: { type: 'string' }, diff_stat: { type: 'string' } }, required: ['accepted_rules', 'rejected', 'matrix', 'suite', 'diff_stat'] }

phase('Generate')
const gen = await agent(`Read sophia/eval/chat_queries.yaml. For every distinct route (total, upcoming, barely_using, tool, grounded, proposal, ask_back) write 6 new paraphrases the way a real user types into a chat box: no question mark sometimes, lowercase, "please", a parenthetical, a typo, two bills in one sentence, a cost question about something that is not a bill. Each entry gets the route it MUST take under the norms (a question is never a change; what's-due needs a due word or a horizon plus a pay word; a dispute request naming one bill is a proposal; a change request missing values is ask_back). Append them to a NEW file sophia/eval/chat_queries_generated.yaml in the same schema (do not edit the main corpus) and return them.\n${CONTEXT}`, { label: 'generate:paraphrases', phase: 'Generate', schema: GEN_SCHEMA, model: 'sonnet', effort: 'medium' })
log(`generated ${gen ? gen.entries.length : 0} paraphrases`)

phase('Sweep')
const MAIN_REPORT = (args && args.mainReport) || ''
const sweep = await agent(`The main corpus was ${MAIN_REPORT ? 'already swept; its JSON report is ' + MAIN_REPORT + ' (read it and include its failing rows)' : 'not swept yet; run "python -m sophia.eval.chat_sweep --base ' + BASE + ' --runs ' + RUNS + '" first'}. Then sweep the generated paraphrases: CHAT_QUERIES=sophia/eval/chat_queries_generated.yaml PYTHONIOENCODING=utf-8 python -u -m sophia.eval.chat_sweep --base ${BASE} --runs ${RUNS}, appending the terminal output to docs/release-2/sophia/chat-eval/sweep-terminal-generated.log. Collect every failing row from both (message, expected route, got route, reply, failures); a query counts as failing if ANY run failed. Afterwards reseed bills-db: docker compose stop bills-db && docker compose rm -f bills-db && docker volume rm tally_bills_data && docker compose up -d bills-db && docker compose restart bills-frontend shared-frontend.
${CONTEXT}`, { label: 'sweep:live', phase: 'Sweep', schema: SWEEP_SCHEMA, model: 'sonnet', effort: 'medium' })
log(`sweep: ${sweep ? sweep.passed + '/' + sweep.total : 'n/a'} passed, ${sweep ? sweep.failures.length : 0} failures`)

phase('Diagnose')
const diag = await agent(`For each sweep failure decide: (a) model noise the code should absorb with a deterministic rule, (b) a wrong expectation in the corpus (then fix the corpus entry and say why), or (c) genuinely ambiguous (leave it, explain). For (a) write the failing matrix/corpus entry FIRST (add the phrasing to sophia/eval/chat_queries.yaml), then the smallest rule in services/chat.py. GATE: after all edits run "python -m pytest sophia/test/test_chat_route_matrix.py -q -p no:cacheprovider" and the whole "sophia/test" suite; if anything fails, revert the offending rule and list it under rejected. Report the accepted rules, the rejected ones with reasons, both test summaries and git diff --stat. Do not commit.\nFailures: ${JSON.stringify(sweep ? sweep.failures : [])}\n${CONTEXT}`, { label: 'diagnose:rules', phase: 'Diagnose', schema: DIAG_SCHEMA, model: 'opus', effort: 'high' })
log(`diagnose: ${diag ? diag.accepted_rules.length : 0} rules accepted, ${diag ? diag.rejected.length : 0} rejected`)

return { generated: gen, sweep, diagnosis: diag }
