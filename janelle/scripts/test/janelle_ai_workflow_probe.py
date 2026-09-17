"""Capture a synthetic Janelle AI workflow and its real stage trace."""

import argparse
import sys
from time import sleep
from urllib.parse import urlencode
from uuid import uuid4

try:
    from .http_probe import (
        normalize_date,
        ProbeError,
        request_json,
        utc_timestamp,
        wait_for,
        write_report,
    )
except ImportError:
    from http_probe import (
        normalize_date,
        ProbeError,
        request_json,
        utc_timestamp,
        wait_for,
        write_report,
    )


def require_trace(result, expected_stages):
    agent = result.get("agent")
    if not isinstance(agent, dict):
        raise ProbeError("response did not include agent evidence")
    trace = agent.get("trace")
    stages = [
        item.get("stage")
        for item in trace
        if isinstance(item, dict)
    ] if isinstance(trace, list) else []
    if stages != expected_stages:
        raise ProbeError(
            f"expected trace {expected_stages}, received {stages}"
        )
    if any(item.get("duration_ms") is None for item in trace):
        raise ProbeError("workflow trace did not include stage durations")


def require_transaction(payload, expected, context):
    if not isinstance(payload, dict):
        raise ProbeError(f"{context} did not include a transaction object")
    mismatches = {
        field: {
            "expected": value,
            "actual": payload.get(field),
        }
        for field, value in expected.items()
        if field != "date" and payload.get(field) != value
    }
    actual_date = normalize_date(payload.get("date"))
    if actual_date != expected["date"]:
        mismatches["date"] = {
            "expected": expected["date"],
            "actual": actual_date,
        }
    if mismatches:
        raise ProbeError(f"{context} transaction mismatch: {mismatches}")


def marker_transactions(rows, marker):
    if not isinstance(rows, list):
        raise ProbeError("transaction search response is not a list")
    normalized_marker = marker.casefold()
    return [
        item
        for item in rows
        if isinstance(item, dict)
        and any(
            normalized_marker in str(item.get(field, "")).casefold()
            for field in ("merchant", "description")
        )
    ]


