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


def test_valid_dispute_proposal_survives_vetting():
    preview = {"op": "create", "entity": "dispute", "id": None, "fields": {"bill_id": 6, "reason": "x"}}
    vetted, reply = _vet_proposal(preview)
    assert vetted == {"bill_id": 6, "reason": "x"} and reply is None


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


def test_say_that_claims_a_new_bill_must_not_ship_an_update_to_an_existing_one(live_client, monkeypatch):
    """Observed on the 3b model, 3 Sep: the reply read "I've suggested adding
    Disney Plus at $15 a month from 5 Sep" while the op was
    {"op": "update", "id": 6, fields: {amount: 15.0, ...}} -- bill 6 being
    GymCo, and no name field anywhere. The sentence describes a bill that does
    not exist; the card silently rewrites one that does. Approving would have
    changed GymCo's amount, next billing date and payment method.

    The op is what gets applied, so a reply that promises a NEW bill may never
    carry an update to an existing one.
    """
    gymco = next(b for b in bills_db_module.list_bills() if b["name"] == "GymCo")

    def fake_chat(model, messages, timeout=None):
        return {"message": {"content": json.dumps({
            "op": "update", "entity": "bill", "id": gymco["id"],
            "fields": {"amount": 15.0, "cadence": "monthly", "next_billing_date": "2026-09-05"},
            "question": "none",
            "say": "I've suggested adding Disney Plus at $15 a month from 5 Sep — approve it to save.",
        })}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    pending_before = {r["id"] for r in bills_db_module.list_suggestions(status="pending")}
    body = _text(live_client.post("/ui/chat", data={"message": "add disney plus"}))

    pending_after = {r["id"] for r in bills_db_module.list_suggestions(status="pending")}
    assert pending_after == pending_before, "no approvable card may be built from a contradictory turn"
    assert "Disney Plus at $15" not in body, "the contradictory sentence must not stand"
    assert bills_db_module.get_bill(gymco["id"])["amount_cents"] == gymco["amount_cents"]


def _update_turn(bill_id, say, fields):
    return lambda model, messages, timeout=None: {"message": {"content": json.dumps({
        "op": "update", "entity": "bill", "id": bill_id, "fields": fields, "question": "none", "say": say})}}


def _pending_ids():
    return {r["id"] for r in bills_db_module.list_suggestions(status="pending")}


def test_update_whose_reply_names_a_different_bill_is_refused_with_a_question(live_client, monkeypatch):
    """Observed on the 3b model: "Cancel Netflix from October" got the reply
    "ending Netflix" with {"op": "update", "id": 5} -- id 5 being Prime Video.
    The card would have ended the wrong subscription."""
    prime = next(b for b in bills_db_module.list_bills() if b["name"] == "Prime Video")
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _update_turn(prime["id"], "I've suggested ending Netflix from 2 October", {"end_date": "2026-10-02"}),
    )
    pending_before = _pending_ids()
    body = _text(live_client.post("/ui/chat", data={"message": "Cancel Netflix from October"}))

    assert "Confirm" not in body and "chat/apply" not in body
    assert "That change would apply to Prime Video, not Netflix. Which bill did you mean?" in body
    assert _pending_ids() == pending_before, "no approvable card may be built for the wrong bill"
    assert bills_db_module.get_bill(prime["id"])["end_date"] is None


def test_update_whose_reply_names_its_target_still_yields_a_proposal(live_client, monkeypatch):
    prime = next(b for b in bills_db_module.list_bills() if b["name"] == "Prime Video")
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _update_turn(prime["id"], "I've suggested ending Prime Video from 2 October", {"end_date": "2026-10-02"}),
    )
    pending_before = _pending_ids()
    body = _text(live_client.post("/ui/chat", data={"message": "Cancel Prime Video from October"}))

    assert "Proposed: <strong>Update Prime Video</strong>" in body
    assert "Which bill did you mean" not in body
    created = [r for r in bills_db_module.list_suggestions(status="pending") if r["id"] not in pending_before]
    assert [(r["op"], r["entity"], r["entity_id"]) for r in created] == [("update", "bill", prime["id"])]


def test_spotify_cancel_reply_naming_spotify_still_yields_a_proposal(live_client, monkeypatch):
    spotify = next(b for b in bills_db_module.list_bills() if b["name"] == "Spotify")
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _update_turn(spotify["id"], "I've suggested ending Spotify after 1 Oct", {"end_date": "2026-10-01"}),
    )
    pending_before = _pending_ids()
    body = _text(live_client.post("/ui/chat", data={"message": "I cancelled Spotify from October"}))

    assert "Proposed: <strong>Update Spotify</strong>" in body
    created = [r for r in bills_db_module.list_suggestions(status="pending") if r["id"] not in pending_before]
    assert [(r["op"], r["entity"], r["entity_id"]) for r in created] == [("update", "bill", spotify["id"])]


def test_update_whose_reply_names_no_bill_is_not_refused(live_client):
    prime = next(b for b in bills_db_module.list_bills() if b["name"] == "Prime Video")
    preview = {"op": "update", "entity": "bill", "id": prime["id"], "fields": {"end_date": "2026-10-02"}}
    vetted, reply = _vet_proposal(preview, "I've suggested ending it from 2 October")
    assert vetted == {"end_date": "2026-10-02"} and reply is None


def test_bill_name_inside_another_word_is_not_a_mention(live_client):
    """Rent is a bill name; "current" contains it, and must not read as naming Rent."""
    netflix = next(b for b in bills_db_module.list_bills() if b["name"] == "Netflix")
    preview = {"op": "update", "entity": "bill", "id": netflix["id"], "fields": {"end_date": "2026-10-02"}}
    vetted, reply = _vet_proposal(preview, "I've suggested ending your current plan from 2 October")
    assert vetted == {"end_date": "2026-10-02"} and reply is None


def test_bill_names_match_case_insensitively(live_client):
    prime = next(b for b in bills_db_module.list_bills() if b["name"] == "Prime Video")
    preview = {"op": "update", "entity": "bill", "id": prime["id"], "fields": {"end_date": "2026-10-02"}}
    vetted, reply = _vet_proposal(preview, "I've suggested ending NETFLIX from 2 October")
    assert vetted is None
    assert reply == "That change would apply to Prime Video, not Netflix. Which bill did you mean?"


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
