"""A dispute proposal starts loading the draft model in the background, so Approve does not wait for the model swap; nothing else warms it and a failed warm-up never reaches the user."""
import json

from sophia.backend import config
from sophia.backend.ai.ollama_client import warm as real_warm
from sophia.backend.services import chat as chat_service

DISPUTE = {"op": "create", "entity": "dispute", "id": None, "fields": {"bill_id": 9, "reason": "Charged twice"}, "question": "none", "say": "I've suggested opening a dispute."}
UPDATE = {"op": "update", "entity": "bill", "id": 3, "fields": {"amount": 15.99}, "question": "none", "say": "I've suggested changing Spotify to $15.99 a month."}
QUESTION = {"op": None, "entity": None, "id": None, "fields": None, "question": "total", "say": "Here."}


def fake_model(monkeypatch, payload):
    monkeypatch.setattr("sophia.backend.ai.guard.chat", lambda model, messages, timeout=None, temperature=None: {"message": {"content": json.dumps(payload)}})


def warmed(monkeypatch):
    models = []
    monkeypatch.setattr(chat_service, "_warm_in_background", models.append)
    return models


def test_warm_posts_an_empty_generate_with_the_keep_alive_and_swallows_failures(monkeypatch):
    posts = []

    def post(url, json=None, timeout=None):
        posts.append((url, json, timeout))
        raise RuntimeError("ollama down")

    monkeypatch.setattr("sophia.backend.ai.ollama_client.requests.post", post)
    assert real_warm("llama3.1:8b") is None
    assert posts == [(f"{config.OLLAMA_URL}/api/generate", {"model": "llama3.1:8b", "prompt": "", "keep_alive": config.OLLAMA_KEEP_ALIVE}, config.AI_TIMEOUT_SECONDS)]


def test_a_dispute_proposal_warms_the_draft_model(live_client, monkeypatch):
    models = warmed(monkeypatch)
    fake_model(monkeypatch, DISPUTE)
    live_client.post("/ui/chat", data={"message": "I want to dispute the Electricity charge, I was charged twice in July"})
    assert models == [config.DRAFT_MODEL]


def test_other_proposals_and_questions_do_not_warm_it(live_client, monkeypatch):
    models = warmed(monkeypatch)
    fake_model(monkeypatch, UPDATE)
    live_client.post("/ui/chat", data={"message": "Update my Spotify to $15.99 a month"})
    fake_model(monkeypatch, QUESTION)
    live_client.post("/ui/chat", data={"message": "What do my bills add up to?"})
    assert models == []


def test_a_warm_up_that_cannot_start_never_breaks_the_reply(live_client, monkeypatch):
    def boom(model):
        raise RuntimeError("thread could not start")

    monkeypatch.setattr(chat_service, "_warm_in_background", boom)
    fake_model(monkeypatch, DISPUTE)
    response = live_client.post("/ui/chat", data={"message": "I want to dispute the Electricity charge, I was charged twice in July"})
    assert response.status_code == 200 and "Open dispute for Electricity" in response.get_data(as_text=True)
