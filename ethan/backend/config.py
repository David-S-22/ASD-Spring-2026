import os


BUDGETS_DB_URL = os.environ.get("BUDGETS_DB_URL", "http://budgets-db:6006").rstrip("/")
DATABASE_TIMEOUT_SECONDS = float(os.environ.get("DATABASE_TIMEOUT_SECONDS", "10"))
TRANSACTIONS_API_URL = os.environ.get("TRANSACTIONS_API_URL", "http://transactions-backend:5001").rstrip("/")
TRANSACTIONS_TIMEOUT_SECONDS = float(os.environ.get("TRANSACTIONS_TIMEOUT_SECONDS", "10"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:3b")
AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "90"))