def run_probe(backend_url):
    records = []
    marker = uuid4().hex[:8]
    merchant = f"Release Evidence Cafe {marker}"
    message = (
        f'Add lunch at the merchant named "{merchant}" on '
        "8 September 2026 for $12.34 in Dining. The eight-character "
        "suffix is part of the merchant's exact name and must be preserved."
    )
    expected_transaction = {
        "date": "2026-09-08",
        "merchant": merchant,
        "description": "Lunch",
        "amount": 12.34,
        "category_id": 80,
    }
    transaction_id = None
    wait_for(f"{backend_url}/health")
    health = request_json(records, "GET", f"{backend_url}/health")
    expected_health = {
        "ok": True,
        "container": "transactions-backend",
    }
    if health != expected_health:
        raise ProbeError(
            f"backend health returned {health}, expected {expected_health}"
        )

    try:
        preview = request_json(
            records,
            "POST",
            f"{backend_url}/chat",
            payload={"message": message},
            timeout=120,
        )
        require_trace(preview, ["PLAN", "ACT", "OBSERVE", "ADAPT"])
        if preview.get("fallback"):
            raise ProbeError("the live planner returned a fallback")
        if preview.get("requires_confirmation") is not True:
            raise ProbeError(
                "the live planner did not create a confirmation gate"
            )
        if not isinstance(preview.get("preview"), dict):
            raise ProbeError("the live planner did not return a preview")
        if preview["preview"].get("operation") != "create":
            raise ProbeError(
                "the evidence probe only accepts create previews"
            )
        require_transaction(
            preview["preview"].get("after"),
            expected_transaction,
            "preview",
        )

        matches_before_confirmation = request_json(
            records,
            "GET",
            (
                f"{backend_url}/transactions?"
                f"{urlencode({'q': marker})}"
            ),
        )
        if marker_transactions(matches_before_confirmation, marker):
            raise ProbeError(
                "the preview persisted a transaction before confirmation"
            )

        applied = request_json(
            records,
            "POST",
            f"{backend_url}/chat/apply",
            payload=preview["preview"],
            timeout=120,
        )
        transaction = applied.get("transaction")
        require_trace(applied, ["PLAN", "ACT", "OBSERVE", "ADAPT"])
        if applied.get("saved") is not True or applied.get("verified") is not True:
            raise ProbeError("the confirmed write was not saved and verified")
        if not isinstance(transaction, dict) or not transaction.get("id"):
            raise ProbeError("the confirmed write returned no transaction")
        require_transaction(
            transaction,
            expected_transaction,
            "confirmed write",
        )
        matches = request_json(
            records,
            "GET",
            (
                f"{backend_url}/transactions?"
                f"{urlencode({'q': marker})}"
            ),
        )
        matching_transactions = marker_transactions(matches, marker)
        if len(matching_transactions) != 1:
            raise ProbeError(
                "confirmed write did not persist exactly one matching "
                f"transaction: found {len(matching_transactions)}"
            )
        persisted_transaction = matching_transactions[0]
        require_transaction(
            persisted_transaction,
            expected_transaction,
            "persisted",
        )
        if transaction.get("id") != persisted_transaction.get("id"):
            raise ProbeError(
                "confirmed write response ID does not match persisted state"
            )
        transaction_id = persisted_transaction["id"]
        return {
            "generated_at": utc_timestamp(),
            "probe": "janelle-live-ai-workflow",
            "status": "passed",
            "input": {
                "kind": "fixed_synthetic_create",
            },
            "checks": {
                "no_write_before_confirmation": True,
                "exactly_one_write_after_confirmation": True,
                "persisted_date": expected_transaction["date"],
            },
            "model": preview["agent"]["models"]["planner"],
            "request_id": preview["agent"]["request_id"],
            "preview": {
                "operation": preview["preview"]["operation"],
                "requires_confirmation": preview["requires_confirmation"],
                "fallback": preview["fallback"],
                "agent": preview["agent"],
            },
            "applied": {
                "operation": applied["operation"],
                "saved": applied["saved"],
                "verified": applied["verified"],
                "fallback": applied["fallback"],
                "agent": applied["agent"],
            },
            "requests": records,
        }
    finally:
        cleanup_errors = []
        transaction_ids = {
            transaction_id
        } if transaction_id is not None else set()
        for attempt in range(3):
            try:
                matches = request_json(
                    records,
                    "GET",
                    (
                        f"{backend_url}/transactions?"
                        f"{urlencode({'q': marker})}"
                    ),
                )
                if isinstance(matches, list):
                    owned_transactions = marker_transactions(
                        matches,
                        marker,
                    )
                    transaction_ids.update(
                        item.get("id")
                        for item in owned_transactions
                        if item.get("id") is not None
                    )
                break
            except Exception as error:
                if attempt == 2:
                    cleanup_errors.append(str(error))
                else:
                    sleep(1)
        for cleanup_transaction_id in transaction_ids:
            try:
                request_json(
                    records,
                    "DELETE",
                    (
                        f"{backend_url}/transactions/"
                        f"{cleanup_transaction_id}"
                    ),
                    expected=(204, 404),
                )
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            remaining = request_json(
                records,
                "GET",
                (
                    f"{backend_url}/transactions?"
                    f"{urlencode({'q': marker})}"
                ),
            )
            if marker_transactions(remaining, marker):
                cleanup_errors.append(
                    "synthetic AI transaction still exists"
                )
        except Exception as error:
            cleanup_errors.append(str(error))
        if cleanup_errors:
            raise ProbeError(
                f"AI evidence cleanup failed: {'; '.join(cleanup_errors)}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend-url",
        default="http://127.0.0.1:5001",
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        report = run_probe(
            args.backend_url.rstrip("/"),
        )
    except Exception as error:
        report = {
            "generated_at": utc_timestamp(),
            "probe": "janelle-live-ai-workflow",
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
        write_report(report, args.output)
        return 1

    write_report(report, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
