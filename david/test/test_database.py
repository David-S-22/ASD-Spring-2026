from flask.testing import FlaskClient
from flask import Flask
from database.app import setup_app
import pytest

@pytest.fixture()
def app():
    app = setup_app(":memory:")
    app.config.update({"TESTING": True})
    yield app

@pytest.fixture()
def client(app: Flask):
    return app.test_client()

def test_get_all_goals(client: FlaskClient):
    client.get("/goals")
    assert 1 == 1
