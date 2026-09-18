from typing import Any

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
    json = dict(transaction_id=101, agent_reason_suspected="beans", is_confirmed_by_user=False)

    # Check we can create the object
    resp = client.post("/anomalies/", json=json)

    assert resp.status_code == 201
    assert isinstance(create_json := resp.json, dict)

    # Check we can fetch the object we just created
    resp = client.get("/anomalies/" + str(create_json["id"]))

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json == create_json

    # Check the expected keys
    assert isinstance(resp.json["id"], int)
    assert isinstance(resp.json["transaction_id"], int)
    assert resp.json["is_confirmed_by_user"] == False
    assert resp.json["agent_reason_suspected"] == "beans"

def test_delete_anomaly(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=201, agent_reason_suspected="beans", is_confirmed_by_user=False)
    response = client.delete(f"/anomalies/{anomaly.id}")

    assert response.status_code == 204
    assert client.get(f"/anomalies/{anomaly.id}").status_code == 404

def test_delete_anomaly_by_transaction(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=301, agent_reason_suspected="beans", is_confirmed_by_user=False)
    response = client.delete(f"/anomalies/by-transaction/{anomaly.transaction_id}")

    assert response.status_code == 204
    assert client.get(f"/anomalies/{anomaly.id}").status_code == 404

def test_get_anomaly_by_transaction_returns_anomaly(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=501, agent_reason_suspected="beans", is_confirmed_by_user=False)

    response = client.get(f"/anomalies/by-transaction/{anomaly.transaction_id}")

    assert response.status_code == 200
    assert isinstance(response.json, dict)
    assert response.json["id"] == anomaly.id
    assert response.json["transaction_id"] == 501
    assert response.json["agent_reason_suspected"] == "beans"


def test_get_anomaly_by_transaction_not_found_returns_404(client: FlaskClient):
    response = client.get("/anomalies/by-transaction/999999")

    assert response.status_code == 404
    assert isinstance(response.json, dict)
    assert response.json["code"] == 404
    assert response.json["name"] == "Not Found"


def test_delete_anomaly_that_doesnt_exist(client: FlaskClient):
    by_id = client.delete("/anomalies/999999")
    by_transaction = client.delete("/anomalies/by-transaction/999999")

    assert by_id.status_code == 204
    assert by_transaction.status_code == 204

def test_route_not_found(client: FlaskClient):
    response = client.get("/whatareyoudoinginmyswamp")

    assert response.status_code == 404
    assert isinstance(response.json, dict)
    assert response.json["code"] == 404
    assert response.json["name"] == "Not Found"


def test_get_all_anomalies_returns_empty_list_for_clean_db(client: FlaskClient):
    response = client.get("/anomalies/")
    assert response.status_code == 200
    assert isinstance(response.json, list)

    for anomaly in response.json:
        assert isinstance(anomaly, dict)
        client.delete(f"/anomalies/{anomaly['id']}")

    response = client.get("/anomalies/")
    assert response.status_code == 200
    assert isinstance(response.json, list)
    assert response.json == []


def test_get_anomaly_not_found_returns_404(client: FlaskClient):
    response = client.get("/anomalies/999999")

    assert response.status_code == 404
    assert isinstance(response.json, dict)
    assert response.json["code"] == 404
    assert response.json["name"] == "Not Found"


def test_create_anomaly_missing_required_fields_returns_400(client: FlaskClient):
    response = client.post("/anomalies/", json={"transaction_id": 123})

    assert response.status_code == 400
    assert isinstance(response.json, dict)
    assert response.json["code"] == 400
    assert response.json["description"] == "Missing required field agent_reason_suspected"


def test_create_anomaly_missing_transaction_id_returns_400(client: FlaskClient):
    response = client.post("/anomalies/", json={"agent_reason_suspected": "beans"})

    assert response.status_code == 400
    assert isinstance(response.json, dict)
    assert response.json["code"] == 400
    assert response.json["description"] == "Missing required field transaction_id"


def test_create_anomaly_rejects_invalid_boolean_flag(client: FlaskClient):
    response = client.post(
        "/anomalies/",
        json={
            "transaction_id": 123,
            "agent_reason_suspected": "beans",
            "is_confirmed_by_user": "maybe",
        },
    )

    assert response.status_code == 400
    assert isinstance(response.json, dict)
    assert response.json["code"] == 400
    assert "Field is_confirmed_by_user expected try_parse_bool" in response.json["description"]


def test_create_anomaly_rejects_invalid_json_body(client: FlaskClient):
    response = client.post(
        "/anomalies/",
        data="{bad-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert isinstance(response.json, dict)
    assert response.json["code"] == 400


def test_patch_anomaly_updates_confirmation_flag(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=401, agent_reason_suspected="beans", is_confirmed_by_user=None)

    response = client.patch(f"/anomalies/{anomaly.id}", json={"is_confirmed_by_user": True})

    assert response.status_code == 200
    assert isinstance(response.json, dict)
    assert response.json["is_confirmed_by_user"] is True

    updated = client.get(f"/anomalies/{anomaly.id}")
    assert isinstance(updated.json, dict)
    assert updated.json["is_confirmed_by_user"] is True


def test_patch_anomaly_ignores_invalid_update_value(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=402, agent_reason_suspected="beans", is_confirmed_by_user=False)

    response = client.patch(f"/anomalies/{anomaly.id}", json={"is_confirmed_by_user": "not-a-bool"})

    assert response.status_code == 200
    assert isinstance(response.json, dict)
    assert response.json["is_confirmed_by_user"] is False

    updated = client.get(f"/anomalies/{anomaly.id}")
    assert isinstance(updated.json, dict)
    assert updated.json["is_confirmed_by_user"] is False


def test_patch_anomaly_with_null_value_is_ignored(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=403, agent_reason_suspected="beans", is_confirmed_by_user=False)

    response = client.patch(f"/anomalies/{anomaly.id}", json={"is_confirmed_by_user": None})

    assert response.status_code == 200
    assert isinstance(response.json, dict)
    assert response.json["is_confirmed_by_user"] is False


def test_patch_anomaly_with_empty_body_does_not_mutate_record(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=404, agent_reason_suspected="beans", is_confirmed_by_user=False)

    response = client.patch(f"/anomalies/{anomaly.id}", json={})

    assert response.status_code == 200
    assert isinstance(response.json, dict)
    assert response.json["is_confirmed_by_user"] is False
    assert response.json["agent_reason_suspected"] == "beans"


def test_patch_anomaly_with_unrelated_keys_does_not_mutate_state(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=405, agent_reason_suspected="beans", is_confirmed_by_user=False)

    response = client.patch(f"/anomalies/{anomaly.id}", json={"foo": "bar"})

    assert response.status_code == 200
    assert isinstance(response.json, dict)
    assert response.json["is_confirmed_by_user"] is False
    assert response.json["agent_reason_suspected"] == "beans"


def test_delete_by_transaction_repeated_calls_are_idempotent(client: FlaskClient):
    anomaly = create_anomaly(client, id=0, transaction_id=406, agent_reason_suspected="beans", is_confirmed_by_user=False)

    first = client.delete(f"/anomalies/by-transaction/{anomaly.transaction_id}")
    second = client.delete(f"/anomalies/by-transaction/{anomaly.transaction_id}")

    assert first.status_code == 204
    assert second.status_code == 204


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
