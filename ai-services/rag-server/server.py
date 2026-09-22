import os

from flask import Flask, jsonify, request

from corpus import refresh
from database import client
from query import MODELS, ask, retrieve

app = Flask(__name__)
PORT = int(os.getenv("RAG_PORT", "5003"))


def to_json(results):
    """Turn retrieved (document, distance) pairs into plain dictionaries."""
    return [{"id": document.id, "text": document.page_content, "metadata": document.metadata, "distance": distance}
            for document, distance in results]


@app.get("/health")
def health():
    """Report the collections in the store and the model for each role."""
    return jsonify({"ok": True, "collections": [collection.name for collection in client.list_collections()], "models": MODELS})


@app.post("/refresh")
def refresh_route():
    """Rebuild a feature's collection from the documents in the request."""
    body = request.get_json()
    total = refresh(body["feature"], body["ids"], body["documents"], body.get("metadatas"))
    return jsonify({"feature": body["feature"], "total": total})


@app.post("/retrieve")
def retrieve_route():
    """Return the documents closest to the question."""
    body = request.get_json()
    results = retrieve(body["feature"], body["question"], body.get("k", 3), body.get("where"))
    return jsonify({"results": to_json(results)})


@app.post("/answer")
def answer_route():
    """Answer the question from a feature's documents with the model for the chosen role."""
    body = request.get_json()
    return jsonify(ask(body["feature"], body["question"], body.get("k", 3), body.get("role", "generation")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
