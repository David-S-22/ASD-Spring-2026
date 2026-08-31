"""Repository and compose architecture evidence.

Collects the service inventory and dependency edges from docker-compose.yml,
the per-student directory layout, and whether the spec's required
directories exist and are populated — including the shared containerised
index.html entry point the assignment asks for. Gaps are evidence for the
model to review, not errors.
"""

from pathlib import Path

from .compose import dependency_edges, load_compose

REQUIRED_DIRS = [".github/workflows", "docs", "shared", "ai-services", "scripts"]
SERVICE_SUBDIRS = ("frontend", "backend", "database")


def _is_populated(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(child.name != ".gitkeep" for child in path.iterdir())


def _student_dirs(repo_root: Path) -> list[str]:
    skip = {".git", ".github", ".vs", ".pytest_cache", "docs", "shared", "ai-services", "scripts", "agentic_loop", "prompts", "reports"}
    found = []
    for child in sorted(repo_root.iterdir()):
        if not child.is_dir() or child.name in skip:
            continue
        subdirs = [s for s in SERVICE_SUBDIRS if (child / s).is_dir()]
        if subdirs:
            found.append(f"{child.name} ({', '.join(subdirs)})")
        else:
            found.append(f"{child.name} (EMPTY — no service directories)")
    return found


def collect(app_dir: Path, repo_root: Path) -> tuple[bool, str]:
    compose = load_compose(repo_root)
    if compose is None:
        return False, "docker-compose.yml not found at the repo root."

    services = sorted((compose.get("services") or {}).keys())
    edges = dependency_edges(compose)
    edge_text = ", ".join(f"{svc}->{dep}" for svc, dep in edges) or "none"

    dir_lines = []
    for rel in REQUIRED_DIRS:
        path = repo_root / rel
        if not path.is_dir():
            dir_lines.append(f"{rel} MISSING")
        elif not _is_populated(path):
            dir_lines.append(f"{rel} present but EMPTY")
        else:
            dir_lines.append(f"{rel} populated")

    shared_index = repo_root / "shared" / "index.html"
    entry_point = (
        "shared/index.html exists"
        if shared_index.exists()
        else "shared/index.html MISSING — no shared containerised entry point routing to the five frontends"
    )

    return True, (
        f"Architecture evidence: compose defines {len(services)} services: "
        + ", ".join(services)
        + f". Dependency edges: {edge_text}. Student directories: "
        + "; ".join(_student_dirs(repo_root))
        + ". Required directories: " + "; ".join(dir_lines)
        + ". Shared entry point: " + entry_point + "."
    )
