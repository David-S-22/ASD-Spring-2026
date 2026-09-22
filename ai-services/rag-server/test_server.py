import pytest
from langchain_core.language_models import FakeListChatModel

import query
from database import client
from server import app

FEATURE = "servertest"
IDS = ["a", "b", "c"]
DOCUMENTS = ["The internet bill is overdue.", "Spotify is a music subscription.", "Rent is paid on the first of the month."]
METADATAS = [{"topic": "bills"}, {"topic": "music"}, {"topic": "bills"}]


@pytest.fixture
def http(monkeypatch):
    """A test client over a small refreshed corpus, with model calls answered by a fake model."""
    monkeypatch.setattr(query, "ChatOllama", lambda **kwargs: FakeListChatModel(responses=["fake reply"]))
    test_client = app.test_client()
    test_client.post("/refresh", json={"feature": FEATURE, "ids": IDS, "documents": DOCUMENTS, "metadatas": METADATAS})
    yield test_client
    client.delete_collection(name=FEATURE)


def test_health_lists_the_collection(http):
    """Health names every collection in the store."""
    body = http.get("/health").get_json()
    assert body["ok"] is True
    assert FEATURE in body["collections"]


def test_refresh_replaces_the_documents(http):
    """Refreshing with one document leaves exactly one document."""
    body = http.post("/refresh", json={"feature": FEATURE, "ids": ["a"], "documents": ["Only one document now."]}).get_json()
    assert body["total"] == 1
