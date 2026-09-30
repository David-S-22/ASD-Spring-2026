import json
import logging
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app
import janelle.backend.services.transaction_orchestrator as transaction_orchestrator
from janelle.backend import config
from janelle.backend.services import category_grounding, rag_answer
from janelle.backend.services.rag_client import RAGError


CATEGORIES = [
    {"id": 1, "name": "Uncategorised", "type": None},
    {"id": 31, "name": "Fitness", "type": "want"},
    {"id": 81, "name": "Groceries", "type": "need"},
]
CREATE_FIELDS = {
    "date": "2026-09-24",
    "merchant": "Anytime Fitness",
    "description": "Membership",
    "amount": 17.5,
}
MESSAGE = "Add $17.50 Anytime Fitness membership on 24 Sep 2026"
RECORD_CITATION = {
    "marker": 1,
    "id": "tx-7",
    "collection": "transactions-records",
    "source": "transaction 7",
    "excerpt": "Transaction 7 on 2026-06-24: Anytime Fitness ...",
    "distance": 0.31,
    "category_id": 31,
    "category": "Fitness",
    "date": "2026-06-24",
    "merchant": "Anytime Fitness Ultimo",
    "amount": 17.5,
}
GUIDE_CITATION = {
    "marker": 2,
    "id": "transactions_categories.md_2",
    "collection": "transactions",
    "source": "categories.md",
    "excerpt": "Fitness: club direct debits such as Anytime Fitness.",
    "distance": 0.52,
}


def grounded(answer="Fitness", confidence="high", **overrides):
    return {
        "status": "grounded",
        "answer": answer,
        "confidence": confidence,
        "insufficient_context": False,
        "uncited": False,
        "derived_from_votes": False,
        "citations": [RECORD_CITATION, GUIDE_CITATION],
        "retrieved": 9,
        "survivors": 2,
        "best_distance": 0.31,
        "model_probability": 0.93,
        "model": "qwen2.5:3b",
        **overrides,
    }


def insufficient():
    return {
        "status": "insufficient",
        "answer": None,
        "confidence": "insufficient",
        "insufficient_context": True,
        "uncited": False,
        "derived_from_votes": False,
        "citations": [],
        "retrieved": 4,
        "survivors": 0,
        "best_distance": 1.4,
        "model": "qwen2.5:3b",
    }


def context():
    return {
        "categories": [dict(item) for item in CATEGORIES],
        "category_names": {c["id"]: c["name"] for c in CATEGORIES},
        "category_ids": {c["name"].casefold(): c["id"] for c in CATEGORIES},
        "request_id": "req-1",
        "phase": "initial",
        "iteration": 1,
    }


def workflow_records(caplog, event):
    return [
        record
        for record in (
            json.loads(item.getMessage().split("AI_WORKFLOW ", 1)[1])
            for item in caplog.records
            if "AI_WORKFLOW " in item.getMessage()
        )
        if record["event"] == event
    ]


@fixture
def client():
    transaction_orchestrator.reset_transaction_requests()
    with backend_app.app.test_client() as test_client:
        yield test_client
    transaction_orchestrator.reset_transaction_requests()


@fixture
def rag_on(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "RAG_ENABLED", True)


@fixture
def grounding(monkeypatch: MonkeyPatch):
    """Install a fake ``rag_answer.grounded_answer``; returns the mock."""
    def install(result=None, error=None):
        mock = Mock(return_value=result, side_effect=error)
        monkeypatch.setattr(rag_answer, "grounded_answer", mock)
        return mock

    return install


@fixture
def database(monkeypatch: MonkeyPatch):
    """Install ``requests.get`` answering each payload in turn; returns the mock."""
    def install(*payloads):
        responses = []
        for payload in payloads:
            response = Mock(status_code=200)
            response.json.return_value = payload
            responses.append(response)
        get = Mock(side_effect=responses)
        monkeypatch.setattr(backend_app.requests, "get", get)
        return get

    return install


@fixture
def extraction(monkeypatch: MonkeyPatch):
    """Make the planner extract a create with the given fields."""
    def install(fields=CREATE_FIELDS):
        monkeypatch.setattr(
            transaction_orchestrator.ollama_service,
            "create_plan",
            Mock(return_value={
                "operation": "create",
                "transaction_id": None,
                "fields": dict(fields),
                "filters": {},
                "calculation": "none",
                "handoff": "none",
                "reply": "Prepared safely.",
                "fallback": False,
                "planning_error": None,
                "retryable": False,
            }),
        )

    return install


# --- unit level -------------------------------------------------------------


def test_disabled_switch_returns_disabled_without_calling_rag(grounding):
    answer = grounding(grounded())

    category_id, result = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert result == {"status": "disabled"}
    answer.assert_not_called()


def test_rag_error_degrades_to_unavailable(rag_on, grounding):
    grounding(error=RAGError("rag_http_error"))

    category_id, result = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert result == {"status": "unavailable", "error": "rag_http_error"}


def test_insufficient_is_passed_through(rag_on, grounding):
    grounding(insufficient())

    category_id, result = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert result["status"] == "insufficient"
    assert result["citations"] == []


def test_question_from_merchant_and_description_resolves_id_by_casefold(
    rag_on,
    grounding,
):
    answer = grounding(grounded(answer="fitness"))

    category_id, result = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert answer.call_args.args[0] == (
        "Merchant: Anytime Fitness; Description: Membership"
    )
    assert category_id == 31
    assert result["status"] == "grounded"


def test_unresolvable_answer_becomes_unavailable(rag_on, grounding):
    grounding(grounded(answer="Retired category"))

    category_id, result = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert result["status"] == "unavailable"
    assert result["error"] == "no_category_resolved"


