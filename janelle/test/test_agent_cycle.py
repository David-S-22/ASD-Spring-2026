from janelle.backend.services.agent_cycle import run_cycle


def test_cycle_runs_stages_in_plan_act_observe_adapt_order():
    stages = []

    result = run_cycle(
        {"request": "test"},
        plan=lambda context: record(stages, "PLAN", {"operation": "read"}),
        act=lambda plan, context: record(stages, "ACT", {"status": "ok"}),
        observe=lambda plan, action, context: record(
            stages,
            "OBSERVE",
            {"status": "ok"},
        ),
        adapt=lambda plan, action, observation, context: record(
            stages,
            "ADAPT",
            {"decision": "complete", "result": {"ok": True}},
        ),
    )

    assert stages == ["PLAN", "ACT", "OBSERVE", "ADAPT"]
    assert result["status"] == "complete"
    assert result["result"] == {"ok": True}
    assert len(result["cycles"]) == 1


def test_cycle_replans_once_then_stops():
    plans = []

    def plan(context):
        plans.append(context.get("previous_observation"))
        return {"attempt": len(plans)}

    result = run_cycle(
        {},
        plan=plan,
        act=lambda planned, context: {"attempt": planned["attempt"]},
        observe=lambda planned, action, context: {
            "attempt": action["attempt"],
        },
        adapt=lambda planned, action, observation, context: {
            "decision": (
                "replan" if observation["attempt"] == 1 else "complete"
            ),
            "result": {"attempt": observation["attempt"]},
        },
        max_iterations=2,
    )

    assert result["status"] == "complete"
    assert result["result"] == {"attempt": 2}
    assert len(result["cycles"]) == 2
    assert plans == [None, {"attempt": 1}]


def test_cycle_cannot_exceed_iteration_limit():
    result = run_cycle(
        {},
        plan=lambda context: {},
        act=lambda planned, context: {},
        observe=lambda planned, action, context: {},
        adapt=lambda planned, action, observation, context: {
            "decision": "replan",
        },
        max_iterations=2,
    )

    assert result["status"] == "failed"
    assert len(result["cycles"]) == 2
    assert result["error"]["type"] == "IterationLimitReached"


def test_cycle_converts_stage_exception_to_explicit_failure():
    def fail_action(planned, context):
        raise RuntimeError("boom")

    result = run_cycle(
        {},
        plan=lambda context: {"operation": "read"},
        act=fail_action,
        observe=lambda planned, action, context: {},
        adapt=lambda planned, action, observation, context: {
            "decision": "complete",
        },
    )

    assert result["status"] == "failed"
    assert result["error"] == {
        "stage": "ACT",
        "type": "RuntimeError",
        "message": "boom",
    }
    assert result["cycles"][0]["plan"] == {"operation": "read"}
    assert "action" not in result["cycles"][0]


def record(stages, stage, value):
    stages.append(stage)
    return value
