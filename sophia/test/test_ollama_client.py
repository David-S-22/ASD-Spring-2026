"""Tests for sophia.backend.ai.ollama_client: the request body it posts to Ollama.

No real HTTP: requests.post is monkeypatched, so these run entirely offline.
"""
from sophia.backend import config
from sophia.backend.ai import ollama_client


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": "{}"}}


def _capture_post(monkeypatch):
    posted = {}

    def fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        posted["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("sophia.backend.ai.ollama_client.requests.post", fake_post)
    return posted


def test_chat_asks_ollama_to_keep_the_model_loaded(monkeypatch):
    posted = _capture_post(monkeypatch)
    ollama_client.chat("qwen2.5:3b", [{"role": "user", "content": "hi"}])
    assert posted["url"] == f"{config.OLLAMA_URL}/api/chat"
    assert posted["json"]["keep_alive"] == config.OLLAMA_KEEP_ALIVE
    assert "temperature" in posted["json"]["options"]


def test_chat_uses_the_configured_temperature_when_none_is_given(monkeypatch):
    posted = _capture_post(monkeypatch)
    monkeypatch.setattr(config, "AI_TEMPERATURE", 0.7)
    ollama_client.chat("qwen2.5:3b", [{"role": "user", "content": "hi"}])
    assert posted["json"]["options"]["temperature"] == 0.7


def test_chat_uses_the_temperature_it_is_given_even_when_zero(monkeypatch):
    posted = _capture_post(monkeypatch)
    ollama_client.chat("qwen2.5:3b", [{"role": "user", "content": "hi"}], temperature=0)
    assert posted["json"]["options"]["temperature"] == 0
