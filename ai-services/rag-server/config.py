"""Settings for the shared RAG server, read from the environment once at import time.
Same style as the MCP server: an env var with a localhost default for everything."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # ai-services/rag-server
REPO_ROOT = BASE_DIR.parent.parent                  # the shared repository root

PORT = int(os.environ.get("RAG_PORT", "5003"))
# Bound to the loopback interface on purpose: the only application client is the MCP server's
# context tool, which runs on the same host. Containers cannot reach 127.0.0.1 through
# host.docker.internal, so feature backends have no direct path to this server. curl, eval.py
# and the agentic loop (all host-side) can still validate it. Override only for a deliberate reason.
HOST = os.environ.get("RAG_HOST", "127.0.0.1")
CHROMA_DIR = os.environ.get("RAG_CHROMA_DIR", str(BASE_DIR / "chroma"))   # Chroma's own on-disk store (gitignored)
AUDIT_FILE = BASE_DIR / "audit.jsonl"                                       # one line per tool call (gitignored)

# The Compose 'ollama' service publishes 11434 on the host, so localhost works from here.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Chroma calls this model to turn text into vectors. It must be in OLLAMA_PULL_MODELS in
# docker-compose.yml (or: docker exec ollama ollama pull nomic-embed-text).
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "nomic-embed-text")
EMBED_TIMEOUT = int(os.environ.get("RAG_EMBED_TIMEOUT", "60"))

DEFAULT_K = int(os.environ.get("RAG_K", "5"))
# From lecture notes; the recommended use is the Cosine distance from benchmark provided where (0 = identical, 1 = unrelated). 
# if nothing is closer, retrieve_context reports insufficient_context. Tune once with eval.py.
MAX_DISTANCE = float(os.environ.get("RAG_MAX_DISTANCE", "0.55"))
