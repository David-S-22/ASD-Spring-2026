"""Bills corpus for the shared RAG server. Owner: Sophia.

Builds the Bills chunks and pushes them to the RAG server (POST /ingest, replace=True):
  tier 1  one plain sentence per bill, payment and dispute from the Bills database API (:6005),
          with the row's own columns as metadata so callers can filter (where={"record": "dispute"})
  tier 2  the four Bills docs, chunked the way ChromaDB recommends for markdown — LangChain's
          MarkdownHeaderTextSplitter (never cross a heading, keep the header path as metadata) then
          RecursiveCharacterTextSplitter (size-limit each section) — with the header path prefixed
          onto each chunk's text: https://docs.trychroma.com/guides/build/chunking

Run from anywhere with the server and the Bills database up:
    python sophia/rag/bills.py
Env: RAG_SERVER_URL (http://localhost:5003), BILLS_DB_API_URL (http://localhost:6005)."""
import os
import sys
from pathlib import Path

import requests
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

FEATURE = "bills"
RAG_SERVER_URL = os.environ.get("RAG_SERVER_URL", "http://localhost:5003")
BILLS_DB_API_URL = os.environ.get("BILLS_DB_API_URL", "http://localhost:6005")
REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = [
    "sophia/README.md",
    "docs/release-0/sophia/api.md",
    "docs/release-0/sophia/contracts-inbound.md",
    "docs/release-0/sophia/schema-adoption.md",
]

HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
CHUNK_SIZE, CHUNK_OVERLAP = 500, 50          # characters; Chroma's example values


def dollars(cents):
    return f"${cents / 100:,.2f}"


def _get(path):
    response = requests.get(f"{BILLS_DB_API_URL}{path}", timeout=5)
    response.raise_for_status()
    return response.json()


def row(record, record_id, text, **meta):
    """One database row as a tier-1 chunk; None-valued columns are dropped (Chroma wants scalars)."""
    return {"id": f"{FEATURE}:{record}/{record_id}", "text": text,
            "metadata": {"tier": 1, "record": record, "record_id": record_id,
                         **{k: v for k, v in meta.items() if v is not None}}}


def row_chunks():
    """Money is written out in the sentence so the model never computes; the same values sit in
    metadata (in cents, as stored) so they can be filtered on."""
    bills = {b["id"]: b for b in _get("/bills")}
    chunks = []
    for b in bills.values():
        ended = f", cancelled from {b['end_date']}" if b.get("end_date") else ""
        chunks.append(row("bill", b["id"],
            f"Bill #{b['id']} {b['name']} ({b.get('merchant', '')}): {dollars(b['amount_cents'])} {b['cadence']}, "
            f"paid by {b.get('payment_method') or 'an unknown method'}, next billing {b['next_billing_date']}{ended}.",
            name=b["name"], merchant=b.get("merchant"), cadence=b["cadence"], amount_cents=b["amount_cents"],
            next_billing_date=b["next_billing_date"], active=not b.get("end_date"),
            label=f"Bill #{b['id']} {b['name']}"))
    for p in _get("/payments"):
        name = bills.get(p["bill_id"], {}).get("name", "")
        chunks.append(row("payment", p["id"],
            f"Payment #{p['id']} for bill #{p['bill_id']} {name}: {dollars(p['amount_cents'])} on {p['date']}.",
            bill_id=p["bill_id"], date=p["date"], amount_cents=p["amount_cents"],
            label=f"Payment #{p['id']} {name} {p['date']}"))
    for d in _get("/disputes"):
        name = bills.get(d["bill_id"], {}).get("name", "")
        opened = str(d.get("created_at", ""))[:10]
        chunks.append(row("dispute", d["id"],
            f"Dispute #{d['id']} for bill #{d['bill_id']} {name}: reason \"{d.get('reason', '')}\", "
            f"status {d.get('status', '')}, opened {opened}.",
            bill_id=d["bill_id"], status=d.get("status"), opened=opened,
            label=f"Dispute #{d['id']} {name}"))
    return chunks


def doc_chunks():
    """Chroma's recommended markdown chunking: split by heading, then by size; header path kept as
    metadata (h1/h2/h3) and prefixed onto the text so each chunk reads in context on its own."""
    by_header = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS)
    by_size = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
                                             separators=["\n\n", "\n", ". ", " "])
    chunks = []
    for rel in DOCS:
        path = REPO_ROOT / rel
        if not path.exists():
            print(f"  skip {rel} (missing)", file=sys.stderr)
            continue
        pieces = by_size.split_documents(by_header.split_text(path.read_text(encoding="utf-8")))
        for n, piece in enumerate(pieces, start=1):
            trail = " › ".join(piece.metadata.values())          # "Bills backend API › JSON API"
            chunks.append({"id": f"{FEATURE}:docs/{path.name}#{n}",
                           "text": f"{trail}: {piece.page_content}" if trail else piece.page_content,
                           "metadata": {"tier": 2, "doc": path.name, "label": f"{path.name} › {trail or path.stem}",
                                        **piece.metadata}})
    return chunks


def build():
    return row_chunks() + doc_chunks()


def push(chunks):
    response = requests.post(f"{RAG_SERVER_URL}/ingest",
                             json={"feature": FEATURE, "replace": True, "chunks": chunks}, timeout=300)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    chunks = build()
    rows = sum(1 for c in chunks if c["metadata"]["tier"] == 1)
    print(f"built {len(chunks)} chunks ({rows} rows, {len(chunks) - rows} doc pieces)")
    print(push(chunks))
