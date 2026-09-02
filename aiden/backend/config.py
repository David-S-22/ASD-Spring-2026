"""Environment configuration for the anomalies backend."""
import os


PORT = int(os.environ["PORT"])
ANOMALIES_DB_URL = os.environ["ANOMALIES_DB_URL"].rstrip("/")
TRANSACTIONS_DB_URL = os.environ["TRANSACTIONS_DB_URL"].rstrip("/")
OLLAMA_URL = os.environ["OLLAMA_URL"].rstrip("/")
OLLAMA_MODEL = os.environ["OLLAMA_MODEL"]
