import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, jsonify


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify(container="transactions-db")


def setup(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)):
        pass
