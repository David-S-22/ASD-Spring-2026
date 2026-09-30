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


def record(identifier, distance, category_id=31, kind="transaction", text=None):
    metadata = {
        "kind": kind,
        "transaction_id": int(identifier.split("-")[1]),
        "date": "2026-06-24",
        "merchant": "Anytime Fitness Ultimo",
        "amount": 17.5,
    }
    if category_id is not None:
        metadata["category_id"] = category_id
        metadata["category"] = {
            1: "Uncategorised",
            31: "Fitness",
            40: "Music subscriptions",
        }[category_id]
    return {
        "id": identifier,
        "text": text or f"Transaction {identifier} text",
        "metadata": metadata,
        "distance": distance,
    }


def guide(identifier, distance, text="Fitness: club direct debits."):
    return {
        "id": identifier,
        "text": text,
        "metadata": {
            "source": "categories.md",
            "feature": "transactions",
            "doc_type": "markdown",
        },
        "distance": distance,
    }


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
    monkeypatch.setattr(config, "RAG_MODEL", "qwen2.5:3b")
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama.test")
    monkeypatch.setattr(config, "AI_TIMEOUT_SECONDS", 9)


def use_retrieve(monkeypatch: MonkeyPatch, records, guide_chunks):
    calls = []

    def retrieve(feature, question, k=3, where=None):
        calls.append((feature, question, k))
        if isinstance(records, Exception) and feature == "transactions-records":
            raise records
        if isinstance(guide_chunks, Exception) and feature == "transactions":
            raise guide_chunks
        return list(records if feature == "transactions-records" else guide_chunks)

    monkeypatch.setattr(rag_answer.rag_client, "retrieve", retrieve)
    return calls


def use_model(monkeypatch: MonkeyPatch, content=None, error=None, logprobs=None):
    post = Mock()
    if error is not None:
        post.side_effect = error
    else:
        response = Mock()
        response.raise_for_status.return_value = None
        body = {"message": {"content": content}}
        if logprobs is not None:
            body["logprobs"] = logprobs
        response.json.return_value = body
        post.return_value = response
    monkeypatch.setattr(rag_answer.requests, "post", post)
    return post


def token_logprobs(*pairs):
    return [{"token": token, "logprob": logprob} for token, logprob in pairs]


def test_merges_both_collections_by_distance_and_numbers_context(
    monkeypatch: MonkeyPatch,
):
    calls = use_retrieve(
        monkeypatch,
        [record("tx-7", 0.31), record("tx-14", 0.7)],
        [guide("transactions_categories.md_2", 0.52)],
    )
    post = use_model(monkeypatch, "Fitness [1][2][3]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert calls == [
        ("transactions-records", QUESTION, 6),
        ("transactions", QUESTION, 3),
    ]
    prompt = post.call_args.kwargs["json"]["messages"][1]["content"]
    assert prompt.index("[1] Transaction tx-7") < prompt.index(
        "[2] Fitness: club direct debits."
    ) < prompt.index("[3] Transaction tx-14")
    assert [c["id"] for c in result["citations"]] == [
        "tx-7",
        "transactions_categories.md_2",
        "tx-14",
    ]
    assert [c["marker"] for c in result["citations"]] == [1, 2, 3]
    assert result["citations"][1]["collection"] == "transactions"
    assert result["citations"][1]["source"] == "categories.md"
    assert "category_id" not in result["citations"][1]
    assert result["citations"][0]["source"] == "transaction 7"
    assert result["citations"][0]["category_id"] == 31
    assert result["retrieved"] == 3
    assert result["status"] == "grounded"


def test_documents_above_threshold_are_dropped(monkeypatch: MonkeyPatch):
    use_retrieve(
        monkeypatch,
        [record("tx-7", 0.5), record("tx-14", 1.21)],
        [guide("g1", 1.9)],
    )
    post = use_model(monkeypatch, "Fitness [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    prompt = post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "[2]" not in prompt
    assert result["survivors"] == 1
    assert result["retrieved"] == 3


def test_no_survivors_means_insufficient_and_no_model_call(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(monkeypatch, [record("tx-7", 1.3)], [guide("g1", 1.5)])
    post = use_model(monkeypatch, "Fitness [1]")

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
    monkeypatch: MonkeyPatch,
):
    use_retrieve(monkeypatch, [record("tx-7", 0.3)], [])
    post = use_model(monkeypatch, "Fitness [1]")

    rag_answer.grounded_answer(QUESTION, CATEGORIES)

    payload = post.call_args.kwargs["json"]
    assert post.call_args.args == ("http://ollama.test/api/chat",)
    assert post.call_args.kwargs["timeout"] == 9
    assert payload["model"] == "qwen2.5:3b"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0}
    assert payload["logprobs"] is True
    user = payload["messages"][1]["content"]
    assert "- Uncategorised\n- Fitness\n- Music subscriptions" in user
    assert "Groceries" not in user
    assert user.endswith(QUESTION)
    assert "NONE" in payload["messages"][0]["content"]


