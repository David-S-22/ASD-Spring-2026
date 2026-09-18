# Shared RAG server (Release 1)

The Lab 8 RAG server, shared by all five features. One process on the host (`127.0.0.1:5003`),
one ChromaDB collection, the three lab tools: `refresh_corpus`, `retrieve_context`,
`answer_question`. Each feature prepares its own corpus as a file (`corpus/<feature>.jsonl`)
from its own database and docs; the server indexes the files and retrieves from them.

```
sophia/rag/build_corpus.py ──writes──▶ corpus/bills.jsonl ──POST /refresh──▶ ChromaDB (tally_enterprise_context)
                                                                                    │
frontend ──▶ feature backend ──▶ MCP server (:8000) ── retrieve_context / answer_question tools ──▶ this server
                                          ◀── ranked chunks · or · answer + citations + confidence ──┘
```

## Run it

```
cd ai-services/rag-server
pip install -r requirements.txt            # flask, requests, chromadb
python rag_http_server.py                  # http://localhost:5003
python ../../sophia/rag/build_corpus.py    # each feature writes its corpus file and refreshes its rows
curl -s localhost:5003/health
```

Embeddings are Chroma's bundled model (all-MiniLM-L6-v2, downloaded once on first use, ~80 MB);
the server does not need Ollama for refresh or retrieval. `answer_question` generates with a local
Ollama model (`RAG_MODEL`, default `qwen2.5:3b`, already in `OLLAMA_PULL_MODELS`; the caller may
name another pulled model per request). Not a Compose service: the assessment requires the RAG
server to stay non-containerised. Its only application client is the shared MCP server on the
same host (`RAG_SERVER_URL=http://localhost:5003`); the loopback bind means containers have no
direct path to it.

## The corpus: what each feature writes

One JSON object per line in `corpus/<feature>.jsonl` — the lecture's "traceable corpus":

```
{"chunk_id": "bills:dispute/2",            unique, "<feature>:<what>"
 "source_id": "bills-db:/disputes",        where it came from (a citation shows this)
 "authority_tier": "tier_1",               tier_1 record · tier_2 approved doc · tier_3 repository content
 "text": "Dispute #2 for bill #12 GymCo: reason \"Charged after I cancelled\", status draft, opened 2026-08-16.",
 "metadata": {"record": "dispute", "bill_id": 12, "status": "draft"}}   optional, flat, filterable
```

How to chunk (Lecture 8, Corpus Preparation): keep each database record as its own chunk, written
as one plain sentence with money in dollars and dates as stored; split document text into
deterministic blocks of up to 80 words. `indexed_at` is added at refresh. The file is generated
(gitignored) — commit the script that writes it, not the file.

## Endpoints

| Endpoint | Input | Returns |
|---|---|---|
| `GET /health` | – | collection, distance threshold, indexed features + counts |
| `POST /refresh` | `feature`? | rebuilds one feature's rows (or the whole collection) from the corpus files |
| `POST /retrieve` | `query`, `k`=5, `feature`?, `where`? | `results[]` ranked by authority tier then distance |
| `POST /answer` | `query`, `k`=5, `feature`?, `model`? | `answer`, `citations[]`, `confidence_category`, `retrieval_summary`, `insufficient_context` |
| `GET /chunks` | `feature`, `limit`? | what is indexed for a feature (knowledge-sources evidence) |

Full input/output contracts: `tool-contracts.md`. `answer_question` returns
`"Insufficient evidence."` — with no model call — when nothing retrieved is within
`RAG_MAX_DISTANCE` (0.55 by default; tune once with `rag_eval.py`). Confidence is High / Medium /
Low / Unknown from the tiers of the chunks used, never from the model.

## How a feature uses it

Through the shared MCP server's tools, never directly. Either ask for the answer:

```python
out = mcp_client.call_tool("answer_question", {"query": q, "feature": "bills"})
# out["answer"], out["citations"], out["confidence_category"], out["insufficient_context"]
```

or take the ranked chunks and write the answer with your own prompt and model:

```python
ctx = mcp_client.call_tool("retrieve_context", {"query": q, "feature": "bills"})
evidence = [r for r in ctx["results"] if r["distance"] <= 0.55]       # same threshold the server uses
if not evidence:  show the insufficient-evidence response, do not call the model
```

Either way the UI shows the answer, one chip per citation (`source_id`), and the confidence category.

The MCP server relays both with the same shape as its `search_transactions` tool:

```python
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:5003")

@mcp.tool()
def answer_question(query: str, feature: str, k: int = 5) -> dict:
    """Grounded answer with citations and a confidence category, or "Insufficient evidence."."""
    r = requests.post(f"{RAG_SERVER_URL}/answer", json={"query": query, "feature": feature, "k": k}, timeout=120)
    r.raise_for_status()
    return r.json()
```

## What each file is for

- `rag_pipeline.py` — the pipeline: reads the corpus files, indexes them in Chroma, and the three tools.
  Same names and contracts as Lab 8's `rag_pipeline.py`; Chroma's own embeddings instead of the lab's
  hashed vectors; a distance threshold instead of a lexical fallback.
