"""Shared terminal agentic loop: Plan -> Act -> Observe -> Adapt.

Deliberately small: this file runs the whole loop, record.py writes the
run record the reports cite. Modes collect evidence from the repository
(architecture) or from the shared MCP and RAG servers, live and read-only
(mcp, rag). To add a review mode, add prompt files under
prompts/<your-family>/ and one entry to MODES below.
"""

import asyncio
import calendar
import json
import os
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib import error, request

import requests
import yaml
from dotenv import load_dotenv
from fastmcp import Client
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


def http_timeout():
    return float(os.getenv("LOOP_HTTP_TIMEOUT", "30"))


def parse_row_date(value):
    """Rows come back RFC 2822 ("Wed, 15 Jul 2026 00:00:00 GMT") or ISO."""
    try:
        return parsedate_to_datetime(str(value)).date()
    except (TypeError, ValueError):
        return datetime.fromisoformat(str(value)[:10]).date()


def month_window(day):
    """First and last day of the month containing `day`, as ISO strings."""
    last_day = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1).isoformat(), day.replace(day=last_day).isoformat()


# -- MCP validation ---------------------------------------------------------

def rows_from_tool_result(result):
    data = result.data if result.data is not None else result.structured_content
    if isinstance(data, dict) and isinstance(data.get("result"), list):
        data = data["result"]
    return data if isinstance(data, list) else []


async def timed_search(client, args):
    """Call search_transactions; return (rows, duration in ms)."""
    started = time.perf_counter()
    result = await client.call_tool("search_transactions", args)
    return rows_from_tool_result(result), (time.perf_counter() - started) * 1000


def filters_from_row(row):
    """Filters that should match `row`: its merchant and its calendar month."""
    start_date, end_date = month_window(parse_row_date(row.get("date")))
    return {"start_date": start_date, "end_date": end_date, "merchant": row.get("merchant")}


async def probe_mcp_server(url, impossible_merchant):
    """One session: list tools, an unfiltered call, a filtered call derived
    from the first row, and a call for a merchant that cannot exist."""
    async with Client(url, timeout=http_timeout()) as client:
        tools = await client.list_tools()
        all_rows, all_ms = await timed_search(client, {})

        seed_args, seed_rows, seed_ms = None, [], None
        if all_rows and isinstance(all_rows[0], dict):
            seed_args = filters_from_row(all_rows[0])
            seed_rows, seed_ms = await timed_search(client, seed_args)

        none_rows, _ = await timed_search(client, {"merchant": impossible_merchant})

    return {"tools": tools, "all_rows": all_rows, "all_ms": all_ms,
            "seed_args": seed_args, "seed_rows": seed_rows, "seed_ms": seed_ms,
            "none_rows": none_rows}


def describe_filtered_call(seed_args, rows, ms, total_rows, row_keys):
    """Evidence sentence for the seeded, filtered search_transactions call."""
    shape_ok = bool(rows) and all(isinstance(row, dict) and row_keys <= row.keys() for row in rows)
    merchants_ok = bool(rows) and all(row.get("merchant") == seed_args["merchant"] for row in rows)
    try:
        dates_ok = bool(rows) and all(
            seed_args["start_date"] <= parse_row_date(row.get("date")).isoformat() <= seed_args["end_date"]
            for row in rows)
    except (TypeError, ValueError):
        dates_ok = False
    sample_row = {key: rows[0].get(key) for key in sorted(row_keys)} if rows else None

    return (f"Filtered call (seeded from the first row) with arguments {seed_args} returned "
            f"{len(rows)} rows in {ms:.0f} ms. "
            f"Result is a list of rows with id, date, merchant, amount: {'PASS' if shape_ok else 'FAIL'}. "
            f"Every row has merchant '{seed_args['merchant']}': {merchants_ok}. "
            f"Every row dated within {seed_args['start_date']}..{seed_args['end_date']}: {dates_ok}. "
            f"Filtered count not above unfiltered count: {len(rows) <= total_rows}. "
            f"Sample row: {sample_row}.")


