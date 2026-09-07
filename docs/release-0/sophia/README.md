# Release 0 — Feature 5 (Bills List & Dispute Assistant) — Sophia

Supporting material for the Release 0 technical report. Everything here is
cited from the report. Per the spec's repository layout the evidence lives
under `docs/`; the only documentation beside the code is the feature's own
`sophia/README.md` (how to run it, engine rules, the two AI calls) and
`sophia/agentic_loop/README.md`.

| Path | Report section | What it is |
|---|---|---|
| `../../architecture/r0-d1-individual-architecture.png` | Individual architecture | Three containers and the backend's internal layers |
| `../../architecture/r0-d2-docker-compose-architecture.png` | Docker Compose architecture | Bills' three containers, their ports, and the `bills_data` volume. **Stale in one respect:** the PNG was rendered 22 Aug and draws Ollama as a host process reached at `host.docker.internal:11434`. Since #69 (30 Aug) compose runs Ollama as the `ollama` service and sets `OLLAMA_URL: http://ollama:11434` for `bills-backend`. There is no `.mmd` source in the repo to re-render from. |
| `../../architecture/r0-d3-paoa-dispute-loop.png` | Plan → Act → Observe → Adapt | The dispute-draft loop |
| `../../architecture/r0-d4-paoa-chat-loop.png` | Plan → Act → Observe → Adapt | The chat loop, compressed |
| `api.md` | Implementation summary | Endpoint reference for the backend (`/api/*`, `/ui/*`) |
| `contracts-inbound.md` | Requirements F5-FR13, risk R2 | Inbound handoff contracts from Features 3 and 4 |
| `schema-adoption.md` | Implementation summary | The six additive schema items |
| `evidence/compose/up.txt` | Docker Compose execution evidence | `docker compose ps` plus health curls on `:6005`, `:5005`, `:3005/` and `:3005/api/bills`, 22 Aug (stamped 21 Aug UTC) |
| `evidence/compose/compose-ps.txt`, `compose-down.txt`, `curl-endpoints.txt` | Docker Compose execution evidence | Baseline verification added with #12 (22 Aug), before the write-route work in #19 |
| `evidence/compose/ui-write-routes.txt`, `four-cases.txt` | Local testing evidence (post) | curl transcripts of 11 of the 15 `/ui/*` write routes, captured 22 Aug — `disputes/<id>/delete` and the three `suggestions/*` actions arrived later, in #105 and #106 — plus four curls confirming the two former 500s are fixed |
| `evidence/ai/README.md` | Local testing evidence, AI-Mode | What each call tested, the 3/3 and 4/4 results, the bug the live run found, and the one answer that validates but is wrong |
| `evidence/ai/*.json` | Local testing evidence, AI-Mode | Seven raw responses from real local Ollama calls, re-captured 7 Sep on `llama3.1:8b` (disputes) and `qwen2.5:3b` (chat). The 22 Aug set ran on `qwen2.5:0.5b`, which stopped being `CHAT_MODEL` on 1 Sep |
| `evidence/compose/pytest-283-passed.txt` | Local testing evidence | `pytest sophia/test -q --cov=sophia/backend --cov-report=term` at ffb625f — 283 passed, 91% coverage, 7 Sep |
| `evidence/ci-summary-2026-09-07.txt` | Continuous integration evidence | Sophia-CI run history: 145 runs, 142 green, the three 21 Aug failures, and the `gh api` calls that reproduce them |
| `evidence/compose/compose-ps-2026-09-07.txt` | Docker Compose execution evidence | All 17 services up, plus the five frontends and five backends probed through the shared shell on `:3000`, 7 Sep |
| `screenshots/r0-NN-*.png` | Screenshots of the integrated application | Numbered to the report's `[SCREENSHOT n]` markers |

Screenshots are numbered to the report's `[SCREENSHOT n]` markers. They were not
all taken at once, and the dates matter when reading them:

- **r0-01 to r0-06c, r0-13, r0-14, r0-15, r0-12g, r0-12h** — captured 2 Sep on
  the dark-theme build (#101, commit `0bd8150`), headless Chrome at 1400px,
  `DEMO_TODAY=2026-08-20` and a fresh seed. **They are not the current
  interface.** Five UI PRs landed after them that day and the next: #103 (a row
  menu instead of four buttons — r0-01, r0-02), #105 (proposals become pending
  suggestions, so the self-applying chat in r0-06c no longer exists), #109 (one
  page — the Calendar and Coming-up tabs in r0-03 and r0-04 were removed),
  #117/#118 (layout polish, Disputes as a tile grid — r0-05, r0-06) and #119
  (deep-link shape — r0-14). Read them as the 2 Sep build; re-shoot before
  citing any of them as current.
