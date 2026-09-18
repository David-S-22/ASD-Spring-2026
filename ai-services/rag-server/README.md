# Shared RAG server (Release 1) — store and retrieve

One server process on the host, **127.0.0.1:5003**, with exactly one application client: the
**MCP server's context tool**. Each feature pushes its own corpus into its own ChromaDB collection
(`POST /ingest`), chunked however that feature likes, from a script in that feature's folder.
For a question, the server returns the relevant context together with the evidence a grounded
answer needs: **citations**, a **confidence category** and the **insufficient-context** decision.
It does not chunk anything and it does not call a chat model. Feature backends never call this
server; they call the MCP tool, and take the bundle it relays into their own prompt and their
own model.

```
<you>/rag/<feature>.py ──POST /ingest──▶ RAG server (host 127.0.0.1:5003) ──▶ Chroma: rag_<feature>
                                                    ▲
frontend ──▶ feature backend ──▶ MCP server (host :8000) ── retrieve_context tool ──┘
                  backend prompt + own model ◀── bundle (context, citations, confidence, insufficient)
```

The server binds to the loopback interface on purpose: containers cannot reach `127.0.0.1` via
`host.docker.internal`, so there is no direct path from any backend. Host-side validation (curl,
`eval.py`, the agentic loop) and each feature's ingest script use the same `localhost:5003`.

## Run it

```
cd ai-services/rag-server
pip install -r requirements.txt       # flask, requests, chromadb
python server.py                      # http://localhost:5003
python ../../sophia/rag/bills.py      # each feature pushes its own corpus (needs its database up)
```

Embeddings are Chroma's own bundled model (all-MiniLM-L6-v2, run through onnxruntime, both already
chromadb dependencies). The first ingest downloads it once (~80 MB, into `~/.cache/chroma/`); after
that the server works offline. The server does not use Ollama at all — Ollama is only what the
feature backends generate with. The same model embeds every feature's chunks and every query,
which is what makes the distances comparable.

Not a Compose service (the assessment requires the RAG server to stay non-containerised), and
nothing in Compose points at it: the only client is the MCP server on the same host, configured
with `RAG_SERVER_URL=http://localhost:5003`. Backends get their RAG access through the MCP
server's Compose wiring, not through a RAG URL of their own.

## Endpoints

| Endpoint | Input | Returns |
|---|---|---|
| `GET /health` | – | embed model, distance threshold, indexed features + chunk counts |
| `POST /ingest` | `feature`, `chunks[]`, `replace`? | stores the chunks in that feature's collection |
| `POST /retrieve` | `query`, `feature`, `k`=5, `where`? | the bundle below |
| `GET /chunks` | `feature`, `where`? (JSON), `limit`? | what is indexed for that feature, with metadata |
| `DELETE /chunks` | `feature` | drops that feature's collection |

A chunk is Chroma's own contract, nothing more:

```
{"id": "bills:dispute/2",                         unique within your feature
 "text": "Dispute #2 for bill #12 GymCo: …",      what gets embedded and shown to the model
 "metadata": {"tier": 1, "record": "dispute", "status": "draft"}}   flat str/int/float/bool — optional
```

`replace: true` rebuilds the collection from exactly the chunks you send (a row that disappeared
from your database disappears from the index); the default upserts, so several pushes add up.
`tier` is the one metadata key the server reads: `1` = a database row (a fact), anything else or
missing = a document. It feeds the confidence category only.

`/retrieve` returns:

```
results[]             every retrieved chunk: id, distance, text + the metadata you pushed
relevant[]            the subset within RAG_MAX_DISTANCE — the only chunks to show a model
context               relevant chunks as "[id] text" lines, ready to paste into a prompt
citations[]           id + metadata of each relevant chunk (source chips in the UI)
confidence_category   High / Medium / Low (Lab 8 tier rule) — Low when insufficient
insufficient_context  true when nothing is within RAG_MAX_DISTANCE
```

`where` is any Chroma metadata filter, e.g. `{"record": "dispute"}`, `{"tier": 1}`, `{"bill_id": 12}`.

Errors: a bad request (missing fields, non-scalar metadata, bad `where`) is a 400 `bad_request`;
the embedding model failing to load (first run with no internet) is a 502 `embedding_unavailable`.

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
- `rag.py` — store and retrieve over Chroma: per-feature collections, `ingest`, `retrieve_context`
  (Chroma `query` flattened into rows + the distance gate, citations and confidence), `chunks`,
  `delete_feature`. No chunking, no model call.
