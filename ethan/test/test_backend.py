import requests
import pytest

from backend import chat_service, db_api, proposal_service, summary_service, transactions_api
from backend.ai import chat_prompt, guard
from backend.app import create_app


def _client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index():
    resp = _client().get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "budgets-backend"


def test_health_reports_database_up(monkeypatch):
    monkeypatch.setattr(db_api, "health", lambda: {"ok": True})
    monkeypatch.setattr(transactions_api, "list_categories", lambda: [{"id": 80, "name": "Dining"}])
    monkeypatch.setattr(transactions_api, "list_transactions", lambda: [{"id": 1, "amount": 42.5}])
    monkeypatch.setattr("backend.app._ollama_status", lambda: "up")

    resp = _client().get("/health")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert resp.get_json()["db_api"] == "up"
    assert resp.get_json()["transactions_api"] == "up"
    assert resp.get_json()["transactions_count"] == 1
    assert resp.get_json()["ollama"] == "up"


def test_list_budgets(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "list_budgets",
        lambda: [{"id": 1, "month": "2026-09"}],
    )

    resp = _client().get("/api/budgets")

    assert resp.status_code == 200
    assert resp.get_json() == [{"id": 1, "month": "2026-09"}]


def test_list_transaction_categories(monkeypatch):
    monkeypatch.setattr(
        transactions_api,
        "list_categories",
        lambda: [{"id": 80, "name": "Dining", "type": "want"}],
    )

    resp = _client().get("/api/transaction-categories")

    assert resp.status_code == 200
    assert resp.get_json() == [{"id": 80, "name": "Dining", "type": "want"}]


def test_create_budget(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "create_budget",
        lambda payload: ({"id": 1, "month": payload["month"]}, 201),
    )

    resp = _client().post("/api/budgets", json={"month": "2026-09"})

    assert resp.status_code == 201
    assert resp.get_json()["id"] == 1


def test_create_budget_line_resolves_transaction_category(monkeypatch):
    monkeypatch.setattr(
        transactions_api,
        "list_categories",
        lambda: [{"id": 81, "name": "Groceries", "type": "need"}],
    )
    monkeypatch.setattr(
        db_api,
        "create_budget_line",
        lambda budget_id, payload: (
            {
                "id": 1,
                "budget_id": budget_id,
                "category_id": payload["category_id"],
                "category": payload["category"],
            },
            201,
        ),
    )

    resp = _client().post("/api/budgets/b1/budget-lines", json={"category_id": 81, "warn_at": 15000})

    assert resp.status_code == 201
    assert resp.get_json() == {
        "id": 1,
        "budget_id": "b1",
        "category_id": 81,
        "category": "Groceries",
    }


def test_patch_budget_line_requires_category_id_when_setting_category(monkeypatch):
    resp = _client().patch("/api/budget-lines/l1", json={"category": "Groceries"})

    assert resp.status_code == 422
    assert resp.get_json() == {
        "error": "category_id is required when setting a budget line category",
        "code": "invalid_field",
    }


def test_create_planned_event(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "create_planned_event",
        lambda budget_id, payload: (
            {
                "id": 7,
                "budget_id": budget_id,
                "category": payload["category"],
                "est_low": payload["est_low"],
                "est_high": payload["est_high"],
                "status": payload["status"],
            },
            201,
        ),
    )

    resp = _client().post(
        "/api/budgets/1/planned-events",
        json={"category": "Dining", "est_low": 3000, "est_high": 5000, "status": "planned"},
    )

    assert resp.status_code == 201
    assert resp.get_json() == {
        "id": 7,
        "budget_id": "1",
        "category": "Dining",
        "est_low": 3000,
        "est_high": 5000,
        "status": "planned",
    }


def test_send_chat_message(monkeypatch):
    monkeypatch.setattr(
        chat_service,
        "send_message",
        lambda budget_id, message, history=None: {
            "reply": "Dining is projected to reach warning this month.",
            "mode": "advice",
            "question": None,
            "proposal": None,
            "fallback": False,
            "user_message": {"role": "user", "content": message},
            "assistant_message": {"role": "assistant", "content": "Dining is projected to reach warning this month."},
        },
    )

    resp = _client().post(
        "/api/chat",
        json={"budget_id": 1, "message": "How is Dining looking?", "history": [{"role": "user", "content": "Earlier"}]},
    )

    assert resp.status_code == 200
    assert resp.get_json()["mode"] == "advice"
    assert resp.get_json()["assistant_message"]["content"] == "Dining is projected to reach warning this month."


