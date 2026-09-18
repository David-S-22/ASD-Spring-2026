"""HTTP face of the shared RAG server: /health, /chunks, /benchmarks, /refresh, /retrieve.
Runs on the host (python server.py), never inside Docker Compose, and listens on 127.0.0.1 only.
Its one application client is the MCP server's context tool (also on the host), which reaches it
at http://localhost:5003. Feature backends never call it directly — they call the MCP tool.
Host-side validation (curl, eval.py, the agentic loop) uses the same localhost address."""
import json

from flask import Flask, jsonify, request

import config
import corpus
import rag

app = Flask(__name__)


def _body():
    """Accept JSON or a form post, so curl, htmx and Python clients all work."""
    return request.get_json(silent=True) or request.form.to_dict() or {}


def _where(raw):
    """`where` arrives as a JSON object, or as a JSON string in a form post / query string."""
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


@app.errorhandler(rag.ModelUnavailable)
def model_unavailable(exc):
    return jsonify({"status": "error", "error": "model_unavailable", "detail": str(exc)}), 502


@app.errorhandler(ValueError)
def bad_request(exc):
    return jsonify({"status": "error", "error": "bad_request", "detail": str(exc)}), 400


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "rag-server", "embed_model": config.EMBED_MODEL,
                    "max_distance": config.MAX_DISTANCE, "features": rag.indexed_features()})


@app.get("/chunks")
def chunks():
    """What is indexed: GET /chunks?feature=bills&limit=20, or &where={"record":"dispute"}."""
    feature = (request.args.get("feature") or "").strip()
    if not feature:
        return jsonify({"status": "error", "error": "feature is required"}), 400
    limit = request.args.get("limit")
    return jsonify(rag.chunks(feature, where=_where(request.args.get("where")), limit=int(limit) if limit else None))


@app.get("/benchmarks")
def benchmarks():
    """Every feature's BENCHMARKS, so the agentic loop's RAG mode can run them over HTTP."""
    return jsonify({"status": "success",
                    "benchmarks": {name: corpus.benchmarks(name) for name in corpus.features()}})


@app.post("/refresh")
def refresh():
    """Re-read every feature's sources, or one: POST /refresh {"feature": "bills"}."""
    return jsonify(rag.refresh_corpus(feature=(_body().get("feature") or "").strip() or None))


@app.post("/retrieve")
def retrieve():
    """POST /retrieve {"query": "...", "feature": "bills", "k": 5, "where": {...}}"""
    body = _body()
    query = (body.get("query") or "").strip()
    feature = (body.get("feature") or "").strip()
    if not query or not feature:
        return jsonify({"status": "error", "error": "query and feature are required"}), 400
    k = int(body.get("k") or config.DEFAULT_K)
    return jsonify(rag.retrieve_context(query, feature, k, _where(body.get("where"))))


if __name__ == "__main__":
    print(f"RAG server on http://{config.HOST}:{config.PORT} · embed {config.EMBED_MODEL} · indexed {rag.indexed_features()}")
    app.run(host=config.HOST, port=config.PORT)
