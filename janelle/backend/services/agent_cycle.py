"""Dependency-free Plan -> Act -> Observe -> Adapt cycle runner."""


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
        cycle = {"iteration": iteration}
        try:
            planned = plan(current_context)
            cycle["plan"] = planned

            action = act(planned, current_context)
            cycle["action"] = action

            observation = observe(planned, action, current_context)
            cycle["observation"] = observation

            adaptation = adapt(
                planned,
                action,
                observation,
                current_context,
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
