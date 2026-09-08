"""Measure repeatable transaction-database latency and concurrency baselines."""

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from janelle.database.app import setup_app
from janelle.database.models import db

try:
    from .http_probe import utc_timestamp, write_report
except ImportError:
    from http_probe import utc_timestamp, write_report


SEQUENTIAL_REQUESTS = 100
PARALLEL_REQUESTS = 40
PARALLEL_WORKERS = 8
MAX_P95_MS = 250
MAX_PARALLEL_ELAPSED_MS = 10_000


def timed_transaction_read(application):
    started_at = perf_counter()
    with application.test_client() as client:
        response = client.get("/transactions")
    return response.status_code, round(
        (perf_counter() - started_at) * 1000,
        3,
    )


def percentile(values, percentile_value):
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile_value) - 1)
    return ordered[index]


def run_probe(database_path):
    application = setup_app(str(database_path))
    application.config["TESTING"] = True
    try:
        for _ in range(5):
            status, _duration = timed_transaction_read(application)
            if status != 200:
                raise RuntimeError(f"warm-up read returned {status}")

        sequential = [
            timed_transaction_read(application)
            for _ in range(SEQUENTIAL_REQUESTS)
        ]
        sequential_statuses = [status for status, _duration in sequential]
        sequential_durations = [
            duration for _status, duration in sequential
        ]

        parallel_started_at = perf_counter()
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            parallel = list(executor.map(
                lambda _index: timed_transaction_read(application),
                range(PARALLEL_REQUESTS),
            ))
        parallel_elapsed_ms = round(
            (perf_counter() - parallel_started_at) * 1000,
            3,
        )
        parallel_statuses = [status for status, _duration in parallel]
        parallel_durations = [
            duration for _status, duration in parallel
        ]

        p95_ms = percentile(sequential_durations, 0.95)
        passed = (
            set(sequential_statuses) == {200}
            and set(parallel_statuses) == {200}
            and p95_ms <= MAX_P95_MS
            and parallel_elapsed_ms <= MAX_PARALLEL_ELAPSED_MS
        )
        return {
            "generated_at": utc_timestamp(),
            "probe": "janelle-database-nfr",
            "passed": passed,
            "thresholds": {
                "sequential_p95_ms": MAX_P95_MS,
                "parallel_elapsed_ms": MAX_PARALLEL_ELAPSED_MS,
                "error_count": 0,
            },
            "sequential": {
                "requests": SEQUENTIAL_REQUESTS,
                "p50_ms": percentile(sequential_durations, 0.50),
                "p95_ms": p95_ms,
                "max_ms": max(sequential_durations),
                "error_count": sum(
                    status != 200 for status in sequential_statuses
                ),
            },
            "parallel": {
                "requests": PARALLEL_REQUESTS,
                "workers": PARALLEL_WORKERS,
                "elapsed_ms": parallel_elapsed_ms,
                "p95_ms": percentile(parallel_durations, 0.95),
                "requests_per_second": round(
                    PARALLEL_REQUESTS / (parallel_elapsed_ms / 1000),
                    2,
                ),
                "error_count": sum(
                    status != 200 for status in parallel_statuses
                ),
            },
        }
    finally:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()

    with TemporaryDirectory(prefix="janelle-nfr-") as temporary_directory:
        report = run_probe(
            Path(temporary_directory) / "transactions.db"
        )

    write_report(report, args.output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
