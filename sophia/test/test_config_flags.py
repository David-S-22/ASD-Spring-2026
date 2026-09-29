"""Tests for the MCP/RAG configuration helpers; module constants are checked after a reload under a clean env."""
import importlib

import pytest

from sophia.backend import config

SWITCHES = ("MCP_ENABLED", "RAG_ENABLED", "MCP_SERVER_URL", "MCP_TIMEOUT_SECONDS", "MCP_ALLOWED_TOOLS", "RAG_TOP_K", "RAG_HIGH", "RAG_MEDIUM", "RAG_LOW", "GROUNDED_TIMEOUT_SECONDS")


@pytest.mark.parametrize("value, expected", [("1", True), ("true", True), ("YES", True), (" on ", True), ("0", False), ("false", False), ("", False)])
def test_flag_accepts_the_team_spellings(monkeypatch, value, expected):
    monkeypatch.setenv("BILLS_TEST_FLAG", value)
    assert config._flag("BILLS_TEST_FLAG", False) is expected


def test_flag_uses_the_default_when_unset(monkeypatch):
    monkeypatch.delenv("BILLS_TEST_FLAG", raising=False)
    assert config._flag("BILLS_TEST_FLAG", False) is False
    assert config._flag("BILLS_TEST_FLAG", True) is True


def test_rag_thresholds_use_defaults_unless_ordered():
    assert config._rag_thresholds({}) == config.RAG_DEFAULT_THRESHOLDS
    assert config._rag_thresholds({"RAG_HIGH": "0.5", "RAG_MEDIUM": "0.7", "RAG_LOW": "0.9"}) == (0.5, 0.7, 0.9)
    assert config._rag_thresholds({"RAG_HIGH": "1.2", "RAG_MEDIUM": "0.9", "RAG_LOW": "0.6"}) == config.RAG_DEFAULT_THRESHOLDS
    assert config._rag_thresholds({"RAG_LOW": "abc"}) == config.RAG_DEFAULT_THRESHOLDS


def test_module_defaults_keep_both_modes_off(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    fresh = importlib.reload(config)
    try:
        assert fresh.MCP_ENABLED is False
        assert fresh.RAG_ENABLED is False
        assert fresh.MCP_SERVER_URL == "http://host.docker.internal:8000/mcp"
        assert fresh.MCP_TIMEOUT_SECONDS == 15
        assert fresh.MCP_ALLOWED_TOOLS == frozenset({"retrieve_context", "search_transactions"})
        assert fresh.RAG_TOP_K == 3
        assert (fresh.RAG_HIGH, fresh.RAG_MEDIUM, fresh.RAG_LOW) == fresh.RAG_DEFAULT_THRESHOLDS == (0.8, 1.1, 1.4)
        assert fresh.GROUNDED_TIMEOUT_SECONDS == 25
    finally:
        monkeypatch.undo()
        importlib.reload(config)
