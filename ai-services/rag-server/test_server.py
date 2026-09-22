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


def test_retrieve_returns_the_closest_document_with_its_distance(http):
    """The overdue question finds the internet bill first."""
    body = http.post("/retrieve", json={"feature": FEATURE, "question": "Which bill is overdue?", "k": 1}).get_json()
    assert body["results"][0]["id"] == "a"
    assert body["results"][0]["distance"] >= 0


def test_retrieve_where_filters_on_metadata(http):
    """A where filter keeps only documents whose metadata matches."""
    body = http.post("/retrieve", json={"feature": FEATURE, "question": "Which bill is overdue?", "where": {"topic": "music"}}).get_json()
    assert [result["id"] for result in body["results"]] == ["b"]


def test_health_names_the_model_roles(http):
    """Health lists the three model roles."""
    body = http.get("/health").get_json()
    assert set(body["models"]) == {"generation", "review", "reasoning"}


def test_answer_uses_the_generation_model_by_default(http):
    """An answer carries the reply, the model used and the retrieved ids."""
    body = http.post("/answer", json={"feature": FEATURE, "question": "Which bill is overdue?"}).get_json()
    assert body["answer"] == "fake reply"
    assert body["model"] == query.MODELS["generation"]
    assert body["sources"][0] == "a"


def test_answer_role_picks_the_model_for_that_role(http, monkeypatch):
    """Asking with the reasoning role builds the reasoning model with reasoning turned on."""
    used = []

    def fake(**kwargs):
        used.append((kwargs["model"], kwargs["reasoning"]))
        return FakeListChatModel(responses=["fake reply"])

    monkeypatch.setattr(query, "ChatOllama", fake)
    http.post("/answer", json={"feature": FEATURE, "question": "Which bill is overdue?", "role": "reasoning"})
    assert used == [(query.MODELS["reasoning"], True)]
