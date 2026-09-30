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
from sophia.backend.services import chat as chat_service
from sophia.backend.services.chat import _build_preview, _stated_text, _ungrounded_fields, _vet_proposal
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


# --- grounding: proposed values must come from the user's own words ----------

FOXTEL_MESSAGE = "Add Foxtel, $30 a month, first charge 10 October, paid by card"
SPOTIFY_MESSAGE = "I cancelled Spotify from September — remove the future payments"
STAN_SAY = "I've suggested adding Stan at $10 a month from 10 Oct"
STAN_NEEDS = (
    "Happy to add that — I just need the amount (in dollars), how often it bills "
    "(weekly, fortnightly or monthly), the next billing date. I won't guess details you haven't given me."
)


def _stan(**overrides):
    fields = {"name": "Stan", "merchant": "Stan", "amount": 10.0, "cadence": "monthly",
              "next_billing_date": "2026-10-10", "payment_method": "card", "type": "subscription"}
    fields.update(overrides)
    return fields


def _create_turn(fields, say):
    return lambda model, messages, timeout=None: {"message": {"content": json.dumps({
        "op": "create", "entity": "bill", "id": None, "fields": fields, "question": "none", "say": say})}}


def _seed_chat(role, content, op=None):
    bills_db_module.create_chat_message({"role": role, "content": content, "op_json": json.dumps(op) if op else None})


def _close_window():
    """End the shared module database's current proposal window, so earlier tests' messages cannot ground anything."""
    _seed_chat("assistant", "I've suggested a change.", op={"op": "create", "entity": "bill", "id": None, "fields": {}})


def _new_pending(before):
    return [r for r in bills_db_module.list_suggestions(status="pending") if r["id"] not in before]


def test_add_stan_with_no_details_is_refused_not_invented(live_client, monkeypatch):
    """Observed through the app: "Add Stan" alone produced $10 a month from 10 Oct,
    the date and card copied from the previous turn and the amount made up."""
    _close_window()
    monkeypatch.setattr("sophia.backend.ai.guard.chat", _create_turn(_stan(), STAN_SAY))
    pending_before, bills_before = _pending_ids(), len(bills_db_module.list_bills())

    response = live_client.post("/api/chat", json={"message": "Add Stan"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["preview"] is None and data["op"] is None
    assert data["reply"] == STAN_NEEDS
    assert bills_db_module.list_chat_messages()[-1]["op_json"] is None
    assert _pending_ids() == pending_before
    assert len(bills_db_module.list_bills()) == bills_before


def test_add_stan_with_no_details_shows_no_card_in_the_chat_panel(live_client, monkeypatch):
    _close_window()
    monkeypatch.setattr("sophia.backend.ai.guard.chat", _create_turn(_stan(), STAN_SAY))
    pending_before = _pending_ids()
    response = live_client.post("/ui/chat", data={"message": "Add Stan"})
    assert response.status_code == 200
    body = _text(response)
    assert "I just need" in body
    assert "Proposed:" not in body and "Confirm" not in body and "chat/apply" not in body
    assert _pending_ids() == pending_before


def test_a_stated_day_cannot_stand_in_for_an_amount(live_client, monkeypatch):
    """"first charge 10 October" states a day, not ten dollars: the $10 is still invented."""
    _close_window()
    monkeypatch.setattr("sophia.backend.ai.guard.chat", _create_turn(_stan(), STAN_SAY))
    pending_before = _pending_ids()
    data = live_client.post("/api/chat", json={"message": "Add Stan, monthly, first charge 10 October"}).get_json()
    assert data["preview"] is None
    assert "the amount (in dollars)" in data["reply"]
    assert _pending_ids() == pending_before


def test_create_whose_values_are_all_stated_still_becomes_a_suggestion(live_client, monkeypatch):
    _close_window()
    foxtel = _stan(name="Foxtel", merchant="Foxtel", amount=30.0)
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _create_turn(foxtel, "I've suggested adding Foxtel at $30 a month from 10 Oct — approve it to save."),
    )
    pending_before = _pending_ids()

    body = _text(live_client.post("/ui/chat", data={"message": FOXTEL_MESSAGE}))

    assert "Proposed: <strong>Add bill: Foxtel</strong>" in body
    created = _new_pending(pending_before)
    assert [(r["op"], r["entity"]) for r in created] == [("create", "bill")]
    assert json.loads(created[0]["payload_json"])["amount_cents"] == 3000


def test_details_given_over_two_turns_still_count(live_client, monkeypatch):
    _close_window()
    _seed_chat("user", "Add Stan")
    _seed_chat("assistant", "Happy to add Stan — how much is it, how often does it bill, and when is the next charge?")
    monkeypatch.setattr("sophia.backend.ai.guard.chat", _create_turn(_stan(), STAN_SAY))
    pending_before = _pending_ids()

    body = _text(live_client.post("/ui/chat", data={"message": "$10 a month from 10 Oct"}))

    assert "Proposed: <strong>Add bill: Stan</strong>" in body
    assert len(_new_pending(pending_before)) == 1


def test_values_stated_before_the_last_proposal_do_not_carry_over(live_client, monkeypatch):
    foxtel_op = {"op": "create", "entity": "bill", "id": None, "fields": _stan(name="Foxtel", amount=30.0)}
    _seed_chat("user", FOXTEL_MESSAGE)
    _seed_chat("assistant", "I've suggested adding Foxtel at $30 a month from 10 Oct — approve it to save.", op=foxtel_op)
    _seed_chat("assistant", "[suggestion #1 approved and applied: added bill 'Foxtel']")
    monkeypatch.setattr("sophia.backend.ai.guard.chat", _create_turn(_stan(amount=30.0), STAN_SAY))
    pending_before = _pending_ids()

    data = live_client.post("/api/chat", json={"message": "Add Stan"}).get_json()

    assert data["preview"] is None
    assert data["reply"] == STAN_NEEDS
    assert _pending_ids() == pending_before


def test_cancel_date_in_a_month_the_user_did_not_name_is_refused(live_client, monkeypatch):
    """Release 0 recorded "cancelled Spotify from September" becoming an October end_date."""
    _close_window()
    spotify = next(b for b in bills_db_module.list_bills() if b["name"] == "Spotify")
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _update_turn(spotify["id"], "I've suggested ending Spotify after 16 Oct", {"end_date": "2026-10-16"}),
    )
    pending_before = _pending_ids()

    body = _text(live_client.post("/ui/chat", data={"message": SPOTIFY_MESSAGE}))

    assert "I'd need you to state the end date before I change Spotify. I won't guess details you haven't given me." in body
    assert "Proposed:" not in body
    assert _pending_ids() == pending_before

    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _update_turn(spotify["id"], "I've suggested ending Spotify after 16 Sep", {"end_date": "2026-09-16"}),
    )
    body = _text(live_client.post("/ui/chat", data={"message": SPOTIFY_MESSAGE}))

    assert "Proposed: <strong>Update Spotify</strong>" in body
    created = _new_pending(pending_before)
    assert [(r["op"], r["entity_id"]) for r in created] == [("update", spotify["id"])]


