"""Environment configuration for the anomalies backend."""
import os


PORT = int(os.environ.get("PORT", "5004"))
ANOMALIES_DB_URL = os.environ.get(
    "ANOMALIES_DB_URL",
    "http://anomalies-db:6004/anomalies",
).rstrip("/")
TRANSACTIONS_DB_URL = os.environ.get(
    "TRANSACTIONS_DB_URL",
    "http://transactions-db:6001",
).rstrip("/")
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://ollama:11434/v1",
).rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
