from typing import Any
from uuid import UUID, uuid4

from flask.testing import FlaskClient
from pytest import fixture

from backend.helpers import deserialise_safe, serialise
from database.app import app, setup_database
from shared.backend import dto


# Tests
def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "anomalies-db"

def test_create_anomaly(client: FlaskClient):
    json = dict(transaction_id=uuid4(), agent_reason_suspected="beans", is_confirmed_by_user=False)

    # Check we can create the object
    resp = client.post("/anomalies/", json=json)

    assert resp.status_code == 201
    assert isinstance(create_json := resp.json, dict)

    # Check we can fetch the object we just created
    resp = client.get("/anomalies/" + create_json["id"])

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
    response = client.delete(f"/anomalies/{anomaly.id}")

    assert response.status_code == 204
    assert client.get(f"/anomalies/{anomaly.id}").status_code == 404

def test_delete_anomaly_by_transaction(client: FlaskClient):
    anomaly = create_anomaly(client, id=uuid4(), transaction_id=uuid4(), agent_reason_suspected="beans", is_confirmed_by_user=False)
    response = client.delete(f"/anomalies/by-transaction/{anomaly.transaction_id}")

    assert response.status_code == 204
    assert client.get(f"/anomalies/{anomaly.id}").status_code == 404

def test_delete_anomaly_that_doesnt_exist(client: FlaskClient):
    by_id = client.delete(f"/anomalies/{uuid4()}")
    by_transaction = client.delete(f"/anomalies/by-transaction/{uuid4()}")

    assert by_id.status_code == 204
    assert by_transaction.status_code == 204

def test_route_not_found(client: FlaskClient):
    response = client.get("/whatareyoudoinginmyswamp")

    assert response.status_code == 404
    assert isinstance(response.json, dict)
    assert response.json["code"] == 404
    assert response.json["name"] == "Not Found"


# Pytest fixtures & helpers
@fixture
def client():
    setup_database(":memory:")

    with app.test_client() as client:
        yield client

def create_anomaly(client: FlaskClient, **kwargs: Any) -> dto.Anomaly:
    model = dto.Anomaly(**kwargs)
    response = client.post("/anomalies/", json=serialise(model))

    assert response.status_code == 201, response.text
    assert isinstance(data := response.json, dict)

    anomaly = deserialise_safe(dto.Anomaly, data)
    assert anomaly is not None

    return anomaly
