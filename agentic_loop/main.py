"""Shared terminal agentic loop: Plan -> Act -> Observe -> Adapt.

Deliberately small: this file runs the whole loop, record.py writes the
run record the Release 0 report cites. To add a review mode, add prompt
files under prompts/<your-family>/ and one entry to MODES below.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

from .record import RunRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"


# --- prompts and models ----------------------------------------------------

def read_prompt(family: str, name: str) -> str:
    return (PROMPTS_DIR / family / name).read_text(encoding="utf-8").strip()


def call_model(system_prompt: str, user_prompt: str, *, review: bool = False):
    """One chat call to the local ollama service. Returns (output, error)."""
    if review:
        model = os.getenv("OLLAMA_REVIEW_MODEL", "llama3.1:8b")
    else:
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                    api_key="ollama", timeout=180.0)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}],
            max_tokens=300,
            temperature=0.1,
        )
        output = (response.choices[0].message.content or "").strip()
        return output or "No response generated.", None
    except Exception as exc:
        return None, f"Model call failed ({model}): {exc}"


# --- evidence collection (OBSERVE) -----------------------------------------

def _host_port(entry):
    if isinstance(entry, dict):          # long-form "published: 3005"
        return entry.get("published")
    head = str(entry).split(":", 1)[0]   # short-form "3005:80"
    return head if head.isdigit() else None


def collect_architecture():
    """Compose topology and repo layout, read from files - nothing must be running."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    if not compose_path.exists():
        return False, "docker-compose.yml not found at the repository root."
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}

    services, edges = [], []
    for name, spec in (compose.get("services") or {}).items():
        spec = spec or {}
        host_ports = [p for p in map(_host_port, spec.get("ports") or []) if p]
        services.append(f"{name}:{host_ports[0]}" if host_ports else name)
        deps = spec.get("depends_on") or []
        for dep in (deps.keys() if isinstance(deps, dict) else deps):
            edges.append(f"{name}->{dep}")

    # a student directory is any root directory with a backend/ ("shared" also
    # has one - shared/backend/dto.py - so it is excluded by name)
    student_dirs = sorted(p.name for p in REPO_ROOT.iterdir()
                          if p.name != "shared" and (p / "backend").is_dir())
    required = [".github/workflows", "docs", "shared", "ai-services", "scripts"]
    missing = [d for d in required if not (REPO_ROOT / d).is_dir()]
    shared_index = (REPO_ROOT / "shared" / "frontend" / "public" / "index.html").exists()

    return True, (
        f"Compose services (host port): {', '.join(sorted(services))}. "
        f"Dependency edges: {', '.join(sorted(edges)) or 'none'}. "
        f"Student directories: {', '.join(student_dirs) or 'none'}. "
        f"Missing required directories: {', '.join(missing) or 'none'}. "
        f"Shared frontend index.html present: {shared_index}."
    )


MODES = {
    "architecture": ("Architecture", "architecture", collect_architecture),
}


# --- the loop --------------------------------------------------------------

def stage(record, label, step, message):
    print(f"[{label}][{step}] {message}")
    record.stage(step, message)


def ask(prompt_text):
    try:
        return input(prompt_text).strip()
    except EOFError:                     # piped input ran out / Ctrl+D
        return None


def adapt(record, label, finding):
    """ADAPT: the human accepts, rejects, or edits the finding; recorded."""
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
            reason = ask("Why is it rejected? (recorded): ") or None
            record.decision("rejected", reason)
            return "rejected", reason
        if choice in ("e", "edit"):
            edit = ask("Enter the corrected finding: ") or ""
            record.decision("edited", edit)
            return "edited", edit
        print("Please answer a, r, or e.")


def run_review(key, record):
    label, family, collect = MODES[key]
    record.start_mode(key, label)
    stage(record, label, "PLAN", f"Review target: {label}; prompts: prompts/{family}/")

    stage(record, label, "OBSERVE", "Collecting evidence from the repository")
    ok, evidence = collect()
    record.set(evidence=evidence)
    if not ok:
        stage(record, label, "OBSERVE", "Failed")
        record.end_mode()
        return f"OBSERVE FAILED: {evidence}"
    stage(record, label, "OBSERVE", "Complete")

    system_prompt = read_prompt(family, "implementation/system_prompt.txt")
    task_prompt = read_prompt(family, "implementation/task_prompt.txt")
    stage(record, label, "ACT", "Running implementation model")
    output, err = call_model(system_prompt, f"{task_prompt}\n\nEvidence:\n{evidence}")
    if err:
        stage(record, label, "ACT", "Failed")
        record.set(implementation_output=err)
        record.end_mode()
        return f"MODEL FAILED: {err}"
    record.set(implementation_output=output)

    review_system = read_prompt(family, "review/review_prompt.txt")
    stage(record, label, "ACT", "Running review model")
    review, review_err = call_model(
        review_system, f"Implementation finding:\n{output}\n\nEvidence:\n{evidence}", review=True)
    # unlike ACT above, a review failure is not fatal: the error text is shown
    # as the review and the human still gets to decide
    if review_err:
        review = review_err
    record.set(review_output=review)

    finding = f"{output}\n\nREVIEW MODEL: {review}"
    decision, edit = adapt(record, label, finding)
    record.end_mode()
    final = edit if decision == "edited" else finding
    return f"OBSERVE: {evidence}\n\nFINDING: {final}\n\nHUMAN DECISION: {decision}"


def main():
    load_dotenv(REPO_ROOT / ".env")      # optional file; a missing one is ignored
    reports_dir = REPO_ROOT / "reports"
    record = RunRecord(reports_dir)
    keys = list(MODES)

    print("AGENTIC LOOP - shared review workflow (Plan -> Act -> Observe -> Adapt)")
    print(f"Run record: {reports_dir}")
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