def test_apply_coach_proposal_route(monkeypatch):
    monkeypatch.setattr(
        proposal_service,
        "apply",
        lambda proposal_id: {"proposal": {"id": int(proposal_id), "status": "accepted"}, "applied": [{"id": 3}]},
    )

    resp = _client().post("/api/coach-proposals/7/apply")

    assert resp.status_code == 200
    assert resp.get_json()["proposal"]["status"] == "accepted"
    assert resp.get_json()["applied"] == [{"id": 3}]


def test_chat_prompt_examples_use_current_summary_values():
    messages = chat_prompt.build(
        "what should i do then",
        [],
        {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 12000,
                "planned_est_high_total": 0,
                "remaining_income_high": 548000,
            },
            "budget_lines": [
                {
                    "id": 8,
                    "category": "Mobile",
                    "actual_spend": 12000,
                    "planned_est_high_total": 0,
                    "projected_high_total": 12000,
                    "warn_at": 7500,
                    "hard_cap": 10000,
                },
            ],
        },
    )

    content = "\n".join(str(message.get("content") or "") for message in messages)

    assert "Mobile" in content
    assert "$120.00" in content
    assert "$100.00" in content
    assert "Dining" not in content
    assert "$791.00" not in content
    assert "$800.00" not in content


def test_chat_route_returns_json_when_proposal_storage_is_unavailable(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60100,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79100,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    monkeypatch.setattr(
        db_api,
        "create_coach_proposal",
        lambda _budget_id, _payload: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    resp = _client().post(
        "/api/chat",
        json={"budget_id": 1, "message": "what adjustments should i make to my budgets", "history": []},
    )

    assert resp.status_code == 503
    assert resp.is_json is True
    assert resp.get_json() == {
        "error": "budgets database is unavailable",
        "code": "database_unavailable",
    }


def test_chat_service_rewrites_direct_change_wording_to_proposal_review(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 29000,
                "planned_est_high_total": 0,
                "remaining_income_high": 531000,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 10000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 29000,
                    "warn_at": 19000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    stored = {}

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 40,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(
        guard,
        "run",
        lambda *_args, **_kwargs: {
            "mode": "proposal",
            "say": "I have adjusted the Dining budget. The warning amount is now set to $260.00 and the hard cap is set to $340.00.",
            "question": None,
            "proposal": {
                "proposal_type": "adjust_budget_line_thresholds",
                "operations": [
                    {
                        "action": "update_budget_line",
                        "budget_line_id": 3,
                        "category": "Dining",
                        "fields": {"warn_at": 26000, "hard_cap": 34000},
                    }
                ],
            },
            "fallback": False,
        },
    )

    result = chat_service.send_message(1, "no i want the cap to instead now be 340, with a warning at 260")

    assert result["mode"] == "proposal"
    assert "I have adjusted" not in result["reply"]
    assert "I revised the proposal to move Dining's warning amount to $260.00 and hard cap to $340.00 for your review." == result["reply"]
    assert stored["rationale"] == result["reply"]


def test_chat_service_summarises_budget_with_grounded_data(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {"category": "Dining", "projected_high_total": 79100, "warn_at": 70000, "hard_cap": 85000},
                {"category": "Fitness", "projected_high_total": 37000, "warn_at": 30000, "hard_cap": 45000},
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "summarise my budget situation")

    assert result["mode"] == "advice"
    assert "September 2026" in result["reply"]
    assert "$5,600.00" in result["reply"]
    assert "$1,071.00" in result["reply"]
    assert "$4,254.00" in result["reply"]
    assert "Dining" in result["reply"]


def test_chat_service_answers_overspending_from_current_thresholds(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 8,
                    "category": "Mobile",
                    "actual_spend": 12000,
                    "planned_est_high_total": 0,
                    "projected_high_total": 12000,
                    "warn_at": 7500,
                    "hard_cap": 10000,
                },
                {
                    "id": 9,
                    "category": "Groceries",
                    "actual_spend": 12500,
                    "planned_est_high_total": 6000,
                    "projected_high_total": 18500,
                    "warn_at": 22000,
                    "hard_cap": 40000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "Where am I overspending most?")

    assert result["mode"] == "advice"
    assert "You are overspending most in Mobile." in result["reply"]
    assert "$20.00 over the hard cap of $100.00" in result["reply"]


def test_chat_service_reuses_recent_amount_for_budget_impact(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    history = [
            {"role": "user", "content": "can i afford to go take my partner out to a fancy restaurant for dinner"},
            {"role": "assistant", "content": "Tell me the rough amount you are considering."},
            {"role": "user", "content": "probably at least $80"},
            {"role": "assistant", "content": "Okay."},
        ]
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "how does it affect my budget", history)

    assert result["mode"] == "advice"
    assert result["question"] is None
    assert "$80.00" in result["reply"]
    assert "$4,254.00" in result["reply"]
    assert "$4,174.00" in result["reply"]


def test_chat_service_answers_category_only_affordability_from_budget(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79000,
                    "warn_at": 70000,
                    "hard_cap": 85000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "Can I still afford to eat out this month?")

    assert result["mode"] == "advice"
    assert result["question"] is None
    assert "Dining is already in warning range" in result["reply"]
    assert "$60.00 left before reaching the hard cap" in result["reply"]


def test_chat_service_answers_spend_more_question_from_current_mobile_budget(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 8,
                    "category": "Mobile",
                    "actual_spend": 12000,
                    "planned_est_high_total": 0,
                    "projected_high_total": 12000,
                    "warn_at": 7500,
                    "hard_cap": 10000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "am i able to spend more in mobile")

    assert result["mode"] == "advice"
    assert result["proposal"] is None
    assert "Mobile is already over its hard cap." in result["reply"]


def test_chat_service_switches_topic_to_category_remaining(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    history = [
            {"role": "user", "content": "am i able to take my partner out to a nice restaurant for dinner"},
            {"role": "assistant", "content": "How much would that cost?"},
            {"role": "user", "content": "about $90"},
            {"role": "assistant", "content": "It depends on Dining."},
            {"role": "user", "content": "ok moving on then, how much am i free to spend on groceries this month"},
        ]
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "category": "Dining",
                    "actual_spend": 60000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79000,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
                {
                    "category": "Groceries",
                    "actual_spend": 12500,
                    "planned_est_high_total": 6000,
                    "projected_high_total": 18500,
                    "warn_at": 22000,
                    "hard_cap": 40000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "ok moving on then, how much am i free to spend on groceries this month", history)

    assert result["mode"] == "advice"
    assert "Groceries" in result["reply"]
    assert "Dining" not in result["reply"]
    assert "$35.00 before warning" in result["reply"]
    assert "$215.00 before hard cap" in result["reply"]


def test_chat_service_answers_spend_most_without_stale_affordability_context(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    history = [
            {"role": "user", "content": "am i able to take my partner out to a nice restaurant for dinner"},
            {"role": "assistant", "content": "How much would that cost?"},
            {"role": "user", "content": "about $90"},
        ]
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "category": "Dining",
                    "actual_spend": 60000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79000,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
                {
                    "category": "Groceries",
                    "actual_spend": 12500,
                    "planned_est_high_total": 6000,
                    "projected_high_total": 18500,
                    "warn_at": 22000,
                    "hard_cap": 40000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "what am i spending the most money on this month", history)

    assert result["mode"] == "advice"
    assert "Dining" in result["reply"]
    assert "$600.00 so far" in result["reply"]
    assert "Groceries" not in result["reply"]


def test_chat_service_answers_savings_question_from_budget_data(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "category": "Dining",
                    "actual_spend": 60000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79000,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
                {
                    "category": "Fitness",
                    "actual_spend": 25000,
                    "planned_est_high_total": 12000,
                    "projected_high_total": 37000,
                    "warn_at": 30000,
                    "hard_cap": 45000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "how can i save money")

    assert result["mode"] == "advice"
    assert "Dining" in result["reply"]
    assert "Fitness" in result["reply"]
    assert "save" in result["reply"].casefold()


def test_chat_service_answers_yes_no_follow_up_from_recent_affordability_context(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    history = [
            {"role": "user", "content": "am i able to take my partner out to a nice restaurant for dinner"},
            {"role": "assistant", "content": "How much would that cost approximately?"},
            {"role": "user", "content": "about $90"},
            {"role": "assistant", "content": "That would affect Dining."},
        ]
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "category": "Dining",
                    "actual_spend": 60000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79000,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
        },
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "oh but i wont be over?", history)

    assert result["mode"] == "advice"
    assert "No, that would put Dining over its hard cap." in result["reply"]
    assert "$90.00" in result["reply"]


def test_chat_service_creates_reviewable_adjustment_proposal(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60100,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79100,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    stored = {}

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 12,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "what adjustments should i make to my budgets")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 12
    assert stored["proposal_json"]["proposal_type"] == "adjust_budget_line_thresholds"
    assert stored["proposal_json"]["operations"][0]["action"] == "update_budget_line"
    assert stored["proposal_json"]["operations"][0]["budget_line_id"] == 3
    assert "Dining is projected to reach $791.00" in result["reply"]
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 80000, "hard_cap": 90000}


def test_chat_service_keeps_increase_proposal_safe_against_projected_spend(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60100,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79100,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    stored = {}

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 13,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "i would like to increase the dining budget by $200 i think")

    fields = stored["proposal_json"]["operations"][0]["fields"]

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 13
    assert stored["proposal_json"]["operations"][0]["budget_line_id"] == 3
    assert fields["warn_at"] == 80000
    assert fields["hard_cap"] == 90000
    assert "A $200.00 increase would still leave Dining below its projected $791.00" in result["reply"]


def test_chat_service_uses_recent_adjustment_context_for_follow_up_ideas(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    history = [
        {"role": "user", "content": "where am i spending overbudget the most"},
        {"role": "assistant", "content": "Dining is under the most pressure this month."},
        {"role": "user", "content": "i would like to increase the dining budget by $200 i think"},
        {"role": "assistant", "content": "Okay."},
    ]
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60100,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79100,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    stored = {}

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 14,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "hit me with ideas", history)

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 14
    assert stored["proposal_json"]["operations"][0]["budget_line_id"] == 3
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 80000, "hard_cap": 90000}


def test_chat_service_uses_latest_open_mobile_proposal_for_enough_follow_up(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 8,
                    "category": "Mobile",
                    "actual_spend": 12000,
                    "planned_est_high_total": 0,
                    "projected_high_total": 12000,
                    "warn_at": 7500,
                    "hard_cap": 10000,
                },
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60100,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79100,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
            "coach_proposals": [
                {
                    "id": 21,
                    "budget_id": 1,
                    "status": "proposed",
                    "proposal_json": {
                        "proposal_type": "adjust_budget_line_thresholds",
                        "summary": "Review Dining warning and hard-cap values.",
                        "operations": [
                            {
                                "action": "update_budget_line",
                                "budget_line_id": 3,
                                "category": "Dining",
                                "fields": {"warn_at": 80000, "hard_cap": 90000},
                            }
                        ],
                    },
                },
                {
                    "id": 22,
                    "budget_id": 1,
                    "status": "proposed",
                    "proposal_json": {
                        "proposal_type": "adjust_budget_line_thresholds",
                        "summary": "Review Mobile warning and hard-cap values.",
                        "operations": [
                            {
                                "action": "update_budget_line",
                                "budget_line_id": 8,
                                "category": "Mobile",
                                "fields": {"warn_at": 13000, "hard_cap": 14000},
                            }
                        ],
                    },
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    deleted_ids = []
    stored = {}
    monkeypatch.setattr(db_api, "delete_coach_proposal", lambda proposal_id: deleted_ids.append(int(proposal_id)) or (None, 204))

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 23,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "im not sure if that will be enough")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 23
    assert deleted_ids == [22]
    assert stored["proposal_json"]["operations"][0]["budget_line_id"] == 8
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 14000, "hard_cap": 15000}
    assert "I adjusted the suggestion upward for Mobile." in result["reply"]


def test_chat_service_increases_mobile_proposal_by_requested_amount(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 8,
                    "category": "Mobile",
                    "actual_spend": 12000,
                    "planned_est_high_total": 0,
                    "projected_high_total": 12000,
                    "warn_at": 7500,
                    "hard_cap": 10000,
                },
            ],
            "coach_proposals": [
                {
                    "id": 22,
                    "budget_id": 1,
                    "status": "proposed",
                    "proposal_json": {
                        "proposal_type": "adjust_budget_line_thresholds",
                        "summary": "Review Mobile warning and hard-cap values.",
                        "operations": [
                            {
                                "action": "update_budget_line",
                                "budget_line_id": 8,
                                "category": "Mobile",
                                "fields": {"warn_at": 13000, "hard_cap": 14000},
                            }
                        ],
                    },
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    deleted_ids = []
    stored = {}
    monkeypatch.setattr(db_api, "delete_coach_proposal", lambda proposal_id: deleted_ids.append(int(proposal_id)) or (None, 204))

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 24,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    history = [
        {"role": "user", "content": "i want to increase my mobile budget"},
        {"role": "assistant", "content": "Mobile is projected to reach $120.00 this month against its current warning amount of $75.00 and hard cap of $100.00."},
    ]
    result = chat_service.send_message(1, "can you increase your mobile proposal by a little bit? maybe $20?", history)

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 24
    assert deleted_ids == [22]
    assert stored["proposal_json"]["operations"][0]["budget_line_id"] == 8
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 15000, "hard_cap": 16000}
    assert "I adjusted the suggestion upward for Mobile." in result["reply"]


def test_chat_service_extends_existing_utilities_proposal(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 26000,
                "planned_est_high_total": 0,
                "remaining_income_high": 503000,
            },
            "budget_lines": [
                {
                    "id": 10,
                    "category": "Utilities",
                    "actual_spend": 26000,
                    "planned_est_high_total": 0,
                    "projected_high_total": 26000,
                    "warn_at": 16000,
                    "hard_cap": 20000,
                },
            ],
            "coach_proposals": [
                {
                    "id": 30,
                    "budget_id": 1,
                    "status": "proposed",
                    "proposal_json": {
                        "proposal_type": "adjust_budget_line_thresholds",
                        "summary": "Review Utilities warning and hard-cap values.",
                        "operations": [
                            {
                                "action": "update_budget_line",
                                "budget_line_id": 10,
                                "category": "Utilities",
                                "fields": {"warn_at": 26000, "hard_cap": 29000},
                            }
                        ],
                    },
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    deleted_ids = []
    stored = {}
    monkeypatch.setattr(db_api, "delete_coach_proposal", lambda proposal_id: deleted_ids.append(int(proposal_id)) or (None, 204))

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 31,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "can you extend it a little further")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 31
    assert deleted_ids == [30]
    fields = stored["proposal_json"]["operations"][0]["fields"]
    assert fields["warn_at"] > 26000
    assert fields["hard_cap"] > 29000


def test_chat_service_uses_explicit_cap_target_instead_of_stacking_increase(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 29000,
                "planned_est_high_total": 0,
                "remaining_income_high": 531000,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 10000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 29000,
                    "warn_at": 19000,
                    "hard_cap": 24000,
                },
            ],
            "coach_proposals": [
                {
                    "id": 41,
                    "budget_id": 1,
                    "status": "proposed",
                    "proposal_json": {
                        "proposal_type": "adjust_budget_line_thresholds",
                        "summary": "Review Dining warning and hard-cap values.",
                        "operations": [
                            {
                                "action": "update_budget_line",
                                "budget_line_id": 3,
                                "category": "Dining",
                                "fields": {"warn_at": 19000, "hard_cap": 31000},
                            }
                        ],
                    },
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    deleted_ids = []
    stored = {}
    monkeypatch.setattr(db_api, "delete_coach_proposal", lambda proposal_id: deleted_ids.append(int(proposal_id)) or (None, 204))

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 42,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "can you increase your proposal to a cap of 350 instead?")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 42
    assert deleted_ids == [41]
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 32000, "hard_cap": 35000}
    assert result["reply"] == "I revised the proposal to move Dining's warning amount to $320.00 and hard cap to $350.00 for your review."


def test_chat_service_uses_explicit_warn_and_cap_targets(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 29000,
                "planned_est_high_total": 0,
                "remaining_income_high": 531000,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 10000,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 29000,
                    "warn_at": 19000,
                    "hard_cap": 24000,
                },
            ],
            "coach_proposals": [
                {
                    "id": 42,
                    "budget_id": 1,
                    "status": "proposed",
                    "proposal_json": {
                        "proposal_type": "adjust_budget_line_thresholds",
                        "summary": "Review Dining warning and hard-cap values.",
                        "operations": [
                            {
                                "action": "update_budget_line",
                                "budget_line_id": 3,
                                "category": "Dining",
                                "fields": {"warn_at": 32000, "hard_cap": 35000},
                            }
                        ],
                    },
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    deleted_ids = []
    stored = {}
    monkeypatch.setattr(db_api, "delete_coach_proposal", lambda proposal_id: deleted_ids.append(int(proposal_id)) or (None, 204))

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 43,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "no i want the cap to be $350, warn at $325")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 43
    assert deleted_ids == [42]
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 32500, "hard_cap": 35000}
    assert result["reply"] == "I revised the proposal to move Dining's warning amount to $325.00 and hard cap to $350.00 for your review."


def test_chat_service_acknowledgement_does_not_spawn_proposal(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 19000,
                "planned_est_high_total": 0,
                "remaining_income_high": 541000,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 0,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 19000,
                    "warn_at": 19000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    monkeypatch.setattr(
        db_api,
        "create_coach_proposal",
        lambda *_args, **_kwargs: pytest.fail("create_coach_proposal should not be called"),
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "awesome thank you")

    assert result["mode"] == "advice"
    assert result["reply"] == "Okay."
    assert result["proposal"] is None


def test_chat_service_creates_requested_lower_cap_proposal(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 19000,
                "planned_est_high_total": 0,
                "remaining_income_high": 541000,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 0,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 19000,
                    "warn_at": 19000,
                    "hard_cap": 24000,
                },
            ],
            "transactions": {"other_expenses": []},
        },
    )
    stored = {}

    def create_coach_proposal(_budget_id, payload):
        stored.update(payload)
        return {
            "id": 32,
            "budget_id": 1,
            "proposal_json": payload["proposal_json"],
            "rationale": payload["rationale"],
            "status": "proposed",
        }, 201

    monkeypatch.setattr(db_api, "create_coach_proposal", create_coach_proposal)
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "make me a suggestion to lower the dining cap to 200")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 32
    assert stored["proposal_json"]["operations"][0]["fields"] == {"warn_at": 19000, "hard_cap": 20000}
    assert "because you asked for it I prepared a proposal" in result["reply"]

