import pytest
from database.app import app, setup
from flask.testing import FlaskClient


@pytest.fixture(scope="session", autouse=True)
def one_time_setup():
    setup(":memory:")


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "ethan-db"
