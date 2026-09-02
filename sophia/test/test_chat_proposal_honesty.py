"""The chat may only promise what can actually happen.

Covers the two halves of "the AI said it changed something and the table never
moved": (1) the validator now refuses incoherent ops (op without entity/id/
fields) so the guard retries instead of silently building no preview, and
(2) an under-specified or malformed proposal becomes a follow-up question,
never a Confirm button that goes nowhere or a value nobody stated.
"""
import json

import pytest

from sophia.backend.ai.schemas import validate_chat_response
from sophia.backend.services.chat import _build_preview, _vet_proposal
from sophia.backend.clients import bills_db as bills_db_module
from conftest import response_text as _text


def _chat(**overrides):
    data = {"op": None, "entity": None, "id": None, "fields": None, "question": "none", "say": "ok"}
    data.update(overrides)
    return data


# --- validator coherence -----------------------------------------------------

def test_create_without_entity_is_rejected():
    error = validate_chat_response(_chat(op="create", fields={"name": "X"}))
    assert error == 'op "create" requires an entity'


def test_create_without_fields_is_rejected():
    error = validate_chat_response(_chat(op="create", entity="bill"))
    assert error == 'op "create" requires fields'


@pytest.mark.parametrize("op", ["update", "delete"])
def test_update_and_delete_without_id_are_rejected(op):
    error = validate_chat_response(_chat(op=op, entity="bill", fields={"end_date": "2026-09-16"}))
    assert error == f'op "{op}" requires an integer id'


def test_read_op_without_id_is_still_valid():
    assert validate_chat_response(_chat(op="read", entity="bill")) is None


def test_null_op_needs_no_counterparts():
    assert validate_chat_response(_chat()) is None


# --- preview building --------------------------------------------------------

def test_read_op_builds_no_preview():
    """A read is a question; a Confirm button for it could only fail."""
    assert _build_preview(_chat(op="read", entity="bill", id=3)) is None


# --- proposal vetting --------------------------------------------------------

def test_underspecified_create_becomes_a_question_not_a_proposal():
    preview = {"op": "create", "entity": "bill", "id": None, "fields": {"name": "Netflix"}}
    vetted, reply = _vet_proposal(preview)
    assert vetted is None
    assert "amount" in reply and "won't guess" in reply


def test_fully_specified_create_survives_vetting():
    fields = {"name": "Disney Plus", "amount": 15.0, "cadence": "monthly",
              "next_billing_date": "2026-09-05", "type": "subscription"}
    vetted, reply = _vet_proposal({"op": "create", "entity": "bill", "id": None, "fields": fields})
    assert vetted is not None and reply is None


def test_non_iso_date_in_proposal_becomes_a_question():
    fields = {"name": "X", "amount": 5, "cadence": "monthly",
              "next_billing_date": "early September", "type": "bill"}
    vetted, reply = _vet_proposal({"op": "create", "entity": "bill", "id": None, "fields": fields})
    assert vetted is None
    assert "calendar date" in reply


def test_invented_field_in_proposal_becomes_a_question():
    vetted, reply = _vet_proposal({"op": "update", "entity": "bill", "id": 3, "fields": {"colour": "blue"}})
    assert vetted is None
    assert "colour" in reply


def test_dispute_proposals_are_not_vetted_here():
    preview = {"op": "create", "entity": "dispute", "id": None, "fields": {"bill_id": 6, "reason": "x"}}
    vetted, reply = _vet_proposal(preview)
    assert vetted is preview and reply is None


# --- end to end through /ui/chat with a stubbed model ------------------------

def test_underspecified_create_from_the_model_yields_a_question_and_no_confirm(live_client, monkeypatch):
    def fake_chat(model, messages, timeout=None):
        return {"message": {"content": json.dumps({
            "op": "create", "entity": "bill", "id": None,
            "fields": {"name": "Netflix"}, "question": "none",
            "say": "Added Netflix for you."})}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    before = len(bills_db_module.list_bills())
    response = live_client.post("/ui/chat", data={"message": "add netflix"})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "chat/apply" not in body and "Confirm" not in body
    assert "I just need" in body
    assert len(bills_db_module.list_bills()) == before


def test_incoherent_op_from_the_model_falls_back_honestly(live_client, monkeypatch):
    """op without entity now fails validation on both attempts; the reply must
    be the fallback, not the model's 'Added it for you.'"""
    def fake_chat(model, messages, timeout=None):
        return {"message": {"content": json.dumps({
            "op": "create", "entity": None, "id": None,
            "fields": {"name": "Ghost"}, "question": "none",
            "say": "Added Ghost for you."})}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    response = live_client.post("/ui/chat", data={"message": "add ghost"})
    assert response.status_code == 200
    body = _text(response)
    assert "Added Ghost" not in body
    assert "couldn't understand" in body