def test_chat_service_reuses_equivalent_open_proposal(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda _budget_id: {"id": 1, "month": "2026-09"})
    existing_proposal = {
        "id": 11,
        "budget_id": 1,
        "status": "proposed",
        "proposal_json": {
            "proposal_type": "adjust_budget_line_thresholds",
            "summary": "Review Dining warning and hard-cap values.",
            "operations": [
                {
                    "action": "update_budget_line",
                    "budget_line_id": 3,
                    "category": "Dining",
                    "fields": {"warn_at": 80000, "hard_cap": 90000},
                }
            ],
        },
        "rationale": "Existing proposal.",
    }
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda _budget_id: {
            "budget": {"id": 1, "month": "2026-09", "declared_income": 560000},
            "totals": {
                "declared_income": 560000,
                "actual_spend_total": 107100,
                "planned_est_high_total": 27500,
                "remaining_income_high": 425400,
            },
            "budget_lines": [
                {
                    "id": 3,
                    "category": "Dining",
                    "actual_spend": 60100,
                    "planned_est_high_total": 19000,
                    "projected_high_total": 79100,
                    "warn_at": 18000,
                    "hard_cap": 24000,
                },
            ],
            "coach_proposals": [existing_proposal],
            "transactions": {"other_expenses": []},
        },
    )
    monkeypatch.setattr(
        db_api,
        "create_coach_proposal",
        lambda *_args, **_kwargs: pytest.fail("create_coach_proposal should not be called"),
    )
    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: pytest.fail("guard should not be called"))

    result = chat_service.send_message(1, "what adjustments should i make to my budgets")

    assert result["mode"] == "proposal"
    assert result["proposal"]["id"] == 11