def test_update_amount_the_user_never_stated_is_refused(live_client, monkeypatch):
    _close_window()
    netflix = next(b for b in bills_db_module.list_bills() if b["name"] == "Netflix")
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        _update_turn(netflix["id"], "I've suggested changing Netflix to $25", {"amount": 25.0}),
    )
    data = live_client.post("/api/chat", json={"message": "Netflix went up"}).get_json()
    assert data["preview"] is None
    assert data["reply"] == (
        "I'd need you to state the amount (in dollars) before I change Netflix. "
        "I won't guess details you haven't given me."
    )


def test_adapt_turn_is_grounded_in_the_history_rows_only(live_client, monkeypatch):
    _close_window()
    foxtel_op = {"op": "create", "entity": "bill", "id": None, "fields": _stan(name="Foxtel", amount=30.0)}
    _seed_chat("user", FOXTEL_MESSAGE)
    _seed_chat("assistant", "I've suggested adding Foxtel at $30 a month from 10 Oct — approve it to save.", op=foxtel_op)
    _seed_chat("user", "Actually make it $25 a month, first charge 10 October")
    _seed_chat("assistant", "[suggestion #1 rejected by the user — NOT applied: added bill 'Foxtel']")
    pending_before = _pending_ids()

    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat", _create_turn(_stan(name="Foxtel", amount=25.0), "Adding Foxtel at $25.")
    )
    adapted = chat_service.adapt_after_rejection()
    assert adapted["preview"] is not None
    assert len(_new_pending(pending_before)) == 1

    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat", _create_turn(_stan(name="Foxtel", amount=30.0), "Adding Foxtel at $30.")
    )
    adapted = chat_service.adapt_after_rejection()
    assert adapted["preview"] is None
    assert "I just need the amount (in dollars)" in adapted["reply"]


