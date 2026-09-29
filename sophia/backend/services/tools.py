"""Shared MCP/RAG mode gate and allow-listed tool call, used by the tools route and the evidence service."""
from sophia.backend import config
from sophia.backend.clients import mcp_server
from sophia.backend.services.errors import ModeError

RETRIEVAL_TOOL = "retrieve_context"


def require_modes(name):
    """The retrieval tool needs RAG mode as well as MCP mode; every tool needs MCP mode."""
    if not config.MCP_ENABLED:
        raise ModeError("mcp_disabled")
    if name == RETRIEVAL_TOOL and not config.RAG_ENABLED:
        raise ModeError("rag_disabled")


def call_allowed_tool(name, arguments):
    """Gate on the mode switches, then call; a tool error from retrieve_context means the RAG server is down."""
    require_modes(name)
    try:
        return mcp_server.call_tool(name, arguments)
    except ModeError as exc:
        if name == RETRIEVAL_TOOL and exc.code == "mcp_tool_error":
            raise ModeError("rag_unavailable") from None
        raise