- `rag_http_server.py` — the thing you run. Flask routes that call the pipeline. Loopback only.
- `rag_eval.py` — P@5 / R@5 and the insufficient-evidence check for every `*/rag/benchmarks.json`,
  written to `retrieval-metrics.md`. This is the retrieval evidence for the report.
- `tool-contracts.md` — inputs and outputs of the three tools and the corpus chunk format.
- `corpus/` — one `<feature>.jsonl` per feature, generated by that feature's script (gitignored).
- `tests/test_rag_pipeline.py` — pytest, no Chroma or Ollama: confidence rule, the insufficient gate,
  the answer contract, corpus validation.
- `requirements.txt` — flask, requests, chromadb.
- `.gitignore` — generated files: `chroma/`, `corpus/*.jsonl`, `rag-audit.jsonl`, `retrieval-metrics.md`.

Generated at runtime: `rag-audit.jsonl` (one line per tool call: request id, tool, input, output
summary, duration) and `retrieval-metrics.md`.

## Add your feature (~20 minutes)

1. Copy `sophia/rag/build_corpus.py` to `<you>/rag/build_corpus.py`. Change `FEATURE`, the database
   URL, the record sentences and the `DOCS` list. Keep one chunk per record (`tier_1`) and ≤80-word
   blocks for docs (`tier_2`).
2. Copy `sophia/rag/benchmarks.json`: one question your records answer, one your docs answer, one
   nothing answers (`expect_insufficient`).
3. `python <you>/rag/build_corpus.py` (writes `corpus/<feature>.jsonl` and refreshes your rows) ·
   `curl "localhost:5003/chunks?feature=<feature>&limit=5"` · `python rag_eval.py <you>/rag/benchmarks.json`.
4. Commit your two files only.

## How this maps to Lecture 8 / Lab 8

| Lecture / lab | Here |
|---|---|
| Corpus preparation: ingest → normalise → chunk; records as discrete chunks, reports in ≤80-word blocks; `chunk_id`, `source_id`, `authority_tier`, `indexed_at`; one chunk per line in `corpus.jsonl` | `corpus/<feature>.jsonl`, written by each feature's `build_corpus.py` |
| Enterprise source tiers: 1 operational data, 2 approved reports, 3 repository content | `authority_tier` |
| Vector index: persistent Chroma collection, same embedding function for documents and queries, rebuild = delete and recreate | `refresh_corpus`, Chroma default embeddings |
| Top-k search, ranked by authority tier then distance; evidence record `rank, chunk_id, source_id, authority_tier, distance, text` | `retrieve_context` |
| Grounded answer contract: only retrieved context, "Insufficient evidence", citations (`chunk_id, source_id, authority_tier`), confidence from evidence, retrieval summary | `answer_question` |
| Service integration: MCP tools and/or HTTP API | HTTP here; the shared MCP server relays |
| Evaluation: P@5, R@5 on benchmark queries, written to `retrieval-metrics.md` | `rag_eval.py` |
| Audit log | `rag-audit.jsonl` |

Deliberate differences: Chroma's bundled embedding model instead of the lab's hashed 256-d
vectors (real similarity, no code); a distance threshold decides "Insufficient evidence" in code
instead of leaving it to the prompt; no lexical fallback and no `deterministic_answer()`; the
corpus is written by each feature rather than by the server walking the repo, because five
features hold their knowledge in five databases.

## Architectural decision (for the report)

**Decision.** One shared, non-containerised RAG server on the host, one ChromaDB collection,
the three Lab 8 tools. Corpus preparation belongs to each feature: a script in the feature's
folder turns that feature's records and approved docs into a traceable corpus file; the server
indexes the files and serves retrieval and grounded answers. The server's single application
client is the shared MCP server, which relays `retrieve_context` and `answer_question`; a feature
may take the grounded answer from the server or take the ranked chunks into its own prompt and
model, applying the same distance threshold.

**Why.** It is the pattern the subject teaches (Lecture 8, Lab 8), so the boundary, the tiers,
the contracts and the evaluation are recognisable to a marker without explanation. Keeping
corpus preparation with each feature respects that the five features hold their knowledge in
five databases with different models and prompts, while one server keeps a single index, a
single place where "insufficient evidence", citations and confidence are decided identically for
everyone, and a single set of terminal-validation and retrieval-metrics artefacts. Routing all
access through the MCP server gives the integrated application one AI tool layer; the loopback
bind makes that the only path.

**Consequence.** A request is traceable identically for any feature: frontend → backend → MCP
tool → RAG `/retrieve` or `/answer` → Chroma → ranked evidence → (server or backend) answer with
citations and confidence. Ingestion is traceable per feature (`build_corpus.py` →
`corpus/<feature>.jsonl` → `POST /refresh` → `GET /chunks`). Retrieval quality is measured with
`rag_eval.py` and recorded in `retrieval-metrics.md`; every tool call is audited in
`rag-audit.jsonl`.
