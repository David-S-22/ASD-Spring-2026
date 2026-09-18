"""Bills knowledge for the shared RAG server. Tier 1 = one sentence per bill, payment and dispute
from the Bills database API (:6005), with the row's own columns as metadata so callers can filter
(where={"record": "dispute"}, where={"bill_id": 12}). Tier 2 = the four Bills docs, split by heading
with doc/section extracted. Owner: Sophia."""
import os

import requests

import config
import corpus

FEATURE = "bills"
BILLS_DB_API_URL = os.environ.get("BILLS_DB_API_URL", "http://localhost:6005")
DOCS = [
    "sophia/README.md",
    "docs/release-0/sophia/api.md",
    "docs/release-0/sophia/contracts-inbound.md",
    "docs/release-0/sophia/schema-adoption.md",
]


def dollars(cents):
    return f"${cents / 100:,.2f}"


def _get(path):
    response = requests.get(f"{BILLS_DB_API_URL}{path}", timeout=5)
    response.raise_for_status()
    return response.json()


def _row_chunks():
    """Money is written out in the sentence so the model never computes; the same values sit in
    metadata (in cents, as stored) so they can be filtered on."""
    bills = {row["id"]: row for row in _get("/bills")}
    chunks = []
    for b in bills.values():
        ended = f", cancelled from {b['end_date']}" if b.get("end_date") else ""
        chunks.append(corpus.row_chunk(
            FEATURE, "bill", b["id"],
            f"Bill #{b['id']} {b['name']} ({b.get('merchant', '')}): {dollars(b['amount_cents'])} {b['cadence']}, "
            f"paid by {b.get('payment_method') or 'an unknown method'}, next billing {b['next_billing_date']}{ended}.",
            name=b["name"], merchant=b.get("merchant"), cadence=b["cadence"], amount_cents=b["amount_cents"],
            next_billing_date=b["next_billing_date"], active=not b.get("end_date"),
            label=f"Bill #{b['id']} {b['name']}"))
    for p in _get("/payments"):
        name = bills.get(p["bill_id"], {}).get("name", "")
        chunks.append(corpus.row_chunk(
            FEATURE, "payment", p["id"],
            f"Payment #{p['id']} for bill #{p['bill_id']} {name}: {dollars(p['amount_cents'])} on {p['date']}.",
            bill_id=p["bill_id"], date=p["date"], amount_cents=p["amount_cents"],
            label=f"Payment #{p['id']} {name} {p['date']}"))
    for d in _get("/disputes"):
        name = bills.get(d["bill_id"], {}).get("name", "")
        opened = str(d.get("created_at", ""))[:10]
        chunks.append(corpus.row_chunk(
            FEATURE, "dispute", d["id"],
            f"Dispute #{d['id']} for bill #{d['bill_id']} {name}: reason \"{d.get('reason', '')}\", "
            f"status {d.get('status', '')}, opened {opened}.",
            bill_id=d["bill_id"], status=d.get("status"), opened=opened,
            label=f"Dispute #{d['id']} {name}"))
    return chunks


def _doc_chunks():
    chunks = []
    for rel in DOCS:
        chunks += corpus.doc_chunks(config.REPO_ROOT / rel, FEATURE)
    return chunks


def load_chunks():
    """Rows first (tier 1), docs second (tier 2). Raises if the Bills database API is down."""
    return _row_chunks() + _doc_chunks()


BENCHMARKS = [
    {"query": "What evidence do I have to dispute the GymCo charge?", "feature": FEATURE,
     "keywords": ["GymCo"], "expected_relevant": 3},
    {"query": "How does Bills decide whether a bill is overdue?", "feature": FEATURE,
     "keywords": ["overdue"], "expected_relevant": 1},
    {"query": "What is the interest rate on my mortgage?", "feature": FEATURE, "expect_insufficient": True},
]
