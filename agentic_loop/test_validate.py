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