def test_apply_proposal_updates_budget_line_and_marks_proposal_accepted(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "get_coach_proposal",
        lambda proposal_id: {
            "id": int(proposal_id),
            "budget_id": 1,
            "status": "proposed",
            "proposal_json": {
                "proposal_type": "adjust_budget_line_thresholds",
                "operations": [
                    {
                        "action": "update_budget_line",
                        "budget_line_id": 3,
                        "fields": {"warn_at": 72000, "hard_cap": 85000},
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        db_api,
        "get_budget_line",
        lambda line_id: {"id": int(line_id), "budget_id": 1, "warn_at": 18000, "hard_cap": 24000},
    )
    monkeypatch.setattr(
        db_api,
        "update_budget_line",
        lambda line_id, payload: {"id": int(line_id), **payload},
    )
    monkeypatch.setattr(
        db_api,
        "update_coach_proposal",
        lambda proposal_id, payload: {"id": int(proposal_id), "status": payload["status"]},
    )

    result = proposal_service.apply(7)

    assert result["proposal"] == {"id": 7, "status": "accepted"}
    assert result["applied"] == [{"id": 3, "warn_at": 72000, "hard_cap": 85000}]


def test_patch_planned_event(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "update_planned_event",
        lambda event_id, payload: {
            "id": int(event_id),
            "status": payload["status"],
        },
    )

    resp = _client().patch("/api/planned-events/7", json={"status": "cancelled"})

    assert resp.status_code == 200
    assert resp.get_json() == {
        "id": 7,
        "status": "cancelled",
    }


def test_budget_snapshot_aggregates_child_collections(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda budget_id: {"id": budget_id, "month": "2026-09"})
    monkeypatch.setattr(db_api, "list_budget_lines", lambda budget_id: [{"id": 1, "budget_id": budget_id}])
    monkeypatch.setattr(db_api, "list_planned_events", lambda budget_id: [{"id": 1, "budget_id": budget_id}])
    monkeypatch.setattr(db_api, "list_coach_proposals", lambda budget_id: [{"id": 1, "budget_id": budget_id}])

    resp = _client().get("/api/budgets/b1/snapshot")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "budget": {"id": "b1", "month": "2026-09"},
        "budget_lines": [{"id": 1, "budget_id": "b1"}],
        "planned_events": [{"id": 1, "budget_id": "b1"}],
        "coach_proposals": [{"id": 1, "budget_id": "b1"}],
    }


def test_budget_summary_route(monkeypatch):
    monkeypatch.setattr(
        summary_service,
        "build_budget_summary",
        lambda budget_id: {
            "budget": {"id": budget_id},
            "totals": {"actual_spend_total": 12345},
        },
    )

    resp = _client().get("/api/budgets/b1/summary")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "budget": {"id": "b1"},
        "totals": {"actual_spend_total": 12345},
    }


def test_service_error_from_database_is_forwarded(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "get_budget",
        lambda _budget_id: (_ for _ in ()).throw(
            db_api.ServiceError("budget not found", 404, "budget_not_found")
        ),
    )

    resp = _client().get("/api/budgets/missing")

    assert resp.status_code == 404
    assert resp.get_json() == {
        "error": "budget not found",
        "code": "budget_not_found",
    }


def test_database_unavailable_returns_503(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "list_budgets",
        lambda: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )

    resp = _client().get("/api/budgets")

    assert resp.status_code == 503
    assert resp.get_json()["code"] == "database_unavailable"


def test_budget_summary_returns_transactions_unavailable(monkeypatch):
    monkeypatch.setattr(db_api, "get_budget", lambda budget_id: {"id": budget_id, "month": "2026-01"})
    monkeypatch.setattr(db_api, "list_budget_lines", lambda _budget_id: [])
    monkeypatch.setattr(db_api, "list_planned_events", lambda _budget_id: [])
    monkeypatch.setattr(db_api, "list_coach_proposals", lambda _budget_id: [])
    monkeypatch.setattr(transactions_api, "list_categories", lambda: [])
    monkeypatch.setattr(
        transactions_api,
        "list_transactions_for_month",
        lambda _month: (_ for _ in ()).throw(
            db_api.ServiceError("transactions API is unavailable", 503, "transactions_unavailable")
        ),
    )

    resp = _client().get("/api/budgets/b1/summary")

    assert resp.status_code == 503
    assert resp.get_json() == {
        "error": "transactions API is unavailable",
        "code": "transactions_unavailable",
    }


def test_budget_summary_calculates_actual_and_planned_totals(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "get_budget",
        lambda _budget_id: {"id": "b1", "month": "2026-09", "declared_income": 30000},
    )
    monkeypatch.setattr(
        db_api,
        "list_budget_lines",
        lambda _budget_id: [
            {"id": 1, "budget_id": "b1", "category_id": 80, "category": "Dining", "warn_at": 10000, "hard_cap": 15000},
            {"id": 2, "budget_id": "b1", "category_id": 81, "category": "Groceries", "warn_at": 12000, "hard_cap": 18000},
        ],
    )
    monkeypatch.setattr(
        db_api,
        "list_planned_events",
        lambda _budget_id: [
            {"id": 1, "budget_id": "b1", "category": "Dining", "est_low": 2000, "est_high": 3000, "status": "planned"},
            {"id": 2, "budget_id": "b1", "category": "Groceries", "est_low": 4000, "est_high": 6000, "status": "confirmed"},
            {"id": 3, "budget_id": "b1", "category": "Dining", "est_low": 9999, "est_high": 9999, "status": "cancelled"},
        ],
    )
    monkeypatch.setattr(db_api, "list_coach_proposals", lambda _budget_id: [])
    monkeypatch.setattr(
        transactions_api,
        "list_categories",
        lambda: [{"id": 80, "name": "Dining"}, {"id": 81, "name": "Groceries"}],
    )
    monkeypatch.setattr(
        transactions_api,
        "list_transactions_for_month",
        lambda _month: [
            {"id": 1, "amount": 42.5, "category_id": 80},
            {"id": 2, "amount": 16.25, "category_id": 80},
            {"id": 3, "amount": 91.0, "category_id": 81},
            {"id": 4, "amount": 11.0, "category_id": 999},
        ],
    )

    summary = summary_service.build_budget_summary("b1")

    assert summary["transactions"] == {
        "count": 4,
        "uncategorised_total": 1100,
        "other_expenses": [],
    }
    assert summary["totals"] == {
        "declared_income": 30000,
        "actual_spend_total": 14975,
        "planned_est_low_total": 6000,
        "planned_est_high_total": 9000,
        "budget_warn_total": 22000,
        "budget_cap_total": 33000,
        "projected_low_total": 20975,
        "projected_high_total": 23975,
        "remaining_income_low": 9025,
        "remaining_income_high": 6025,
    }
    dining_line = next(line for line in summary["budget_lines"] if line["category"] == "Dining")
    assert dining_line["actual_spend"] == 5875
    assert dining_line["planned_est_low_total"] == 2000
    assert dining_line["planned_est_high_total"] == 3000
    assert dining_line["warning_state"] is False
    assert dining_line["cap_state"] is False
    groceries_line = next(line for line in summary["budget_lines"] if line["category"] == "Groceries")
    assert groceries_line["actual_spend"] == 9100
    assert groceries_line["planned_est_low_total"] == 4000
    assert groceries_line["planned_est_high_total"] == 6000
    assert groceries_line["warning_state"] is False
    assert groceries_line["cap_state"] is False


def test_budget_summary_lists_other_expense_categories_without_budget_lines(monkeypatch):
    monkeypatch.setattr(
        db_api,
        "get_budget",
        lambda _budget_id: {"id": "b1", "month": "2026-09", "declared_income": 50000},
    )
    monkeypatch.setattr(
        db_api,
        "list_budget_lines",
        lambda _budget_id: [
            {"id": 1, "budget_id": "b1", "category_id": 80, "category": "Dining", "warn_at": 10000, "hard_cap": 15000},
        ],
    )
    monkeypatch.setattr(db_api, "list_planned_events", lambda _budget_id: [])
    monkeypatch.setattr(db_api, "list_coach_proposals", lambda _budget_id: [])
    monkeypatch.setattr(
        transactions_api,
        "list_categories",
        lambda: [{"id": 80, "name": "Dining"}, {"id": 81, "name": "Groceries"}, {"id": 82, "name": "Fuel"}],
    )
    monkeypatch.setattr(
        transactions_api,
        "list_transactions_for_month",
        lambda _month: [
            {"id": 1, "amount": 25.0, "category_id": 80},
            {"id": 2, "amount": 35.0, "category_id": 81},
            {"id": 3, "amount": 22.5, "category_id": 82},
            {"id": 4, "amount": 5.0, "category_id": 81},
        ],
    )

    summary = summary_service.build_budget_summary("b1")

    assert summary["transactions"] == {
        "count": 4,
        "uncategorised_total": 0,
        "other_expenses": [
            {"category_id": 82, "category": "Fuel", "actual_spend": 2250},
            {"category_id": 81, "category": "Groceries", "actual_spend": 4000},
        ],
    }