def collect_mcp():
    """MCP tool contract: search_transactions is registered, exposes the filter
    parameters, returns well-formed rows, and honours the filters both ways."""
    url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
    row_keys = {"id", "date", "merchant", "amount"}
    filter_params = ("start_date", "end_date", "merchant")
    impossible_merchant = "Quantum Llama Rentals"

    try:
        probe = asyncio.run(probe_mcp_server(url, impossible_merchant))
    except Exception as exc:
        return False, f"MCP server unreachable or tool call failed at {url}: {type(exc).__name__}"

    tool_names = [tool.name for tool in probe["tools"]]
    search_tool = None
    for tool in probe["tools"]:
        if tool.name == "search_transactions":
            search_tool = tool
    schema = (getattr(search_tool, "input_schema", None) or {}) if search_tool else {}
    schema_params = set((schema.get("properties") or {}).keys())
    missing_params = [name for name in filter_params if name not in schema_params]

    evidence = [
        f"MCP server: {url}. Registered tools: {', '.join(tool_names) or 'none'}. "
        f"search_transactions registered: {search_tool is not None}. "
        f"Filter parameters in its schema: {', '.join(sorted(schema_params)) or 'none'}; "
        f"missing: {', '.join(missing_params) or 'none'}. "
        f"Unfiltered call returned {len(probe['all_rows'])} rows in {probe['all_ms']:.0f} ms."
    ]

    if probe["seed_args"] is None:
        evidence.append("No rows available, so the filtered call was skipped: "
                        "result shape FAIL, filters honoured FAIL.")
    else:
        evidence.append(describe_filtered_call(
            probe["seed_args"], probe["seed_rows"], probe["seed_ms"],
            total_rows=len(probe["all_rows"]), row_keys=row_keys))

    none_rows = probe["none_rows"]
    evidence.append(f"Call with merchant '{impossible_merchant}' returned {len(none_rows)} rows "
                    f"(expected 0): {'FAIL' if none_rows else 'PASS'}.")

    return True, " ".join(evidence)


# -- RAG validation ---------------------------------------------------------

def post_retrieve(url, collection, question, k=3, where=None):
    """POST /retrieve; returns (results, ms) or raises with the failure text."""
    body = {"feature": collection, "question": question, "k": k}
    if where:
        body["where"] = where
    started = time.perf_counter()
    response = requests.post(f"{url}/retrieve", json=body, timeout=http_timeout())
    ms = (time.perf_counter() - started) * 1000
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code} in {ms:.0f} ms")
    results = (response.json() or {}).get("results") or []
    return results, ms


def seed_merchant_from_corpus(url, records_collection):
    """Merchant of the best transaction chunk for a generic query, used as the
    seeded question; None when the collection holds no transaction chunks."""
    results, _ = post_retrieve(url, records_collection, "transaction", k=1,
                               where={"kind": "transaction"})
    if not results:
        return None
    return (results[0].get("metadata") or {}).get("merchant") or None


def describe_retrieve(url, label, collection, question, threshold, expect_merchant=None):
    try:
        results, ms = post_retrieve(url, collection, question)
    except requests.RequestException as exc:
        return f"[{collection}/{label}] retrieve failed: {type(exc).__name__}."
    except RuntimeError as exc:
        return f"[{collection}/{label}] retrieve failed: {exc}."
    if not results:
        return f"[{collection}/{label}] 0 results in {ms:.0f} ms."

    best_chunk = min(results, key=lambda chunk: chunk.get("distance", float("inf")))
    distance = best_chunk.get("distance")
    metadata = best_chunk.get("metadata") or {}
    under_threshold = distance is not None and distance <= threshold

    parts = [f"[{collection}/{label}] {len(results)} results",
             f"best distance {distance:.3f}",
             f"under_threshold: {under_threshold}",
             f"doc_type: {metadata.get('doc_type')}",
             f"kind: {metadata.get('kind')}",
             f"category_id: {metadata.get('category_id')}"]
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
        health = requests.get(f"{url}/health", timeout=http_timeout()).json()
    except Exception as exc:
        return False, f"RAG server unreachable at {url}: {type(exc).__name__}"
    collections = health.get("collections") or []
    evidence = [
        f"RAG server: {url}. Insufficient threshold (distance above): {threshold}. "
        f"Collections: {', '.join(collections) or 'none'}. "
        f"{guide} present: {guide in collections}. "
        f"{records} present: {records in collections}."
    ]

    try:
        seed_merchant = seed_merchant_from_corpus(url, records)
    except (requests.RequestException, RuntimeError) as exc:
        seed_merchant = None
        evidence.append(f"Seed lookup on {records} failed: {exc}.")
    if seed_merchant:
        evidence.append(f"Question (seeded from the corpus): '{seed_merchant}'.")
        evidence.append(describe_retrieve(url, "seeded", records, seed_merchant, threshold,
                                          expect_merchant=seed_merchant))
        evidence.append(describe_retrieve(url, "seeded", guide, seed_merchant, threshold))
    else:
        evidence.append(f"No transaction chunk found in {records}; seeded question skipped.")

    evidence.append(f"Question (unrelated, fixed): '{unrelated_question}'.")
    evidence.append(describe_retrieve(url, "unrelated", records, unrelated_question, threshold))
    evidence.append(describe_retrieve(url, "unrelated", guide, unrelated_question, threshold))

    return True, " ".join(evidence)


