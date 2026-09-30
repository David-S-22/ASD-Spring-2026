import json
from typing import Any
import httpx
import pytest
from backend.savings_service.classifier_service import classify_feedback
from backend.savings_service import ollama_service
from shared.backend import dto


@pytest.fixture
def categories():
    return [
        dto.Category(id=80, name="Dining", type="want"),
        dto.Category(id=81, name="Groceries", type="need"),
        dto.Category(id=70, name="Transport", type="need"),
    ]


class MockAIState:
    """Tracks outgoing requests and provides controlled responses without monkeypatching."""
    def __init__(self):
        self.last_request_body: dict[str, Any] | None = None
        self.response_json: Any = {}
        self.status_code: int = 200
        self.raw_content: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.last_request_body = json.loads(request.content.decode("utf-8"))
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"error": "Mocked server error"})

        if self.raw_content is not None:
            content_str = self.raw_content
        elif isinstance(self.response_json, (dict, list)):
            content_str = json.dumps(self.response_json)
        else:
            content_str = str(self.response_json)

        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 123456789,
                "model": "qwen2.5:3b",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content_str,
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )


@pytest.fixture
def ai_state():
    state = MockAIState()
    orig_client = ollama_service.client
    ollama_service.client = ollama_service.OpenAI(
        base_url="http://mock-ollama/v1",
        api_key="ollama",
        http_client=httpx.Client(transport=httpx.MockTransport(state.handler)),
    )
    yield state
    ollama_service.client = orig_client


def test_classify_empty_or_whitespace_feedback(categories, ai_state: MockAIState):
    assert classify_feedback("", categories) == (None, None)
    assert classify_feedback("   \n\t  ", categories) == (None, None)
    assert classify_feedback(None, categories) == (None, None)
    # Ensure no request was dispatched to AI
    assert ai_state.last_request_body is None


def test_classify_empty_categories_list(ai_state: MockAIState):
    assert classify_feedback("Focus on dining", []) == (None, None)
    assert classify_feedback("Focus on dining", None) == (None, None)
    assert ai_state.last_request_body is None


def test_classify_focus_intent_matched_category_and_timeframe(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "focus",
        "category": "Dining",
        "timeframe": "2 weeks",
    }
    input_text = "Cut dining out for the next 2 weeks"
    cat_id, timeframe = classify_feedback(input_text, categories)

    assert cat_id == 80
    assert timeframe == "2 weeks"

    # Verify that the actual input text and schema were properly transmitted
    req = ai_state.last_request_body
    assert req is not None
    messages = req.get("messages", [])
    assert any(m["role"] == "user" and m["content"] == input_text for m in messages)
    assert req.get("temperature") == 0.0

    schema = req["response_format"]["json_schema"]["schema"]
    assert "Dining" in schema["properties"]["category"]["enum"]
    assert "Groceries" in schema["properties"]["category"]["enum"]
    assert "Transport" in schema["properties"]["category"]["enum"]
    assert "null" in schema["properties"]["category"]["enum"]


def test_classify_focus_intent_case_insensitive_matching(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "focus",
        "category": "groceries",
        "timeframe": "null",
    }
    cat_id, timeframe = classify_feedback("Reduce spending on groCERies", categories)
    assert cat_id == 81
    assert timeframe is None


def test_classify_focus_numeric_timeframe_appends_weeks(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "focus",
        "category": "Transport",
        "timeframe": "3",
    }
    cat_id, timeframe = classify_feedback("Limit travel spending for 3", categories)
    assert cat_id == 70
    assert timeframe == "3 weeks"


def test_classify_focus_timeframe_only_without_category(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "focus",
        "category": "null",
        "timeframe": "1 month",
    }
    cat_id, timeframe = classify_feedback("Save extra money for 1 month", categories)
    assert cat_id is None
    assert timeframe == "1 month"


def test_classify_focus_unrecognized_category_with_timeframe(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "focus",
        "category": "Entertainment",
        "timeframe": "4 weeks",
    }
    cat_id, timeframe = classify_feedback("Limit entertainment spending for 4 weeks", categories)
    assert cat_id is None
    assert timeframe == "4 weeks"


def test_classify_focus_both_category_and_timeframe_null(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "focus",
        "category": "null",
        "timeframe": "null",
    }
    cat_id, timeframe = classify_feedback("Focus on saving more", categories)
    assert cat_id is None
    assert timeframe is None


def test_classify_constraint_intent_returns_none_tuple(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "constraint",
        "category": "Dining",
        "timeframe": "null",
    }
    cat_id, timeframe = classify_feedback("Never suggest cutting coffee", categories)
    assert cat_id is None
    assert timeframe is None


def test_classify_general_intent_returns_none_tuple(categories, ai_state: MockAIState):
    ai_state.response_json = {
        "intent": "general",
        "category": "null",
        "timeframe": "null",
    }
    cat_id, timeframe = classify_feedback("I want to save more money each month", categories)
    assert cat_id is None
    assert timeframe is None


@pytest.mark.parametrize("tf_value", ["null", "none", "None", ""])
def test_classify_normalizes_null_timeframe_strings_to_none(categories, ai_state: MockAIState, tf_value):
    ai_state.response_json = {
        "intent": "focus",
        "category": "Dining",
        "timeframe": tf_value,
    }
    cat_id, timeframe = classify_feedback("Focus on food", categories)
    assert cat_id == 80
    assert timeframe is None


def test_classify_handles_model_http_error_gracefully(categories, ai_state: MockAIState):
    ai_state.status_code = 500
    cat_id, timeframe = classify_feedback("Focus on food", categories)
    assert cat_id is None
    assert timeframe is None


def test_classify_handles_malformed_json_response(categories, ai_state: MockAIState):
    ai_state.raw_content = "This is not valid JSON at all"
    cat_id, timeframe = classify_feedback("Focus on food", categories)
    assert cat_id is None
    assert timeframe is None


def test_classify_handles_unexpected_json_type(categories, ai_state: MockAIState):
    # Model returns a list instead of a dict
    ai_state.response_json = ["focus", "Dining", "2 weeks"]
    cat_id, timeframe = classify_feedback("Focus on dining", categories)
    assert cat_id is None
    assert timeframe is None
