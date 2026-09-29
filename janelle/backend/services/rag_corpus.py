"""Build and push the ``transactions-records`` RAG collection.

One document is produced per transaction and one per category correction.
Ids are stable (``tx-<id>``, ``corr-<id>``) so a refresh is idempotent, and
metadata values are scalars only because Chroma rejects anything else.
"""
import json
import threading
import time

from .. import config
from ..Helpers import parse_transaction_datetime
from . import chat_service, rag_client


def build_documents(transactions, categories, corrections):
    """Return ``(ids, documents, metadatas)`` for the records collection."""
    names = {}
    types = {}
    for category in categories:
        if isinstance(category, dict):
            names[category.get("id")] = category.get("name")
            types[category.get("id")] = category.get("type")

    ids = []
    documents = []
    metadatas = []

    for transaction in transactions:
        if not isinstance(transaction, dict) or transaction.get("id") is None:
            continue
        category_id = transaction.get("category_id")
        category_name = names.get(category_id) or "Uncategorised"
        category_type = types.get(category_id)
        date = _iso_date(transaction.get("date"))
        amount = _float_or_none(transaction.get("amount"))
        label = category_name
        if category_type:
            label = f"{category_name} ({category_type})"
        ids.append(f"tx-{transaction['id']}")
        documents.append(
            f"Transaction {transaction['id']} on {date}: "
            f"{transaction.get('merchant') or 'Unknown merchant'} charged "
            f"{_money(amount)} for '{transaction.get('description') or ''}'. "
            f"Category: {label}."
        )
        metadatas.append(_scalars({
            "kind": "transaction",
            "transaction_id": transaction["id"],
            "date": date,
            "merchant": transaction.get("merchant"),
            "category": category_name,
            "category_id": category_id,
            "category_type": category_type,
            "amount": amount,
        }))

    for correction in corrections:
        if not isinstance(correction, dict) or correction.get("id") is None:
            continue
        category_id = correction.get("user_category_id")
        category_name = (
            correction.get("user_category_name")
            or names.get(category_id)
            or "Uncategorised"
        )
        previous_name = (
            correction.get("previous_category_name")
            or names.get(correction.get("previous_category_id"))
            or "Uncategorised"
        )
        date = _iso_date(correction.get("corrected_at"))
        ids.append(f"corr-{correction['id']}")
        documents.append(
            f"Transaction {correction.get('transaction_id')} "
            f"({correction.get('merchant') or 'Unknown merchant'}, "
            f"'{correction.get('description') or ''}') was recategorised "
            f"from {previous_name} to {category_name} on {date}."
        )
        metadatas.append(_scalars({
            "kind": "correction",
            "transaction_id": correction.get("transaction_id"),
            "date": date,
            "merchant": correction.get("merchant"),
            "category": category_name,
            "category_id": category_id,
            "category_type": types.get(category_id),
        }))

    return ids, documents, metadatas


def fetch_and_build(db_url):
    """Fetch the three tables and return ``(ids, documents, metadatas, kinds)``."""
    db_url = db_url.rstrip("/")
    transactions = chat_service.database_request(
        "get",
        f"{db_url}/transactions",
        list,
    )
    categories = chat_service.database_request(
        "get",
        f"{db_url}/categories",
        list,
    )
    corrections = chat_service.database_request(
        "get",
        f"{db_url}/category-corrections",
        list,
    )
    ids, documents, metadatas = build_documents(
        transactions,
        categories,
        corrections,
    )
    kinds = {
        "transaction": sum(
            1 for item in metadatas if item.get("kind") == "transaction"
        ),
        "correction": sum(
            1 for item in metadatas if item.get("kind") == "correction"
        ),
    }
    return ids, documents, metadatas, kinds


def refresh_records(db_url, trigger):
    """Rebuild the records collection once and emit one RAG_REFRESH record.

    Returns the refresh summary. Raises ``RAGError`` or ``ChatError`` so the
    manual route can map them; background callers catch and log instead.
    """
    started = time.perf_counter()
    kinds = {"transaction": 0, "correction": 0}
    try:
        ids, documents, metadatas, kinds = fetch_and_build(db_url)
        result = rag_client.refresh(
            config.RAG_RECORDS_COLLECTION,
            ids,
            documents,
            metadatas,
        )
    except rag_client.RAGError as error:
        log_refresh(trigger, 0, kinds, started, "failed", error.code)
        raise
    except chat_service.ChatError as error:
        log_refresh(trigger, 0, kinds, started, "failed", error.code)
        raise
    summary = {
        "feature": result["feature"],
        "total": result["total"],
        "kinds": kinds,
        "duration_ms": _elapsed_ms(started),
    }
    log_refresh(
        trigger,
        summary["total"],
        kinds,
        started,
        "succeeded",
        None,
    )
    return summary


def refresh_with_retries(db_url, trigger, attempts=1, delay_seconds=0):
    """Try ``refresh_records`` up to ``attempts`` times; never raise."""
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            return refresh_records(db_url, trigger)
        except (rag_client.RAGError, chat_service.ChatError):
            # Already logged by refresh_records with a safe code.
            if attempt < attempts and delay_seconds > 0:
                time.sleep(delay_seconds)
    return None


def start_background_refresh(db_url, trigger, attempts=1, delay_seconds=0):
    """Run the refresh on a daemon thread so callers never wait or fail."""
    if not config.RAG_ENABLED:
        return None
    thread = threading.Thread(
        target=refresh_with_retries,
        args=(db_url, trigger, attempts, delay_seconds),
        name=f"rag-refresh-{trigger}",
        daemon=True,
    )
    thread.start()
    return thread


def log_refresh(trigger, total, kinds, started, status, error):
    if not config.AGENT_LOG_ENABLED:
        return
    from .transaction_orchestrator import log_workflow_event

    log_workflow_event({
        "event": "RAG_REFRESH",
        "trigger": trigger,
        "collection": config.RAG_RECORDS_COLLECTION,
        "total": total,
        "kinds": dict(kinds),
        "duration_ms": _elapsed_ms(started),
        "status": status,
        "error": error,
    })


def _elapsed_ms(started):
    return round((time.perf_counter() - started) * 1000, 1)


def _iso_date(value):
    """Normalise any database date form (ISO or RFC 2822) to YYYY-MM-DD."""
    parsed = parse_transaction_datetime(value) if value is not None else None
    if parsed is not None:
        return parsed.date().isoformat()
    return str(value) if value is not None else ""


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(amount):
    if amount is None:
        return "an unknown amount"
    return f"${amount:.2f}"


def _scalars(metadata):
    """Drop ``None`` values and coerce anything non-scalar to a string."""
    cleaned = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, bool) or isinstance(value, (int, float, str)):
            cleaned[key] = value
        else:
            cleaned[key] = json.dumps(value, sort_keys=True)
    return cleaned