def _json_request(method: str, url: str, payload: dict | None = None, timeout: float = 20.0):
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{url} returned HTTP {exc.code}. {details[:300]}"
    except error.URLError as exc:
        return False, f"{url} could not be reached. {exc.reason}"
    except TimeoutError:
        return False, f"{url} timed out."
    except OSError as exc:
        return False, f"{url} failed. {exc}"
    try:
        return True, json.loads(raw)
    except json.JSONDecodeError:
        snippet = raw.strip().replace("\n", " ")
        return False, f"{url} returned non-JSON output: {snippet[:300]}"


def _budgets_backend_url() -> str:
    return os.getenv("BUDGETS_BACKEND_URL", "http://127.0.0.1:5006").rstrip("/")


def _budgets_rag_url() -> str:
    return os.getenv("BUDGETS_RAG_URL", "http://127.0.0.1:5003").rstrip("/")


def _selected_budget(base_url: str):
    ok, budgets = _json_request("GET", f"{base_url}/api/budgets")
    if not ok:
        return False, budgets
    if not isinstance(budgets, list) or not budgets:
        return False, "No budgets were returned from the Budgets backend."
    requested_id = os.getenv("BUDGETS_VALIDATION_BUDGET_ID")
    if requested_id:
        try:
            selected_id = int(requested_id)
        except ValueError:
            return False, "BUDGETS_VALIDATION_BUDGET_ID must be an integer when set."
        for budget in budgets:
            if isinstance(budget, dict) and budget.get("id") == selected_id:
                return True, budget
        return False, f"Budget id {selected_id} was not found in /api/budgets."
    candidates = [
        budget
        for budget in budgets
        if isinstance(budget, dict)
        and isinstance(budget.get("id"), int)
        and isinstance(budget.get("month"), str)
    ]
    if candidates:
        current_month = datetime.now().astimezone().strftime("%Y-%m")
        current_budget = next((budget for budget in candidates if budget["month"] == current_month), None)
        if current_budget is not None:
            return True, current_budget
        return True, max(candidates, key=lambda budget: budget["month"])
    for budget in budgets:
        if isinstance(budget, dict) and isinstance(budget.get("id"), int):
            return True, budget
    return False, "No budget with an integer id was returned from the Budgets backend."


def _preview_lines(tool_result: dict | None) -> str:
    if not isinstance(tool_result, dict):
        return "none"
    preview = tool_result.get("result_preview")
    if not isinstance(preview, list) or not preview:
        return "none"
    items = []
    for row in preview[:3]:
        if not isinstance(row, dict):
            continue
        date = row.get("date") or "unknown-date"
        merchant = row.get("merchant") or row.get("description") or "unknown-merchant"
        amount = row.get("amount")
        amount_text = str(amount) if amount is not None else "unknown-amount"
        items.append(f"{date} {merchant} ({amount_text})")
    return "; ".join(items) if items else "none"


