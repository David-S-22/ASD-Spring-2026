from pathlib import Path

from flask.testing import FlaskClient
from pytest import fixture

from janelle.database.app import app, setup


@fixture
def database_client(tmp_path: Path):
    original_path = app.config["DB_PATH"]
    database_path = tmp_path / "data" / "transactions.db"
    setup(str(database_path))

    try:
        with app.test_client() as client:
            yield client, database_path
    finally:
        app.config["DB_PATH"] = original_path


def test_index_identifies_database(database_client):
    client, _database_path = database_client

    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"container": "transactions-db"}


def test_transactions_returns_list_and_creates_database(database_client):
    client, database_path = database_client

    response = client.get("/transactions")

    assert response.status_code == 200
    assert response.get_json() == []
    assert database_path.is_file()


def test_transactions_reports_unavailable_database(
    database_client,
    tmp_path: Path,
):
    client, _database_path = database_client
    app.config["DB_PATH"] = str(tmp_path)

    response = client.get("/transactions")

    assert response.status_code == 503
    assert response.get_json() == {"error": "database unavailable"}
