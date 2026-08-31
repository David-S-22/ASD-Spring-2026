import os
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, jsonify


app = Flask(__name__)
app.config["DB_PATH"] = os.environ.get("DB_PATH", "./transactions.db")


def _check_database():
    with closing(sqlite3.connect(app.config["DB_PATH"])) as connection:
        connection.execute("SELECT 1").fetchone()


@app.get("/")
def get_index():
    return jsonify(container="transactions-db")


@app.get("/transactions")
def get_transactions():
    try:
        _check_database()
    except (OSError, sqlite3.Error):
        return jsonify(error="database unavailable"), 503

    return jsonify([])


def setup(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    app.config["DB_PATH"] = str(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("SELECT 1").fetchone()