# --- through the create flow -----------------------------------------------


def test_chat_grounded_suggestion_sets_id_and_carries_grounding(
    client: FlaskClient,
    rag_on,
    database,
    extraction,
    grounding,
):
    get = database(CATEGORIES)
    extraction()
    grounding(grounded())

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.status_code == 200
    result = response.get_json()
    selection = result["category_selection"]
    assert selection["suggested_category_id"] == 31
    assert selection["suggested_category_name"] == "Fitness"
    assert selection["grounding"]["status"] == "grounded"
    assert selection["grounding"]["confidence"] == "high"
    assert len(selection["grounding"]["citations"]) == 2
    assert result["reply"] == (
        "I suggest Fitness. Use Fitness, or choose another category."
    )
    # The Release 0 correction vote did not run.
    assert get.call_count == 1


def test_chat_unavailable_runs_release_0_correction_vote(
    client: FlaskClient,
    rag_on,
    database,
    extraction,
    grounding,
):
    get = database(
        CATEGORIES,
        [{"user_category_id": 81, "user_category_name": "Groceries"}],
    )
    extraction()
    grounding(error=RAGError("rag_http_error"))

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.status_code == 200
    selection = response.get_json()["category_selection"]
    assert selection["suggested_category_id"] == 81
    assert selection["grounding"] == {
        "status": "unavailable",
        "error": "rag_http_error",
    }
    assert get.call_count == 2
    assert get.call_args.kwargs["params"] == {
        "merchant": "Anytime Fitness",
        "limit": 10,
    }


def test_chat_insufficient_asks_the_user_to_choose(
    client: FlaskClient,
    rag_on,
    database,
    extraction,
    grounding,
):
    database(CATEGORIES, [])
    extraction()
    grounding(insufficient())

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.status_code == 200
    result = response.get_json()
    assert result["reply"] == (
        "I couldn't find past transactions or notes similar enough to "
        "suggest a category. Choose a category to continue."
    )
    selection = result["category_selection"]
    assert selection["suggested_category_id"] is None
    assert selection["grounding"]["status"] == "insufficient"
    assert selection["grounding"]["citations"] == []


def test_chat_category_echoes_grounding_from_pending_request(
    client: FlaskClient,
    rag_on,
    database,
    extraction,
    grounding,
):
    database(CATEGORIES, CATEGORIES, [])
    extraction()
    grounding(grounded(confidence="medium"))

    first = client.post("/chat", json={"message": MESSAGE}).get_json()
    second = client.post(
        "/chat/category",
        json={
            "request_id": first["agent"]["request_id"],
            "category_id": 31,
        },
    )

    assert second.status_code == 200
    selection = second.get_json()["category_selection"]
    assert selection["source"] == "ai_suggestion"
    assert selection["selected_category_id"] == 31
    assert selection["grounding"] == first["category_selection"]["grounding"]


def test_chat_disabled_switch_leaves_release_0_payload_identical(
    client: FlaskClient,
    database,
    extraction,
    grounding,
):
    database(CATEGORIES, [])
    extraction({**CREATE_FIELDS, "category": "Fitness"})
    answer = grounding(grounded())

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.get_json()["category_selection"] == {
        "source": "ai_suggestion",
        "suggested_category_id": 31,
        "suggested_category_name": "Fitness",
        "selected_category_id": None,
        "selected_category_name": None,
        "requires_user_response": True,
    }
    answer.assert_not_called()


def test_ui_chat_renders_correction_citation_without_amount(
    client: FlaskClient,
    rag_on,
    database,
    extraction,
    grounding,
):
    """Correction documents carry no amount; the card must still render."""
    database(CATEGORIES)
    extraction()
    grounding(grounded(citations=[
        {
            **RECORD_CITATION,
            "id": "corr-3",
            "source": "correction 3",
            "date": "2026-08-20",
            "amount": None,
        },
        {**RECORD_CITATION, "marker": 2},
    ]))

    response = client.post("/ui/chat", data={"message": MESSAGE})

    assert response.status_code == 200
    assert "20 Aug 2026 · Anytime Fitness Ultimo · Fitness" in response.text
    assert "(correction)" in response.text
    assert "24 Jun 2026 · Anytime Fitness Ultimo · $17.50 · Fitness" in response.text


@mark.parametrize("outcome, status, confidence, error", [
    (grounded(), "grounded", "high", None),
    (RAGError("rag_timeout"), "unavailable", None, "rag_timeout"),
])
def test_grounding_log_record_is_redacted(
    client: FlaskClient,
    rag_on,
    database,
    extraction,
    grounding,
    caplog,
    outcome,
    status,
    confidence,
    error,
):
    database(CATEGORIES, [])
    extraction()
    if isinstance(outcome, Exception):
        grounding(error=outcome)
    else:
        grounding(outcome)

    with caplog.at_level(logging.INFO, logger=client.application.logger.name):
        response = client.post("/chat", json={"message": MESSAGE})

    records = workflow_records(caplog, "RAG_GROUNDING")
    assert len(records) == 1
    record = records[0]
    assert record["request_id"] == response.get_json()["agent"]["request_id"]
    assert record["status"] == status
    assert record["confidence"] == confidence
    assert record["error"] == error
    assert record["collections"] == ["transactions-records", "transactions"]
    assert record["duration_ms"] >= 0
    if status == "grounded":
        assert record["citations"] == 2
        assert record["best_distance"] == 0.31
        assert record["model_probability"] == 0.93
    assert "excerpt" not in json.dumps(record)
    assert "Anytime Fitness" not in caplog.text
    assert "Membership" not in caplog.text
