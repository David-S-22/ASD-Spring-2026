# ADR: Bills delivers its RAG corpus as a generated folder

Status: accepted, 26 Sep 2026. Owner: Sophia Nguyen (Bills List & Dispute Assistant).

## Context

The shared retrieval server (`ai-services/rag-server/`, PR #152) keeps one
Chroma collection per feature and answers `POST /retrieve`; by team decision
(18 Sep) it does retrieval only, and the Bills backend reaches it through the
MCP tool `retrieve_context` alone. PR #152 filled the `bills` collection by
pushing five hand-written sentences through `POST /refresh`. PR #154 adds
folder ingestion: every `sources/<feature>/` folder is chunked with LangChain
splitters and stored under the folder's name, at server start-up and on
`POST /sources/refresh`.

## Decision

Bills adopts the folder model. `ai-services/rag-server/sources/billing/` holds
one Markdown file per bill — name, merchant, type, cadence, amount, next
billing date, the stored status, payment method, last payment and the count of
open disputes — generated from the bills database by
`python -m sophia.rag.build_corpus` and committed. The `test` job in Sophia-CI
runs `--from-seed --check` and fails when the committed folder differs from a
fresh build. The push-model files from #152 (`bills_corpus.py` constants,
`bills_ragtest.py`, `test_bills_rag.py`) are removed; `mcp_ragtest.py` stays
as the end-to-end check.

## Alternatives considered

- **Keep pushing through `/refresh`** (the 18 Sep plan). Rejected: #154 ships
  a `sources/billing/` copy of the same sentences under a second collection
  name, so two corpora would compete, and a push has to be repeated by hand
  on every fresh store (a new clone, or a rebuilt container without a
  volume).
- **Hybrid: the server ingests from a path under `sophia/`.** Rejected: it
  needs a change to the shared server that Bills does not own.
- **A hand-written explainer file next to the bill files** (what paid, due and
  overdue mean, how cadence works). Deferred: measured with the server's
  default embedder, such a file outranks the Home internet chunk for "Which
  bill is overdue?", so it would blunt the one-chunk-per-bill retrieval until
  the loader supports front-matter metadata or the chat filters by file.

## Consequences

- One file is one chunk. Files stay under 800 characters because the server's
  splitters default to 4,000-character chunks and its embedder reads roughly
  the first 1,000. Every line is a stored fact; nothing is invented.
- Chunk metadata is whatever the loader sets (`source`, `feature`,
  `doc_type`); type and status live in the text and the file name until front
  matter lands in the loader.
- Bills excluded from the monthly plan stay in the corpus, with a line saying
  so — they are still bills the user may ask about.
- The corpus must be regenerated whenever the seed or the demo data changes;
  CI enforces that, and a bill that would exceed the cap stops the build
  rather than being truncated.
- `sophia/rag/test_sources_bills.py` ingests the committed folder into a
  throwaway `bills-ragtest` collection; the server's own `bills` collection is
  written only by the server's ingestion.
- RAG does not run in CI: the rubric has AI Mode, MCP and RAG disabled during
  CI/CD, so Sophia-CI's `rag` job is removed. The `test` job runs the
  freshness check and the two non-RAG corpus test files; the retrieval-order
  test above is a local check that skips in CI.

## Amendment, 29 Sep 2026

The generated files now live in `ai-services/rag-server/sources/billing/`,
beside the two hand-written files already there (`billing_overview.md` and
`billing_policy.pdf`), so the server ingests them into the `billing`
collection; there is no `bills` collection. Bills answers use only its own
`bill-*.md` sources: the hand-written overview and policy PDF are not Bills
data, and `evidence.retrieve` drops them before the distance gate and the
citations. Measured with all chunks in one collection, every Bills question's
best match is unchanged, but the overview enters the second and third slots
inside the low-confidence threshold for four on-topic questions and a late-fee
question pulls in both hand-written files, hence the filter by source. The
build and its `--check` only ever touch `bill-*.md`.
