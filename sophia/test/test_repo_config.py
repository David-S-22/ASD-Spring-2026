"""Repo-file checks: the compose block and the workflow carry the MCP/RAG switches the report cites."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _services():
    """The compose services mapping, parsed rather than string-split."""
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def test_compose_bills_backend_block_carries_the_switches_and_keeps_the_r0_ollama_wiring():
    block = _services()["bills-backend"]
    env = block["environment"]
    assert env["MCP_ENABLED"] == "${MCP_ENABLED:-true}"
    assert env["MCP_SERVER_URL"] == "http://host.docker.internal:8000/mcp"
    assert env["RAG_ENABLED"] == "${RAG_ENABLED:-true}"
    assert env["OLLAMA_URL"] == "http://ollama:11434"
    assert "RAG_SERVER_URL" not in env
    assert "host.docker.internal:host-gateway" in block["extra_hosts"]
    assert block["depends_on"] == ["bills-db", "ollama"]
    assert "network_mode" not in block
