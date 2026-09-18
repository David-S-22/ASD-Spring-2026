"""Copy me to sources/<feature>.py. Files starting with _ are skipped.

A chunk is {"id", "text", "metadata"}:
  id        unique, "<feature>:<what>"                       "savings:goal/3"
  text      one plain sentence per row, or a doc paragraph;  money in dollars, dates as stored
  metadata  flat dict of str/int/float/bool — MUST have feature and tier (1 = database row,
            2 = approved doc); add whatever else is worth filtering or showing on a citation.
            Callers can then ask /retrieve or /answer with where={"record": "goal"} etc.

Two helpers in corpus.py do the boring part:
  corpus.row_chunk(FEATURE, record, record_id, text, **metadata)   one database row
  corpus.doc_chunks(path, FEATURE)                                 one markdown file, split by
                                                                   heading, with doc/section/part
                                                                   extracted into metadata
"""
import config
import corpus

FEATURE = "example"          # your feature name, lowercase — must match this file's name


def load_chunks():
    """Return every chunk the RAG server may cite for this feature. Raise on failure — refresh
    reports the error under your feature name and the other features are unaffected."""
    return [
        # tier 1: one plain sentence per row from YOUR database API (:600x), columns as metadata
        corpus.row_chunk(FEATURE, "goal", 3, "Goal #3 Holiday: target $1,200.00, due 2026-12-20.",
                         name="Holiday", due="2026-12-20", label="Goal #3 Holiday"),
        # tier 2: your approved docs, split by heading with doc/section extracted
        # *corpus.doc_chunks(config.REPO_ROOT / "docs/release-0/<you>/api.md", FEATURE),
    ]


# eval.py and the loop's RAG mode run these. keywords = words a relevant chunk contains;
# expected_relevant = how many such chunks exist. One question your rows answer, one your docs
# answer, one nothing in the project answers (expect_insufficient).
BENCHMARKS = [
    {"query": "a question your rows answer", "feature": FEATURE, "keywords": ["Holiday"], "expected_relevant": 1},
    {"query": "a question nothing in your data answers", "feature": FEATURE, "expect_insufficient": True},
]
