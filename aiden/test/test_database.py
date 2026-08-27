import pytest
from database.app import app, setup
from flask.testing import FlaskClient
from shared.backend import dto
from typing import Any
from uuid import UUID, uuid4


# Setup pytest and flask test client
@pytest.fixture(scope="session", autouse=True)
def one_time_setup():
    setup(":memory:")

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def create_anomaly(client: FlaskClient, **kwargs: Any) -> dto.Anomaly:
    if "id" in kwargs:
        kwargs["id"] = str(kwargs["id"])

    if "transaction_id" in kwargs:
        kwargs["transaction_id"] = str(kwargs["transaction_id"])

    response = client.post("/anomaly", json=kwargs)

    assert response.status_code == 201, response.text
    assert isinstance(data := response.json, dict)

    return dto.Anomaly(
        id=UUID(data["id"]),
        transaction_id=UUID(data["transaction_id"]),
        agent_reason_suspected=data["agent_reason_suspected"],
        is_confirmed_by_user=data["is_confirmed_by_user"],
    )


# Tests
def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "anomalies-db"

def test_create_anomaly(client: FlaskClient):
    json = dict(transaction_id=uuid4(), agent_reason_suspected="beans", is_confirmed_by_user=False)

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

def test_delete_anomaly(client: FlaskClient):
    anomaly = create_anomaly(client, id=uuid4(), transaction_id=uuid4(), agent_reason_suspected="beans", is_confirmed_by_user=False)
    response = client.delete(f"/anomaly/{anomaly.id}")

    assert response.status_code == 204
    assert client.get(f"/anomaly/{anomaly.id}").status_code == 404

def test_delete_anomaly_by_transaction(client: FlaskClient):
    anomaly = create_anomaly(client, id=uuid4(), transaction_id=uuid4(), agent_reason_suspected="beans", is_confirmed_by_user=False)
    response = client.delete(f"/anomaly/by-transaction/{anomaly.transaction_id}")

    assert response.status_code == 204
    assert client.get(f"/anomaly/{anomaly.id}").status_code == 404

def test_delete_anomaly_that_doesnt_exist(client: FlaskClient):
    by_id = client.delete(f"/anomaly/{uuid4()}")
    by_transaction = client.delete(f"/anomaly/by-transaction/{uuid4()}")

    assert by_id.status_code == 204
    assert by_transaction.status_code == 204
