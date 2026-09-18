"""Shared RAG pipeline for Tally — the three Lab 8 tools over one ChromaDB collection.

    refresh_corpus(feature)      read corpus/<feature>.jsonl (or every file) and (re)index it
    retrieve_context(query, ...) top-k vector search, ranked by authority tier then distance
    answer_question(query, ...)  grounded answer contract: answer, citations, confidence, retrieval summary

Corpus preparation is each feature's job (Lecture 8: ingest -> normalise -> chunk, attach source
identity and authority). A feature writes ONE chunk per line into corpus/<feature>.jsonl:

    {"chunk_id": "bills:dispute/2", "source_id": "bills-db:/disputes", "authority_tier": "tier_1",
     "text": "Dispute #2 for bill #12 GymCo: ...", "metadata": {"record": "dispute", "status": "draft"}}

    authority_tier   tier_1 = operational data (a database record)   tier_2 = approved docs/reports
                     tier_3 = repository content
    metadata         optional, flat str/int/float/bool — comes back on every citation, filterable

This file never reads a database or a document itself. Chroma embeds with its bundled model
(all-MiniLM-L6-v2, downloaded once on first use) and does the similarity search.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import requests

BASE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BASE_DIR / "corpus"
AUDIT_PATH = BASE_DIR / "rag-audit.jsonl"
CHROMA_PATH = os.getenv("RAG_CHROMA_DIR", str(BASE_DIR / "chroma"))
COLLECTION_NAME = "tally_enterprise_context"

# Cosine distance: 0 = identical, 1 = unrelated. A chunk further than this is not evidence; if no
# retrieved chunk is closer, answer_question returns "Insufficient evidence." without calling the
# model. Tune once with rag_eval.py.
MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.55"))
DEFAULT_K = int(os.getenv("RAG_K", "5"))

# Generation (answer_question only): the Compose 'ollama' service publishes :11434 on the host.
OLLAMA_GENERATE_URL = os.getenv("OLLAMA_GENERATE_URL", "http://localhost:11434/api/generate")
RAG_MODEL = os.getenv("RAG_MODEL", "qwen2.5:3b")

TIER_WEIGHT = {"tier_1": 3, "tier_2": 2, "tier_3": 1}
REQUIRED_KEYS = ("chunk_id", "source_id", "authority_tier", "text")

_client = chromadb.PersistentClient(path=CHROMA_PATH)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_collection():
    # No embedding_function argument → Chroma's default model; cosine so distances are comparable.
    return _client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


# --- corpus ----------------------------------------------------------------------------

def corpus_files(feature=None):
    """corpus/<feature>.jsonl, or every corpus/*.jsonl. The file name is the feature name."""
    if feature:
        path = CORPUS_DIR / f"{feature}.jsonl"
        return [path] if path.exists() else []
    return sorted(p for p in CORPUS_DIR.glob("*.jsonl") if not p.name.startswith("_"))


def read_corpus(feature=None):
    """Chunks from the corpus files, validated, with `feature` and `indexed_at` filled in."""
    chunks, seen = [], set()
    for path in corpus_files(feature):
        name = path.stem
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_no}: not JSON ({exc})") from exc
            missing = [k for k in REQUIRED_KEYS if not chunk.get(k)]
            if missing:
                raise ValueError(f"{path.name}:{line_no}: missing {missing}")
            if chunk["authority_tier"] not in TIER_WEIGHT:
                raise ValueError(f"{path.name}:{line_no}: authority_tier must be one of {list(TIER_WEIGHT)}")
            if chunk["chunk_id"] in seen:
                raise ValueError(f"{path.name}:{line_no}: duplicate chunk_id {chunk['chunk_id']!r}")
            seen.add(chunk["chunk_id"])
            meta = chunk.get("metadata") or {}
            bad = {k: v for k, v in meta.items() if not isinstance(v, (str, int, float, bool))}
            if not isinstance(meta, dict) or bad:
                raise ValueError(f"{path.name}:{line_no}: metadata must be flat str/int/float/bool, got {bad or meta}")
            chunk["feature"] = name
            chunk.setdefault("indexed_at", now_iso())
            chunks.append(chunk)
    return chunks


def indexed_features():
    """{feature: chunk_count} for what is in the collection right now."""
    col = get_collection()
    if col.count() == 0:
        return {}
    got = col.get(include=["metadatas"])
    counts = {}
    for meta in got["metadatas"]:
        counts[meta["feature"]] = counts.get(meta["feature"], 0) + 1
    return counts


# --- the three tools --------------------------------------------------------------------

def refresh_corpus(feature=None):
    """Rebuild the index from the corpus files: one feature's (its rows are replaced) or all of
    them (the collection is recreated). Output: status, chunk_count, features, corpus_files."""
    start = time.time()
    chunks = read_corpus(feature)
    if feature:
        col = get_collection()
        if col.count() and feature in indexed_features():
            col.delete(where={"feature": feature})
    else:
        try:
            _client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        col = get_collection()
    if chunks:
        col.add(ids=[c["chunk_id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[{"source_id": c["source_id"], "authority_tier": c["authority_tier"],
                            "feature": c["feature"], "indexed_at": c["indexed_at"], **(c.get("metadata") or {})}
                           for c in chunks])
    output = {"status": "success", "feature": feature, "chunk_count": len(chunks), "collection": COLLECTION_NAME,
              "features": indexed_features(), "corpus_files": [p.name for p in corpus_files(feature)]}
    append_audit("refresh_corpus", {"feature": feature}, {"chunk_count": len(chunks)}, start)
    return output


def retrieve_context(query, k=DEFAULT_K, feature=None, where=None):
    """Top-k vector search, then the lecture's ranking policy: higher authority tier first, smaller
    distance within a tier. Output: status, query, k, feature, retrieval_mode, results[] with
    rank, chunk_id, source_id, authority_tier, feature, distance, text + the chunk's metadata."""
    start = time.time()
    col = get_collection()
    if col.count() == 0:
        refresh_corpus()
        col = get_collection()
    clauses = [c for c in ({"feature": feature} if feature else None, where or None) if c]
    filt = None if not clauses else clauses[0] if len(clauses) == 1 else {"$and": clauses}
    results = []
    if col.count():
        found = col.query(query_texts=[query], n_results=max(1, min(k, col.count())), where=filt)
        for chunk_id, text, meta, distance in zip(found["ids"][0], found["documents"][0],
                                                  found["metadatas"][0], found["distances"][0]):
            meta = dict(meta or {})
            results.append({"chunk_id": chunk_id, "source_id": meta.pop("source_id", None),
                            "authority_tier": meta.pop("authority_tier", None), "feature": meta.pop("feature", None),
                            "distance": round(distance, 3), "text": text, **meta})
        results.sort(key=lambda r: (-TIER_WEIGHT.get(r["authority_tier"], 0), r["distance"]))
        for i, r in enumerate(results, start=1):
            r["rank"] = i
    output = {"status": "success", "query": query, "k": k, "feature": feature, "retrieval_mode": "vector",
              "results": results}
    append_audit("retrieve_context", {"query": query, "k": k, "feature": feature, "where": where},
                 {"result_count": len(results), "chunk_ids": [r["chunk_id"] for r in results]}, start)
    return output


def confidence_from_results(results):
    """Lab 8 rule: High = at least two tier_1 hits among three or more; Medium = one tier_1 or two
    tier_2; otherwise Low; Unknown when nothing was retrieved. Evidence quantity and authority,
    never the model's self-assessment."""
    if not results:
        return "Unknown"
    tier_1 = sum(1 for r in results if r.get("authority_tier") == "tier_1")
    tier_2 = sum(1 for r in results if r.get("authority_tier") == "tier_2")
    if tier_1 >= 2 and len(results) >= 3:
        return "High"
    if tier_1 >= 1 or tier_2 >= 2:
        return "Medium"
    return "Low"


def answer_question(query, k=DEFAULT_K, feature=None, model=None):
    """Grounded answer contract (Lecture 8): use only the retrieved context; return "Insufficient
    evidence." when support is inadequate — decided here, by MAX_DISTANCE, before any model call;
    citations name chunk_id, source_id, authority_tier; confidence comes from the evidence.
    Output: status, query, answer, insufficient_context, citations[], confidence_category,
    retrieval_summary{k, retrieved_count, relevant_count, top_chunk, closest_distance}."""
    start = time.time()
    results = retrieve_context(query, k, feature)["results"]
    relevant = [r for r in results if r["distance"] <= MAX_DISTANCE]
    summary = {"k": k, "retrieved_count": len(results), "relevant_count": len(relevant),
               "top_chunk": relevant[0]["chunk_id"] if relevant else None,
               "closest_distance": min((r["distance"] for r in results), default=None),
               "max_distance": MAX_DISTANCE}
    if not relevant:
        output = {"status": "success", "query": query, "answer": "Insufficient evidence.", "insufficient_context": True,
                  "citations": [], "confidence_category": "Low", "retrieval_summary": summary}
        append_audit("answer_question", {"query": query, "k": k, "feature": feature}, {"insufficient": True}, start)
        return output
    context = "\n\n".join(f"[{r['chunk_id']}] {r['text']}" for r in relevant)
    answer = generate_with_ollama(query, context, model or RAG_MODEL)
    if answer is None:
        output = {"status": "error", "error": "ollama_unavailable", "query": query}
        append_audit("answer_question", {"query": query, "k": k, "feature": feature}, output, start)
        return output
    output = {"status": "success", "query": query, "answer": answer, "insufficient_context": False,
              "citations": [{"chunk_id": r["chunk_id"], "source_id": r["source_id"], "authority_tier": r["authority_tier"]}
                            for r in relevant],
              "confidence_category": confidence_from_results(relevant), "retrieval_summary": summary}
    append_audit("answer_question", {"query": query, "k": k, "feature": feature},
                 {"confidence_category": output["confidence_category"], "citation_count": len(relevant)}, start)
    return output


# --- helpers ----------------------------------------------------------------------------

PROMPT = """You are a retrieval-grounded assistant.
Use only the provided context. Copy amounts, dates and names exactly as written.
If evidence is missing, return exactly: Insufficient evidence.

QUESTION:
{query}

CONTEXT:
{context}

Return exactly:
Answer:
<answer>

Evidence:
<summary>
"""


def generate_with_ollama(query, context, model):
    """One /api/generate call (Lab 8 prompt). Returns None when Ollama is unreachable."""
    try:
        resp = requests.post(OLLAMA_GENERATE_URL,
                             json={"model": model, "prompt": PROMPT.format(query=query, context=context),
                                   "stream": False, "options": {"temperature": 0.1, "num_predict": 250}},
                             timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "").strip() or "Insufficient evidence."
    except requests.RequestException:
        return None


def append_audit(tool_name, tool_input, tool_output, start):
    """One JSON line per tool call — the audit trail the lecture's traceability requirement asks for."""
    record = {"request_id": str(uuid.uuid4()), "tool_name": tool_name, "tool_input": tool_input,
              "tool_output": tool_output, "timestamp": now_iso(), "duration_ms": int((time.time() - start) * 1000)}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    print(json.dumps(refresh_corpus(), indent=2))
    print(json.dumps(retrieve_context("What evidence do I have to dispute the GymCo charge?", 5, "bills"), indent=2))
    print(json.dumps(answer_question("What evidence do I have to dispute the GymCo charge?", 5, "bills"), indent=2))
