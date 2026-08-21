"""Tests for sophia.backend.ai.guard, schemas, and dispute_prompt's step injection.

No real HTTP: sophia.backend.ai.guard.chat is monkeypatched throughout, so
these run entirely offline.
"""
import json
from datetime import date

import requests

from sophia.backend.ai import dispute_prompt, guard
from sophia.backend.ai.schemas import validate_chat_response, validate_dispute_draft
from sophia.backend.engine import Bill

VALID_DRAFT = {
    "letter_text": "x" * 100,
    "steps": ["Do the first thing", "Do the second thing"],
    "escalation": ["Merchant support"],
    "payment_method_note": None,
}

VALID_CHAT = {
    "op": None,
    "entity": None,
    "id": None,
    "fields": None,
    "question": "total",
    "say": "Here is the total.",
}


def _bill(**overrides):
    defaults = dict(
        id=1,
        name="Test Bill",
        merchant="Test Merchant",
        amount_cents=1000,
        cadence="monthly",
        next_billing_date=date(2026, 9, 1),
        type="bill",
        payment_method=None,
    )
    defaults.update(overrides)
    return Bill(**defaults)


def _chat_response(payload):
    return {"message": {"content": json.dumps(payload)}}


def test_validate_dispute_draft_accepts_a_valid_response():
    assert validate_dispute_draft(VALID_DRAFT) is None


def test_validate_dispute_draft_rejects_short_letter():
    data = dict(VALID_DRAFT, letter_text="too short")
    assert validate_dispute_draft(data) is not None


def test_validate_dispute_draft_rejects_too_few_steps():
    data = dict(VALID_DRAFT, steps=["only one"])
    assert validate_dispute_draft(data) is not None


def test_validate_dispute_draft_rejects_too_many_steps():
    data = dict(VALID_DRAFT, steps=[f"step {i}" for i in range(9)])
    assert validate_dispute_draft(data) is not None


def test_validate_dispute_draft_rejects_empty_escalation():
    data = dict(VALID_DRAFT, escalation=[])
    assert validate_dispute_draft(data) is not None


def test_validate_dispute_draft_rejects_non_string_note():
    data = dict(VALID_DRAFT, payment_method_note=123)
    assert validate_dispute_draft(data) is not None


def test_validate_dispute_draft_rejects_non_object():
    assert validate_dispute_draft(["not", "an", "object"]) is not None


def test_validate_chat_response_accepts_a_valid_response():
    assert validate_chat_response(VALID_CHAT) is None


def test_validate_chat_response_rejects_bad_op():
    data = dict(VALID_CHAT, op="destroy")
    assert validate_chat_response(data) is not None


def test_validate_chat_response_rejects_bad_entity():
    data = dict(VALID_CHAT, entity="account")
    assert validate_chat_response(data) is not None


def test_validate_chat_response_rejects_non_int_id():
    data = dict(VALID_CHAT, id="3")
    assert validate_chat_response(data) is not None


def test_validate_chat_response_rejects_non_object_fields():
    data = dict(VALID_CHAT, fields="end_date=2026-09-16")
    assert validate_chat_response(data) is not None


def test_validate_chat_response_rejects_bad_question():
    data = dict(VALID_CHAT, question="how much")
    assert validate_chat_response(data) is not None


def test_validate_chat_response_rejects_say_too_long():
    data = dict(VALID_CHAT, say="x" * 301)
    assert validate_chat_response(data) is not None


def test_guard_succeeds_on_first_attempt_without_retry(monkeypatch):
    calls = []

    def fake_chat(model, messages, timeout=None):
        calls.append(messages)
        return _chat_response(VALID_DRAFT)

    monkeypatch.setattr(guard, "chat", fake_chat)
    result = guard.run("draft-model", lambda error: [{"role": "user", "content": "go"}], validate_dispute_draft, {})
    assert result["fallback"] is False
    assert result["letter_text"] == VALID_DRAFT["letter_text"]
    assert len(calls) == 1


