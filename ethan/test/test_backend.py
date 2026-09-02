import pytest
from backend.app import app
from flask.testing import FlaskClient


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "ethan-backend"
