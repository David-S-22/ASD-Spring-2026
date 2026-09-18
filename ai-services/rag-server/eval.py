"""Retrieval quality for every feature's BENCHMARKS: P@5, R@5, and the insufficient-context check.
Needs the real thing running (Ollama + the feature databases); tests/ covers the rules without them.

Use it once per machine to tune RAG_MAX_DISTANCE: the covered queries' "closest" must sit below it,
the out-of-scope query's above it."""
import corpus
import rag


def relevant(text, keywords):
    return any(word.lower() in text.lower() for word in keywords)


def run():
    print(f"{'feature':8} {'query':52} {'P@5':>5} {'R@5':>5}  note")
    for feature in corpus.features():
        for bench in corpus.benchmarks(feature):
            query = bench["query"]
            out = rag.retrieve_context(query, feature, 5)
            if bench.get("expect_insufficient"):
                note = "insufficient ✓" if out["insufficient_context"] else "RETRIEVED — lower RAG_MAX_DISTANCE?"
                print(f"{feature:8} {query[:52]:52} {'-':>5} {'-':>5}  {note}  closest {out['retrieval_summary']['closest_distance']}")
                continue
            hits = out["results"]
            good = [r for r in hits if relevant(r["text"], bench["keywords"])]
            p_at_5 = len(good) / 5
            r_at_5 = min(1.0, len(good) / max(1, bench["expected_relevant"]))
            flag = "" if not out["insufficient_context"] else "  INSUFFICIENT — raise RAG_MAX_DISTANCE?"
            print(f"{feature:8} {query[:52]:52} {p_at_5:5.2f} {r_at_5:5.2f}  closest {hits[0]['distance'] if hits else '-'}"
                  f"  {out['confidence_category']}{flag}")


if __name__ == "__main__":
    run()