def test_guard_retries_once_then_succeeds(monkeypatch):
    attempts = {"count": 0}

    def fake_chat(model, messages, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return _chat_response({"letter_text": "too short"})
        return _chat_response(VALID_DRAFT)

    monkeypatch.setattr(guard, "chat", fake_chat)
    errors_seen = []
    result = guard.run(
        "draft-model",
        lambda error: errors_seen.append(error) or [{"role": "user", "content": "go"}],
        validate_dispute_draft,
        {},
    )
    assert result["fallback"] is False
    assert attempts["count"] == 2
    assert errors_seen[0] is None
    assert errors_seen[1] is not None


def test_guard_falls_back_after_two_failed_attempts(monkeypatch):
    attempts = {"count": 0}

    def fake_chat(model, messages, timeout=None):
        attempts["count"] += 1
        return _chat_response({"letter_text": "still too short"})

    monkeypatch.setattr(guard, "chat", fake_chat)
    fallback = {"letter_text": "fallback text", "steps": [], "escalation": []}
    result = guard.run("draft-model", lambda error: [{"role": "user", "content": "go"}], validate_dispute_draft, fallback)
    assert result["fallback"] is True
    assert result["letter_text"] == "fallback text"
    assert attempts["count"] == 2


def test_guard_falls_back_when_ollama_unreachable_and_never_raises(monkeypatch):
    def raise_connection_error(model, messages, timeout=None):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(guard, "chat", raise_connection_error)
    fallback = {"op": None, "entity": None, "id": None, "fields": None, "question": "none", "say": "fallback"}
    result = guard.run("chat-model", lambda error: [{"role": "user", "content": "go"}], validate_chat_response, fallback)
    assert result["fallback"] is True
    assert result["say"] == "fallback"


def test_guard_falls_back_on_malformed_json(monkeypatch):
    def fake_chat(model, messages, timeout=None):
        return {"message": {"content": "not json at all"}}

    monkeypatch.setattr(guard, "chat", fake_chat)
    fallback = {"letter_text": "fallback text", "steps": [], "escalation": []}
    result = guard.run("draft-model", lambda error: [{"role": "user", "content": "go"}], validate_dispute_draft, fallback)
    assert result["fallback"] is True


def test_enforce_payment_method_step_injects_direct_debit_step_when_missing():
    bill = _bill(payment_method="direct_debit")
    data = {"steps": ["Contact the merchant", "Keep records"]}
    result = dispute_prompt.enforce_payment_method_step(data, bill)
    joined = " ".join(result["steps"]).lower()
    assert "direct-debit authority" in joined or "direct debit authority" in joined


def test_enforce_payment_method_step_does_not_duplicate_when_already_present():
    bill = _bill(payment_method="direct_debit")
    data = {"steps": ["Ask your bank to remove the direct debit authority on this account."]}
    result = dispute_prompt.enforce_payment_method_step(data, bill)
    assert len(result["steps"]) == 1


def test_enforce_payment_method_step_not_fooled_by_afca_name():
    bill = _bill(payment_method="direct_debit")
    data = {"steps": ["Escalate to the Australian Financial Complaints Authority (AFCA) if unresolved."]}
    result = dispute_prompt.enforce_payment_method_step(data, bill)
    assert len(result["steps"]) == 2
    assert "direct-debit authority" in result["steps"][-1].lower()


def test_enforce_payment_method_step_injects_card_step_when_missing():
    bill = _bill(payment_method="card")
    data = {"steps": ["Contact the merchant"]}
    result = dispute_prompt.enforce_payment_method_step(data, bill)
    assert any("account page" in s.lower() for s in result["steps"])


def test_enforce_payment_method_step_does_not_duplicate_card_step():
    bill = _bill(payment_method="card")
    data = {"steps": ["Cancel the subscription from the app's account page to stop future charges."]}
    result = dispute_prompt.enforce_payment_method_step(data, bill)
    assert len(result["steps"]) == 1


def test_enforce_payment_method_step_leaves_other_methods_untouched():
    bill = _bill(payment_method="bpay")
    data = {"steps": ["Contact the merchant"]}
    result = dispute_prompt.enforce_payment_method_step(data, bill)
    assert result["steps"] == ["Contact the merchant"]
