"""Exercise the running Janelle frontend, backend, and database APIs."""

import argparse
import sys
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


def require_health(payload, container):
    expected = {"ok": True, "container": container}
    if payload != expected:
        raise ProbeError(
            f"{container} health returned {payload}, expected {expected}"
        )


def require_fields(payload, expected, entity):
    if not isinstance(payload, dict):
        raise ProbeError(f"{entity} response is not an object")
    mismatches = {}
    for field, value in expected.items():
        actual = payload.get(field)
        if field == "date":
            actual = normalize_date(actual)
        if actual != value:
            mismatches[field] = {
                "expected": value,
                "actual": actual,
            }
    if mismatches:
        raise ProbeError(f"{entity} response mismatch: {mismatches}")
    if payload.get("id") is None:
        raise ProbeError(f"{entity} response returned no ID")
    return payload["id"]


def run_smoke(
    frontend_url,
    backend_url,
    database_url,
):
    records = []
    suffix = uuid4().hex[:8]
    category_name = f"Endpoint Evidence {suffix}"
    updated_category_name = f"Endpoint Evidence Updated {suffix}"
    category_names = {category_name, updated_category_name}
    transaction_merchant = f"Endpoint Evidence Cafe {suffix}"
    category_id = None
    transaction_id = None
    request_backend_url = (
        f"{frontend_url}/transactions-backend"
        if frontend_url is not None
        else backend_url
    )
    report = {
        "generated_at": utc_timestamp(),
        "probe": "janelle-live-endpoints",
        "status": "failed",
        "requests": records,
    }
    try:
        base_urls = [backend_url, database_url]
        if frontend_url is not None:
            base_urls.insert(0, frontend_url)
        for base_url in base_urls:
            wait_for(f"{base_url}/health")

        frontend_health = (
            request_json(
                records,
                "GET",
                f"{frontend_url}/health",
            )
            if frontend_url is not None
            else "not_run"
        )
        backend_health = request_json(
            records,
            "GET",
            f"{backend_url}/health",
        )
        database_health = request_json(
            records,
            "GET",
            f"{database_url}/health",
        )
        if frontend_url is not None:
            require_health(frontend_health, "transactions-frontend")
        require_health(backend_health, "transactions-backend")
        require_health(database_health, "transactions-db")
        frontend_root = "not_run"
        frontend_backend_health = "not_run"
        if frontend_url is not None:
            frontend_root = request_json(
                records,
                "GET",
                f"{frontend_url}/",
            )
            if not isinstance(frontend_root, str) or (
                "transactions-backend/ui/transactions/page"
                not in frontend_root
            ):
                raise ProbeError(
                    "frontend root did not return the transaction application"
                )
            frontend_backend_health = request_json(
                records,
                "GET",
                f"{request_backend_url}/health",
            )
            require_health(
                frontend_backend_health,
                "transactions-backend",
            )
        categories = request_json(
            records,
            "GET",
            f"{request_backend_url}/categories",
        )
        transactions = request_json(
            records,
            "GET",
            f"{request_backend_url}/transactions",
        )
        request_json(records, "GET", f"{database_url}/categories")
        request_json(records, "GET", f"{database_url}/transactions")

        if not isinstance(categories, list) or not categories:
            raise ProbeError("backend returned no categories")
        if not isinstance(transactions, list):
            raise ProbeError("backend transactions response is not a list")

        created_category = request_json(
            records,
            "POST",
            f"{request_backend_url}/categories",
            payload={
                "name": category_name,
                "type": "want",
            },
            expected=(201,),
        )
        candidate_category_id = require_fields(
            created_category,
            {"name": category_name, "type": "want"},
            "created category",
        )
        read_category = request_json(
            records,
            "GET",
            f"{request_backend_url}/categories/{candidate_category_id}",
        )
        require_fields(
            read_category,
            {
                "id": candidate_category_id,
                "name": category_name,
                "type": "want",
            },
            "read category",
        )
        category_id = candidate_category_id
        updated_category = request_json(
            records,
            "PATCH",
            f"{request_backend_url}/categories/{category_id}",
            payload={
                "name": updated_category_name,
                "type": "saving",
            },
        )
        require_fields(
            updated_category,
            {
                "id": category_id,
                "name": updated_category_name,
                "type": "saving",
            },
            "updated category",
        )
        persisted_category = request_json(
            records,
            "GET",
            f"{request_backend_url}/categories/{category_id}",
        )
        require_fields(
            persisted_category,
            {
                "id": category_id,
                "name": updated_category_name,
                "type": "saving",
            },
            "persisted category",
        )

        seeded_category_id = categories[0]["id"]
        expected_transaction = {
            "date": "2026-09-08",
            "merchant": transaction_merchant,
            "description": "Synthetic endpoint smoke transaction",
            "amount": 12.34,
            "category_id": seeded_category_id,
        }
        created_transaction = request_json(
            records,
            "POST",
            f"{request_backend_url}/transactions",
            payload={
                "date": "2026-09-08",
                "merchant": transaction_merchant,
                "description": "Synthetic endpoint smoke transaction",
                "amount": 12.34,
                "category_id": seeded_category_id,
            },
            expected=(201,),
        )
        candidate_transaction_id = require_fields(
            created_transaction,
            expected_transaction,
            "created transaction",
        )
        read_transaction = request_json(
            records,
            "GET",
            (
                f"{request_backend_url}/transactions/"
                f"{candidate_transaction_id}"
            ),
        )
        require_fields(
            read_transaction,
            {
                "id": candidate_transaction_id,
                **expected_transaction,
            },
            "read transaction",
        )
        transaction_id = candidate_transaction_id
        updated_transaction = request_json(
            records,
            "PATCH",
            f"{request_backend_url}/transactions/{transaction_id}",
            payload={"amount": 13.45},
        )
        expected_transaction["amount"] = 13.45
        require_fields(
            updated_transaction,
            {
                "id": transaction_id,
                **expected_transaction,
            },
            "updated transaction",
        )
        persisted_transaction = request_json(
            records,
            "GET",
            f"{request_backend_url}/transactions/{transaction_id}",
        )
        require_fields(
            persisted_transaction,
            {
                "id": transaction_id,
                **expected_transaction,
            },
            "persisted transaction",
        )
        request_json(
            records,
            "POST",
            f"{request_backend_url}/chat",
            payload={},
            expected=(422,),
        )

        report.update({
            "status": "passed",
            "checks": {
                "frontend_health": frontend_health,
                "frontend_root": (
                    True if frontend_url is not None else "not_run"
                ),
                "frontend_backend_proxy": frontend_backend_health,
                "backend_health": backend_health,
                "database_health": database_health,
                "backend_category_crud": True,
                "backend_transaction_crud": True,
                "transaction_date": expected_transaction["date"],
                "chat_validation": True,
            },
        })
    finally:
        cleanup_errors = []
        transaction_ids = {
            transaction_id
        } if transaction_id is not None else set()
        try:
            matches = request_json(
                records,
                "GET",
                (
                    f"{request_backend_url}/transactions?"
                    f"{urlencode({'merchant': transaction_merchant})}"
                ),
            )
            if isinstance(matches, list):
                transaction_ids.update(
                    item.get("id")
                    for item in matches
                    if (
                        isinstance(item, dict)
                        and item.get("merchant") == transaction_merchant
                        and item.get("id") is not None
                    )
                )
        except Exception as error:
            cleanup_errors.append(str(error))
        for cleanup_transaction_id in transaction_ids:
            try:
                request_json(
                    records,
                    "DELETE",
                    (
                        f"{request_backend_url}/transactions/"
                        f"{cleanup_transaction_id}"
                    ),
                    expected=(204, 404),
                )
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            remaining_transactions = request_json(
                records,
                "GET",
                (
                    f"{request_backend_url}/transactions?"
                    f"{urlencode({'merchant': transaction_merchant})}"
                ),
            )
            if any(
                isinstance(item, dict)
                and item.get("merchant") == transaction_merchant
                for item in (
                    remaining_transactions
                    if isinstance(remaining_transactions, list)
                    else []
                )
            ):
                cleanup_errors.append(
                    "synthetic endpoint transaction still exists"
                )
        except Exception as error:
            cleanup_errors.append(str(error))

        category_ids = {category_id} if category_id is not None else set()
        try:
            categories = request_json(
                records,
                "GET",
                f"{request_backend_url}/categories",
            )
            if isinstance(categories, list):
                category_ids.update(
                    item.get("id")
                    for item in categories
                    if (
                        isinstance(item, dict)
                        and item.get("name") in category_names
                        and item.get("id") is not None
                    )
                )
        except Exception as error:
            cleanup_errors.append(str(error))
        for cleanup_category_id in category_ids:
            try:
                request_json(
                    records,
                    "DELETE",
                    (
                        f"{request_backend_url}/categories/"
                        f"{cleanup_category_id}"
                    ),
                    expected=(204, 404),
                )
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            remaining_categories = request_json(
                records,
                "GET",
                f"{request_backend_url}/categories",
            )
            if any(
                isinstance(item, dict)
                and item.get("name") in category_names
                for item in (
                    remaining_categories
                    if isinstance(remaining_categories, list)
                    else []
                )
            ):
                cleanup_errors.append(
                    "synthetic endpoint category still exists"
                )
        except Exception as error:
            cleanup_errors.append(str(error))
        if cleanup_errors:
            raise ProbeError(
                f"endpoint cleanup failed: {'; '.join(cleanup_errors)}"
            )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--frontend-url",
        default="http://127.0.0.1:3001",
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip the frontend health check when nginx is unavailable.",
    )
    parser.add_argument(
        "--backend-url",
        default="http://127.0.0.1:5001",
    )
    parser.add_argument(
        "--database-url",
        default="http://127.0.0.1:6001",
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        report = run_smoke(
            (
                None
                if args.skip_frontend
                else args.frontend_url.rstrip("/")
            ),
            args.backend_url.rstrip("/"),
            args.database_url.rstrip("/"),
        )
    except Exception as error:
        report = {
            "generated_at": utc_timestamp(),
            "probe": "janelle-live-endpoints",
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
        write_report(report, args.output)
        return 1

    write_report(report, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
