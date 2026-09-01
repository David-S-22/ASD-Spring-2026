"""The run record: reports/report.json, report.md and run-view.md.

Written after every completed mode rather than at the end, so a run that is
interrupted still leaves usable evidence behind. Every field is read with
.get(), which means a mode that carries extra keys -- or is missing ones a
future mode adds -- still writes cleanly instead of raising mid-run.
"""

import json
from datetime import datetime
from pathlib import Path

FIELDS = ("evidence", "implementation_output", "review_output",
          "decision", "decision_note", "traceback")


class RunRecord:
    def __init__(self, reports_dir: Path):
        self.reports_dir = Path(reports_dir)
        self.started = datetime.now().astimezone().isoformat(timespec="seconds")
        self.modes = []
        self.current = None
        # Run-level, not per-mode: which endpoint answered and what it served.
        # Recorded because "localhost:11434" alone does not identify an ollama
        # instance on a machine that has more than one.
        self.environment = {}

    def set_environment(self, **fields):
        self.environment.update(fields)

    def start_mode(self, key, label):
        self.current = {"mode": key, "label": label, "stages": []}
        self.current.update({field: None for field in FIELDS})

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
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        (self.reports_dir / "report.json").write_text(
            json.dumps({"started": self.started,
                        "environment": self.environment,
                        "modes": self.modes}, indent=2),
            encoding="utf-8")

        lines = [f"# Agentic loop run - {self.started}", ""]
        if self.environment:
            lines.append("## Environment")
            lines.append("")
            for field, value in self.environment.items():
                lines.append(f"- {field.replace('_', ' ').capitalize()}: {value}")
            lines.append("")
        for mode in self.modes:
            note = f" - {mode.get('decision_note')}" if mode.get("decision_note") else ""
            lines += [f"## {mode.get('label', mode.get('mode', 'unknown'))}", "",
                      f"- Evidence: {mode.get('evidence')}",
                      f"- Implementation model: {mode.get('implementation_output')}",
                      f"- Review model: {mode.get('review_output')}",
                      f"- Human decision (ADAPT): {mode.get('decision')}{note}"]
            if mode.get("traceback"):
                lines += ["- Traceback:", "", "```", mode["traceback"].strip(), "```"]
            lines.append("")
        (self.reports_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

        view = [f"Run started: {self.started}"]
        for field, value in self.environment.items():
            view.append(f"{field.replace('_', ' ').capitalize()}: {value}")
        view.append("")
        for mode in self.modes:
            path = " -> ".join(s["stage"] for s in mode.get("stages", []))
            view.append(f"[{mode.get('label', mode.get('mode', 'unknown'))}] "
                        f"{path} => {mode.get('decision')}")
        (self.reports_dir / "run-view.md").write_text("\n".join(view) + "\n",
                                                      encoding="utf-8")
