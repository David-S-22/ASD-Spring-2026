"""Run record for the agentic loop.

Writes reports/report.json (machine-readable), report.md (human-readable)
and run-view.md (one line per reviewed mode) after every completed mode.
"""

import json
from datetime import datetime
from pathlib import Path


class RunRecord:
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.started = datetime.now().astimezone().isoformat(timespec="seconds")
        self.modes = []
        self.current = None

    def start_mode(self, key, label):
        self.current = {"mode": key, "label": label, "stages": [],
                        "evidence": None, "implementation_output": None,
                        "review_output": None, "decision": None, "decision_note": None}

    def stage(self, step, message):
        self.current["stages"].append({"stage": step, "message": message})

    def set(self, **fields):
        self.current.update(fields)

    def decision(self, decision, note):
        self.current["decision"] = decision
        self.current["decision_note"] = note

    def end_mode(self):
        self.modes.append(self.current)
        self.current = None
        self.write()

    def write(self):
        self.reports_dir.mkdir(exist_ok=True)
        report = {"started": self.started, "modes": self.modes}
        (self.reports_dir / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")

        lines = [f"# Agentic loop run - {self.started}", ""]
        for mode in self.modes:
            note = f" - {mode['decision_note']}" if mode["decision_note"] else ""
            lines += [f"## {mode['label']}", "",
                      f"- Evidence: {mode['evidence']}",
                      f"- Implementation model: {mode['implementation_output']}",
                      f"- Review model: {mode['review_output']}",
                      f"- Human decision (ADAPT): {mode['decision']}{note}", ""]
        (self.reports_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

        view = [f"Run started: {self.started}", ""]
        for mode in self.modes:
            path = " -> ".join(s["stage"] for s in mode["stages"])
            view.append(f"[{mode['label']}] {path} => {mode['decision']}")
        (self.reports_dir / "run-view.md").write_text("\n".join(view) + "\n", encoding="utf-8")
