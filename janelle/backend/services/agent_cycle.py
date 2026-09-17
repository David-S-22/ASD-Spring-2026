"""Dependency-free Plan -> Act -> Observe -> Adapt cycle runner."""

from time import perf_counter


DECISIONS = {"complete", "clarify", "confirm", "replan", "failed"}
SAFE_FAILURE = {
    "reply": "I could not safely complete that request. No changes were made.",
}


def run_cycle(
    context,
    *,
    plan,
    act,
    observe,
    adapt,
    max_iterations=2,
):
    if (
        not isinstance(max_iterations, int)
        or isinstance(max_iterations, bool)
        or max_iterations < 1
    ):
        raise ValueError("max_iterations must be a positive integer")
    if not isinstance(context, dict):
        raise TypeError("context must be a dictionary")

    cycles = []
    current_context = dict(context)

    for iteration in range(1, max_iterations + 1):
        cycle = {"iteration": iteration, "durations_ms": {}}
        try:
            planned = run_stage(
                cycle,
                "PLAN",
                lambda: plan(current_context),
            )
            cycle["plan"] = planned

            action = run_stage(
                cycle,
                "ACT",
                lambda: act(planned, current_context),
            )
            cycle["action"] = action

            observation = run_stage(
                cycle,
                "OBSERVE",
                lambda: observe(planned, action, current_context),
            )
            cycle["observation"] = observation

            adaptation = run_stage(
                cycle,
                "ADAPT",
                lambda: adapt(
                    planned,
                    action,
                    observation,
                    current_context,
                ),
            )
            validate_adaptation(adaptation)
            cycle["adaptation"] = adaptation
        except Exception as error:
            cycle["error"] = {
                "stage": next_stage(cycle),
                "type": type(error).__name__,
                "message": str(error),
            }
            cycles.append(cycle)
            return {
                "status": "failed",
                "cycles": cycles,
                "result": dict(SAFE_FAILURE),
                "error": cycle["error"],
            }

        cycles.append(cycle)
        decision = adaptation["decision"]
        if decision != "replan":
            return {
                "status": decision,
                "cycles": cycles,
                "result": adaptation.get("result"),
            }

        if iteration < max_iterations:
            current_context = {
                **current_context,
                "previous_observation": observation,
                "revised_plan": adaptation.get("revised_plan"),
            }

    return {
        "status": "failed",
        "cycles": cycles,
        "result": dict(SAFE_FAILURE),
        "error": {
            "stage": "ADAPT",
            "type": "IterationLimitReached",
            "message": "maximum agent iterations reached",
        },
    }


def run_stage(cycle, stage, operation):
    started_at = perf_counter()
    try:
        return operation()
    finally:
        cycle["durations_ms"][stage] = round(
            (perf_counter() - started_at) * 1000,
            3,
        )


def validate_adaptation(adaptation):
    if not isinstance(adaptation, dict):
        raise TypeError("adaptation must be a dictionary")
    if adaptation.get("decision") not in DECISIONS:
        raise ValueError("adaptation returned an unsupported decision")


def next_stage(cycle):
    if "plan" not in cycle:
        return "PLAN"
    if "action" not in cycle:
        return "ACT"
    if "observation" not in cycle:
        return "OBSERVE"
    return "ADAPT"
