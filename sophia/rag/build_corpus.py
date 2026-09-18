"""Bills corpus preparation (Lecture 8: ingest -> normalise -> chunk, attach source identity and
authority tier). Writes ai-services/rag-server/corpus/bills.jsonl, one chunk per line, then asks
the RAG server to refresh the Bills rows. Owner: Sophia.

    tier_1  one chunk per database record — bills, payments, disputes from the Bills DB API (:6005),
            written as one plain sentence with money in dollars so the model never computes;
            the record's columns go into metadata so callers can filter (where={"record": "dispute"})
    tier_2  the four approved Bills docs, split into deterministic blocks of up to 80 words

Run with the Bills database and the RAG server up:
    python sophia/rag/build_corpus.py
Env: BILLS_DB_API_URL (http://localhost:6005), RAG_SERVER_URL (http://localhost:5003)."""
import json
import os
import sys
from pathlib import Path

import requests

FEATURE = "bills"
REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "ai-services" / "rag-server" / "corpus" / f"{FEATURE}.jsonl"
BILLS_DB_API_URL = os.environ.get("BILLS_DB_API_URL", "http://localhost:6005")
RAG_SERVER_URL = os.environ.get("RAG_SERVER_URL", "http://localhost:5003")
DOCS = ["sophia/README.md", "docs/release-0/sophia/api.md",
        "docs/release-0/sophia/contracts-inbound.md", "docs/release-0/sophia/schema-adoption.md"]
MAX_WORDS = 80


def dollars(cents):
    return f"${cents / 100:,.2f}"


def get(path):
    r = requests.get(f"{BILLS_DB_API_URL}{path}", timeout=5)
    r.raise_for_status()
    return r.json()


def chunk(chunk_id, source_id, tier, text, **metadata):
    return {"chunk_id": f"{FEATURE}:{chunk_id}", "source_id": source_id, "authority_tier": tier, "text": text,
            "metadata": {k: v for k, v in metadata.items() if v is not None}}


def record_chunks():
    """One chunk per row (tier_1)."""
    bills = {b["id"]: b for b in get("/bills")}
    out = []
    for b in bills.values():
        ended = f", cancelled from {b['end_date']}" if b.get("end_date") else ""
        out.append(chunk(f"bill/{b['id']}", "bills-db:/bills", "tier_1",
            f"Bill #{b['id']} {b['name']} ({b.get('merchant', '')}): {dollars(b['amount_cents'])} {b['cadence']}, "
            f"paid by {b.get('payment_method') or 'an unknown method'}, next billing {b['next_billing_date']}{ended}.",
            record="bill", record_id=b["id"], name=b["name"], merchant=b.get("merchant"), cadence=b["cadence"],
            amount_cents=b["amount_cents"], next_billing_date=b["next_billing_date"], active=not b.get("end_date")))
    for p in get("/payments"):
        name = bills.get(p["bill_id"], {}).get("name", "")
        out.append(chunk(f"payment/{p['id']}", "bills-db:/payments", "tier_1",
            f"Payment #{p['id']} for bill #{p['bill_id']} {name}: {dollars(p['amount_cents'])} on {p['date']}.",
            record="payment", record_id=p["id"], bill_id=p["bill_id"], date=p["date"], amount_cents=p["amount_cents"]))
    for d in get("/disputes"):
        name = bills.get(d["bill_id"], {}).get("name", "")
        opened = str(d.get("created_at", ""))[:10]
        out.append(chunk(f"dispute/{d['id']}", "bills-db:/disputes", "tier_1",
            f"Dispute #{d['id']} for bill #{d['bill_id']} {name}: reason \"{d.get('reason', '')}\", "
            f"status {d.get('status', '')}, opened {opened}.",
            record="dispute", record_id=d["id"], bill_id=d["bill_id"], status=d.get("status"), opened=opened))
    return out


def doc_chunks():
    """Approved docs in deterministic blocks of up to MAX_WORDS words (tier_2)."""
    out = []
    for rel in DOCS:
        path = REPO_ROOT / rel
        if not path.exists():
            print(f"  skip {rel} (missing)", file=sys.stderr)
            continue
        words = path.read_text(encoding="utf-8").split()
        for n, start in enumerate(range(0, len(words), MAX_WORDS), start=1):
            out.append(chunk(f"docs/{path.name}#{n}", rel, "tier_2", " ".join(words[start:start + MAX_WORDS]),
                             doc=path.name, part=n))
    return out


def main():
    chunks = record_chunks() + doc_chunks()
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    records = sum(1 for c in chunks if c["authority_tier"] == "tier_1")
    print(f"wrote {len(chunks)} chunks ({records} records, {len(chunks) - records} doc blocks) -> {CORPUS_PATH.relative_to(REPO_ROOT)}")
    try:
        r = requests.post(f"{RAG_SERVER_URL}/refresh", json={"feature": FEATURE}, timeout=300)
        r.raise_for_status()
        print("refresh:", r.json())
    except requests.RequestException as exc:
        print(f"corpus written; RAG server not refreshed ({exc}). Start it and POST /refresh.", file=sys.stderr)


if __name__ == "__main__":
    main()
