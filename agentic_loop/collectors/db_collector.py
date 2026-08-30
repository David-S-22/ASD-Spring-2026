"""Database evidence over HTTP.

The team rule forbids reaching into another feature's SQLite file, so this
collector talks to each student's database API instead: every compose
service named *-db gets its health route and its list route probed, and the
row count is checked against the spec's minimum of ten seeded rows per
table. An unreachable service is recorded as evidence, not treated as an
error.
"""

from pathlib import Path

import requests

from .compose import load_compose, services_with_suffix

EXPECTED_DB_SERVICES = 5  # one per student
MIN_SEED_ROWS = 10


def _get_json(url: str):
    try:
        response = requests.get(url, timeout=3)
        return response.status_code, response.json()
    except requests.exceptions.RequestException:
        return None, None
    except ValueError:
        return response.status_code, None


def _row_count(payload) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return len(value)
    return None


def collect(app_dir: Path, repo_root: Path) -> tuple[bool, str]:
    compose = load_compose(repo_root)
    if compose is None:
        return False, "docker-compose.yml not found at the repo root."

    db_services = services_with_suffix(compose, "-db")
    if not db_services:
        return False, "No *-db services defined in docker-compose.yml."

    lines = [
        f"Compose defines {len(db_services)} database service(s) "
        f"(spec expects {EXPECTED_DB_SERVICES}, one per student): "
        + ", ".join(sorted(db_services)) + "."
    ]

    for name in sorted(db_services):
        port = db_services[name]
        if port is None:
            lines.append(f"{name}: no published host port in compose — cannot probe.")
            continue
        base = f"http://localhost:{port}"
        feature = name.removesuffix("-db")

        health_status, _ = _get_json(f"{base}/health")
        if health_status is None:
            lines.append(f"{name} (:{port}): UNREACHABLE — service not running or no /health route.")
            continue

        list_status, payload = _get_json(f"{base}/{feature}")
        if list_status is None or list_status >= 400:
            lines.append(
                f"{name} (:{port}): health {health_status}; list route /{feature} "
                f"{'unreachable' if list_status is None else list_status} — row count unknown."
            )
            continue

        count = _row_count(payload)
        if count is None:
            lines.append(f"{name} (:{port}): health {health_status}; /{feature} returned non-list JSON — row count unknown.")
        else:
            meets = "meets" if count >= MIN_SEED_ROWS else "BELOW"
            lines.append(
                f"{name} (:{port}): health {health_status}; /{feature} has {count} rows "
                f"({meets} the {MIN_SEED_ROWS}-row seed minimum)."
            )

    return True, "Database evidence: " + " ".join(lines)
