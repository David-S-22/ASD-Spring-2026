"""Build the bills corpus folder for the shared RAG server from the bills database.

Run from the repository root:

    python -m sophia.rag.build_corpus                       # against BILLS_DB_API_URL
    python -m sophia.rag.build_corpus --from-seed           # against sophia/database/seed.py, no service needed
    python -m sophia.rag.build_corpus --from-seed --check   # what Sophia-CI runs: exit 1 if the folder is stale

Every file is written before any stale bill-*.md file is removed, so a failed build never
leaves the folder emptier than it found it.
"""
import argparse
import importlib.util
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import requests
from werkzeug.serving import make_server

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.rag.bills_corpus import render_corpus

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO_ROOT / "ai-services" / "rag-server" / "sources" / "bills"
DATABASE_DIR = REPO_ROOT / "sophia" / "database"


def fetch():
    """Return (bills, payments, disputes) exactly as the bills database API sends them."""
    return bills_db.list_bills(), bills_db.list_payments(), bills_db.list_disputes()


@contextmanager
def seed_database_api():
    """Serve sophia/database on a temporary seeded SQLite file and yield its base URL."""
    if str(DATABASE_DIR) not in sys.path:
        sys.path.insert(0, str(DATABASE_DIR))
    spec = importlib.util.spec_from_file_location("bills_database_app_for_corpus", DATABASE_DIR / "app.py")
    database_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(database_app)
    folder = Path(tempfile.mkdtemp(prefix="bills-seed-"))
    db_path = str(folder / "bills.db")
    connection = database_app.get_connection(db_path)
    database_app.load_schema(connection, database_app.SCHEMA_PATH)
    database_app.seed(connection)
    connection.close()
    server = make_server("127.0.0.1", 0, database_app.create_app(db_path=db_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            requests.get(f"{base_url}/health", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.05)
    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=5)
        shutil.rmtree(folder, ignore_errors=True)


def write_corpus(files, out_dir):
    """Write every file, then remove bill-*.md files that no longer belong; return the removed names."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    stale = sorted(path.name for path in out_dir.glob("bill-*.md") if path.name not in files)
    for name in stale:
        (out_dir / name).unlink()
    return stale


def check_corpus(files, out_dir):
    """Return the differences between the rendered files and the folder; empty means fresh."""
    problems = []
    for name, text in files.items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"changed: {name}")
    for path in sorted(out_dir.glob("bill-*.md")):
        if path.name not in files:
            problems.append(f"stale: {path.name}")
    return problems


def main(argv=None):
    """Build or check the corpus folder and return the process exit code."""
    parser = argparse.ArgumentParser(description="Build the bills corpus folder for the shared RAG server.")
    parser.add_argument("--out", type=Path, default=SOURCES_DIR, help="folder to write; defaults to the server's sources/bills")
    parser.add_argument("--check", action="store_true", help="exit 1 if the folder differs from a fresh build")
    parser.add_argument("--from-seed", action="store_true", help="read the seed data instead of BILLS_DB_API_URL")
    args = parser.parse_args(argv)
    if args.from_seed:
        live_url = config.BILLS_DB_API_URL
        with seed_database_api() as base_url:
            config.BILLS_DB_API_URL = base_url
            try:
                bills, payments, disputes = fetch()
            finally:
                config.BILLS_DB_API_URL = live_url
    else:
        bills, payments, disputes = fetch()
    files = render_corpus(bills, payments, disputes)
    if args.check:
        problems = check_corpus(files, args.out)
        for problem in problems:
            print(problem)
        if problems:
            print("bills corpus is stale; run: python -m sophia.rag.build_corpus" + (" --from-seed" if args.from_seed else ""))
            return 1
        print(f"bills corpus is fresh ({len(files)} files)")
        return 0
    stale = write_corpus(files, args.out)
    print(f"wrote {len(files)} bill files" + (f", removed {len(stale)} stale" if stale else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
