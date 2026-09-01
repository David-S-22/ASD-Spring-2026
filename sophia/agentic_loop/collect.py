"""Evidence collection for the four review modes (the OBSERVE stage).

Every function here is deterministic given the repository and whatever is
running: it reads docker-compose.yml, walks the repo, or makes read-only HTTP
calls. Nothing writes, and nothing calls a model -- that keeps this module
testable without a network or a container, which is why the tests import it
directly.

Ports are parsed from docker-compose.yml at run time rather than hardcoded,
so the loop keeps working when the team moves a port.
"""

import json
import shutil
import subprocess
from pathlib import Path

import requests
import yaml

MIN_SEED_ROWS = 10          # spec's seeded-rows minimum, per table
EXPECTED_DB_SERVICES = 5    # one database service per student
HTTP_TIMEOUT = 5

# Bills GET routes, taken from the route decorators in sophia/backend/routes/.
# Only parameterless reads: the loop must never write, and must not invent ids.
# /ui/modal and /ui/toast are deliberately absent -- they are generic helpers
# that render nothing meaningful without query parameters.
BILLS_GET_ROUTES = [
    "/api/bills",
    "/api/timeline?days=60",
    "/api/upcoming?days=60",
    "/api/calendar/2026-09",
    "/api/calendar?from=2026-09&months=6",
    "/api/disputes",
    "/api/chat/history",
    "/ui/bills",
    "/ui/calendar",
    "/ui/timeline?days=60",
    "/ui/disputes",
    "/ui/disputes-tab",
    "/ui/chat",
]


# --- docker-compose.yml ----------------------------------------------------

def load_compose(repo_root: Path):
    """Parsed docker-compose.yml, or None when the file is not there."""
    path = repo_root / "docker-compose.yml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def host_port(entry):
    """The published host port from one compose `ports:` entry, or None.

    Handles the three forms the file actually uses or could use:
      "3005:80"            -> 3005
      {"published": 3005}  -> 3005
      "127.0.0.1:3005:80"  -> 3005   (ip:host:container)
    A bare "80" publishes a random host port, so there is nothing to probe.
    """
    if isinstance(entry, dict):
        published = entry.get("published")
        return int(published) if published is not None else None
    parts = str(entry).split(":")
    candidate = parts[1] if len(parts) == 3 else (parts[0] if len(parts) == 2 else None)
    return int(candidate) if candidate is not None and candidate.isdigit() else None


def service_ports(compose):
    """{service name: first published host port or None} for every service."""
    ports = {}
    for name, spec in (compose.get("services") or {}).items():
        found = None
        for entry in (spec or {}).get("ports") or []:
            found = host_port(entry)
            if found is not None:
                break
        ports[name] = found
    return ports


def services_with_suffix(compose, suffix):
    return {name: port for name, port in service_ports(compose).items()
            if name.endswith(suffix)}


def dependency_edges(compose):
    edges = []
    for name, spec in (compose.get("services") or {}).items():
        deps = (spec or {}).get("depends_on") or []
        for dep in (deps.keys() if isinstance(deps, dict) else deps):
            edges.append(f"{name}->{dep}")
    return sorted(edges)


def student_dirs(repo_root: Path):
    """Root directories that look like a student's feature folder.

    A student directory is any root directory containing backend/. `shared`
    also has one (shared/backend/dto.py), so it is excluded by name.
    """
    return sorted(p.name for p in repo_root.iterdir()
                  if p.is_dir() and p.name != "shared" and (p / "backend").is_dir())


# --- HTTP helpers ----------------------------------------------------------

def _get(url):
    """(status, payload, latency_ms). status is None when unreachable."""
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException:
        return None, None, None
    latency_ms = int(response.elapsed.total_seconds() * 1000)
    try:
        return response.status_code, response.json(), latency_ms
    except ValueError:
        return response.status_code, None, latency_ms


def _row_count(payload):
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return len(value)
    return None


# --- the four modes --------------------------------------------------------

def collect_architecture(repo_root: Path):
    """Compose topology and repo layout. Reads files; nothing need be running."""
    compose = load_compose(repo_root)
    if compose is None:
        return False, "docker-compose.yml not found at the repository root."

    ports = service_ports(compose)
    inventory = ", ".join(f"{name}:{port}" if port else name
                          for name, port in sorted(ports.items()))
    edges = dependency_edges(compose)
    students = student_dirs(repo_root)
    required = [".github/workflows", "docs", "shared", "ai-services", "scripts"]
    missing = [d for d in required if not (repo_root / d).is_dir()]
    shared_index = (repo_root / "shared" / "frontend" / "public" / "index.html").exists()

    return True, (
        f"Compose defines {len(ports)} services (host port): {inventory}. "
        f"Dependency edges: {', '.join(edges) or 'none'}. "
        f"Student directories: {', '.join(students) or 'none'}. "
        f"Missing required directories: {', '.join(missing) or 'none'}. "
        f"Shared frontend index.html present: {shared_index}."
    )