def collect_budgets_mcp():
    base_url = _budgets_backend_url()
    ok, health = _json_request("GET", f"{base_url}/health")
    if not ok:
        return False, health
    ok, budget = _selected_budget(base_url)
    if not ok:
        return False, budget
    ok, summary = _json_request("GET", f"{base_url}/api/budgets/{budget['id']}/summary")
    if not ok:
        return False, summary
    ok, chat = _json_request(
        "POST",
        f"{base_url}/api/chat",
        {
            "budget_id": budget["id"],
            "integration_mode": "mcp",
            "message": "Show me the most relevant transactions for this month's budget pressure.",
        },
    )
    if not ok:
        return False, chat
    if not isinstance(chat, dict):
        return False, "The Budgets MCP chat validation returned an invalid payload."
    tool_result = chat.get("tool_result") if isinstance(chat.get("tool_result"), dict) else {}
    totals = summary.get("totals") if isinstance(summary, dict) and isinstance(summary.get("totals"), dict) else {}
    return True, (
        f"Budgets backend: {base_url}. "
        f"Health ok={health.get('ok')} db_api={health.get('db_api')} transactions_api={health.get('transactions_api')} "
        f"mcp_mode={health.get('mcp_mode')} rag_mode={health.get('rag_mode')}. "
        f"Budget id={budget.get('id')} month={budget.get('month')} "
        f"projected_high_total={totals.get('projected_high_total')} remaining_income_high={totals.get('remaining_income_high')}. "
        f"MCP chat response_source={chat.get('response_source')} mode={chat.get('mode')} fallback={chat.get('fallback')} "
        f"tool_name={tool_result.get('tool_name')} count={tool_result.get('count')} "
        f"reply={json.dumps(chat.get('reply', ''))}. "
        f"Preview={_preview_lines(tool_result)}."
    )


def collect_budgets_rag():
    base_url = _budgets_backend_url()
    ok, health = _json_request("GET", f"{base_url}/health")
    if not ok:
        return False, health
    ok, budget = _selected_budget(base_url)
    if not ok:
        return False, budget
    ok, rag_health = _json_request("GET", f"{_budgets_rag_url()}/health")
    if not ok:
        return False, rag_health
    ok, chat = _json_request(
        "POST",
        f"{base_url}/api/chat",
        {
            "budget_id": budget["id"],
            "integration_mode": "rag",
            "message": "Using grounded budget guidance with sources, what should I focus on this month?",
        },
    )
    if not ok:
        return False, chat
    if not isinstance(chat, dict):
        return False, "The Budgets RAG chat validation returned an invalid payload."
    grounding = chat.get("grounding") if isinstance(chat.get("grounding"), dict) else {}
    citations = grounding.get("citations") if isinstance(grounding.get("citations"), list) else []
    citation_labels = [
        str(citation.get("label") or citation.get("source"))
        for citation in citations[:3]
        if isinstance(citation, dict)
    ]
    return True, (
        f"Budgets backend: {base_url}. "
        f"Health ok={health.get('ok')} db_api={health.get('db_api')} transactions_api={health.get('transactions_api')} "
        f"mcp_mode={health.get('mcp_mode')} rag_mode={health.get('rag_mode')}. "
        f"Budget id={budget.get('id')} month={budget.get('month')}. "
        f"RAG health collections={json.dumps(rag_health.get('collections'))}. "
        f"RAG chat response_source={chat.get('response_source')} mode={chat.get('mode')} fallback={chat.get('fallback')} "
        f"confidence={grounding.get('confidence')} insufficient_context={grounding.get('insufficient_context')} "
        f"citations={json.dumps(citation_labels)} reply={json.dumps(chat.get('reply', ''))}."
    )


MODES = {
    "architecture": ("Architecture", "architecture", collect_architecture),
    "mcp": ("MCP validation", "mcp", collect_mcp),
    "rag": ("RAG validation", "rag", collect_rag),
    "budgets-mcp": ("Budgets MCP validation", "budgets_mcp", collect_budgets_mcp),
    "budgets-rag": ("Budgets RAG validation", "budgets_rag", collect_budgets_rag),
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
