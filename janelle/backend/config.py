"""Environment configuration for the transactions backend."""
import os


def _environment_flag(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


PORT = int(os.environ.get("PORT", "5001"))
TRANSACTIONS_DB_URL = os.environ.get(
    "TRANSACTIONS_DB_URL",
    "http://transactions-db:6001",
).rstrip("/")
DATABASE_TIMEOUT_SECONDS = float(os.environ.get("DATABASE_TIMEOUT_SECONDS", "20"))
ANOMALIES_BACKEND_URL = os.environ.get(
    "ANOMALIES_BACKEND_URL",
    "http://anomalies-backend:5004",
).rstrip("/")
ANOMALIES_DB_URL = os.environ.get(
    "ANOMALIES_DB_URL",
    "http://anomalies-db:6004/anomalies",
).rstrip("/")
ANOMALIES_TIMEOUT_SECONDS = float(
    os.environ.get("ANOMALIES_TIMEOUT_SECONDS", "10")
)
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://ollama:11434",
).rstrip("/")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:3b")
AGENT_MAX_ITERATIONS = min(
    2,
    max(
        1,
        int(os.environ.get("AGENT_MAX_ITERATIONS", "2")),
    ),
)
AGENT_TRACE_ENABLED = _environment_flag("AGENT_TRACE_ENABLED", True)
AGENT_REQUEST_TTL_SECONDS = max(
    1,
    int(os.environ.get("AGENT_REQUEST_TTL_SECONDS", "900")),
)
AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "90"))
