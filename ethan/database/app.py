import sqlite3
from pathlib import Path

from flask import Flask, jsonify


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify(container="ethan-db")


def setup(db_path: str):
    if db_path == ":memory:":
        return

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path):
        pass
