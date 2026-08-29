import re

import pytest
import responses
from flask.testing import FlaskClient
from requests import PreparedRequest

from backend.app import app
from database.app import app as dbapp, setup_database


# Setup pytest and flask test client
@pytest.fixture
def client():
    setup_database(":memory:")

    with app.test_client() as client:
        yield client

@pytest.fixture(autouse=True)
def integrate_database(monkeypatch: pytest.MonkeyPatch):
    # In order to get the backend client to send requests
    # to the actual database server, we have to intercept
    # the requests via responses and redirect them to the
    # test_client instance

    def intercept(request: PreparedRequest):
        with dbapp.test_client() as dbclient:
            resp = dbclient.open(
                path=request.path_url,
                method=request.method,
                headers=dict(request.headers),
                data=request.body,
            )

            return resp.status_code, dict(resp.headers), resp.get_data()

    db_url = "http://mock-database-url/anomalies"
    monkeypatch.setenv("ANOMALIES_DB_URL", db_url)
    url = re.compile(rf"^{re.escape(db_url)}/?$")

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        for method in (responses.GET, responses.POST, responses.PATCH, responses.DELETE, responses.OPTIONS):
            rsps.add_callback(method, url, intercept)

        yield

# Tests
def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "anomalies-backend"

def test_create_anomaly(client: FlaskClient):
    resp = client.post("/dummy-anomaly")
    assert resp.text.count("<tr>") == 1

    resp = client.post("/dummy-anomaly")
    assert resp.text.count("<tr>") == 2

    resp = client.post("/dummy-anomaly")
    assert resp.text.count("<tr>") == 3
