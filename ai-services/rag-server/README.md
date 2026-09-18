# Shared RAG server (Release 1) — context retrieval

One server process on the host, **127.0.0.1:5003**, with exactly one application client: the
**MCP server's context tool**. It ingests each feature's knowledge into its own ChromaDB
collection and, for a question, returns the relevant context together with the evidence a
grounded answer needs: **citations**, a **confidence category** and the **insufficient-context**
decision. It does not call a chat model. Feature backends never call this server; they call the
MCP tool, and take the bundle it relays into their own prompt and their own model.

```
frontend ──▶ feature backend ──▶ MCP server (host :8000) ── context tool ──▶ RAG server (host 127.0.0.1:5003)
                                                                                 │ Chroma: rag_<feature>
                  backend prompt + own model ◀── bundle ◀──────────────────────────┘
```

The server binds to the loopback interface on purpose: containers cannot reach `127.0.0.1` via
`host.docker.internal`, so there is no direct path from any backend. Host-side validation (curl,
`eval.py`, the agentic loop) uses the same `localhost:5003`.

## Run it

```
docker compose up -d                  # the ollama service publishes :11434 on the host
docker exec ollama ollama pull nomic-embed-text   # once per machine — or add it to OLLAMA_PULL_MODELS
cd ai-services/rag-server
pip install -r requirements.txt
python server.py                      # http://localhost:5003
curl -s -X POST localhost:5003/refresh
```

Not a Compose service (the assessment requires the RAG server to stay non-containerised), and
nothing in Compose points at it: the only client is the MCP server on the same host, configured
with `RAG_SERVER_URL=http://localhost:5003`. Backends get their RAG access through the MCP
server's Compose wiring, not through a RAG URL of their own.

## Endpoints

| Endpoint | Input | Returns |
|---|---|---|
| `GET /health` | – | embed model, distance threshold, indexed features + chunk counts |
| `GET /chunks` | `feature`, `where`? (JSON), `limit`? | what is indexed for that feature, with metadata |
| `GET /benchmarks` | – | every feature's `BENCHMARKS` (the agentic loop's RAG mode runs these) |
| `POST /refresh` | `feature`? | re-reads one feature's sources (or all); per-feature `loaders` report |
| `POST /retrieve` | `query`, `feature`, `k`=5, `where`? | the bundle below |

`/retrieve` returns:

```
results[]             every retrieved chunk: id, distance, text + the loader's metadata
relevant[]            the subset within RAG_MAX_DISTANCE — the only chunks to show a model
context               relevant chunks as "[id] text" lines, ready to paste into a prompt
citations[]           id + metadata of each relevant chunk (source chips in the UI)
confidence_category   High / Medium / Low (Lab 8 tier rule) — Low when insufficient
insufficient_context  true when nothing is within RAG_MAX_DISTANCE
```

`where` is any Chroma metadata filter, e.g. `{"record": "dispute"}`, `{"tier": 1}`, `{"bill_id": 12}`.

## The one access point: the MCP context tool

The MCP server (`ai-services/mcp-server/server.py`, FastMCP over HTTP on :8000) is the only
application code that calls this server. The tool is a relay — same style as `search_transactions`:

```python
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:5003")

@mcp.tool()
def retrieve_context(query: str, feature: str, k: int = 5, where: dict | None = None) -> dict:
    """Relevant project context for one feature, with citations, a confidence category and the
    insufficient-context decision. The caller writes the answer from `context`.

    Args:
        query: the user's question.
        feature: which feature's knowledge to search (bills, savings, transactions, anomalies, budgets).
        k: how many chunks to retrieve (default 5).
        where: optional Chroma metadata filter, e.g. {"record": "dispute"}.
    """
    resp = requests.post(f"{RAG_SERVER_URL.rstrip('/')}/retrieve",
                         json={"query": query, "feature": feature, "k": k, "where": where}, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

## How a backend uses the bundle it gets back from the tool

```python
bundle = mcp_client.call_tool("retrieve_context", {"query": question, "feature": "bills"})
if bundle["insufficient_context"]:
    return {"answer": None, "citations": [], "confidence": "Low", "insufficient": True}   # show the insufficient card
prompt = MY_PROMPT.format(context=bundle["context"], question=question)     # your prompt, your model
answer = my_model(prompt)
return {"answer": answer, "citations": bundle["citations"],
        "confidence": bundle["confidence_category"], "insufficient": False}
