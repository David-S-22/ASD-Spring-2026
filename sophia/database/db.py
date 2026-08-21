"""SQLite connection helper for the bills database API."""
import sqlite3
from pathlib import Path


def get_connection(db_path):
    """Open a new SQLite connection with row access by column name and foreign keys enforced."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_schema(connection, schema_path):
    """Execute the schema.sql script against connection."""
    sql = Path(schema_path).read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.commit()


def row_to_dict(row):
    """Convert a sqlite3.Row into a plain dict, or return None unchanged."""
    return dict(row) if row is not None else None


def rows_to_list(rows):
    """Convert an iterable of sqlite3.Row into a list of dicts."""
    return [dict(row) for row in rows]
