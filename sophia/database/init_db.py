"""Creates the schema (if missing) and seeds the database when it is empty."""
import os

from db import get_connection, load_schema
from seed import seed

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def init_db(db_path):
    """Ensure db_path has the current schema and demo seed data, then close the connection."""
    connection = get_connection(db_path)
    load_schema(connection, SCHEMA_PATH)
    seed(connection)
    connection.close()


if __name__ == "__main__":
    init_db(os.environ.get("DB_PATH", "./bills.db"))
