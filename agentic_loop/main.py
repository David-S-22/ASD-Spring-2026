"""Shared terminal agentic loop: Plan -> Act -> Observe -> Adapt.

Deliberately small: this file runs the whole loop, record.py writes the
run record the reports cite. Modes collect evidence from the repository
(architecture) or from the shared MCP and RAG servers, live and read-only
(mcp, rag). To add a review mode, add prompt files under
prompts/<your-family>/ and one entry to MODES below.
"""

import asyncio
import calendar
import os
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
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


def _timeout():
    return float(os.getenv("LOOP_HTTP_TIMEOUT", "30"))


def _parse_date(value):
    """Rows come back RFC 2822 ("Wed, 15 Jul 2026 00:00:00 GMT") or ISO."""
    try:
        return parsedate_to_datetime(str(value)).date()
    except (TypeError, ValueError):
        return datetime.fromisoformat(str(value)[:10]).date()


def _month_window(day):
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1).isoformat(), day.replace(day=last).isoformat()


def _tool_rows(result):
    data = result.data if result.data is not None else result.structured_content
    if isinstance(data, dict) and isinstance(data.get("result"), list):
        data = data["result"]              # fastmcp wraps a bare list result
    return data if isinstance(data, list) else []


def _mcp_probe(url, unrelated_merchant):
    """One session: list tools, an unfiltered call, a filtered call derived
    from the first row, and a call for a merchant that cannot exist."""
    from fastmcp import Client

    async def timed(client, args):
        started = time.perf_counter()
        result = await client.call_tool("search_transactions", args)
        return _tool_rows(result), (time.perf_counter() - started) * 1000

    async def probe():
        async with Client(url, timeout=_timeout()) as client:
            tools = await client.list_tools()
            all_rows, all_ms = await timed(client, {})
            args, rows, ms = None, [], None
            if all_rows and isinstance(all_rows[0], dict):
                seed = all_rows[0]
                start, end = _month_window(_parse_date(seed.get("date")))
                args = {"start_date": start, "end_date": end, "merchant": seed.get("merchant")}
                rows, ms = await timed(client, args)
            none_rows, _ = await timed(client, {"merchant": unrelated_merchant})
            return tools, (all_rows, all_ms), (args, rows, ms), none_rows

    return asyncio.run(probe())


def collect_mcp():
    """MCP tool contract: search_transactions is registered, exposes the filter
    parameters, returns well-formed rows, and honours the filters both ways."""
    url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
    row_keys = {"id", "date", "merchant", "amount"}
    filter_params = ("start_date", "end_date", "merchant")
    unrelated_merchant = "Quantum Llama Rentals"      # negative control: expects 0 rows
    try:
        tools, (all_rows, all_ms), (args, rows, ms), none_rows = _mcp_probe(url, unrelated_merchant)
    except Exception as exc:
        return False, f"MCP server unreachable or tool call failed at {url}: {type(exc).__name__}"
    names = [t.name for t in tools]
    tool = next((t for t in tools if t.name == "search_transactions"), None)
    schema = (getattr(tool, "input_schema", None) or {}) if tool else {}
    params = set((schema.get("properties") or {}).keys())
    missing = [name for name in filter_params if name not in params]

    lines = [f"MCP server: {url}. Registered tools: {', '.join(names) or 'none'}. "
             f"search_transactions registered: {tool is not None}. "
             f"Filter parameters in its schema: {', '.join(sorted(params)) or 'none'}; "
             f"missing: {', '.join(missing) or 'none'}. "
             f"Unfiltered call returned {len(all_rows)} rows in {all_ms:.0f} ms."]
    if args is None:
        lines.append("No rows available, so the filtered call was skipped: "
                     "result shape FAIL, filters honoured FAIL.")
    else:
        valid = bool(rows) and all(isinstance(r, dict) and row_keys <= r.keys() for r in rows)
        merchants_ok = bool(rows) and all(r.get("merchant") == args["merchant"] for r in rows)
        try:
            dates_ok = bool(rows) and all(
                args["start_date"] <= _parse_date(r.get("date")).isoformat() <= args["end_date"]
                for r in rows)
        except (TypeError, ValueError):
            dates_ok = False
        sample = {k: rows[0].get(k) for k in sorted(row_keys)} if rows else None
        lines.append(
            f"Filtered call (seeded from the first row) with arguments {args} returned "
            f"{len(rows)} rows in {ms:.0f} ms. "
            f"Result is a list of rows with id, date, merchant, amount: {'PASS' if valid else 'FAIL'}. "
            f"Every row has merchant '{args['merchant']}': {merchants_ok}. "
            f"Every row dated within {args['start_date']}..{args['end_date']}: {dates_ok}. "
            f"Filtered count not above unfiltered count: {len(rows) <= len(all_rows)}. "
            f"Sample row: {sample}.")
    lines.append(f"Call with merchant '{unrelated_merchant}' returned {len(none_rows)} rows "
                 f"(expected 0): {'PASS' if not none_rows else 'FAIL'}.")
    return True, " ".join(lines)


