from unittest.mock import Mock

import requests
from pytest import MonkeyPatch, fixture, mark, raises

from janelle.backend import config
from janelle.backend.services import rag_answer
from janelle.backend.services.rag_client import RAGError


CATEGORIES = [
    {"id": 1, "name": "Uncategorised", "type": None},
    {"id": 31, "name": "Fitness", "type": "want"},
    {"id": 40, "name": "Music subscriptions", "type": "want"},
]
QUESTION = "Merchant: Anytime Fitness; Description: membership"
GUIDE_TEXT = "Fitness: club direct debits."


def record(identifier, distance, category_id=31):
    return {
        "id": identifier,
        "text": f"Transaction {identifier} text",
        "metadata": {
            "kind": "transaction",
            "transaction_id": int(identifier.split("-")[1]),
            "category_id": category_id,
        },
        "distance": distance,
    }


def guide(identifier, distance):
    return {
        "id": identifier,
        "text": GUIDE_TEXT,
        "metadata": {"source": "categories.md"},
        "distance": distance,
    }


def token_logprobs(*pairs):
    return [{"token": token, "logprob": logprob} for token, logprob in pairs]


@fixture(autouse=True)
def rag_settings(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(config, "RAG_RECORDS_COLLECTION", "transactions-records")
    monkeypatch.setattr(config, "RAG_GUIDE_COLLECTION", "transactions")
    monkeypatch.setattr(config, "RAG_TOP_K", 6)
    monkeypatch.setattr(config, "RAG_GUIDE_TOP_K", 3)
    monkeypatch.setattr(config, "RAG_HIGH", 0.6)
    monkeypatch.setattr(config, "RAG_MEDIUM", 0.9)
    monkeypatch.setattr(config, "RAG_LOW", 1.2)
    monkeypatch.setattr(config, "RAG_PROB_HIGH", 0.8)
    monkeypatch.setattr(config, "RAG_PROB_MEDIUM", 0.5)
    monkeypatch.setattr(config, "RAG_MODEL", "qwen2.5:3b")
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama.test")
    monkeypatch.setattr(config, "AI_TIMEOUT_SECONDS", 9)


@fixture
def fake_retrieve(monkeypatch: MonkeyPatch):
    """Install a fake ``rag_client.retrieve``; returns the recorded calls."""
    def install(records, guide_chunks=()):
        calls = []

        def retrieve(feature, question, k=3, where=None):
            calls.append((feature, question, k))
            hits = records if feature == "transactions-records" else guide_chunks
            if isinstance(hits, Exception):
                raise hits
            return list(hits)

        monkeypatch.setattr(rag_answer.rag_client, "retrieve", retrieve)
        return calls

    return install


@fixture
def fake_model(monkeypatch: MonkeyPatch):
    """Install a fake Ollama ``requests.post``; returns the mock."""
    def install(content=None, error=None, logprobs=None):
        post = Mock(side_effect=error)
        if error is None:
            body = {"message": {"content": content}}
            if logprobs is not None:
                body["logprobs"] = logprobs
            post.return_value = Mock(**{"json.return_value": body})
        monkeypatch.setattr(rag_answer.requests, "post", post)
        return post

    return install


def prompt_of(post):
    return post.call_args.kwargs["json"]["messages"][1]["content"]


def test_merges_both_collections_by_distance_and_numbers_context(
    fake_retrieve,
    fake_model,
):
    calls = fake_retrieve(
        [record("tx-7", 0.31), record("tx-14", 0.7)],
        [guide("categories.md_2", 0.52)],
    )
    post = fake_model("Fitness [1][2][3]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert calls == [
        ("transactions-records", QUESTION, 6),
        ("transactions", QUESTION, 3),
    ]
    prompt = prompt_of(post)
    assert prompt.index("[1] Transaction tx-7") < prompt.index(
        f"[2] {GUIDE_TEXT}"
    ) < prompt.index("[3] Transaction tx-14")
    assert result["status"] == "grounded"
    assert result["retrieved"] == 3
    assert [(c["marker"], c["id"]) for c in result["citations"]] == [
        (1, "tx-7"),
        (2, "categories.md_2"),
        (3, "tx-14"),
    ]
    assert result["citations"][0]["source"] == "transaction 7"
    assert result["citations"][0]["category_id"] == 31
    assert result["citations"][1]["collection"] == "transactions"
    assert result["citations"][1]["source"] == "categories.md"
    assert "category_id" not in result["citations"][1]


def test_documents_above_threshold_are_dropped(fake_retrieve, fake_model):
    fake_retrieve([record("tx-7", 0.5), record("tx-14", 1.21)], [guide("g1", 1.9)])
    post = fake_model("Fitness [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert "[2]" not in prompt_of(post)
    assert result["survivors"] == 1
    assert result["retrieved"] == 3


def test_no_survivors_means_insufficient_and_no_model_call(
    fake_retrieve,
    fake_model,
):
    fake_retrieve([record("tx-7", 1.3)], [guide("g1", 1.5)])
    post = fake_model("Fitness [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    post.assert_not_called()
    assert result["status"] == "insufficient"
    assert result["confidence"] == "insufficient"
    assert result["insufficient_context"] is True
    assert result["citations"] == []
    assert result["retrieved"] == 2
    assert result["model_probability"] is None
    assert result["thresholds"] == {
        "insufficient_above": 1.2,
        "high_below": 0.6,
        "medium_below": 0.9,
        "probability_high_at_least": 0.8,
        "probability_medium_at_least": 0.5,
    }


def test_prompt_lists_live_categories_only_and_uses_rag_model(
    fake_retrieve,
    fake_model,
):
    fake_retrieve([record("tx-7", 0.3)])
    post = fake_model("Fitness [1]")

    rag_answer.grounded_answer(QUESTION, CATEGORIES)

    payload = post.call_args.kwargs["json"]
    assert post.call_args.args == ("http://ollama.test/api/chat",)
    assert post.call_args.kwargs["timeout"] == 9
    assert payload["model"] == "qwen2.5:3b"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0}
    assert payload["logprobs"] is True
    assert "NONE" in payload["messages"][0]["content"]
    user = payload["messages"][1]["content"]
    assert "- Uncategorised\n- Fitness\n- Music subscriptions" in user
    assert "Groceries" not in user
    assert user.endswith(QUESTION)


def test_markers_disagreeing_with_the_category_are_dropped(
    fake_retrieve,
    fake_model,
):
    fake_retrieve(
        [record("tx-7", 0.3), record("tx-9", 0.4, category_id=40)],
        [guide("g1", 0.5)],
    )
    fake_model("Fitness [1][2][3][9]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert [c["id"] for c in result["citations"]] == ["tx-7", "g1"]
    assert result["uncited"] is False
    assert result["derived_from_votes"] is False


@mark.parametrize("distances, expected", [
    ([0.3, 0.5], "high"),
    ([0.3], "medium"),  # a single survivor cannot be high
    ([1.0, 1.1], "low"),
])
def test_confidence_bands(fake_retrieve, fake_model, distances, expected):
    fake_retrieve([record(f"tx-{i}", d) for i, d in enumerate(distances, 1)])
    fake_model("Fitness [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["confidence"] == expected
    assert result["best_distance"] == min(distances)


def test_uncited_answer_is_downgraded_and_cites_agreeing_records(
    fake_retrieve,
    fake_model,
):
    fake_retrieve([record("tx-7", 0.3), record("tx-14", 0.4)])
    fake_model("Fitness")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["status"] == "grounded"
    assert result["uncited"] is True
    assert result["confidence"] == "medium"
    assert [c["id"] for c in result["citations"]] == ["tx-7", "tx-14"]
    assert result["derived_from_votes"] is False


@mark.parametrize("content, confidence", [
    ("Gym [1]", "medium"),  # off-list: vote downgrade only, no gate
    ("Fitness", "low"),     # on-list but unsupported: gated, then vote downgrade
])
def test_unusable_answer_falls_back_to_vote_with_downgrade(
    fake_retrieve,
    fake_model,
    content,
    confidence,
):
    fake_retrieve(
        [record("tx-8", 0.3, category_id=40), record("tx-9", 0.5, category_id=40)],
        [guide("g1", 0.4)],
    )
    fake_model(content, logprobs=token_logprobs((content.split()[0], -1.2)))

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["answer"] == "Music subscriptions"
    assert result["derived_from_votes"] is True
    assert result["uncited"] is False
    assert result["confidence"] == confidence
    assert result["model_probability"] == 0.3012
    assert [(c["marker"], c["id"]) for c in result["citations"]] == [
        (1, "tx-8"),
        (2, "tx-9"),
    ]


def test_vote_tie_is_broken_by_lower_best_distance(fake_retrieve, fake_model):
    fake_retrieve([record("tx-7", 0.45), record("tx-8", 0.3, category_id=40)])
    fake_model("NONE")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["answer"] == "Music subscriptions"
    assert result["derived_from_votes"] is True


def test_grounded_result_always_has_a_citation(fake_retrieve, fake_model):
    fake_retrieve([record("tx-7", 0.3)])
    fake_model("Fitness [7]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["status"] == "grounded"
    assert len(result["citations"]) >= 1


def test_guide_retrieve_failure_gives_no_partial_grounding(
    fake_retrieve,
    fake_model,
):
    fake_retrieve([record("tx-7", 0.3)], RAGError("rag_timeout"))
    post = fake_model("Fitness [1]")

    with raises(RAGError):
        rag_answer.grounded_answer(QUESTION, CATEGORIES)
    post.assert_not_called()


def test_ollama_failure_raises_rag_error(fake_retrieve, fake_model):
    fake_retrieve([record("tx-7", 0.3)])
    fake_model(error=requests.ConnectionError("boom"))

    with raises(RAGError) as info:
        rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert info.value.code == "rag_generation_failed"


@mark.parametrize("content, logprobs, confidence, probability", [
    # exp(-0.03): only the category-name tokens count, not the markers.
    (
        "Fitness [1]",
        token_logprobs(("Fit", -0.02), ("ness", -0.01), (" [", -0.9), ("1", -2.0)),
        "high",
        0.9704,
    ),
    ("Fitness [1]", token_logprobs(("Fitness", -0.5), (" [1]", -0.1)), "medium", 0.6065),
    ("Fitness [1]", token_logprobs(("Fitness", -1.2), (" [1]", -0.1)), "low", 0.3012),
    # high -> medium (gate) -> low (uncited) stack.
    ("Fitness", token_logprobs(("Fitness", -0.5)), "low", 0.6065),
    # Missing or malformed log probabilities skip the gate.
    ("Fitness [1]", None, "high", None),
    ("Fitness [1]", [], "high", None),
    ("Fitness [1]", [{"token": "Fitness", "logprob": "-0.1"}], "high", None),
])
def test_log_probability_gate(
    fake_retrieve,
    fake_model,
    content,
    logprobs,
    confidence,
    probability,
):
    fake_retrieve([record("tx-7", 0.3), record("tx-14", 0.4)])
    fake_model(content, logprobs=logprobs)

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["confidence"] == confidence
    assert result["model_probability"] == probability


def test_answer_probability_uses_only_name_tokens():
    logprobs = token_logprobs(
        (" ", -0.3),  # whitespace-only tokens cover text but are not counted
        ("Music", -0.1),
        (" subscriptions", -0.2),
        (" [", -0.5),
        ("2", -0.7),
    )

    probability = rag_answer.answer_probability(" Music subscriptions [2]", logprobs)

    assert probability == round(rag_answer.math.exp(-0.3), 4)
    assert rag_answer.answer_probability("NONE", None) is None
    assert rag_answer.answer_probability("[1]", logprobs) is None
