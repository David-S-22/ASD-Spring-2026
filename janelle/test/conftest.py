from pytest import MonkeyPatch, fixture

from janelle.backend import config


@fixture(autouse=True)
def mcp_disabled_by_default(monkeypatch: MonkeyPatch):
    """Keep MCP off unless a test switches it on.

    ``MCP_ENABLED`` defaults to true so the deployed backend reaches the
    shared server, but the unit suite must never open a socket. Tests that
    exercise the MCP path re-enable it and install a fake client.
    """
    monkeypatch.setattr(config, "MCP_ENABLED", False)