- `config.py` — every setting, read from env with a localhost default (port, bind address, Chroma
  directory, `RAG_MAX_DISTANCE`). Change things here, nowhere else.
- `eval.py` — runs one feature's `benchmarks.json` against the running server and prints P@5 / R@5 and
  the insufficient-context check. This is the retrieval evidence for the report and how you tune
  `RAG_MAX_DISTANCE`. Needs the server up and the feature's corpus pushed.
- `tests/test_rag_rules.py` — pytest, no Chroma needed: the confidence rule, the distance
  gate, the bundle shape, the ingest validation.
- `requirements.txt` — flask, requests, chromadb. Nothing else; the embedding model comes with chromadb.
- `.gitignore` — the generated files: `chroma/` (the vector store) and `audit.jsonl` (one line per call).

## Add your feature (everything lives in your own folder)

Write one script, `<you>/rag/<feature>.py`, that builds your chunks and posts them. How you chunk is
yours. Chroma's recommended approach for markdown is LangChain's two splitters (header-aware, then
size-limited — https://docs.trychroma.com/guides/build/chunking); `pip install langchain-text-splitters`
is the whole dependency. `sophia/rag/bills.py` is a worked example: one plain sentence per database row
with the row's columns as metadata (`tier: 1`), documents chunked with the LangChain splitters
(`tier: 2`), then one `POST /ingest` with `replace: true`.

```python
requests.post("http://localhost:5003/ingest",
              json={"feature": "savings", "replace": True, "chunks": chunks}, timeout=120).raise_for_status()
```

Next to it, `<you>/rag/benchmarks.json`: one question your rows answer, one your docs answer, one
nothing answers (`expect_insufficient`). Then:

```
python <you>/rag/<feature>.py
curl "localhost:5003/chunks?feature=<feature>&limit=5"
python ai-services/rag-server/eval.py <you>/rag/benchmarks.json
```

## Architectural decision (for the report)

**Decision.** One shared, non-containerised RAG server on the host owns indexing and retrieval for
all five features, with one ChromaDB collection per feature. Ingestion belongs to each feature:
a script in the feature's own folder turns that feature's rows and documents into chunks, chunked
as that feature sees fit, and pushes them to the server. The server's single application client is
the shared MCP server's `retrieve_context` tool; feature backends reach retrieval only through
that tool. The server returns retrieved context with citations, a confidence category and the
insufficient-context decision; each feature's backend generates the grounded answer from that
bundle with its own prompt and model.

**Why.** The five features use different models and prompts and hold their knowledge in five
separate databases, so the content of each corpus, and the right way to chunk it, is feature
knowledge rather than shared knowledge. Keeping the shared part down to Chroma's own contract
(an id, a text, flat metadata) means the server carries no opinion about anyone's data, while
one independently identifiable server still gives the assessment a clear RAG boundary, one place
where indexing and retrieval occur, and one place where the evidence rules (what counts as
relevant, how confidence is computed, when context is insufficient) are enforced identically for
every feature. Per-feature collections keep feature knowledge separated without splitting the
server. Routing all access through the MCP tool gives the integrated application one AI tool
layer and one contract to validate, and binding the server to the loopback interface makes that
the only path rather than a convention. Leaving generation in each backend preserves each
feature's existing AI-Mode prompts and model choice and keeps the frontend unaware of both servers.

**Consequence.** Every backend follows the same two rules (no model call when
`insufficient_context` is true; the model sees only `context`), so a request can be traced
identically for any feature: frontend → backend → MCP `retrieve_context` tool → RAG
`/retrieve` → bundle → backend prompt → model → answer with citations and confidence. Ingestion is
traceable per feature (`<you>/rag/<feature>.py` → `POST /ingest` → `GET /chunks`), and terminal
validation of the server is host-local (`curl localhost:5003`, `eval.py`, the agentic loop's RAG
mode). The Assessment 2 page describes the RAG server as generating the grounded response; the
team read the tutor's guidance (18 Sep) as accepting either placement provided the boundary,
scoping and trace are documented, and chose backend generation for the reasons above. Adding a
shared `/answer` endpoint later would be additive.
