"""Environment configuration for the bills backend, read once at import time."""
import os
from datetime import datetime

PORT = int(os.environ.get("PORT", "5005"))
BILLS_DB_API_URL = os.environ.get("BILLS_DB_API_URL", "http://bills-db:6005")
TRANSACTIONS_DB_API_URL = os.environ.get("TRANSACTIONS_DB_API_URL") or None
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3005")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
DRAFT_MODEL = os.environ.get("DRAFT_MODEL", "llama3.1:8b")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:0.5b")
AI_TIMEOUT_SECONDS = int(os.environ.get("AI_TIMEOUT_SECONDS", "90"))
DEMO_TODAY = datetime.strptime(os.environ.get("DEMO_TODAY", "2026-08-20")[:10], "%Y-%m-%d").date()
