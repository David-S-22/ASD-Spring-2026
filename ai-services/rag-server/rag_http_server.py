"""HTTP face of the shared RAG server (Lab 8 rag_http_server, in Flask like every Tally backend).

    GET  /health                       status + what is indexed
    POST /refresh   {feature?}         refresh_corpus
    POST /retrieve  {query, k?, feature?, where?}
    POST /answer    {query, k?, feature?, model?}
    GET  /chunks?feature=bills&limit=  what is indexed for a feature (knowledge-sources evidence)

Runs on the host (python rag_http_server.py), never in Docker Compose, and listens on 127.0.0.1
only: its one application client is the shared MCP server's context tool on the same host.
Containers cannot reach 127.0.0.1 through host.docker.internal, so backends have no direct path;
host-side validation (curl, rag_eval.py, the agentic loop) uses http://localhost:5003."""
import json
import os

from flask import Flask, jsonify, request

import rag_pipeline as rag

app = Flask(__name__)
HOST = os.getenv("RAG_HOST", "127.0.0.1")
PORT = int(os.getenv("RAG_PORT", "5003"))


def _body():
    return request.get_json(silent=True) or request.form.to_dict() or {}


def _where(raw):
    return json.loads(raw) if isinstance(raw, str) and raw else (raw or None)


@app.errorhandler(ValueError)
def bad_request(exc):
    return jsonify({"status": "error", "error": "bad_request", "detail": str(exc)}), 400


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "rag-server", "collection": rag.COLLECTION_NAME,
                    "max_distance": rag.MAX_DISTANCE, "features": rag.indexed_features()})


@app.post("/refresh")
def refresh():
    return jsonify(rag.refresh_corpus((_body().get("feature") or "").strip() or None))


@app.post("/retrieve")
def retrieve():
    body = _body()
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400
    return jsonify(rag.retrieve_context(query, int(body.get("k") or rag.DEFAULT_K),
                                        (body.get("feature") or "").strip() or None, _where(body.get("where"))))


@app.post("/answer")
def answer():
    body = _body()
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400
    result = rag.answer_question(query, int(body.get("k") or rag.DEFAULT_K),
                                 (body.get("feature") or "").strip() or None, (body.get("model") or "").strip() or None)
    return jsonify(result), (502 if result.get("status") == "error" else 200)


@app.get("/chunks")
def chunks():
    feature = (request.args.get("feature") or "").strip()
    if not feature:
        return jsonify({"status": "error", "error": "feature is required"}), 400
    col = rag.get_collection()
    limit = request.args.get("limit")
    got = col.get(where={"feature": feature}, limit=int(limit) if limit else None) if col.count() else {"ids": [], "documents": [], "metadatas": []}
    rows = [{"chunk_id": i, **(m or {}), "text": t} for i, t, m in zip(got["ids"], got["documents"], got["metadatas"])]
    return jsonify({"status": "success", "feature": feature, "count": len(rows), "chunks": rows})


if __name__ == "__main__":
    print(f"RAG HTTP server running on {HOST}:{PORT} · indexed {rag.indexed_features()}")
    app.run(host=HOST, port=PORT)
