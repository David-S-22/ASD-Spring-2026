"""DevOps pipeline evidence from .github/workflows/.

Lists the workflow files, maps each to a student, reads the jobs each one
defines, and — when the GitHub CLI is available — fetches the latest run
conclusion per workflow on main. The deviation from the spec's
student-N.yml naming is reported as a finding.
"""

import json
import shutil
import subprocess
from pathlib import Path

import yaml

# The repo names workflows per student first name instead of student-N.yml.
STUDENT_WORKFLOW_MAP = {
    "sophia-ci": "student 5 (Sophia, bills)",
    "david-ci": "student ? (David, savings)",
    "aiden-ci": "student ? (Aiden, anomalies)",
    "janelle-ci": "student ? (Janelle, transactions)",
}


def _jobs(path: Path) -> list[str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return sorted((data.get("jobs") or {}).keys())
    except Exception:
        return []


def _latest_run(repo_root: Path, workflow_file: str) -> str | None:
    if shutil.which("gh") is None:
        return None
    try:
        result = subprocess.run(
            ["gh", "run", "list", "--workflow", workflow_file, "--branch", "main",
             "--limit", "1", "--json", "conclusion,createdAt"],
            cwd=repo_root, capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return None
        runs = json.loads(result.stdout or "[]")
        if not runs:
            return "no runs on main"
        conclusion = runs[0].get("conclusion") or "in progress"
        return f"{conclusion} ({runs[0].get('createdAt', '?')})"
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def collect(app_dir: Path, repo_root: Path) -> tuple[bool, str]:
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False, ".github/workflows/ does not exist."

    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    if not files:
        return False, ".github/workflows/ contains no workflow files."

    lines = []
    spec_named = 0
    for path in files:
        stem = path.stem.lower()
        student = STUDENT_WORKFLOW_MAP.get(stem, "unmapped")
        if stem.startswith("student-"):
            spec_named += 1
        jobs = _jobs(path)
        line = f"{path.name}: student mapping {student}; jobs [{', '.join(jobs) or 'unparsed'}]"
        latest = _latest_run(repo_root, path.name)
        if latest:
            line += f"; latest run on main: {latest}"
        lines.append(line)

    findings = []
    if spec_named == 0:
        findings.append(
            "NAMING DEVIATION: no workflow follows the spec's student-N.yml convention — "
            "the team uses per-first-name files (declared in the report)."
        )
    if len(files) < 5:
        findings.append(
            f"Only {len(files)} workflow file(s) for 5 students — at least one student has no CI workflow."
        )

    return True, (
        "DevOps evidence: " + " | ".join(lines)
        + (" | " + " ".join(findings) if findings else "")
    )
