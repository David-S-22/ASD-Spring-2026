"""OBSERVE collectors for the MCP and RAG validation modes: deterministic probes, failures recorded as evidence.

Module-level imports stay stdlib + requests; fastmcp is imported inside the MCP probe, so this file imports
without it and a missing fastmcp is reported as a loop misconfiguration (ok=False), never as the server being
down. SMOKE_CALLS and RAG_BENCHMARKS are the extension point: one read-only call per tool, one question per
sources/<feature> collection, each line added by the feature's owner in their own PR.
"""
import asyncio
import json
import os
import time

import requests

HTTP_TIMEOUT = 10
DEFAULT_MCP_URL = "http://localhost:8000/mcp"
DEFAULT_RAG_URL = "http://localhost:5003"

SMOKE_CALLS = {
    "search_transactions": {"merchant": "FibreLink"},
    "retrieve_context": {"feature": "bills", "question": "Which bill is overdue?", "k": 2},
}
BOUNDARY_PROBES = (("no_such_tool", {}),)
RAG_BENCHMARKS = {
    "bills": "Which bill is overdue?",
}
OFF_TOPIC_QUESTION = "What is the capital of France?"
UNKNOWN_FEATURE = "no-such-feature"


def _shape(data):
    """Describe a tool result as 'list of N', 'N results, closest distance d', 'dict with keys …' or its type name."""
    if isinstance(data, list):
        return f"list of {len(data)}"
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        distances = [r.get("distance") for r in data["results"] if isinstance(r, dict) and isinstance(r.get("distance"), (int, float))]
        closest = f", closest distance {min(distances):.3f}" if distances else ""
        return f"{len(data['results'])} results{closest}"
    if isinstance(data, dict):
        return f"dict with keys {', '.join(sorted(data))}"
    return type(data).__name__


def _one_line(text):
    """Collapse whitespace and cap at 160 characters so every evidence value stays on one line."""
    return " ".join(str(text).split())[:160]


async def _timed_call(client, name, arguments):
    """Call one tool and return {tool, arguments, ok, detail, ms}; errors are values here, never raised."""
    started = time.perf_counter()
    try:
        outcome = await client.call_tool(name, arguments, raise_on_error=False)
        ms = round((time.perf_counter() - started) * 1000)
        if getattr(outcome, "is_error", False):
            text = outcome.content[0].text if getattr(outcome, "content", None) else "error"
            return {"tool": name, "arguments": arguments, "ok": False, "detail": _one_line(text), "ms": ms}
        return {"tool": name, "arguments": arguments, "ok": True, "detail": _shape(outcome.data), "ms": ms}
    except Exception as exc:
        ms = round((time.perf_counter() - started) * 1000)
        return {"tool": name, "arguments": arguments, "ok": False, "detail": _one_line(exc), "ms": ms}


async def _probe_mcp(url):
    """List tools, run the registered smoke calls, then the unknown-tool probe and a missing-required-argument probe."""
    from fastmcp import Client

    result = {"tools": [], "calls": [], "boundary": []}
    async with Client(url, timeout=HTTP_TIMEOUT, init_timeout=HTTP_TIMEOUT) as client:
        for tool in await client.list_tools():
            schema = getattr(tool, "input_schema", None)
            if schema is None:
                schema = getattr(tool, "inputSchema", None)
            result["tools"].append({"name": tool.name, "required": list((schema or {}).get("required") or [])})
        registered = {tool["name"] for tool in result["tools"]}
        for name, arguments in SMOKE_CALLS.items():
            if name in registered:
                result["calls"].append(await _timed_call(client, name, arguments))
        probes = list(BOUNDARY_PROBES)
        with_required = next((tool["name"] for tool in result["tools"] if tool["required"]), None)
        if with_required:
            probes.append((with_required, {}))
        for name, arguments in probes:
            result["boundary"].append(await _timed_call(client, name, arguments))
    return result


def _format_mcp(url, result):
    """Render the probe result as the one-paragraph OBSERVE evidence."""
    tools = ", ".join(f"{t['name']} (required: {', '.join(t['required']) or 'none'})" for t in result["tools"]) or "none"
    exercised = {c["tool"] for c in result["calls"]}
    calls = []
    for call in result["calls"]:
        args = json.dumps(call["arguments"])
        if call["ok"]:
            calls.append(f"{call['tool']} {args} -> ok, {call['detail']} in {call['ms']}ms")
        else:
            calls.append(f"{call['tool']} {args} -> error ({call['detail']}) in {call['ms']}ms")
    for tool in result["tools"]:
        if tool["name"] not in exercised:
            calls.append(f"{tool['name']} -> not exercised (no entry in validate.SMOKE_CALLS)")
    probes = []
    for probe in result["boundary"]:
        label = f"{probe['tool']} {json.dumps(probe['arguments'])}"
        probes.append(f"{label} -> rejected ({probe['detail']})" if not probe["ok"] else f"{label} -> NOT rejected ({probe['detail']})")
    return (
        f"MCP evidence: endpoint {url}; session ok; "
        f"{len(result['tools'])} tools registered: {tools}. "
        f"Smoke calls: {'; '.join(calls) or 'none'}. Boundary probes: {'; '.join(probes) or 'none'}."
    )