- **r0-12e / r0-12f** (1 Sep) are the fluid-layout evidence from #96 and
  **r0-12g / r0-12h** (2 Sep) are the dark theme in the shell and standalone.
  They are kept as the before/after halves of two separate comparisons; do not
  overwrite them with a single "current" capture.
- **r0-07 (pytest) and r0-10 (compose ps)** were re-captured 7 Sep. r0-07 shows
  283 passed / 91% with the full per-module coverage table, matching
  `evidence/compose/pytest-283-passed.txt`; the previous shot showed 159 and no
  coverage. r0-10 now shows all 17 compose services, where the previous shot
  showed only the three `bills-*` containers plus `ollama` from a partial run.
  Both are renderings of real captured output in the same terminal style as the
  rest of the set — the commands shown are the commands that produced the text.
- **r0-09 (Actions run summary)** was re-captured 7 Sep and now shows run **#145**
  — the run the report cites — with `test` and `docker-health` both green (26s and
  37s, 1m 10s total) at sha `9454b11`. The previous shot was run #66 from 30 Aug.
  Captured signed-out on the public repository, which is why the page shows Sign
  in / Sign up and "Sign in to view logs"; that matches how the image it replaces
  was taken.

  The run's title reads "Automatically check anomalies of new transactions (#99)"
  and was pushed by a teammate, not by me. That is expected rather than a mix-up:
  Sophia-CI triggers on `sophia/**` **and** `shared/**`, and #99 touched `shared/`.
  It is still the run that covers this feature's code — `git rev-parse HEAD:sophia`
  and `git rev-parse 9454b11:sophia` both return `b23a2be`, so the Bills tree it
  tested is byte-identical to the submitted one. See
  `evidence/ci-summary-2026-09-07.txt`.
- **r0-08 (Actions list) and r0-11 (health)** are both from 30 Aug (`4dbb4d6`)
  and are now the oldest images in the set.

`r0-12` and `r0-12b` document a defect that has since been **fixed**. Read them as
history, with `r0-12c`/`r0-12d` (1 Sep, #89: Bills rendering and a write
completing inside the shell after the fix) and `r0-12g` (the 2 Sep dark theme in
the shell) beside them:

- `r0-12-shell-bills.png` — the Bills tab in the shared shell as it was on 1 Sep.
  The whole Bills document was swapped into `#content`, so the `<head>` was dropped
  by the innerHTML parse, taking both stylesheets and the vendored htmx with it.
  Every fragment request then resolved against `:3000`, where the shell had no
  `/ui/`, `/css/` or `/js/` location and no `location /` fallback, so `/ui/bills`,
  `/ui/calendar`, `/ui/timeline`, `/ui/disputes-tab`, `/ui/chat` and `/js/app.js`
  all 404'd — twelve console errors, and the cards rendered empty.
- `r0-12b-bills-standalone.png` — the same feature at `:3005` on the same day,
  fully rendered, no console errors, no failed requests.

htmx was never at fault: the shell's htmx processed the swapped content correctly,
which is why those requests fired at all. Bills' own half of the contract — the
missing `/bills-backend/` mapping, which made `:3000/bills-backend/ui/bills` return
`index.html` with a 200 — was fixed in #86.

The remaining half was the root-absolute paths, and it is now closed: `index.html`
requests `/bills-frontend/css/*`, `/bills-frontend/js/*` and `/bills-backend/ui/*`,
one URL shape that both contexts serve. The 7 Sep stack capture
(`evidence/compose/compose-ps-2026-09-07.txt`) probes `/bills-frontend/`,
`/bills-backend/health` and `/bills-backend/api/bills` through the shell, all 200;
the individual `/ui/*`, `/css/*` and `/js/*` paths were checked against the running
stack on 7 Sep but are not in any capture file. Two of the six paths listed above
(`/ui/calendar`, `/ui/timeline`) are no longer requested by any page since #109.
Bare `/ui/bills`, `/css/bills.css` and `/js/app.js` still 404 at the shell, but
nothing requests them any more.
