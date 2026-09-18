"""Retrieval evaluation (Lab 8 rag_eval): P@5 and R@5 per benchmark query, plus the
insufficient-evidence check, written to retrieval-metrics.md.

    python rag_eval.py ../../sophia/rag/benchmarks.json      # one feature's benchmarks
    python rag_eval.py                                       # every */rag/benchmarks.json in the repo

A benchmark is {"query", "feature", "relevant_keywords": [...], "expected_relevant": n}
or            {"query", "feature", "expect_insufficient": true}.
Runs in-process against the corpus files (no server needed); Ollama is not used."""
import json
import sys
from pathlib import Path

import rag_pipeline as rag

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
METRICS_PATH = BASE_DIR / "retrieval-metrics.md"


def is_relevant(text, keywords):
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


def evaluate(bench):
    query, feature = bench["query"], bench.get("feature")
    response = rag.retrieve_context(query, 5, feature)
    results = response["results"][:5]
    closest = min((r["distance"] for r in results), default=None)
    if bench.get("expect_insufficient"):
        insufficient = not any(r["distance"] <= rag.MAX_DISTANCE for r in results)
        return {"query": query, "feature": feature, "expect_insufficient": True, "insufficient": insufficient,
                "closest_distance": closest, "retrieved_chunk_ids": [r["chunk_id"] for r in results]}
    relevant = [r for r in results if is_relevant(r["text"], bench["relevant_keywords"])]
    return {"query": query, "feature": feature,
            "retrieved_chunk_ids": [r["chunk_id"] for r in results],
            "relevant_chunk_ids": [r["chunk_id"] for r in relevant],
            "p_at_5": len(relevant) / 5,
            "r_at_5": min(1.0, len(relevant) / max(bench["expected_relevant"], 1)),
            "closest_distance": closest,
            "confidence_category": rag.confidence_from_results([r for r in results if r["distance"] <= rag.MAX_DISTANCE])}


def write_metrics(results):
    lines = ["# Retrieval Metrics", "", f"RAG_MAX_DISTANCE = {rag.MAX_DISTANCE}", ""]
    for r in results:
        lines.append(f"## {r['query']}  ({r['feature']})")
        lines.append(f"- Retrieved: {r['retrieved_chunk_ids']}")
        if r.get("expect_insufficient"):
            lines.append(f"- Expected insufficient evidence: {'PASS' if r['insufficient'] else 'FAIL — a chunk was within the threshold'}")
        else:
            lines.append(f"- Relevant: {r['relevant_chunk_ids']}")
            lines.append(f"- P@5: {r['p_at_5']:.2f}")
            lines.append(f"- R@5: {r['r_at_5']:.2f}")
            lines.append(f"- Confidence: {r['confidence_category']}")
        lines.append(f"- Closest distance: {r['closest_distance']}")
        lines.append("")
    METRICS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main(paths):
    if not paths:
        paths = sorted(str(p) for p in REPO_ROOT.glob("*/rag/benchmarks.json"))
    benchmarks = [b for p in paths for b in json.loads(Path(p).read_text(encoding="utf-8"))]
    if not benchmarks:
        sys.exit("no benchmarks found — pass a benchmarks.json path")
    results = [evaluate(b) for b in benchmarks]
    print(f"{'feature':8} {'query':52} {'P@5':>5} {'R@5':>5}  note")
    for r in results:
        if r.get("expect_insufficient"):
            note = "insufficient ✓" if r["insufficient"] else "RETRIEVED — lower RAG_MAX_DISTANCE?"
            print(f"{r['feature']:8} {r['query'][:52]:52} {'-':>5} {'-':>5}  {note}  closest {r['closest_distance']}")
        else:
            print(f"{r['feature']:8} {r['query'][:52]:52} {r['p_at_5']:5.2f} {r['r_at_5']:5.2f}  "
                  f"closest {r['closest_distance']}  {r['confidence_category']}")
    write_metrics(results)
    print(f"\nwritten: {METRICS_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
