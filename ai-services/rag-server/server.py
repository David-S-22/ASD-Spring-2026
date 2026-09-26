import logging
import os
import sys
import threading

# Prioritize local directory for imports
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request

from corpus import ingest_sources, refresh
from database import client
from query import retrieve

logger = logging.getLogger(__name__)

rag_lock = threading.Lock()

app = Flask(__name__)
PORT = int(os.getenv("RAG_PORT", "5003"))


def to_json(results):
    """Turn retrieved (document, distance) pairs into plain dictionaries."""
    return [
        {
            "id": document.id,
            "text": document.page_content,
            "metadata": document.metadata,
            "distance": distance,
        }
        for document, distance in results
    ]


@app.get("/health")
def health():
    """Report the collections in the store."""
    return jsonify(
        {"ok": True, "collections": [collection.name for collection in client.list_collections()]}
    )


@app.post("/refresh")
def refresh_route():
    """Rebuild a feature's collection from the documents in the request."""
    body = request.get_json()
    with rag_lock:
        total = refresh(body["feature"], body["ids"], body["documents"], body.get("metadatas"))
    return jsonify({"feature": body["feature"], "total": total})


@app.post("/retrieve")
def retrieve_route():
    """Return the documents closest to the question."""
    body = request.get_json()
    with rag_lock:
        results = retrieve(body["feature"], body["question"], body.get("k", 3), body.get("where"))
    return jsonify({"results": to_json(results)})


@app.post("/sources/refresh")
def refresh_sources_route():
    """Re-ingest all documents from the sources directory."""
    with rag_lock:
        results = ingest_sources()
    return jsonify({"ok": True, "sources": results})


# Ingest documents from sources/ on startup
if os.getenv("RAG_AUTO_INGEST", "true").lower() == "true":
    try:
        ingested = ingest_sources()
        logger.info(f"RAG server startup ingestion complete: {ingested}")
    except Exception as e:
        logger.error(f"Error during RAG server startup ingestion: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
