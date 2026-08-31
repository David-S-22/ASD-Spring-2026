"""Shared docker-compose.yml parsing for the collectors.

Ports are read from the compose file rather than hardcoded because the
team's port assignments are still unsettled; whatever the file says at run
time is what the loop probes.
"""

from pathlib import Path

import yaml


def load_compose(repo_root: Path) -> dict | None:
    path = repo_root / "docker-compose.yml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _host_port(entry) -> int | None:
    # Entries look like "3005:80", 11434:11434 (parsed as str), or a long-form dict.
    if isinstance(entry, dict):
        published = entry.get("published")
        return int(published) if published is not None else None
    text = str(entry)
    host = text.split(":", 1)[0]
    return int(host) if host.isdigit() else None


def service_host_ports(compose: dict) -> dict[str, int | None]:
    ports: dict[str, int | None] = {}
    for name, spec in (compose.get("services") or {}).items():
        first = None
        for entry in (spec or {}).get("ports") or []:
            first = _host_port(entry)
            if first is not None:
                break
        ports[name] = first
    return ports


def services_with_suffix(compose: dict, suffix: str) -> dict[str, int | None]:
    return {
        name: port
        for name, port in service_host_ports(compose).items()
        if name.endswith(suffix)
    }


def dependency_edges(compose: dict) -> list[tuple[str, str]]:
    edges = []
    for name, spec in (compose.get("services") or {}).items():
        deps = (spec or {}).get("depends_on") or []
        dep_names = deps.keys() if isinstance(deps, dict) else deps
        for dep in dep_names:
            edges.append((name, dep))
    return edges
