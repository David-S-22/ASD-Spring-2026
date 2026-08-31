"""Run recorder — the Agentic Loop Workflow Record.

Every run writes reports/report.json, reports/report.md and
reports/run-view.md, capturing per mode: the stage transitions, the
evidence collected, the prompt families and filenames used (not the full
text), the model names, the model output, and the human decision from the
ADAPT stage. This is the review record the Release 0 report requires.
"""

import json
from datetime import datetime
from pathlib import Path


class RunRecorder:
    def __init__(self, repo_root: Path):
        self.reports_dir = repo_root / "reports"
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.modes: list[dict] = []
        self._current: dict | None = None

    def start_mode(self, key: str, label: str) -> None:
        self._current = {
            "mode": key,
            "label": label,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "stages": [],
            "prompts": [],
            "models": {},
            "evidence": None,
            "implementation_output": None,
            "review_output": None,
            "human_decision": None,
        }

    def stage(self, step: str, message: str) -> None:
        if self._current is not None:
            self._current["stages"].append(
                {"at": datetime.now().isoformat(timespec="seconds"), "stage": step, "message": message}
            )

    def prompt_used(self, family: str, filename: str) -> None:
        if self._current is not None:
            self._current["prompts"].append({"family": family, "file": filename})

    def set(self, **fields) -> None:
        if self._current is not None:
            self._current.update(fields)

    def human_decision(self, decision: str, edit: str | None) -> None:
        if self._current is not None:
            self._current["human_decision"] = {
                "at": datetime.now().isoformat(timespec="seconds"),
                "decision": decision,
                "edit": edit,
            }

    def end_mode(self) -> None:
        if self._current is not None:
            self._current["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self.modes.append(self._current)
            self._current = None
        self.write()

    # ---- output ----

    def write(self) -> None:
        self.reports_dir.mkdir(exist_ok=True)
        record = {"run_started_at": self.started_at, "modes": self.modes}
        (self.reports_dir / "report.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        (self.reports_dir / "report.md").write_text(self._report_md(), encoding="utf-8")
        (self.reports_dir / "run-view.md").write_text(self._run_view_md(), encoding="utf-8")

    def _report_md(self) -> str:
        lines = [
            "# Agentic loop run record",
            "",
            f"Run started: {self.started_at}",
            "",
        ]
        for mode in self.modes:
            lines += [f"## {mode['label']} ({mode['started_at']} → {mode.get('finished_at', '?')})", ""]
            models = mode.get("models") or {}
            if models:
                lines.append("Models: " + ", ".join(f"{role}={name}" for role, name in models.items()))
            prompts = mode.get("prompts") or []
            if prompts:
                lines.append("Prompts: " + ", ".join(f"{p['family']}/{p['file']}" for p in prompts))
            lines += ["", "### Evidence (OBSERVE)", "", str(mode.get("evidence")), ""]
            if mode.get("implementation_output") is not None:
                lines += ["### Model finding (ACT)", "", str(mode["implementation_output"]), ""]
            if mode.get("review_output") is not None:
                lines += ["### Review model verdict", "", str(mode["review_output"]), ""]
            decision = mode.get("human_decision")
            if decision:
                lines += [f"### Human decision (ADAPT): {decision['decision']}", ""]
                if decision.get("edit"):
                    lines += ["Edited finding:", "", decision["edit"], ""]
        return "\n".join(lines) + "\n"

    def _run_view_md(self) -> str:
        lines = ["# Run view — stage transitions", "", f"Run started: {self.started_at}", ""]
        for mode in self.modes:
            lines.append(f"## {mode['label']}")
            for stage in mode["stages"]:
                lines.append(f"- `{stage['at']}` **{stage['stage']}** — {stage['message']}")
            decision = mode.get("human_decision")
            if decision:
                lines.append(f"- `{decision['at']}` **ADAPT** — human decision: {decision['decision']}")
            lines.append("")
        return "\n".join(lines) + "\n"
