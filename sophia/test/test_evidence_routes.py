"""Tests for the Ask-with-evidence card fragments; the evidence service is faked."""
import pytest

from conftest import response_text as _text
from sophia.backend import app as backend_app_module
from sophia.backend import config
from sophia.backend.services import evidence as evidence_service
from sophia.backend.services.errors import ModeError

GROUNDED = {"answer": "Home internet (FibreLink, $79.00) is overdue.", "citations": [{"source": "bill-7-home-internet.md", "bill_id": 7, "title": "Home internet", "distance": 1.083}],
            "confidence": "medium", "insufficient": False, "retrieval": [{"id": "bills_bill-7-home-internet.md_0", "source": "bill-7-home-internet.md", "distance": 1.083}], "fallback": False, "duration_ms": 310.0}
INSUFFICIENT = {"answer": "Tally couldn't find a bill that covers that.", "citations": [], "confidence": "none", "insufficient": True,
                "retrieval": [{"id": "x", "source": "bill-1-rent.md", "distance": 1.62}], "fallback": False, "duration_ms": 290.0}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_panel_has_form_chips_and_result_target(client):
    body = _text(client.get("/ui/evidence"))
    assert 'id="evidence-panel"' in body
    assert 'hx-post="/bills-backend/ui/evidence"' in body and 'hx-target="#evidence-result"' in body
    assert 'data-evidence-chip="How much is my music subscription?"' in body
    assert 'data-evidence-chip="Which bill is overdue?"' in body
    assert 'data-evidence-chip="What is the capital of France?"' in body
    assert "RAG enabled" in body


def test_grounded_answer_shows_citation_chips_and_badge(client, monkeypatch):
    monkeypatch.setattr(evidence_service, "ask", lambda question: GROUNDED)
    response = client.post("/ui/evidence", data={"question": "Which bill is overdue?"})
    assert response.status_code == 200
    body = _text(response)
    assert "Home internet (FibreLink, $79.00) is overdue." in body
    assert "bill #7 · Home internet · 1.08" in body
    assert 'confidence-badge confidence-medium' in body
    assert "bill-7-home-internet.md · 1.083" in body
    assert "HX-Trigger" not in response.headers


def test_insufficient_answer_shows_the_card_with_no_chips(client, monkeypatch):
    monkeypatch.setattr(evidence_service, "ask", lambda question: INSUFFICIENT)
    body = _text(client.post("/ui/evidence", data={"question": "What is the capital of France?"}))
    assert "Insufficient context" in body and "couldn't find a bill" in body
    assert "citation-chip" not in body
    assert "evidence-insufficient" in body


def test_disabled_and_unavailable_render_error_fragments_without_server_names(client, monkeypatch):
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    response = client.post("/ui/evidence", data={"question": "x"})
    assert response.status_code == 503 and "RAG mode is disabled." in _text(response)
    monkeypatch.setattr(config, "RAG_ENABLED", True)

    def ask(question):
        raise ModeError("rag_unavailable")

    monkeypatch.setattr(evidence_service, "ask", ask)
    response = client.post("/ui/evidence", data={"question": "x"})
    body = _text(response)
    assert response.status_code == 503 and "The RAG server is unavailable." in body
    assert "8000" not in body and "5003" not in body
