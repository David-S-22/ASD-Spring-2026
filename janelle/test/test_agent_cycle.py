from janelle.backend.services.agent_cycle import run_cycle


def cycle(**overrides):
    """run_cycle with no-op stages; override only the stage under test."""
    stages = {
        "plan": lambda context: {},
        "act": lambda planned, context: {},
        "observe": lambda planned, action, context: {},
        "adapt": lambda planned, action, observation, context: {
            "decision": "complete",
        },
    }
    return run_cycle({}, **{**stages, **overrides})


def test_cycle_runs_stages_in_plan_act_observe_adapt_order():
    stages = []

    def record(stage, value):
        stages.append(stage)
        return value

    result = cycle(
        plan=lambda context: record("PLAN", {"operation": "read"}),
        act=lambda plan, context: record("ACT", {"status": "ok"}),
        observe=lambda plan, action, context: record("OBSERVE", {"status": "ok"}),
        adapt=lambda plan, action, observation, context: record(
            "ADAPT", {"decision": "complete", "result": {"ok": True}}
        ),
    )

    assert stages == ["PLAN", "ACT", "OBSERVE", "ADAPT"]
    assert result["status"] == "complete"
    assert result["result"] == {"ok": True}
    assert len(result["cycles"]) == 1
    durations = result["cycles"][0]["durations_ms"]
    assert set(durations) == {"PLAN", "ACT", "OBSERVE", "ADAPT"}
    assert all(duration >= 0 for duration in durations.values())


def test_cycle_replans_once_then_stops():
    plans = []

    def plan(context):
        plans.append(context.get("previous_observation"))
        return {"attempt": len(plans)}

    result = cycle(
        plan=plan,
        observe=lambda planned, action, context: {"attempt": planned["attempt"]},
        adapt=lambda planned, action, observation, context: {
            "decision": "replan" if observation["attempt"] == 1 else "complete",
            "result": observation,
        },
        max_iterations=2,
    )

    assert result["status"] == "complete"
    assert result["result"] == {"attempt": 2}
    assert len(result["cycles"]) == 2
    assert plans == [None, {"attempt": 1}]


def test_cycle_cannot_exceed_iteration_limit():
    result = cycle(
        adapt=lambda planned, action, observation, context: {"decision": "replan"},
        max_iterations=2,
    )

    assert result["status"] == "failed"
    assert len(result["cycles"]) == 2
    assert result["error"]["type"] == "IterationLimitReached"


def test_cycle_converts_stage_exception_to_explicit_failure():
    def fail_action(planned, context):
        raise RuntimeError("boom")

    result = cycle(plan=lambda context: {"operation": "read"}, act=fail_action)

    assert result["status"] == "failed"
    assert result["error"] == {
        "stage": "ACT",
        "type": "RuntimeError",
        "message": "boom",
    }
    assert result["cycles"][0]["plan"] == {"operation": "read"}
    assert set(result["cycles"][0]["durations_ms"]) == {"PLAN", "ACT"}
    assert "action" not in result["cycles"][0]
