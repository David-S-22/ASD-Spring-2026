import re

from pytest import MonkeyPatch, fixture
from flask.testing import FlaskClient
from requests import PreparedRequest
from responses import RequestsMock

from backend.app import app
from database.app import app as dbapp, setup_database


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


# Pytest fixtures
@fixture
def client():
    setup_database(":memory:")

    with app.test_client() as client:
        yield client

@fixture(autouse=True)
def integrate_database(monkeypatch: MonkeyPatch):
    # In order to get the backend client to send requests
    # to the actual database server, we have to intercept
    # the requests via responses and redirect them to the
    # test_client instance

    def intercept(request: PreparedRequest):
        with dbapp.test_client() as dbclient:
            resp = dbclient.open(
                path = request.path_url,
                method = request.method,
                headers = dict(request.headers),
                data = request.body)

            return resp.status_code, dict(resp.headers), resp.get_data()

    db_url = "http://mock-database-url/anomalies"
    monkeypatch.setenv("ANOMALIES_DB_URL", db_url)
    url = re.compile(rf"^{re.escape(db_url)}/?$")

    with RequestsMock(assert_all_requests_are_fired=False) as rsps:
        for method in (RequestsMock.GET, RequestsMock.POST, RequestsMock.PATCH, RequestsMock.DELETE, RequestsMock.OPTIONS):
            rsps.add_callback(method, url, intercept)

        yield
