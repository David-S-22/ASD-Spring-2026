"""Run the Ask Tally regression corpus against a live bills-backend and write a report.

    python -m sophia.eval.chat_sweep                      # http://localhost:5005, 1 run per query
    python -m sophia.eval.chat_sweep --runs 3 --base http://localhost:3000/bills-backend

Each query is posted to /api/chat; the response's route, reply and proposal are scored against
sophia/eval/chat_queries.yaml. The report (markdown + JSON) lands in docs/release-2/sophia/chat-eval/.
Approve nothing: proposals stay pending, so reseed bills-db after a sweep.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(os.environ.get("CHAT_QUERIES", REPO_ROOT / "sophia" / "eval" / "chat_queries.yaml"))
REPORTS = REPO_ROOT / "docs" / "release-2" / "sophia" / "chat-eval"


def score(entry, payload):
    """Return the list of failed expectations for one response; empty means pass."""
    failures = []
    expect = entry.get("expect") or {}
    if payload.get("route") != entry["route"]:
        failures.append(f"route {payload.get('route')} != {entry['route']}")
    reply = payload.get("reply") or ""
    failures += [f"missing {text!r}" for text in expect.get("contains", []) if text not in reply]
    failures += [f"unwanted {text!r}" for text in expect.get("not", []) if text in reply]
    if "insufficient" in expect and (payload.get("grounded") or {}).get("insufficient") is not expect["insufficient"]:
        failures.append("insufficient flag")
    if "title" in expect and expect["title"] not in (payload.get("suggestion_title") or ""):
        failures.append(f"title {payload.get('suggestion_title')!r} != {expect['title']!r}")
    return failures


def run(base, runs, timeout):
    corpus = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    results = []
    for entry in corpus:
        for attempt in range(1, runs + 1):
            started = time.perf_counter()
            try:
                response = requests.post(f"{base}/api/chat", json={"message": entry["message"]}, timeout=timeout)
                payload = response.json()
                status = response.status_code
            except Exception as error:
                payload, status = {"reply": f"{type(error).__name__}"}, 0
            seconds = round(time.perf_counter() - started, 1)
            failures = score(entry, payload) if status == 200 else [f"http {status}"]
            results.append({"message": entry["message"], "attempt": attempt, "status": status, "seconds": seconds, "route": payload.get("route"),
                            "reply": (payload.get("reply") or "")[:300], "suggestion_title": payload.get("suggestion_title"), "failures": failures})
            mark = "PASS" if not failures else "FAIL"
            print(f"[{mark}] {seconds:5.1f}s {entry['message'][:60]!r} -> {payload.get('route')}" + (f"  {failures}" if failures else ""), flush=True)
    return results


def write_report(results, base, runs):
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (REPORTS / f"sweep-{stamp}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    by_message = {}
    for r in results:
        by_message.setdefault(r["message"], []).append(r)
    lines = [f"# Ask Tally live sweep {stamp}", "", f"Base `{base}`, {runs} run(s) per query, {len(by_message)} queries.", "", "| Query | Pass | Route(s) | Seconds | Failures |", "|---|---|---|---|---|"]
    for message, rows in by_message.items():
        passes = sum(1 for r in rows if not r["failures"])
        routes = ", ".join(sorted({str(r["route"]) for r in rows}))
        secs = "/".join(str(r["seconds"]) for r in rows)
        fails = "; ".join(sorted({f for r in rows for f in r["failures"]})) or ""
        lines.append(f"| {message} | {passes}/{len(rows)} | {routes} | {secs} | {fails} |")
    total = sum(1 for r in results if not r["failures"])
    lines += ["", f"**{total}/{len(results)} passed.**"]
    path = REPORTS / f"sweep-{stamp}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, total, len(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Ask Tally regression corpus against a live backend.")
    parser.add_argument("--base", default="http://localhost:5005")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    results = run(args.base.rstrip("/"), args.runs, args.timeout)
    path, passed, total = write_report(results, args.base, args.runs)
    print(f"\n{passed}/{total} passed; report {path.relative_to(REPO_ROOT)}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
