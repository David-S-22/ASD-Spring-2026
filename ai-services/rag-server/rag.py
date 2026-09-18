"""Context retrieval for the shared RAG server. No generation happens here.

Chroma owns the vectors: it calls Ollama to embed (embedding_function), stores documents +
metadata, finds the nearest chunks (query_texts), filters on metadata (where) and persists to
disk. Each feature gets its own collection ("rag_<feature>"), so features are ingested,
refreshed and searched independently and never see each other's rows.

This file adds only what a vector store has no opinion on:
  refresh_corpus(feature)   which sources to (re)read — runs the feature's loader, replaces its collection
  retrieve_context(...)     Chroma's query() flattened into rows, plus the three things every caller needs
                            and that depend on the retrieval result alone: citations, a confidence
                            category (Lab 8 tier rule) and the insufficient-context decision (MAX_DISTANCE)
  chunks(...)               what is indexed right now — Chroma's get() flattened (knowledge-sources evidence)

The feature's backend takes the returned bundle (context + citations + confidence) into its own
prompt and its own model. See README "How a backend uses the bundle".
"""
import json
import time
from datetime import datetime, timezone

import chromadb
from chromadb.errors import ChromaError
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

import config
import corpus

_client = chromadb.PersistentClient(path=config.CHROMA_DIR)
_embed = OllamaEmbeddingFunction(url=config.OLLAMA_URL, model_name=config.EMBED_MODEL, timeout=config.EMBED_TIMEOUT)


class ModelUnavailable(Exception):
    """Ollama could not be reached or refused the request (server.py turns this into a 502)."""


def collection_name(feature):
    return f"rag_{feature}"


def collection(feature):
    """The feature's own collection. Cosine space so distances mean the same thing across runs."""
    return _client.get_or_create_collection(collection_name(feature), embedding_function=_embed,
                                            metadata={"hnsw:space": "cosine"})


def indexed_features():
    """Features that currently have a collection, with their chunk counts."""
    counts = {}
    for col in _client.list_collections():
        name = col.name if hasattr(col, "name") else str(col)
        if name.startswith("rag_"):
            counts[name[len("rag_"):]] = _client.get_collection(name, embedding_function=_embed).count()
    return counts


def _require_model():
    """Fail fast with one clear error when Ollama is down, instead of a Chroma stack trace per chunk."""
    try:
        _embed(["ping"])
    except Exception as exc:
        raise ModelUnavailable(f"embedding model {config.EMBED_MODEL} at {config.OLLAMA_URL}: {exc}") from exc


def _rows(ids, documents, metadatas, distances=None):
    """Chroma answers in columns (ids[], documents[], metadatas[]); everything downstream wants rows."""
    rows = []
    for i, (id_, text, meta) in enumerate(zip(ids, documents, metadatas)):
        row = {"rank": i + 1, "id": id_, **(meta or {}), "text": text}
        if distances is not None:
            row["distance"] = round(distances[i], 3)
        rows.append(row)
    return rows


# --- the tools -------------------------------------------------------------------------

def refresh_corpus(feature=None):
    """Re-read one feature's sources (or every feature's) into that feature's collection. The
    collection is rebuilt, so a row that disappeared from the database disappears from the index.
    A loader that fails is reported under its name; the other features are untouched."""
    started = time.time()
    _require_model()
    report = {}
    for name in ([feature] if feature else corpus.features()):
        try:
            chunks = corpus.load(name)
            try:
                _client.delete_collection(collection_name(name))
            except Exception:
                pass
            col = collection(name)
            if chunks:
                col.add(ids=[c["id"] for c in chunks],
                        documents=[c["text"] for c in chunks],
                        metadatas=[c["metadata"] for c in chunks])
            report[name] = f"ok ({len(chunks)} chunks)"
        except Exception as exc:
            report[name] = f"error: {exc}"
    result = {"status": "success", "features": indexed_features(), "loaders": report}
    _audit("refresh_corpus", {"feature": feature}, {"features": result["features"]}, started)
    return result


