"""Environment configuration for the transactions backend."""
import os


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
ANOMALIES_TIMEOUT_SECONDS = float(
    os.environ.get("ANOMALIES_TIMEOUT_SECONDS", "10")
)
