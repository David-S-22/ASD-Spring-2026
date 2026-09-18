"""The rules a marker will ask about, without Chroma or Ollama doing any work."""
import json

import pytest

import rag_pipeline as rag


def _row(tier, distance, chunk_id="bills:bill/12", **meta):
    return {"chunk_id": chunk_id, "source_id": "bills-db:/bills", "authority_tier": tier, "feature": "bills",
            "distance": distance, "text": "x", **meta}


def test_confidence_follows_evidence_authority():
    assert rag.confidence_from_results([]) == "Unknown"
    assert rag.confidence_from_results([_row("tier_1", .2), _row("tier_1", .3), _row("tier_2", .4)]) == "High"
    assert rag.confidence_from_results([_row("tier_1", .2)]) == "Medium"
    assert rag.confidence_from_results([_row("tier_2", .2), _row("tier_2", .3)]) == "Medium"
    assert rag.confidence_from_results([_row("tier_3", .2)]) == "Low"


def test_insufficient_evidence_is_decided_before_the_model(monkeypatch):
    monkeypatch.setattr(rag, "retrieve_context", lambda q, k, f=None, w=None: {"results": [_row("tier_1", 0.9)]})
    monkeypatch.setattr(rag, "generate_with_ollama", lambda *a: (_ for _ in ()).throw(AssertionError("model must not be called")))
    monkeypatch.setattr(rag, "append_audit", lambda *a: None)
    out = rag.answer_question("What is my mortgage rate?", 5, "bills")
    assert out["answer"] == "Insufficient evidence." and out["insufficient_context"] is True
    assert out["citations"] == [] and out["confidence_category"] == "Low"
    assert out["retrieval_summary"]["closest_distance"] == 0.9


def test_grounded_answer_contract(monkeypatch):
    rows = [_row("tier_1", .2, "bills:dispute/2"), _row("tier_1", .3, "bills:bill/12"),
            _row("tier_2", .4, "bills:docs/api.md#3"), _row("tier_2", .95, "bills:docs/README.md#1")]
    monkeypatch.setattr(rag, "retrieve_context", lambda q, k, f=None, w=None: {"results": rows})
    monkeypatch.setattr(rag, "generate_with_ollama", lambda q, c, m: "Answer:\nGymCo is $24.99 a month.")
    monkeypatch.setattr(rag, "append_audit", lambda *a: None)
    out = rag.answer_question("evidence for GymCo?", 5, "bills")
    assert out["insufficient_context"] is False
    assert [c["chunk_id"] for c in out["citations"]] == ["bills:dispute/2", "bills:bill/12", "bills:docs/api.md#3"]
    assert out["citations"][0] == {"chunk_id": "bills:dispute/2", "source_id": "bills-db:/bills", "authority_tier": "tier_1"}
    assert out["confidence_category"] == "High"
    assert out["retrieval_summary"]["relevant_count"] == 3 and out["retrieval_summary"]["top_chunk"] == "bills:dispute/2"


def test_ollama_down_is_an_error_not_a_fake_answer(monkeypatch):
    monkeypatch.setattr(rag, "retrieve_context", lambda q, k, f=None, w=None: {"results": [_row("tier_1", .2)]})
    monkeypatch.setattr(rag, "generate_with_ollama", lambda q, c, m: None)
    monkeypatch.setattr(rag, "append_audit", lambda *a: None)
    assert rag.answer_question("x", 5, "bills")["error"] == "ollama_unavailable"


def test_read_corpus_validates_the_chunk_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "CORPUS_DIR", tmp_path)
    good = {"chunk_id": "bills:bill/1", "source_id": "bills-db:/bills", "authority_tier": "tier_1", "text": "Bill #1",
            "metadata": {"record": "bill", "amount_cents": 2499}}
    (tmp_path / "bills.jsonl").write_text(json.dumps(good) + "\n\n" + json.dumps({**good, "chunk_id": "bills:bill/2"}) + "\n")
    chunks = rag.read_corpus()
    assert [c["chunk_id"] for c in chunks] == ["bills:bill/1", "bills:bill/2"]
    assert chunks[0]["feature"] == "bills" and chunks[0]["indexed_at"]
    assert rag.read_corpus("bills") == chunks and rag.read_corpus("savings") == []

    (tmp_path / "bad.jsonl").write_text(json.dumps({**good, "authority_tier": "tier_9"}) + "\n")
    with pytest.raises(ValueError, match="authority_tier"):
        rag.read_corpus("bad")
    (tmp_path / "bad.jsonl").write_text(json.dumps({**good, "metadata": {"tags": ["a"]}}) + "\n")
    with pytest.raises(ValueError, match="flat"):
        rag.read_corpus("bad")
    (tmp_path / "bad.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(good) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        rag.read_corpus("bad")