def test_stated_text_is_the_users_words_since_the_last_proposal():
    history = [
        {"role": "user", "content": "Add Foxtel, $30 a month", "op_json": None},
        {"role": "assistant", "content": "I've suggested adding Foxtel.", "op_json": '{"op": "create"}'},
        {"role": "user", "content": "Add Stan", "op_json": None},
        {"role": "assistant", "content": "How much is it, and how often?", "op_json": None},
        {"role": "assistant", "content": "[suggestion #2 rejected by the user]", "op_json": None},
    ]
    assert _stated_text("$10 a month", history) == "$10 a month Add Stan"
    assert _stated_text("", history) == " Add Stan"


@pytest.mark.parametrize("stated, cents, grounded", [
    ("the rent is now 1,200", 120000, True),
    ("it costs $13.99 now", 1399, True),
    ("it costs $14 now", 1399, False),
    ("$30.50 a month", 3000, False),
    ("$30 a month", 3000, True),
    ("30.00 each month", 3000, True),
    ("Add Stan", 1000, False),
    ("move it to 30 October", 3000, False),
    ("from 2026-10-30", 3000, False),
    ("first charge 10 October", 1000, False),
])
def test_amount_must_appear_as_a_whole_number_token(stated, cents, grounded):
    result = _ungrounded_fields("bill", "update", {"amount_cents": cents}, stated)
    assert result == ([] if grounded else ["amount_cents"])


@pytest.mark.parametrize("stated, cadence, grounded", [
    ("$17.50 every two weeks", "fortnightly", True),
    ("$17.50 every 2 weeks", "fortnightly", True),
    ("$17.50 a fortnight", "fortnightly", True),
    ("$17.50 every two weeks", "weekly", False),
    ("$25 a week", "weekly", True),
    ("$25/wk", "weekly", True),
    ("$15/mo", "monthly", True),
    ("$15 per month", "monthly", True),
    ("Monthly please", "monthly", True),
    ("$15 for the month", "monthly", False),
    ("Add Stan", "monthly", False),
])
def test_cadence_needs_a_stated_phrase(stated, cadence, grounded):
    result = _ungrounded_fields("bill", "create", {"cadence": cadence}, stated)
    assert result == ([] if grounded else ["cadence"])


@pytest.mark.parametrize("stated, grounded", [
    ("first charge 10 Oct", True),
    ("first charge October 10", True),
    ("first charge 10th of October", True),
    ("first charge 10/10", True),
    ("first charge 10/10/2026", True),
    ("first charge 2026-10-10", True),
    ("first charge from October", False),
    ("$10 a month from October", False),
    ("first charge on the 10th", False),
    ("first charge 10 September", False),
    ("first charge 11 October", False),
    ("$10.50 a month from October", False),
])
def test_create_date_needs_both_day_and_month(stated, grounded):
    result = _ungrounded_fields("bill", "create", {"next_billing_date": "2026-10-10"}, stated)
    assert result == ([] if grounded else ["next_billing_date"])


def test_slashed_day_and_month_ground_a_create_date():
    assert _ungrounded_fields("bill", "create", {"next_billing_date": "2026-09-05"}, "starts 5/9") == []
    assert _ungrounded_fields("bill", "create", {"next_billing_date": "2026-05-09"}, "starts 5/9") == ["next_billing_date"]


def test_update_date_needs_only_the_month():
    fields = {"end_date": "2026-10-16"}
    assert _ungrounded_fields("bill", "update", fields, "cancel it from October") == []
    assert _ungrounded_fields("bill", "update", fields, "cancel it from September") == ["end_date"]
    assert _ungrounded_fields("bill", "update", {"next_billing_date": "2026-10-16"}, "moved to Oct") == []
    assert _ungrounded_fields("bill", "create", {"next_billing_date": "2026-10-10"}, "from October") == ["next_billing_date"]


def test_only_creates_and_updates_are_checked():
    assert _ungrounded_fields("bill", "delete", {"amount_cents": 500}, "") == []
    assert _ungrounded_fields("dispute", "create", {"bill_id": 6, "reason": "Charged after I cancelled"}, "") == []


def test_stated_none_skips_the_check():
    preview = {"op": "create", "entity": "bill", "id": None, "fields": _stan()}
    vetted, reply = _vet_proposal(preview)
    assert vetted is not None and reply is None
    vetted, reply = _vet_proposal(preview, stated="Add Stan")
    assert vetted is None and reply == STAN_NEEDS
