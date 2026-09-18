"""Environment configuration for the anomalies database."""
import os


PORT = int(os.environ.get("PORT", "6004"))
DB_PATH = os.environ.get("DB_PATH", "/app/data/anomalies.db")
