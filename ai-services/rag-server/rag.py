"""Store-and-retrieve over ChromaDB. No ingestion logic and no generation live here.

Each feature owns its corpus: it decides what its rows and documents become as text, how they are
chunked and what metadata they carry, and pushes the result to this server (POST /ingest). The
server keeps one Chroma collection per feature ("rag_<feature>"), so features are indexed and
searched independently and never see each other's rows.

Chroma owns the vectors: it embeds with its own bundled model (all-MiniLM-L6-v2, downloaded once
on first use — no Ollama involved), stores documents + metadata, finds the nearest chunks
(query_texts), filters on metadata (where) and persists to disk. This file adds only what a vector
store has no opinion on:
  ingest(feature, chunks, replace)   accept a feature's chunks (Chroma's own contract: id, text, flat metadata)
  retrieve_context(...)              Chroma's query() flattened into rows, plus the three things every caller
                                     needs that depend on the retrieval result alone: citations, a confidence
                                     category (Lab 8 tier rule) and the insufficient-context decision
  chunks(...) / delete_feature(...)  what is indexed right now; remove a feature's collection
"""
import json
import time
from datetime import datetime, timezone

import chromadb
from chromadb.errors import ChromaError

import config

_client = chromadb.PersistentClient(path=config.CHROMA_DIR)

EMBED_MODEL = "chroma default (all-MiniLM-L6-v2)"   # informational — Chroma picks it when no embedding_function is given
SCALARS = (str, int, float, bool)


class EmbeddingUnavailable(Exception):
    """Chroma's embedding model could not be loaded (server.py turns this into a 502). The first run
    downloads all-MiniLM-L6-v2 (~80 MB) into ~/.cache/chroma/, so this is almost always "no internet
    on first start"; afterwards it works offline."""


def collection_name(feature):
    return f"rag_{feature}"


def collection(feature):
    """The feature's own collection, embedded by Chroma's default model. Cosine space so distances
    mean the same thing across runs."""
    return _client.get_or_create_collection(collection_name(feature), metadata={"hnsw:space": "cosine"})


def indexed_features():
    """Features that currently have a collection, with their chunk counts."""
    counts = {}
    for col in _client.list_collections():
        name = col.name if hasattr(col, "name") else str(col)
        if name.startswith("rag_"):
            counts[name[len("rag_"):]] = _client.get_collection(name).count()
    return counts


def _embedding_failed(exc):
    return EmbeddingUnavailable(f"Chroma's embedding model (all-MiniLM-L6-v2) could not be loaded — the first "
                                f"run downloads it, so check internet access and try again: {exc}")


def _rows(ids, documents, metadatas, distances=None):
    """Chroma answers in columns (ids[], documents[], metadatas[]); everything downstream wants rows."""
    rows = []
    for i, (id_, text, meta) in enumerate(zip(ids, documents, metadatas)):
        row = {"rank": i + 1, "id": id_, **(meta or {}), "text": text}
        if distances is not None:
            row["distance"] = round(distances[i], 3)
        rows.append(row)
    return rows


def _validate(feature, chunks):
    """Only what Chroma itself needs, said in plain English instead of a Chroma stack trace."""
    if not feature or not feature.replace("_", "").replace("-", "").isalnum():
        raise ValueError("feature must be a short name such as 'bills'")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("chunks must be a non-empty list")
    seen = set()
    for i, c in enumerate(chunks):
        if not isinstance(c, dict) or not c.get("id") or not c.get("text"):
            raise ValueError(f"chunk {i} needs a non-empty 'id' and 'text'")
        if c["id"] in seen:
            raise ValueError(f"duplicate chunk id {c['id']!r}")
        seen.add(c["id"])
        meta = c.get("metadata") or {}
        if not isinstance(meta, dict):
            raise ValueError(f"chunk {c['id']!r}: metadata must be an object")
        bad = {k: v for k, v in meta.items() if not isinstance(v, SCALARS)}
        if bad:
            raise ValueError(f"chunk {c['id']!r}: metadata values must be str/int/float/bool, got {bad}")


# --- the tools -------------------------------------------------------------------------

def ingest(feature, chunks, replace=False):
    """Store a feature's chunks. replace=True rebuilds the feature's collection from exactly these
    chunks (a row that disappeared from your database disappears from the index); replace=False
    upserts, so several pushes can add up. The 'feature' metadata is set for you."""
    started = time.time()
    _validate(feature, chunks)
    if replace:
        try:
            _client.delete_collection(collection_name(feature))
        except Exception:
            pass
    col = collection(feature)
    try:
        col.upsert(ids=[c["id"] for c in chunks],
                   documents=[c["text"] for c in chunks],
                   metadatas=[{**(c.get("metadata") or {}), "feature": feature} for c in chunks])
    except ChromaError as exc:                      # e.g. a metadata value Chroma rejects → 400
        raise ValueError(str(exc)) from exc
    except Exception as exc:                        # the embedding model itself → 502
        raise _embedding_failed(exc) from exc
    result = {"status": "success", "feature": feature, "received": len(chunks), "replace": replace, "indexed": col.count()}
    _audit("ingest", {"feature": feature, "received": len(chunks), "replace": replace}, {"indexed": col.count()}, started)
    return result


def delete_feature(feature):
    """Remove a feature's collection entirely."""
    existed = feature in indexed_features()
    if existed:
        _client.delete_collection(collection_name(feature))
    return {"status": "success", "feature": feature, "deleted": existed}


def confidence(results):
    """Team-wide rule (Lab 8): High = at least two tier-1 hits among three or more results;
    Medium = one tier-1 hit or two tier-2 hits; otherwise Low; Unknown when nothing was retrieved.
    tier is optional metadata: 1 = a database row (fact); anything else, or missing, counts as 2 (a doc)."""
    if not results:
        return "Unknown"
    tier1 = sum(1 for r in results if r.get("tier") == 1)
    tier2 = len(results) - tier1
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
      results[]             every retrieved chunk: id, distance, text and the metadata it was pushed with
      relevant[]            the subset within MAX_DISTANCE — the only chunks a backend should show the model
      context               relevant chunks joined as "[id] text" lines, ready to paste into a prompt
      citations[]           id + metadata of each relevant chunk (what the UI shows as source chips)
      confidence_category   High / Medium / Low / Unknown, from the tiers of the relevant chunks
      insufficient_context  True when no chunk is within MAX_DISTANCE — the backend must show the
                            insufficient-context response and must not call its model
    """
    started = time.time()
    results = []
    if feature in indexed_features():
        col = collection(feature)
        if col.count():
            try:
                found = col.query(query_texts=[query], n_results=max(1, min(k, col.count())), where=where or None)
            except ChromaError as exc:                  # a bad where-filter from the caller → 400
                raise ValueError(f"bad where filter {where!r}: {exc}") from exc
            except Exception as exc:                    # the embedding model itself → 502
                raise _embedding_failed(exc) from exc
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
