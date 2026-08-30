"""Live endpoint evidence.

Backends are discovered from docker-compose.yml (every *-backend service)
and probed over HTTP: the health route on each, plus the documented GET
/api/* and /ui/* routes for the bills backend (docs/release-0/sophia/api.md).
The status-plus-latency format doubles as the NFR timing evidence the
report asks for. Only GET routes are swept — the loop must never write.
"""

from pathlib import Path

import requests

from .compose import load_compose, services_with_suffix

# Documented read-only routes for the bills backend, from
# docs/release-0/sophia/api.md. Other students can add their own entries.
DOCUMENTED_GET_ROUTES = {
    "bills-backend": [
        "/api/bills",
        "/api/timeline?days=60",
        "/api/upcoming?days=60",
        "/api/calendar/2026-09",
        "/api/disputes",
        "/api/chat/history",
        "/ui/bills",
        "/ui/calendar",
        "/ui/timeline?days=60",
        "/ui/disputes",
        "/ui/chat",
    ],
}


def _probe(base_url: str, path: str) -> str:
    url = f"{base_url}{path}"
    try:
        response = requests.get(url, timeout=5)
        elapsed_ms = int(response.elapsed.total_seconds() * 1000)
        return f"GET {path} returned {response.status_code} in {elapsed_ms}ms"
    except requests.exceptions.ConnectionError:
        return f"GET {path} [CONNECTION REFUSED - service not running]"
    except requests.exceptions.Timeout:
        return f"GET {path} [TIMEOUT]"
    except Exception as exc:
        return f"GET {path} [ERROR: {type(exc).__name__}]"


def collect(app_dir: Path, repo_root: Path) -> tuple[bool, str]:
    compose = load_compose(repo_root)
    if compose is None:
        return False, "docker-compose.yml not found at the repo root."

    backends = services_with_suffix(compose, "-backend")
    if not backends:
        return False, "No *-backend services defined in docker-compose.yml."

    parts = []
    for name in sorted(backends):
        port = backends[name]
        if port is None:
            parts.append(f"{name}: no published host port in compose — cannot probe")
            continue
        base = f"http://localhost:{port}"
        parts.append(f"{name} (:{port}): " + _probe(base, "/health"))
        for route in DOCUMENTED_GET_ROUTES.get(name, []):
            parts.append(f"{name}: " + _probe(base, route))

    return True, "Live endpoint evidence: " + "; ".join(parts) + "."