def collect_database(repo_root: Path):
    """Row counts over HTTP from every *-db service compose defines.

    The team rule forbids reaching into another feature's SQLite file, so this
    goes through each database API. An unreachable service is recorded as a
    finding, not raised as an error.
    """
    compose = load_compose(repo_root)
    if compose is None:
        return False, "docker-compose.yml not found at the repository root."
    databases = services_with_suffix(compose, "-db")
    if not databases:
        return False, "No *-db services are defined in docker-compose.yml."

    lines = [f"Compose defines {len(databases)} database service(s) "
             f"(spec expects {EXPECTED_DB_SERVICES}, one per student): "
             f"{', '.join(sorted(databases))}."]

    for name in sorted(databases):
        port = databases[name]
        if port is None:
            lines.append(f"{name}: no published host port in compose - cannot probe.")
            continue
        base = f"http://localhost:{port}"
        feature = name[:-len("-db")]

        health, _, _ = _get(f"{base}/health")
        if health is None:
            lines.append(f"{name} (:{port}): UNREACHABLE - not running, or no /health route.")
            continue

        status, payload, _ = _get(f"{base}/{feature}")
        if status is None or status >= 400:
            reported = "unreachable" if status is None else status
            lines.append(f"{name} (:{port}): health {health}; list route /{feature} "
                         f"{reported} - row count unknown.")
            continue

        count = _row_count(payload)
        if count is None:
            lines.append(f"{name} (:{port}): health {health}; /{feature} returned "
                         f"non-list JSON - row count unknown.")
        else:
            verdict = "meets" if count >= MIN_SEED_ROWS else "BELOW"
            lines.append(f"{name} (:{port}): health {health}; /{feature} has {count} rows "
                         f"({verdict} the {MIN_SEED_ROWS}-row seed minimum).")

    return True, "Database evidence: " + " ".join(lines)


def collect_endpoints(repo_root: Path):
    """Status and latency for every *-backend, plus the Bills GET routes."""
    compose = load_compose(repo_root)
    if compose is None:
        return False, "docker-compose.yml not found at the repository root."
    backends = services_with_suffix(compose, "-backend")
    if not backends:
        return False, "No *-backend services are defined in docker-compose.yml."

    parts = []
    for name in sorted(backends):
        port = backends[name]
        if port is None:
            parts.append(f"{name}: no published host port in compose - cannot probe")
            continue
        base = f"http://localhost:{port}"
        status, _, latency = _get(f"{base}/health")
        parts.append(f"{name} (:{port}): GET /health "
                     + (f"{status} in {latency}ms" if status else "UNREACHABLE"))
        if name == "bills-backend":
            for route in BILLS_GET_ROUTES:
                status, _, latency = _get(f"{base}{route}")
                parts.append(f"{name}: GET {route} "
                             + (f"{status} in {latency}ms" if status else "UNREACHABLE"))

    return True, ("Live endpoint evidence (" + str(len(BILLS_GET_ROUTES))
                  + " documented Bills GET routes swept): " + "; ".join(parts) + ".")


def workflow_student(workflow: dict, known_students):
    """Which student folder a workflow watches, derived from its path filters.

    The repo names workflows per first name rather than the spec's
    student-N.yml, so the mapping is derived from what each file actually
    watches instead of being asserted from a hardcoded table.
    """
    triggers = workflow.get(True) or workflow.get("on") or {}
    paths = []
    if isinstance(triggers, dict):
        for trigger in triggers.values():
            if isinstance(trigger, dict):
                paths += trigger.get("paths") or []
    owners = {p.split("/", 1)[0] for p in paths} & set(known_students)
    return ", ".join(sorted(owners)) if owners else "no student path filter"


def collect_devops(repo_root: Path):
    """Workflow files, their jobs, the student each watches, and latest run."""
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False, ".github/workflows/ does not exist."
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    if not files:
        return False, ".github/workflows/ contains no workflow files."

    students = student_dirs(repo_root)
    lines, spec_named = [], 0
    for path in files:
        if path.stem.lower().startswith("student-"):
            spec_named += 1
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            lines.append(f"{path.name}: could not be parsed ({exc.__class__.__name__})")
            continue
        jobs = sorted((workflow.get("jobs") or {}).keys())
        line = (f"{path.name}: covers [{workflow_student(workflow, students)}]; "
                f"jobs [{', '.join(jobs) or 'none'}]")
        latest = latest_run(repo_root, path.name)
        if latest:
            line += f"; latest run on main: {latest}"
        lines.append(line)

    findings = []
    if spec_named == 0:
        findings.append("NAMING DEVIATION: no workflow uses the spec's student-N.yml "
                        "convention; the team names them per student first name.")
    if len(files) < len(students):
        findings.append(f"Only {len(files)} workflow file(s) for {len(students)} "
                        f"student directories - at least one student has no CI.")

    return True, ("DevOps evidence: " + " | ".join(lines)
                  + (" | " + " ".join(findings) if findings else ""))


def latest_run(repo_root: Path, workflow_file: str):
    """Latest run conclusion on main via gh, or None when gh is unavailable."""
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
        return f"{runs[0].get('conclusion') or 'in progress'} ({runs[0].get('createdAt', '?')})"
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
