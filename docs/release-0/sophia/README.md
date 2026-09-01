# Release 0 — Feature 5 (Bills List & Dispute Assistant) — Sophia

Supporting material for the Release 0 technical report. Everything here is
cited from the report; nothing is in the `sophia/` code directory because the
spec's repository layout keeps documentation under `docs/`.

| Path | Report section | What it is |
|---|---|---|
| `../../architecture/r0-d1-individual-architecture.png` | Individual architecture | Three containers and the backend's internal layers |
| `../../architecture/r0-d2-docker-compose-architecture.png` | Docker Compose architecture | Services, ports, volume, host Ollama |
| `../../architecture/r0-d3-paoa-dispute-loop.png` | Plan → Act → Observe → Adapt | The dispute-draft loop |
| `../../architecture/r0-d4-paoa-chat-loop.png` | Plan → Act → Observe → Adapt | The chat loop, compressed |
| `api.md` | Implementation summary | Endpoint reference for the backend (`/api/*`, `/ui/*`) |
| `contracts-inbound.md` | Requirements F5-FR13, risk R2 | Inbound handoff contracts from Features 3 and 4 |
| `schema-adoption.md` | Implementation summary | The four additive schema items |
| `evidence/compose/up.txt` | Docker Compose execution evidence | build → up → ps → health → down, 21 Aug |
| `evidence/compose/compose-ps.txt`, `compose-down.txt`, `curl-endpoints.txt` | Docker Compose execution evidence | Baseline run from the first compose PR |
| `evidence/compose/ui-write-routes.txt`, `four-cases.txt` | Local testing evidence (post) | curl transcripts of every `/ui/*` write route and the four former 500s |
| `evidence/ai/README.md` | Local testing evidence, AI-Mode | What each call tested, the 3/3 and 4/4 results, and the bug the live run found |
| `evidence/ai/*.json` | Local testing evidence, AI-Mode | Seven raw responses from real local Ollama calls (3/3 dispute, 4/4 chat) |
| `evidence/pytest-159-passed.txt` | Local testing evidence | `pytest sophia/test -q` at ed9c5ac |
| `screenshots/r0-NN-*.png` | Screenshots of the integrated application | Numbered to the report's `[SCREENSHOT n]` markers |

Screenshots were captured from `main` at 8ebbf12 (30 Aug) with
`DEMO_TODAY=2026-08-20` and a fresh seed, headless Chrome at 1400px: the
full r0-01…r0-11 set (r0-07 is the pytest run, regenerated at ed9c5ac),
plus r0-13 (the Feature 4 handoff link's prefilled form with its evidence
banner), r0-14 (deep-link landing on an F4-suggested bill's Confirm
prompt), and r0-15 (the 422 error banner for `amount=nan` in a handoff
link).

`r0-12` (feature reached from the shared home page) was captured on 1 Sep,
once #77 had added `shared/frontend/**` and a `shared-frontend` service on
`:3000`. It documents a defect rather than a working path, so read it with
`r0-12b` beside it:

- `r0-12-shell-bills.png` — the Bills tab selected in the shared shell. The
  browser stays on `:3000` and the whole Bills document is swapped into
  `#content`, so the body markup arrives but the `<head>` is dropped by the
  innerHTML parse, taking both stylesheets and the vendored htmx with it.
  The shell's own theme then styles the markup, which is why this shot and
  `r0-12b` differ in colour. Every fragment request resolves against `:3000`,
  where the shell config has no `/ui/`, `/css/` or `/js/` location and no
  `location /` fallback, so `/ui/bills`, `/ui/calendar`, `/ui/timeline`,
  `/ui/disputes-tab`, `/ui/chat` and `/js/app.js` all 404 — twelve console
  errors, and the cards render empty.
- `r0-12b-bills-standalone.png` — the same feature at `:3005`, fully
  rendered, with no console errors and no failed requests.

htmx is not at fault: the shell's htmx processes the swapped content
correctly, which is why those requests fire at all. Bills' own half of the
contract — the missing `/bills-backend/` mapping, which made
`:3000/bills-backend/ui/bills` return `index.html` with a 200 — was fixed in
#86. The head-drop and the root-absolute paths are shell-side and remain
open; see the report's known issues.
