"""Environment configuration for the transactions backend."""
import os


PORT = int(os.environ.get("PORT", "5001"))
TRANSACTIONS_DB_URL = os.environ.get(
    "TRANSACTIONS_DB_URL",
    "http://transactions-db:6001",
).rstrip("/")
DATABASE_TIMEOUT_SECONDS = float(os.environ.get("DATABASE_TIMEOUT_SECONDS", "20"))
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://ollama:11434",
).rstrip("/")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:3b")
AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "90"))
