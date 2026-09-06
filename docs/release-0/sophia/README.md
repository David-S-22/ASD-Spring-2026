# Release 0 — Feature 5 (Bills List & Dispute Assistant) — Sophia

Supporting material for the Release 0 technical report. Everything here is
cited from the report; nothing is in the `sophia/` code directory because the
spec's repository layout keeps documentation under `docs/`.

| Path | Report section | What it is |
|---|---|---|
| `../../architecture/r0-d1-individual-architecture.png` | Individual architecture | Three containers and the backend's internal layers |
| `../../architecture/r0-d2-docker-compose-architecture.png` | Docker Compose architecture | Bills' three containers, their ports, and the `bills_data` volume. **Stale in one respect:** the PNG was rendered 22 Aug and draws Ollama as a host process reached at `host.docker.internal:11434`. Since #69 (30 Aug) compose runs Ollama as the `ollama` service and sets `OLLAMA_URL: http://ollama:11434` for `bills-backend`. There is no `.mmd` source in the repo to re-render from. |
| `../../architecture/r0-d3-paoa-dispute-loop.png` | Plan → Act → Observe → Adapt | The dispute-draft loop |
| `../../architecture/r0-d4-paoa-chat-loop.png` | Plan → Act → Observe → Adapt | The chat loop, compressed |
| `api.md` | Implementation summary | Endpoint reference for the backend (`/api/*`, `/ui/*`) |
| `contracts-inbound.md` | Requirements F5-FR13, risk R2 | Inbound handoff contracts from Features 3 and 4 |
| `schema-adoption.md` | Implementation summary | The six additive schema items |
| `evidence/compose/up.txt` | Docker Compose execution evidence | build → up → ps → health → down, 21 Aug |
| `evidence/compose/compose-ps.txt`, `compose-down.txt`, `curl-endpoints.txt` | Docker Compose execution evidence | Baseline run from the first compose PR |
| `evidence/compose/ui-write-routes.txt`, `four-cases.txt` | Local testing evidence (post) | curl transcripts of 11 of the 15 `/ui/*` write routes, captured 22 Aug — `disputes/<id>/delete` and the three `suggestions/*` actions arrived later, in #105 and #106 — plus four curls confirming the two former 500s are fixed |
| `evidence/ai/README.md` | Local testing evidence, AI-Mode | What each call tested, the 3/3 and 4/4 results, the bug the live run found, and the one answer that validates but is wrong |
| `evidence/ai/*.json` | Local testing evidence, AI-Mode | Seven raw responses from real local Ollama calls, re-captured 7 Sep on `llama3.1:8b` (disputes) and `qwen2.5:3b` (chat). The 22 Aug set ran on `qwen2.5:0.5b`, which stopped being `CHAT_MODEL` on 1 Sep |
| `evidence/compose/pytest-283-passed.txt` | Local testing evidence | `pytest sophia/test -q --cov=sophia/backend --cov-report=term` at ffb625f — 283 passed, 91% coverage, 7 Sep |
| `evidence/ci-summary-2026-09-07.txt` | Continuous integration evidence | Sophia-CI run history: 145 runs, 142 green, the three 21 Aug failures, and the `gh api` calls that reproduce them |
| `evidence/compose/compose-ps-2026-09-07.txt` | Docker Compose execution evidence | All 17 services up, plus the five frontends and five backends probed through the shared shell on `:3000`, 7 Sep |
| `screenshots/r0-NN-*.png` | Screenshots of the integrated application | Numbered to the report's `[SCREENSHOT n]` markers |

Screenshots are numbered to the report's `[SCREENSHOT n]` markers. They were not
all taken at once, and the dates matter when reading them:

- **r0-01 to r0-06c, r0-13, r0-14, r0-15** — re-captured 2 Sep against the dark
  theme, headless Chrome at 1400px, `DEMO_TODAY=2026-08-20` and a fresh seed.
  These are the current interface.
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
- **r0-08, r0-09 (Actions) and r0-11 (health)** are still from 30–31 Aug and are
  now the oldest in the set. r0-09 predates CI run 145.

`r0-12` and `r0-12b` document a defect that has since been **fixed**. Read them as
history, with `r0-12g` beside them for the current state:

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
one URL shape that both contexts serve. Verified 7 Sep against the running stack —
all six of the paths listed above return 200 through the shell on `:3000`, and the
identical paths return 200 on `:3005`. Bare `/ui/bills`, `/css/bills.css` and
`/js/app.js` still 404 at the shell, but nothing requests them any more.
