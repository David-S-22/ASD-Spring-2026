"""Sophia's extended agentic loop: Plan -> Act -> Observe -> Adapt.

Four review modes over the group app. This is the individual, extended
counterpart to the shared file-only loop the team agreed to (#78): same
four-stage workflow and the same MODES extension point, but the service
modes observe the running system rather than only the files.

Run it from the repository root:

    python -m sophia.agentic_loop.main

Everything it reads or writes lives under sophia/agentic_loop/, except the
evidence it observes -- docker-compose.yml, .github/workflows/ and the live
services -- which it only ever reads.
"""

import os
import traceback
from pathlib import Path

import requests

from .collect import (collect_architecture, collect_database, collect_devops,
                      collect_endpoints)
from .record import RunRecord

# Two roots, named separately on purpose. The shared loop sits at the repo
# root and can get away with one; this one is two levels down, so collapsing
# them would silently point the collectors at sophia/.
FEATURE_ROOT = Path(__file__).resolve().parent      # prompts, reports
REPO_ROOT = FEATURE_ROOT.parent.parent              # compose, workflows, students
PROMPTS_DIR = FEATURE_ROOT / "prompts"
REPORTS_DIR = FEATURE_ROOT / "reports"

MODES = {
    "architecture": ("Architecture", "architecture", collect_architecture),
    "database": ("Database", "database", collect_database),
    "endpoints": ("Endpoints", "endpoints", collect_endpoints),
    "devops": ("DevOps", "devops", collect_devops),
}


# --- prompts and models ----------------------------------------------------

def read_prompt(family: str, name: str) -> str:
    path = PROMPTS_DIR / family / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise SystemExit(
            f"Prompt file missing: {path}\n"
            f"Every mode needs implementation/system_prompt.txt, "
            f"implementation/task_prompt.txt and review/review_prompt.txt "
            f"under {PROMPTS_DIR}/<family>/."
        )


def call_model(system_prompt: str, user_prompt: str, *, review: bool = False):
    """One chat call to the local ollama service.

    Returns (output, error, traceback_text). Ollama's OpenAI-compatible route
    is used over plain HTTP so the loop needs no SDK -- requests is already a
    dependency of the Bills test environment.
    """
    model = (os.getenv("OLLAMA_REVIEW_MODEL", "llama3.1:8b") if review
             else os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"))
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": user_prompt}],
                # Generous on purpose: the earlier 300-token cap was cutting
                # findings mid-sentence, which made them unusable as evidence.
                "max_tokens": 900,
                "temperature": 0.1,
            },
            timeout=180,
        )
        response.raise_for_status()
        output = (response.json()["choices"][0]["message"]["content"] or "").strip()
        return output or "No response generated.", None, None
    except Exception as exc:
        # The failure is still shown to the human as a finding, but the
        # traceback goes into the run record so a real defect is diagnosable
        # rather than reduced to one line of exception text.
        return None, f"Model call failed ({model} at {base_url}): {exc}", traceback.format_exc()


# --- the loop --------------------------------------------------------------

def stage(record, label, step, message):
    print(f"[{label}][{step}] {message}")
    record.stage(step, message)


def ask(prompt_text):
    """Input that reports EOF as None rather than raising."""
    try:
        return input(prompt_text).strip()
    except EOFError:                     # piped input ran out / Ctrl+D
        return None


def adapt(record, label, finding):
    """ADAPT: the human accepts, rejects or edits the finding; recorded.

    Every EOF path records an explicit abandonment. An earlier version fell
    back to `ask(...) or ""` at the follow-up prompts, so closing stdin
    mid-decision recorded an empty edit as though it were a real one.
    """
    stage(record, label, "ADAPT", "Human review of the finding")
    print("-" * 70)
    print("FINDING UNDER REVIEW:")
    print(finding)
    print("-" * 70)
    while True:
        answer = ask("Accept, reject, or edit this finding? [a/r/e]: ")
        if answer is None:
            record.decision("abandoned", "input closed before a decision")
            return "abandoned", None
        choice = answer.lower()
        if choice in ("a", "accept"):
            record.decision("accepted", None)
            return "accepted", None
        if choice in ("r", "reject"):
            reason = ask("Why is it rejected? (recorded): ")
            if reason is None:
                record.decision("abandoned", "input closed before a reason was given")
                return "abandoned", None
            record.decision("rejected", reason or None)
            return "rejected", reason or None
        if choice in ("e", "edit"):
            edit = ask("Enter the corrected finding: ")
            if edit is None:
                record.decision("abandoned", "input closed before an edit was given")
                return "abandoned", None
            record.decision("edited", edit)
            return "edited", edit
        print("Please answer a, r, or e.")


def run_review(key, record):
    label, family, collect = MODES[key]
    record.start_mode(key, label)
    stage(record, label, "PLAN",
          f"Review target: {label}; prompts: sophia/agentic_loop/prompts/{family}/")

    stage(record, label, "OBSERVE", "Collecting evidence")
    ok, evidence = collect(REPO_ROOT)
    record.set(evidence=evidence)
    if not ok:
        stage(record, label, "OBSERVE", "Failed")
        record.end_mode()
        return f"OBSERVE FAILED: {evidence}"
    stage(record, label, "OBSERVE", "Complete")

    system_prompt = read_prompt(family, "implementation/system_prompt.txt")
    task_prompt = read_prompt(family, "implementation/task_prompt.txt")
    stage(record, label, "ACT", "Running implementation model")
    output, err, tb = call_model(system_prompt, f"{task_prompt}\n\nEvidence:\n{evidence}")
    if err:
        stage(record, label, "ACT", "Failed")
        record.set(implementation_output=err, traceback=tb)
        record.end_mode()
        return f"MODEL FAILED: {err}"
    record.set(implementation_output=output)

    review_system = read_prompt(family, "review/review_prompt.txt")
    stage(record, label, "ACT", "Running review model")
    review, review_err, review_tb = call_model(
        review_system, f"Implementation finding:\n{output}\n\nEvidence:\n{evidence}",
        review=True)
    # Unlike ACT above, a review failure is not fatal: the error text stands in
    # as the review and the human still gets to decide.
    if review_err:
        review = review_err
        record.set(traceback=review_tb)
    record.set(review_output=review)

    finding = f"{output}\n\nREVIEW MODEL: {review}"
    decision, edit = adapt(record, label, finding)
    record.end_mode()
    final = edit if decision == "edited" else finding
    return f"OBSERVE: {evidence}\n\nFINDING: {final}\n\nHUMAN DECISION: {decision}"


def main():
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.exists():
        raise SystemExit(
            f"Expected the repository root at {REPO_ROOT}, but {compose} is not there.\n"
            f"Run this from the repository root: python -m sophia.agentic_loop.main"
        )

    record = RunRecord(REPORTS_DIR)
    keys = list(MODES)

    print("AGENTIC LOOP - Bills extended review (Plan -> Act -> Observe -> Adapt)")
    print(f"Repository: {REPO_ROOT}")
    print(f"Run record: {REPORTS_DIR}")
    while True:
        print()
        print("=" * 70)
        for number, key in enumerate(keys, start=1):
            print(f"{number} - {MODES[key][0]}")
        print("0 - Exit")
        print("=" * 70)
        choice = ask("Choose a review target: ")
        if choice is None or choice == "0":
            print("Loop closed.")
            break
        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            print()
            print(run_review(keys[int(choice) - 1], record))
        else:
            print(f"Choose 0-{len(keys)}.")


if __name__ == "__main__":
    main()