def _retrieve(url, feature, question, k=3, where=None):
    """POST /retrieve; returns (results, ms) or raises with the failure text."""
    body = {"feature": feature, "question": question, "k": k}
    if where:
        body["where"] = where
    started = time.perf_counter()
    response = requests.post(f"{url}/retrieve", json=body, timeout=_timeout())
    ms = (time.perf_counter() - started) * 1000
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code} in {ms:.0f} ms")
    return ((response.json() or {}).get("results") or []), ms


def _seed_record(url, records):
    """Best chunk for a generic query, restricted to transaction rows; returns
    (question, merchant) or (None, None) when the collection has nothing."""
    results, _ = _retrieve(url, records, "transaction", k=1, where={"kind": "transaction"})
    if not results:
        return None, None
    best = results[0]
    merchant = (best.get("metadata") or {}).get("merchant") or ""
    described = re.search(r"for '([^']*)'", best.get("text") or "")
    description = described.group(1) if described else ""
    question = " ".join(part for part in (merchant, description) if part).strip()
    return (question or None), merchant


def _retrieve_line(url, label, feature, question, threshold, expect_merchant=None):
    try:
        results, ms = _retrieve(url, feature, question)
    except requests.RequestException as exc:
        return f"[{feature}/{label}] retrieve failed: {type(exc).__name__}."
    except RuntimeError as exc:
        return f"[{feature}/{label}] retrieve failed: {exc}."
    if not results:
        return f"[{feature}/{label}] 0 results in {ms:.0f} ms."
    best = min(results, key=lambda r: r.get("distance", float("inf")))
    distance = best.get("distance")
    metadata = best.get("metadata") or {}
    under = distance is not None and distance <= threshold
    parts = [f"[{feature}/{label}] {len(results)} results", f"best distance {distance:.3f}",
             f"under_threshold: {under}", f"doc_type: {metadata.get('doc_type')}",
             f"kind: {metadata.get('kind')}", f"category_id: {metadata.get('category_id')}"]
    if expect_merchant:
        parts.append(f"best chunk merchant '{metadata.get('merchant')}' matches seed: "
                     f"{metadata.get('merchant') == expect_merchant}")
    parts.append(f"{ms:.0f} ms")
    return "; ".join(parts) + "."


def collect_rag():
    """RAG corpus contract: collections present, a seeded question grounds on
    its own record, an unanswerable one is insufficient, the guide is markdown."""
    url = os.getenv("RAG_SERVER_URL", "http://localhost:5003").rstrip("/")
    threshold = float(os.getenv("RAG_INSUFFICIENT_ABOVE", "1.2"))
    records, guide = "transactions-records", "transactions"
    unrelated_question = "Quantum Llama Rentals equipment hire"   # negative control: expects insufficient
    try:
        health = requests.get(f"{url}/health", timeout=_timeout()).json()
    except Exception as exc:
        return False, f"RAG server unreachable at {url}: {type(exc).__name__}"
    collections = health.get("collections") or []
    lines = [f"RAG server: {url}. Insufficient threshold (distance above): {threshold}. "
             f"Collections: {', '.join(collections) or 'none'}. "
             f"{guide} present: {guide in collections}. "
             f"{records} present: {records in collections}."]

    try:
        seeded_question, seed_merchant = _seed_record(url, records)
    except (requests.RequestException, RuntimeError) as exc:
        seeded_question, seed_merchant = None, None
        lines.append(f"Seed lookup on {records} failed: {exc}.")
    if seeded_question:
        lines.append(f"Question (seeded from the corpus, merchant '{seed_merchant}'): "
                     f"'{seeded_question}'.")
        lines.append(_retrieve_line(url, "seeded", records, seeded_question, threshold,
                                    expect_merchant=seed_merchant))
        lines.append(_retrieve_line(url, "seeded", guide, seeded_question, threshold))
    else:
        lines.append(f"No transaction chunk found in {records}; seeded question skipped.")
    lines.append(f"Question (unrelated, fixed): '{unrelated_question}'.")
    for feature in (records, guide):
        lines.append(_retrieve_line(url, "unrelated", feature, unrelated_question, threshold))
    return True, " ".join(lines)


MODES = {
    "architecture": ("Architecture", "architecture", collect_architecture),
    "mcp": ("MCP validation", "mcp", collect_mcp),
    "rag": ("RAG validation", "rag", collect_rag),
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

    stage(record, label, "OBSERVE", "Collecting evidence")
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
    print(f"Run record: {reports_dir.relative_to(REPO_ROOT).as_posix()}")
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
