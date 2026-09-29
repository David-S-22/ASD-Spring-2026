"""Tests for the grounded prompt builder and its response validator."""
from sophia.backend.ai import grounded_prompt
from sophia.backend.ai.schemas import validate_grounded_answer

CHUNKS = [
    {"source": "bill-7-home-internet.md", "text": "# Home internet (bill)\n\n- Merchant: FibreLink\n- Status: overdue", "distance": 1.083},
    {"source": "bill-3-spotify.md", "text": "# Spotify (subscription)\n\n- Amount: $13.99", "distance": 1.4},
]


def test_build_puts_every_source_in_the_system_message_and_the_question_last():
    messages = grounded_prompt.build("Which bill is overdue?", CHUNKS)
    assert messages[0]["role"] == "system"
    assert "- [Source: bill-7-home-internet.md]: # Home internet (bill) - Merchant: FibreLink - Status: overdue" in messages[0]["content"]
    assert "- [Source: bill-3-spotify.md]:" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "Which bill is overdue?"}


def test_build_appends_the_retry_note_when_error_is_given():
    messages = grounded_prompt.build("q", CHUNKS, error="cited must be a list")
    assert messages[-1]["content"] == "Your last response was invalid: cited must be a list. Reply again, JSON only."


def test_validator_accepts_the_shape_and_rejects_each_bad_field():
    assert validate_grounded_answer({"answer": "Home internet is overdue.", "cited": ["bill-7-home-internet.md"], "insufficient": False}) is None
    assert validate_grounded_answer({"answer": "", "cited": [], "insufficient": True}) is None
    assert validate_grounded_answer([]) == "response must be a JSON object"
    assert validate_grounded_answer({"answer": "x" * 301, "cited": [], "insufficient": False}).startswith("answer must be")
    assert validate_grounded_answer({"answer": "ok", "cited": "bill-7", "insufficient": False}).startswith("cited must be")
    assert validate_grounded_answer({"answer": "ok", "cited": [], "insufficient": "no"}).startswith("insufficient must be")
    assert validate_grounded_answer({"answer": "  ", "cited": [], "insufficient": False}).startswith("answer must not be empty")


def test_fallback_is_an_insufficient_answer():
    assert grounded_prompt.FALLBACK == {"answer": "", "cited": [], "insufficient": True}
    assert validate_grounded_answer(grounded_prompt.FALLBACK) is None