```

Two rules every feature follows so the evidence is comparable: when `insufficient_context` is
true the backend does not call its model, and the model only ever sees `context` (the relevant
chunks), never the raw `results`.

## What each file is for

- `server.py` — the thing you run. Flask routes that parse the request and call `rag.py`. Nothing clever.
- `rag.py` — the retrieval logic: per-feature Chroma collections, `refresh_corpus`, `retrieve_context`
  (Chroma `query` flattened into rows + the distance gate, citations and confidence), `chunks`.
- `corpus.py` — where knowledge comes from: finds every loader in `sources/`, runs and validates it,
  and provides the two extractors loaders use (`row_chunk`, `doc_chunks`). No vectors in here.
- `config.py` — every setting, read from env with a localhost default (port, Ollama URL, embed model,
  `RAG_MAX_DISTANCE`). Change things here, nowhere else.
- `sources/_template.py` — copy me to `sources/<feature>.py`. Files starting with `_` are skipped.
- `sources/bills.py` — worked example (Sophia's loader): rows from `:6005` as tier-1 sentences with
  their columns as metadata, the four Bills docs as tier-2 chunks split by heading.
- `sources/__init__.py` — empty; makes `sources/` importable so `corpus.py` can iterate it.
- `eval.py` — asks the running server every feature's `BENCHMARKS` and prints P@5 / R@5 and the
  insufficient-context check. This is the retrieval evidence for the report and how you tune
  `RAG_MAX_DISTANCE`. Needs Ollama and the databases up.
- `tests/test_rag_rules.py` — pytest, no Chroma or Ollama needed: the confidence rule, the distance
  gate, the bundle shape, the doc/row extractors.
- `requirements.txt` — flask, requests, chromadb, ollama (Chroma's Ollama embedding function uses it).
- `.gitignore` — the generated files: `chroma/` (the vector store) and `audit.jsonl` (one line per call).

## Add your feature (15 minutes)

1. Copy `sources/_template.py` to `sources/<feature>.py`; set `FEATURE`.
2. In `load_chunks()`, fetch your rows from your database API and write one plain sentence per row
   with `corpus.row_chunk(...)` (money in dollars, dates as stored, useful columns as metadata).
   Add your approved docs with `corpus.doc_chunks(config.REPO_ROOT / "docs/release-0/<you>/x.md", FEATURE)`.
3. Fill `BENCHMARKS`: one question your rows answer, one your docs answer, one nothing answers
   (`expect_insufficient`).
4. `python -m pytest tests -q` · `curl -X POST localhost:5003/refresh -d feature=<feature>` ·
   `curl "localhost:5003/chunks?feature=<feature>&limit=5"` · `python eval.py`. Commit only your loader.

## Architectural decision (for the report)

**Decision.** One shared, non-containerised RAG server on the host owns ingestion, indexing and
retrieval for all five features, with one ChromaDB collection per feature. Its single
application client is the shared MCP server's `retrieve_context` tool; feature backends reach
retrieval only through that tool. The server returns retrieved context with citations, a
confidence category and the insufficient-context decision; each feature's backend generates
the grounded answer from that bundle with its own prompt and model.

**Why.** The five features use different models and prompts and hold their knowledge in five
separate databases. Keeping retrieval in one independently identifiable server gives the
assessment a clear RAG boundary, one place where ingestion, indexing and retrieval occur, and
one place where the evidence rules (what counts as relevant, how confidence is computed, when
context is insufficient) are enforced identically for every feature. Per-feature collections
keep feature knowledge separated without splitting the server. Routing all access through the
MCP tool gives the integrated application one AI tool layer and one contract to validate, and
binding the server to the loopback interface makes that the only path rather than a convention.
Leaving generation in each backend preserves each feature's existing AI-Mode prompts and model
choice and keeps the frontend unaware of both servers.

**Consequence.** Every backend follows the same two rules (no model call when
`insufficient_context` is true; the model sees only `context`), so a request can be traced
identically for any feature: frontend → backend → MCP `retrieve_context` tool → RAG
`/retrieve` → bundle → backend prompt → model → answer with citations and confidence. Terminal
validation of the RAG server is host-local (`curl localhost:5003`, `eval.py`, the agentic
loop's RAG mode). The Assessment 2 page describes the RAG server as generating the grounded
response; the team read the tutor's guidance (18 Sep) as accepting either placement provided
the boundary, scoping and trace are documented, and chose backend generation for the reasons
above. Adding a shared `/answer` endpoint later would be additive.
