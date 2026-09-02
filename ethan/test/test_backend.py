import requests

from backend import db_api, summary_service, transactions_api
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

    resp = _client().get("/health")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert resp.get_json()["db_api"] == "up"
    assert resp.get_json()["transactions_api"] == "up"
    assert resp.get_json()["transactions_count"] == 1


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
