import os
import pathlib
import sys

# Backend/database config modules read these environment variables at import time
# (see aiden/backend/config.py and aiden/database/config.py). Tests import the apps
# at module load, so the variables must be set before those imports run. Values use
# the mock URLs the backend test suite intercepts via the `responses` library.
os.environ.setdefault("PORT", "5004")
os.environ.setdefault("ANOMALIES_DB_URL", "http://mock-database-url/anomalies")
os.environ.setdefault("TRANSACTIONS_DB_URL", "http://mock-transactions-url")
os.environ.setdefault("OLLAMA_URL", "http://mock-ollama-url")
os.environ.setdefault("OLLAMA_MODEL", "billy")
os.environ.setdefault("DB_PATH", ":memory:")

# Add the package root (aiden/) to sys.path so tests can import the local `database` package
# using absolute imports like `from database.app import app`. Pytest imports test modules as
# top-level modules, so relative imports (e.g. `from .database`) will fail otherwise.
def add_to_path(path: pathlib.Path):
    path_str = str(path)

    if path_str not in sys.path:
        sys.path.insert(0, path_str)

add_to_path(pathlib.Path(__file__).resolve().parent.parent.parent)
add_to_path(pathlib.Path(__file__).resolve().parent.parent)
