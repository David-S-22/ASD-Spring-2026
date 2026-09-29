"""Tests for the shared loop's MCP and RAG collectors; no socket is opened, probes and HTTP are injected."""
import importlib
import sys
import types
from pathlib import Path

import pytest
import requests

from agentic_loop import validate

REPO_ROOT = Path(__file__).resolve().parents[1]

PROBE = {
    "tools": [{"name": "search_transactions", "required": []}, {"name": "retrieve_context", "required": ["feature", "question"]}, {"name": "get_transactions_with_confirmed_anomalies", "required": []}],
    "calls": [
        {"tool": "search_transactions", "arguments": {"merchant": "FibreLink"}, "ok": True, "detail": "list of 2", "ms": 84},
        {"tool": "retrieve_context", "arguments": {"feature": "bills", "question": "Which bill is overdue?", "k": 2}, "ok": True, "detail": "2 results, closest distance 1.083", "ms": 310},
    ],
    "boundary": [
        {"tool": "no_such_tool", "arguments": {}, "ok": False, "detail": "Unknown tool: 'no_such_tool'", "ms": 5},
        {"tool": "retrieve_context", "arguments": {}, "ok": False, "detail": "2 validation errors for call[retrieve_context] feature Missing required argument", "ms": 6},
    ],
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("RAG_SERVER_URL", raising=False)


def test_collect_mcp_lists_tools_smoke_results_and_boundaries():
    ok, evidence = validate.collect_mcp(probe=lambda url: PROBE)
    assert ok is True
    assert evidence.startswith("MCP evidence: endpoint http://localhost:8000/mcp; session ok; 3 tools registered: search_transactions (required: none), retrieve_context (required: feature, question), get_transactions_with_confirmed_anomalies (required: none).")
    assert 'search_transactions {"merchant": "FibreLink"} -> ok, list of 2 in 84ms' in evidence
    assert "closest distance 1.083 in 310ms" in evidence
    assert "get_transactions_with_confirmed_anomalies -> not exercised (no entry in validate.SMOKE_CALLS)" in evidence
    assert "no_such_tool {} -> rejected (Unknown tool: 'no_such_tool')" in evidence
    assert "retrieve_context {} -> rejected (2 validation errors for call[retrieve_context] feature Missing required argument)" in evidence


def test_collect_mcp_reports_a_failed_smoke_call_as_error_not_ok():
    probe = dict(PROBE, calls=[{"tool": "search_transactions", "arguments": {"merchant": "FibreLink"}, "ok": False, "detail": "HTTP 500 from transactions-db", "ms": 40}])
    evidence = validate.collect_mcp(probe=lambda url: probe)[1]
    assert 'search_transactions {"merchant": "FibreLink"} -> error (HTTP 500 from transactions-db) in 40ms' in evidence
    assert "retrieve_context -> not exercised (no entry in validate.SMOKE_CALLS)" in evidence


def test_collect_mcp_flags_an_accepted_boundary_probe():
    probe = dict(PROBE, boundary=[{"tool": "no_such_tool", "arguments": {}, "ok": True, "detail": "list of 0", "ms": 1}])
    assert "no_such_tool {} -> NOT rejected (list of 0)" in validate.collect_mcp(probe=lambda url: probe)[1]


def test_collect_mcp_records_unreachable_instead_of_raising():
    def probe(url):
        raise RuntimeError("Client failed to connect: Failed to initialize server session")

    ok, evidence = validate.collect_mcp(probe=probe)
    assert ok is True
    assert "UNREACHABLE (Client failed to connect" in evidence
    assert "No tools listed, no calls made." in evidence


def test_collect_mcp_reports_a_missing_client_library_as_misconfiguration():
    def probe(url):
        raise ImportError("No module named 'fastmcp'")

    ok, evidence = validate.collect_mcp(probe=probe)
    assert ok is False
    assert "UNREACHABLE" not in evidence
    assert "fastmcp" in evidence and "agentic_loop/requirements.txt" in evidence


def test_collect_mcp_honours_MCP_SERVER_URL(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
    seen = {}

    def probe(url):
        seen["url"] = url
        return PROBE

    _ok, evidence = validate.collect_mcp(probe=probe)
    assert seen["url"] == "http://127.0.0.1:8000/mcp" and "endpoint http://127.0.0.1:8000/mcp" in evidence


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _chunk(source, distance, text="# Home internet (bill)\n\n- Merchant: FibreLink"):
    return {"id": f"x_{source}_0", "text": text, "metadata": {"source": source}, "distance": distance}


def fake_rag(collections, retrievals, unknown_status=500):
    posts = []

    def get(url, timeout=None):
        assert url.endswith("/health")
        return FakeResponse({"ok": True, "collections": collections})

    def post(url, json=None, timeout=None):
        posts.append(json)
        if json["feature"] == validate.UNKNOWN_FEATURE:
            return FakeResponse("<html>500</html>" if unknown_status >= 500 else {"error": "unknown feature"}, unknown_status)
        return FakeResponse({"results": retrievals[(json["feature"], json["question"])]})

    return get, post, posts


BENCHMARKS = {"bills": "Which bill is overdue?", "savings": "advice about how to generate savings advice", "transactions": "Which category does a supermarket purchase belong to?"}


def test_collect_rag_reports_collections_distances_and_off_topic(monkeypatch):
    monkeypatch.setattr(validate, "RAG_BENCHMARKS", BENCHMARKS)
    retrievals = {
        ("bills", "Which bill is overdue?"): [_chunk("bill-1-rent.md", 1.5), _chunk("bill-7-home-internet.md", 1.083)],
        ("bills", validate.OFF_TOPIC_QUESTION): [_chunk("bill-1-rent.md", 1.62)],
        ("savings", BENCHMARKS["savings"]): [_chunk("savings_advice_guide.md", 0.9, "Save ten percent")],
    }
    get, post, posts = fake_rag(["billing", "bills", "savings"], retrievals)
    ok, evidence = validate.collect_rag(get=get, post=post)
    assert ok is True
    assert evidence.startswith("RAG evidence: endpoint http://localhost:5003; /health ok, 3 collections: billing, bills, savings.")
    assert 'bills "Which bill is overdue?" -> 2 results, closest 1.083 from bill-7-home-internet.md ("Home internet (bill) - Merchant: FibreLink")' in evidence
    assert "transactions: collection absent, no benchmark run" in evidence
    assert "Off-topic probe on bills -> closest 1.620 (on-topic 1.083)" in evidence
    assert "Unknown feature no-such-feature -> server error (HTTP 500), not a clean rejection" in evidence
    assert "billing: collection listed, no benchmark registered" in evidence
    assert all(p["feature"] != "transactions" for p in posts)


def test_collect_rag_reports_a_4xx_unknown_feature_as_rejected():
    get, post, _posts = fake_rag(["bills"], {("bills", "Which bill is overdue?"): [_chunk("bill-7-home-internet.md", 1.0)], ("bills", validate.OFF_TOPIC_QUESTION): [_chunk("bill-1-rent.md", 1.5)]}, unknown_status=404)
    assert "Unknown feature no-such-feature -> rejected (HTTP 404)" in validate.collect_rag(get=get, post=post)[1]


def test_collect_rag_reports_an_unknown_feature_that_was_not_rejected():
    get, post, _posts = fake_rag(["bills"], {("bills", "Which bill is overdue?"): [_chunk("bill-7-home-internet.md", 1.0)], ("bills", validate.OFF_TOPIC_QUESTION): [_chunk("bill-1-rent.md", 1.5)]})

    def accepting_post(url, json=None, timeout=None):
        if json["feature"] == validate.UNKNOWN_FEATURE:
            return FakeResponse({"results": []})
        return post(url, json=json, timeout=timeout)

    assert "Unknown feature no-such-feature -> NOT rejected (0 results)" in validate.collect_rag(get=get, post=accepting_post)[1]


def test_collect_rag_unreachable():
    def get(url, timeout=None):
        raise requests.exceptions.ConnectionError("connection refused")

    ok, evidence = validate.collect_rag(get=get, post=lambda *a, **k: None)
    assert ok is True and "UNREACHABLE (connection refused)" in evidence and "No collections listed" in evidence


def test_collect_rag_keeps_going_when_one_retrieval_fails_after_health_ok():
    get, _post, _posts = fake_rag(["bills"], {})

    def post(url, json=None, timeout=None):
        raise requests.exceptions.ReadTimeout("read timed out")

    ok, evidence = validate.collect_rag(get=get, post=post)
    assert ok is True
    assert evidence.startswith("RAG evidence: endpoint http://localhost:5003; /health ok, 1 collections: bills.")
    assert 'bills "Which bill is overdue?" -> error (read timed out)' in evidence
    assert "Off-topic probe skipped (no benchmark returned results)" in evidence
    assert "Unknown feature no-such-feature -> error (read timed out)" in evidence


def test_collect_rag_honours_RAG_SERVER_URL(monkeypatch):
    monkeypatch.setenv("RAG_SERVER_URL", "http://127.0.0.1:5003/")
    seen = {}

    def get(url, timeout=None):
        seen["url"] = url
        return FakeResponse({"ok": True, "collections": []})

    _ok, evidence = validate.collect_rag(get=get, post=lambda *a, **k: FakeResponse("", 500))
    assert seen["url"] == "http://127.0.0.1:5003/health" and "endpoint http://127.0.0.1:5003;" in evidence


def test_prompt_families_exist_for_both_modes():
    for family in ("mcp", "rag"):
        for name in ("implementation/system_prompt.txt", "implementation/task_prompt.txt", "review/review_prompt.txt"):
            path = REPO_ROOT / "prompts" / family / name
            assert path.is_file(), path
            assert path.read_text(encoding="utf-8").strip()


def test_shared_record_round_trip_for_new_modes(tmp_path):
    """Regression pin, not a new behaviour: the run-view line format the Release 1 captures cite."""
    from agentic_loop.record import RunRecord

    record = RunRecord(tmp_path / "reports")
    record.start_mode("mcp", "MCP validation")
    for step, message in (("PLAN", "Review target"), ("OBSERVE", "Collecting evidence"), ("OBSERVE", "Complete"), ("ACT", "impl"), ("ACT", "review"), ("ADAPT", "human")):
        record.stage(step, message)
    record.set(evidence="MCP evidence: endpoint x", implementation_output="o", review_output="r")
    record.decision("edited", "corrected")
    record.end_mode()
    assert "[MCP validation] PLAN -> OBSERVE -> OBSERVE -> ACT -> ACT -> ADAPT => edited" in (tmp_path / "reports" / "run-view.md").read_text(encoding="utf-8")


def test_modes_wiring(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=object))
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
    sys.modules.pop("agentic_loop.main", None)
    try:
        main = importlib.import_module("agentic_loop.main")
        assert main.MODES["architecture"][2] is main.collect_architecture
        assert main.MODES["mcp"] == ("MCP validation", "mcp", validate.collect_mcp)
        assert main.MODES["rag"] == ("RAG validation", "rag", validate.collect_rag)
    finally:
        sys.modules.pop("agentic_loop.main", None)
