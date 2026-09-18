"""The rules a marker will ask about, tested without Chroma or Ollama doing any work."""
import pytest

import rag


def _hit(tier, distance=0.3, id_="bills:bill/1", **meta):
    row = {"rank": 1, "id": id_, "feature": "bills", "distance": distance, "text": "x", **meta}
    if tier is not None:
        row["tier"] = tier
    return row


class _FakeCollection:
    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def query(self, query_texts, n_results, where=None):
        rows = self.rows[:n_results]
        return {"ids": [[r["id"] for r in rows]], "documents": [[r["text"] for r in rows]],
                "metadatas": [[{k: v for k, v in r.items() if k not in ("rank", "id", "text", "distance")} for r in rows]],
                "distances": [[r["distance"] for r in rows]]}


def _fake_index(monkeypatch, rows):
    monkeypatch.setattr(rag, "indexed_features", lambda: {"bills": len(rows)})
    monkeypatch.setattr(rag, "collection", lambda feature: _FakeCollection(rows))
    monkeypatch.setattr(rag, "_audit", lambda *a, **k: None)


def test_confidence_categories_and_optional_tier():
    assert rag.confidence([]) == "Unknown"
    assert rag.confidence([_hit(1), _hit(1), _hit(2)]) == "High"
    assert rag.confidence([_hit(1)]) == "Medium"
    assert rag.confidence([_hit(2), _hit(2)]) == "Medium"
    assert rag.confidence([_hit(2)]) == "Low"
    assert rag.confidence([_hit(None), _hit(None)]) == "Medium"      # no tier → counts as a doc
    assert rag.confidence([_hit(None)]) == "Low"


def test_insufficient_context_is_decided_by_distance(monkeypatch):
    _fake_index(monkeypatch, [_hit(1, distance=0.95), _hit(2, distance=0.97, id_="bills:docs/api.md#1")])
    out = rag.retrieve_context("What is my mortgage rate?", "bills", 5)
    assert out["insufficient_context"] is True
    assert out["relevant"] == [] and out["citations"] == [] and out["context"] == ""
    assert out["confidence_category"] == "Low"
    assert len(out["results"]) == 2                      # the caller can still see what was nearest


def test_unknown_feature_is_insufficient_not_an_error(monkeypatch):
    monkeypatch.setattr(rag, "indexed_features", lambda: {})
    monkeypatch.setattr(rag, "_audit", lambda *a, **k: None)
    out = rag.retrieve_context("anything", "savings", 5)
    assert out["insufficient_context"] is True and out["results"] == []


def test_relevant_bundle_carries_context_citations_and_confidence(monkeypatch):
    _fake_index(monkeypatch, [
        _hit(1, record="bill", record_id=12, label="Bill #12 GymCo"),
        _hit(1, id_="bills:payment/403", record="payment", record_id=403, date="2026-08-03"),
        _hit(1, id_="bills:dispute/2", record="dispute", record_id=2, status="draft"),
        _hit(2, distance=0.9, id_="bills:docs/README.md#1"),        # too far: retrieved, not relevant
    ])
    out = rag.retrieve_context("evidence for GymCo?", "bills", 5)
    assert out["insufficient_context"] is False
    assert [c["id"] for c in out["citations"]] == ["bills:bill/1", "bills:payment/403", "bills:dispute/2"]
    assert out["citations"][2]["status"] == "draft" and "text" not in out["citations"][0]
    assert out["context"].splitlines()[0] == "[bills:bill/1] x"
    assert out["confidence_category"] == "High"
    assert len(out["results"]) == 4 and len(out["relevant"]) == 3


def test_ingest_validation_is_only_chromas_contract():
    ok = [{"id": "bills:bill/1", "text": "Bill #1", "metadata": {"tier": 1, "amount_cents": 2499, "active": True}}]
    rag._validate("bills", ok)                                                   # id, text, flat scalars → fine
    rag._validate("bills", [{"id": "x", "text": "no metadata at all"}])          # metadata optional
    with pytest.raises(ValueError, match="feature"):
        rag._validate("", ok)
    with pytest.raises(ValueError, match="non-empty list"):
        rag._validate("bills", [])
    with pytest.raises(ValueError, match="'id' and 'text'"):
        rag._validate("bills", [{"id": "x"}])
    with pytest.raises(ValueError, match="duplicate"):
        rag._validate("bills", ok + ok)
    with pytest.raises(ValueError, match="str/int/float/bool"):
        rag._validate("bills", [{"id": "x", "text": "y", "metadata": {"tags": ["a", "b"]}}])
