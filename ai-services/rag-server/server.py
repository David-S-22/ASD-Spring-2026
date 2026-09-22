import os

from flask import Flask, jsonify, request

from corpus import refresh
from database import client

app = Flask(__name__)
PORT = int(os.getenv("RAG_PORT", "5003"))


@app.get("/health")
def health():
    """Report the collections in the store."""
    return jsonify({"ok": True, "collections": [collection.name for collection in client.list_collections()]})


@app.post("/refresh")
def refresh_route():
    """Rebuild a feature's collection from the documents in the request."""
    body = request.get_json()
    total = refresh(body["feature"], body["ids"], body["documents"], body.get("metadatas"))
    return jsonify({"feature": body["feature"], "total": total})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