def collect_mcp(probe=None):
    """MCP validation evidence; a server that is down is UNREACHABLE evidence, a missing fastmcp is a loop failure."""
    url = os.getenv("MCP_SERVER_URL", DEFAULT_MCP_URL)
    probe = probe or (lambda target: asyncio.run(_probe_mcp(target)))
    try:
        result = probe(url)
    except ImportError as exc:
        return False, f"MCP validation needs fastmcp (pip install -r agentic_loop/requirements.txt): {_one_line(exc)}"
    except Exception as exc:
        return True, f"MCP evidence: endpoint {url} UNREACHABLE ({_one_line(exc)}). No tools listed, no calls made."
    return True, _format_mcp(url, result)


def _retrieve(post, url, feature, question):
    """POST /retrieve once and summarise the closest chunk; a failure is recorded on this probe only."""
    started = time.perf_counter()
    try:
        response = post(f"{url}/retrieve", json={"feature": feature, "question": question, "k": 3}, timeout=HTTP_TIMEOUT)
        ms = round((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            return {"status": response.status_code, "detail": "", "ms": ms, "count": 0, "closest": None, "source": None, "text": ""}
        results = [r for r in (response.json().get("results") or []) if isinstance(r, dict)]
    except Exception as exc:
        ms = round((time.perf_counter() - started) * 1000)
        return {"status": "error", "detail": _one_line(exc), "ms": ms, "count": 0, "closest": None, "source": None, "text": ""}
    top = min(results, key=lambda r: r.get("distance", float("inf"))) if results else None
    return {
        "status": 200,
        "detail": "",
        "ms": ms,
        "count": len(results),
        "closest": float(top["distance"]) if top else None,
        "source": (top.get("metadata") or {}).get("source", "?") if top else None,
        "text": " ".join((top.get("text") or "").lstrip("# ").split())[:60] if top else "",
    }


def _format_benchmark(probe):
    """Render one benchmark probe as 'feature "question" -> …' for the evidence line."""
    if probe["absent"]:
        return f"{probe['feature']}: collection absent, no benchmark run"
    if probe["status"] == "error":
        return f"{probe['feature']} \"{probe['question']}\" -> error ({probe['detail']})"
    if probe["status"] != 200:
        return f"{probe['feature']} \"{probe['question']}\" -> HTTP {probe['status']}, no results"
    if probe["closest"] is None:
        return f"{probe['feature']} \"{probe['question']}\" -> 0 results, {probe['ms']}ms"
    return (f"{probe['feature']} \"{probe['question']}\" -> {probe['count']} results, closest {probe['closest']:.3f} "
            f"from {probe['source']} (\"{probe['text']}\"), {probe['ms']}ms")


def _format_rag(url, collections, probes, off_topic, unknown):
    """Render the collections, benchmarks, off-topic and unknown-feature probes as the one-paragraph OBSERVE evidence."""
    benchmarks = "; ".join(_format_benchmark(p) for p in probes) or "none"
    extras = "; ".join(f"{name}: collection listed, no benchmark registered" for name in collections if name not in RAG_BENCHMARKS)
    if off_topic is None:
        off_text = "Off-topic probe skipped (no benchmark returned results)"
    elif off_topic["status"] == "error":
        off_text = f"Off-topic probe on {off_topic['feature']} -> error ({off_topic['detail']})"
    elif off_topic["closest"] is None:
        off_text = f"Off-topic probe on {off_topic['feature']} -> no results"
    else:
        off_text = f"Off-topic probe on {off_topic['feature']} -> closest {off_topic['closest']:.3f} (on-topic {off_topic['on_topic']:.3f})"
    if unknown["status"] == "error":
        unknown_text = f"error ({unknown['detail']})"
    elif unknown["status"] == 200:
        unknown_text = f"NOT rejected ({unknown['count']} results)"
    elif 400 <= unknown["status"] < 500:
        unknown_text = f"rejected (HTTP {unknown['status']})"
    else:
        unknown_text = f"server error (HTTP {unknown['status']}), not a clean rejection"
    return (
        f"RAG evidence: endpoint {url}; /health ok, {len(collections)} collections: {', '.join(collections) or 'none'}. "
        f"Benchmarks: {benchmarks}{'; ' + extras if extras else ''}. {off_text}. "
        f"Unknown feature {UNKNOWN_FEATURE} -> {unknown_text}."
    )


def collect_rag(get=None, post=None):
    """RAG validation evidence: collections, one benchmark per registered feature, an off-topic and an unknown-feature probe."""
    url = os.getenv("RAG_SERVER_URL", DEFAULT_RAG_URL).rstrip("/")
    get = get or requests.get
    post = post or requests.post
    try:
        collections = [str(c) for c in (get(f"{url}/health", timeout=HTTP_TIMEOUT).json().get("collections") or [])]
    except Exception as exc:
        return True, f"RAG evidence: endpoint {url} UNREACHABLE ({_one_line(exc)}). No collections listed, no retrieval made."
    probes = []
    for feature, question in RAG_BENCHMARKS.items():
        if feature not in collections:
            probes.append({"feature": feature, "question": question, "absent": True})
            continue
        probes.append({"feature": feature, "question": question, "absent": False, **_retrieve(post, url, feature, question)})
    answered = [p for p in probes if not p["absent"] and p["status"] == 200 and p["closest"] is not None]
    off_topic = None
    if answered:
        first = answered[0]
        off_topic = {"feature": first["feature"], "on_topic": first["closest"], **_retrieve(post, url, first["feature"], OFF_TOPIC_QUESTION)}
    unknown = _retrieve(post, url, UNKNOWN_FEATURE, OFF_TOPIC_QUESTION)
    return True, _format_rag(url, collections, probes, off_topic, unknown)
