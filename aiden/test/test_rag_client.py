import re

import pytest
from pytest import MonkeyPatch
from responses import RequestsMock

from backend.services import rag_client
from backend.services.rag_client import RAGError


RAG_URL = "http://mock-rag-server:5003"


@pytest.fixture(autouse=True)
def rag_env(monkeypatch: MonkeyPatch):
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_SERVER_URL", RAG_URL)
    monkeypatch.setenv("RAG_FEATURE", "anomalies")
    monkeypatch.setenv("RAG_TIMEOUT_SECONDS", "5")


def test_retrieve_returns_normalised_results():
    with RequestsMock() as rsps:
        rsps.post(
            f"{RAG_URL}/retrieve",
            json={
                "results": [
                    {
                        "id": "anomalies_fraud-red-flags.md_0",
                        "text": "ATM charges are higher risk.",
                        "metadata": {"source": "fraud-red-flags.md"},
                        "distance": 0.3,
                    }
                ]
            },
        )

        results = rag_client.retrieve("anomalies", "Sketchy ATM cash", k=2)

    assert results == [
        {
            "id": "anomalies_fraud-red-flags.md_0",
            "text": "ATM charges are higher risk.",
            "metadata": {"source": "fraud-red-flags.md"},
            "distance": 0.3,
        }
    ]


def test_retrieve_raises_when_disabled(monkeypatch: MonkeyPatch):
    monkeypatch.setenv("RAG_ENABLED", "false")

    with pytest.raises(RAGError) as excinfo:
        rag_client.retrieve("anomalies", "question")

    assert excinfo.value.code == "rag_disabled"


def test_retrieve_raises_on_http_error():
    with RequestsMock() as rsps:
        rsps.post(f"{RAG_URL}/retrieve", status=500)

        with pytest.raises(RAGError) as excinfo:
            rag_client.retrieve("anomalies", "question")

    assert excinfo.value.code == "rag_http_error"


def test_retrieve_raises_on_invalid_result_shape():
    with RequestsMock() as rsps:
        rsps.post(
            f"{RAG_URL}/retrieve",
            json={"results": [{"id": 1, "text": "x", "metadata": {}, "distance": 0.1}]},
        )

        with pytest.raises(RAGError) as excinfo:
            rag_client.retrieve("anomalies", "question")

    assert excinfo.value.code == "rag_invalid_response"


def test_retrieve_raises_on_connection_error():
    with RequestsMock(assert_all_requests_are_fired=False):
        with pytest.raises(RAGError) as excinfo:
            rag_client.retrieve("anomalies", "question")

    assert excinfo.value.code == "rag_connection"


def test_health_returns_collections():
    with RequestsMock() as rsps:
        rsps.get(f"{RAG_URL}/health", json={"ok": True, "collections": ["anomalies"]})

        body = rag_client.health()

    assert body["collections"] == ["anomalies"]