def test_markers_disagreeing_with_the_category_are_dropped(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(
        monkeypatch,
        [record("tx-7", 0.3, category_id=31), record("tx-9", 0.4, category_id=40)],
        [guide("g1", 0.5)],
    )
    use_model(monkeypatch, "Fitness [1][2][3][9]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert [c["id"] for c in result["citations"]] == ["tx-7", "g1"]
    assert result["uncited"] is False
    assert result["derived_from_votes"] is False


@mark.parametrize(
    ("distances", "expected"),
    [
        ([0.3, 0.5], "high"),
        ([0.3], "medium"),        # single survivor cannot be high
        ([0.7, 0.8], "medium"),
        ([1.0, 1.1], "low"),
    ],
)
def test_confidence_bands(monkeypatch: MonkeyPatch, distances, expected):
    use_retrieve(
        monkeypatch,
        [record(f"tx-{i}", d) for i, d in enumerate(distances, start=1)],
        [],
    )
    use_model(monkeypatch, "Fitness [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["confidence"] == expected
    assert result["best_distance"] == min(distances)


def test_uncited_answer_is_downgraded_and_cites_agreeing_records(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(
        monkeypatch,
        [record("tx-7", 0.3), record("tx-14", 0.4)],
        [],
    )
    use_model(monkeypatch, "Fitness")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["status"] == "grounded"
    assert result["uncited"] is True
    assert result["confidence"] == "medium"
    assert [c["id"] for c in result["citations"]] == ["tx-7", "tx-14"]
    assert result["derived_from_votes"] is False


def test_off_list_answer_triggers_vote_and_downgrade(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(
        monkeypatch,
        [
            record("tx-7", 0.3, category_id=31),
            record("tx-8", 0.35, category_id=40),
            record("tx-9", 0.5, category_id=40),
        ],
        [guide("g1", 0.4)],
    )
    use_model(monkeypatch, "Gym [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["answer"] == "Music subscriptions"
    assert result["derived_from_votes"] is True
    assert result["confidence"] == "medium"
    assert [c["id"] for c in result["citations"]] == ["tx-8", "tx-9"]
    assert [c["marker"] for c in result["citations"]] == [1, 2]


def test_vote_tie_is_broken_by_lower_best_distance(monkeypatch: MonkeyPatch):
    use_retrieve(
        monkeypatch,
        [
            record("tx-7", 0.45, category_id=31),
            record("tx-8", 0.3, category_id=40),
        ],
        [],
    )
    use_model(monkeypatch, "NONE")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["answer"] == "Music subscriptions"
    assert result["derived_from_votes"] is True


def test_answer_without_support_in_context_falls_back_to_vote(
    monkeypatch: MonkeyPatch,
):
    # Model names Fitness but every surviving record is Music subscriptions.
    use_retrieve(
        monkeypatch,
        [record("tx-8", 0.3, category_id=40)],
        [],
    )
    use_model(monkeypatch, "Fitness")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["answer"] == "Music subscriptions"
    assert result["derived_from_votes"] is True
    assert result["citations"][0]["id"] == "tx-8"


def test_grounded_result_always_has_a_citation(monkeypatch: MonkeyPatch):
    use_retrieve(monkeypatch, [record("tx-7", 0.3)], [])
    use_model(monkeypatch, "Fitness [7]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["status"] == "grounded"
    assert len(result["citations"]) >= 1


def test_guide_retrieve_failure_gives_no_partial_grounding(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(monkeypatch, [record("tx-7", 0.3)], RAGError("rag_timeout"))
    post = use_model(monkeypatch, "Fitness [1]")

    with raises(RAGError):
        rag_answer.grounded_answer(QUESTION, CATEGORIES)
    post.assert_not_called()


@mark.parametrize("error", [
    requests.ConnectionError("boom"),
    requests.Timeout("slow"),
])
def test_ollama_failure_raises_rag_error(monkeypatch: MonkeyPatch, error):
    use_retrieve(monkeypatch, [record("tx-7", 0.3)], [])
    use_model(monkeypatch, error=error)

    with raises(RAGError) as info:
        rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert info.value.code == "rag_generation_failed"


def test_confident_logprobs_keep_the_distance_band(monkeypatch: MonkeyPatch):
    use_retrieve(monkeypatch, [record("tx-7", 0.3), record("tx-14", 0.4)], [])
    use_model(
        monkeypatch,
        "Fitness [1][2]",
        logprobs=token_logprobs(("Fit", -0.02), ("ness", -0.01), (" [", -0.9), ("1", -2.0)),
    )

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["confidence"] == "high"
    # exp(-0.03): only the category-name tokens count, not the markers.
    assert result["model_probability"] == 0.9704
    assert result["thresholds"]["probability_high_at_least"] == 0.8
    assert result["thresholds"]["probability_medium_at_least"] == 0.5


def test_unsure_model_downgrades_high_to_medium(monkeypatch: MonkeyPatch):
    use_retrieve(monkeypatch, [record("tx-7", 0.3), record("tx-14", 0.4)], [])
    use_model(
        monkeypatch,
        "Fitness [1]",
        logprobs=token_logprobs(("Fitness", -0.5), (" [1]", -0.1)),
    )

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["model_probability"] == 0.6065
    assert result["confidence"] == "medium"


def test_very_unsure_model_downgrades_high_to_low(monkeypatch: MonkeyPatch):
    use_retrieve(monkeypatch, [record("tx-7", 0.3), record("tx-14", 0.4)], [])
    use_model(
        monkeypatch,
        "Fitness [1]",
        logprobs=token_logprobs(("Fitness", -1.2), (" [1]", -0.1)),
    )

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["model_probability"] == 0.3012
    assert result["confidence"] == "low"


def test_probability_gate_stacks_with_uncited_downgrade(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(monkeypatch, [record("tx-7", 0.3), record("tx-14", 0.4)], [])
    use_model(
        monkeypatch,
        "Fitness",
        logprobs=token_logprobs(("Fitness", -0.5)),
    )

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    # high -> medium (probability 0.61 < 0.8) -> low (uncited).
    assert result["uncited"] is True
    assert result["confidence"] == "low"


def test_missing_logprobs_skips_the_gate(monkeypatch: MonkeyPatch):
    use_retrieve(monkeypatch, [record("tx-7", 0.3), record("tx-14", 0.4)], [])
    use_model(monkeypatch, "Fitness [1]")

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["confidence"] == "high"
    assert result["model_probability"] is None


@mark.parametrize("logprobs", [
    [],
    "not a list",
    [{"token": "Fitness"}],
    [{"token": 7, "logprob": -0.1}],
    [{"token": "Fitness", "logprob": "-0.1"}],
    [{"token": "Fitness", "logprob": True}],
])
def test_malformed_logprobs_are_ignored(monkeypatch: MonkeyPatch, logprobs):
    use_retrieve(monkeypatch, [record("tx-7", 0.3), record("tx-14", 0.4)], [])
    use_model(monkeypatch, "Fitness [1]", logprobs=logprobs)

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["confidence"] == "high"
    assert result["model_probability"] is None


def test_vote_path_reports_probability_but_does_not_gate_on_it(
    monkeypatch: MonkeyPatch,
):
    use_retrieve(
        monkeypatch,
        [record("tx-8", 0.3, category_id=40), record("tx-9", 0.4, category_id=40)],
        [],
    )
    use_model(
        monkeypatch,
        "Gym [1]",
        logprobs=token_logprobs(("Gym", -0.01)),
    )

    result = rag_answer.grounded_answer(QUESTION, CATEGORIES)

    assert result["derived_from_votes"] is True
    assert result["confidence"] == "medium"  # one vote downgrade only
    assert result["model_probability"] == 0.99


def test_answer_probability_uses_only_name_tokens():
    logprobs = token_logprobs(
        (" ", -0.3),
        ("Music", -0.1),
        (" subscriptions", -0.2),
        (" [", -0.5),
        ("2", -0.7),
        ("]", -0.1),
    )

    probability = rag_answer.answer_probability(
        " Music subscriptions [2]",
        logprobs,
    )

    assert probability == round(rag_answer.math.exp(-0.3), 4)
    assert rag_answer.answer_probability("NONE", None) is None
    assert rag_answer.answer_probability("", logprobs) is None
    assert rag_answer.answer_probability("[1]", logprobs) is None