def confidence(results):
    """Team-wide rule (Lab 8): High = at least two tier-1 hits among three or more results;
    Medium = one tier-1 hit or two tier-2 hits; otherwise Low; Unknown when nothing was retrieved."""
    if not results:
        return "Unknown"
    tier1 = sum(1 for r in results if r["tier"] == 1)
    tier2 = sum(1 for r in results if r["tier"] == 2)
    if tier1 >= 2 and len(results) >= 3:
        return "High"
    if tier1 >= 1 or tier2 >= 2:
        return "Medium"
    return "Low"


def retrieve_context(query, feature, k=config.DEFAULT_K, where=None):
    """The k chunks of `feature` nearest the query, plus everything the caller needs to build a
    grounded prompt and display evidence. `where` is any Chroma metadata filter, e.g.
    {"record": "dispute"} or {"tier": 1}.

    Output:
      results[]             every retrieved chunk: id, distance, text and the loader's metadata
      relevant[]            the subset within MAX_DISTANCE — the only chunks a backend should show the model
      context               relevant chunks joined as "[id] text" lines, ready to paste into a prompt
      citations[]           id + metadata of each relevant chunk (what the UI shows as source chips)
      confidence_category   High / Medium / Low / Unknown, from the tiers of the relevant chunks
      insufficient_context  True when no chunk is within MAX_DISTANCE — the backend must show the
                            insufficient-context response and must not call its model
    """
    started = time.time()
    if feature not in indexed_features():
        refresh_corpus(feature)
    col = collection(feature)
    if col.count() == 0:
        results = []
    else:
        try:
            found = col.query(query_texts=[query], n_results=max(1, min(k, col.count())), where=where or None)
        except ChromaError as exc:                  # a bad where-filter from the caller → 400
            raise ValueError(f"bad where filter {where!r}: {exc}") from exc
        except Exception as exc:                    # Ollama down while embedding the query → 502
            raise ModelUnavailable(f"embedding model {config.EMBED_MODEL}: {exc}") from exc
        results = _rows(found["ids"][0], found["documents"][0], found["metadatas"][0], found["distances"][0])
    relevant = [r for r in results if r["distance"] <= config.MAX_DISTANCE]
    output = {
        "status": "success", "query": query, "feature": feature, "k": k, "where": where,
        "results": results,
        "relevant": relevant,
        "context": "\n".join(f"[{r['id']}] {r['text']}" for r in relevant),
        "citations": [{key: value for key, value in r.items() if key not in ("rank", "text")} for r in relevant],
        "confidence_category": confidence(relevant) if relevant else "Low",
        "insufficient_context": not relevant,
        "retrieval_summary": {"retrieved": len(results), "relevant": len(relevant),
                              "closest_distance": results[0]["distance"] if results else None,
                              "max_distance": config.MAX_DISTANCE},
    }
    _audit("retrieve_context", {"query": query, "feature": feature, "k": k, "where": where},
           {"relevant": len(relevant), "confidence": output["confidence_category"],
            "insufficient": output["insufficient_context"]}, started)
    return output


def chunks(feature, where=None, limit=None):
    """What is indexed for a feature right now — Chroma's get() flattened. This is the
    'knowledge sources' evidence for the report."""
    if feature not in indexed_features():
        return {"status": "success", "feature": feature, "count": 0, "total": 0, "chunks": []}
    col = collection(feature)
    try:
        got = col.get(where=where or None, limit=limit)
    except ChromaError as exc:
        raise ValueError(f"bad where filter {where!r}: {exc}") from exc
    return {"status": "success", "feature": feature, "count": len(got["ids"]), "total": col.count(),
            "chunks": _rows(got["ids"], got["documents"], got["metadatas"])}


def _audit(tool, inputs, summary, started):
    """One JSON line per call: what was asked, what came back, how long it took (traceability NFR)."""
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tool": tool,
              "input": inputs, "output": summary, "ms": int((time.time() - started) * 1000)}
    with open(config.AUDIT_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
