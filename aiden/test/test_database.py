import pytest
from database.app import app, setup
from flask.testing import FlaskClient
from uuid import UUID, uuid4


# Setup pytest and flask test client
@pytest.fixture(scope="session", autouse=True)
def one_time_setup():
    setup(":memory:")

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


# Tests
def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "anomalies-db"

def test_create_anomaly(client: FlaskClient):
    json = dict(transaction_id=uuid4(), agent_reason_suspected="beans", is_confirmed_by_user="False")

    # Check we can create the object
    resp = client.post("/anomaly", json=json)

    assert resp.status_code == 201
    assert isinstance(create_json := resp.json, dict)

    # Check we can fetch the object we just created
    resp = client.get("/anomaly/" + create_json["id"])

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json == create_json

    # Check the expected keys
    assert UUID(resp.json["id"])
    assert UUID(resp.json["transaction_id"])
    assert resp.json["is_confirmed_by_user"] == False
    assert resp.json["agent_reason_suspected"] == "beans"
