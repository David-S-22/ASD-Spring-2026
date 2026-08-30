from pathlib import Path

from ..collectors import architecture_collector, db_collector, devops_collector, endpoints_collector
from ..config.review_config import ModeConfig
from ..pipelines import architecture_pipeline, db_pipeline, devops_pipeline, endpoints_pipeline
from .ai_runner import AIRunner
from .prompt_registry import PromptRegistry
from .recorder import RunRecorder

COLLECTORS = {
    "db": db_collector.collect,
    "endpoints": endpoints_collector.collect,
    "architecture": architecture_collector.collect,
    "devops": devops_collector.collect,
}

TWO_STAGE_PIPELINES = {
    "architecture": architecture_pipeline,
    "devops": devops_pipeline,
}


def _stage(recorder: RunRecorder, mode_label: str, step: str, message: str) -> None:
    print(f"[{mode_label}][{step}] {message}")
    recorder.stage(step, message)


def _adapt(recorder: RunRecorder, mode_label: str, finding: str) -> tuple[str, str | None]:
    """Human review-and-adapt stage: the finding is accepted, rejected, or
    edited by the person driving the loop, and the decision is recorded."""
    _stage(recorder, mode_label, "ADAPT", "Human review of the finding")
    print()
    print("-" * 70)
    print("FINDING UNDER REVIEW:")
    print(finding)
    print("-" * 70)
    while True:
        choice = input("Accept, reject, or edit this finding? [a/r/e]: ").strip().lower()
        if choice in {"a", "accept"}:
            recorder.human_decision("accepted", None)
            _stage(recorder, mode_label, "ADAPT", "Finding accepted")
            return "accepted", None
        if choice in {"r", "reject"}:
            reason = input("Why is it rejected? (recorded): ").strip()
            recorder.human_decision("rejected", reason or None)
            _stage(recorder, mode_label, "ADAPT", "Finding rejected")
            return "rejected", reason or None
        if choice in {"e", "edit"}:
            edit = input("Enter the corrected finding: ").strip()
            recorder.human_decision("edited", edit)
            _stage(recorder, mode_label, "ADAPT", "Finding edited by human")
            return "edited", edit
        print("Please answer a, r, or e.")


def run_mode(mode: ModeConfig, app_dir: Path, repo_root: Path, prompts: PromptRegistry,
             ai: AIRunner, recorder: RunRecorder) -> str:
    recorder.start_mode(mode.key, mode.label)
    _stage(recorder, mode.label, "PLAN", f"Review target: {mode.label}; prompt family: {mode.prompt_family}")

    _stage(recorder, mode.label, "OBSERVE", "Collecting evidence")
    ok, evidence = COLLECTORS[mode.key](app_dir, repo_root)
    recorder.set(evidence=evidence)
    if not ok:
        _stage(recorder, mode.label, "OBSERVE", "Failed")
        recorder.end_mode()
        return f"OBSERVE FAILED: {evidence}"
    _stage(recorder, mode.label, "OBSERVE", "Complete")

    _stage(recorder, mode.label, "PLAN", f"Loading prompt family: {mode.prompt_family}")
    for filename in mode.implementation_prompts + mode.review_prompts:
        recorder.prompt_used(mode.prompt_family, filename)
    recorder.set(models={"implementation": ai.implementation_model,
                         **({"review": ai.review_model} if mode.review_prompts else {})})

    if mode.key in {"db", "endpoints"}:
        system_prompt = prompts.read(mode.prompt_family, mode.implementation_prompts[0])
        task_prompt = prompts.read(mode.prompt_family, mode.implementation_prompts[1])
        context_prompt = prompts.read(mode.prompt_family, mode.implementation_prompts[2])
        pipeline = db_pipeline if mode.key == "db" else endpoints_pipeline
        user_prompt = pipeline.build_user_prompt(task_prompt, context_prompt, evidence)
        _stage(recorder, mode.label, "PLAN", "Implementation prompt set loaded")

        _stage(recorder, mode.label, "ACT", f"Running implementation model ({ai.implementation_model})")
        output, err = ai.call(system_prompt, user_prompt, review=False)
        if err:
            _stage(recorder, mode.label, "ACT", "Failed")
            recorder.set(implementation_output=err)
            recorder.end_mode()
            return f"MODEL FAILED: {err}"
        recorder.set(implementation_output=output)
        _stage(recorder, mode.label, "ACT", "Complete")

        decision, edit = _adapt(recorder, mode.label, output)
        recorder.end_mode()
        final = edit if decision == "edited" else output
        return f"OBSERVE: {evidence}\n\nREVIEW: {final}\n\nHUMAN DECISION: {decision}"

    pipeline = TWO_STAGE_PIPELINES[mode.key]
    system_prompt = prompts.read(mode.prompt_family, mode.implementation_prompts[0])
    task_prompt = prompts.read(mode.prompt_family, mode.implementation_prompts[1])
    implementation_user_prompt = pipeline.build_implementation_prompt(task_prompt, evidence)
    _stage(recorder, mode.label, "PLAN", "Implementation prompts loaded")

    _stage(recorder, mode.label, "ACT", f"Running implementation model ({ai.implementation_model})")
    implementation_output, err = ai.call(system_prompt, implementation_user_prompt, review=False)
    if err:
        _stage(recorder, mode.label, "ACT", "Failed")
        recorder.set(implementation_output=err)
        recorder.end_mode()
        return f"MODEL FAILED: {err}"
    recorder.set(implementation_output=implementation_output)
    _stage(recorder, mode.label, "ACT", "Implementation model complete")

    review_system_prompt = prompts.read(mode.prompt_family, mode.review_prompts[0])
    review_user_prompt = pipeline.build_review_prompt(implementation_output, evidence)
    _stage(recorder, mode.label, "ACT", f"Running review model ({ai.review_model})")
    review_output, review_err = ai.call(review_system_prompt, review_user_prompt, review=True)
    if review_err:
        review_output = review_err
        _stage(recorder, mode.label, "ACT", "Review model failed")
    else:
        _stage(recorder, mode.label, "ACT", "Review model complete")
    recorder.set(review_output=review_output)

    finding = f"{implementation_output}\n\nREVIEW MODEL: {review_output}"
    decision, edit = _adapt(recorder, mode.label, finding)
    recorder.end_mode()
    final = edit if decision == "edited" else finding
    return (
        f"OBSERVE: {evidence}\n\n"
        f"FINDING: {final}\n\n"
        f"HUMAN DECISION: {decision}"
    )
