"""Retrieval quality for one feature's benchmarks: P@5, R@5 and the insufficient-context check,
against the running server. Benchmarks live in the feature's own folder, e.g.

    python eval.py ../../sophia/rag/benchmarks.json

The file is a JSON list; each entry is either
    {"query": "...", "feature": "bills", "keywords": ["GymCo"], "expected_relevant": 3}
or  {"query": "...", "feature": "bills", "expect_insufficient": true}

Use it once per machine to tune RAG_MAX_DISTANCE: the covered queries' "closest" must sit below it,
the out-of-scope query's above it. This table is the retrieval evidence for the report."""
import json
import os
import sys

import requests

RAG_SERVER_URL = os.environ.get("RAG_SERVER_URL", "http://localhost:5003")


def relevant(text, keywords):
    return any(word.lower() in text.lower() for word in keywords)


def run(path):
    benchmarks = json.load(open(path, encoding="utf-8"))
    print(f"{'feature':8} {'query':52} {'P@5':>5} {'R@5':>5}  note")
    for bench in benchmarks:
        query, feature = bench["query"], bench["feature"]
        r = requests.post(f"{RAG_SERVER_URL}/retrieve", json={"query": query, "feature": feature, "k": 5}, timeout=60)
        r.raise_for_status()
        out = r.json()
        closest = out["retrieval_summary"]["closest_distance"]
        if bench.get("expect_insufficient"):
            note = "insufficient ✓" if out["insufficient_context"] else "RETRIEVED — lower RAG_MAX_DISTANCE?"
            print(f"{feature:8} {query[:52]:52} {'-':>5} {'-':>5}  {note}  closest {closest}")
            continue
        hits = out["results"]
        good = [h for h in hits if relevant(h["text"], bench["keywords"])]
        p_at_5 = len(good) / 5
        r_at_5 = min(1.0, len(good) / max(1, bench["expected_relevant"]))
        flag = "" if not out["insufficient_context"] else "  INSUFFICIENT — raise RAG_MAX_DISTANCE?"
        print(f"{feature:8} {query[:52]:52} {p_at_5:5.2f} {r_at_5:5.2f}  closest {closest}  {out['confidence_category']}{flag}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python eval.py <benchmarks.json>")
    run(sys.argv[1])
