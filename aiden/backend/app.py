import os
from random import choice, randint

from flask import Flask, abort, jsonify, render_template, request

from shared.backend import dto
from .helpers import deserialise_or_abort, get_env
from .services import anomalies_api, ollama_api, review_queue, transaction_api


app = Flask(__name__)
review_queue.start_worker(app)

# How long the /anomaly-alert endpoint long-polls for a new anomaly before
# returning empty so the client can re-poll.
ANOMALY_WAIT_SECONDS = float(os.environ.get("ANOMALY_WAIT_SECONDS", "60"))


@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.get("/fact")
def get_fact():
    return ollama_api.prompt(
        system_prompt="You are a helpful assistant",
        user_prompt="tell me a random fact",
        model=get_env("OLLAMA_MODEL"),
        temperature=0.5,
        output_tokens=500)

@app.get("/anomalies")
def get_anomaly_rows():
    anomalies = anomalies_api.get_all_anomalies()
    transactions = {t.id: t for t in transaction_api.get_all_transactions()}

    return render_template("anomalies.jinja", anomalies=anomalies, transactions=transactions)

@app.post("/check-transaction")
def check_transaction():
    data = request.get_json() or {}
    transaction = deserialise_or_abort(dto.Transaction, data)

    review_queue.enqueue(transaction)
    app.logger.info("Queued transaction %s for anomaly review", transaction.id)

    return jsonify(status="queued", transaction_id=transaction.id), 202

@app.get("/anomaly-alert")
def wait_for_anomaly_alert():
    """Wait for a specific queued transaction to finish review, then report it.

    The client passes the `key` (the transaction id returned by
    /check-transaction). Blocks for up to ANOMALY_WAIT_SECONDS until that item
    has been reviewed. Returns the alert HTML if the transaction was flagged as
    anomalous, otherwise 204 (no anomaly, still processing, or unknown key) so
    the client can re-poll.
    """
    key = request.args.get("key", type=int)
    if key is None:
        abort(400, "missing 'key' query parameter")

    anomaly = review_queue.wait_for_result(key, timeout=ANOMALY_WAIT_SECONDS)

    if anomaly is None:
        return "", 204

    return render_template("alert.jinja", anomaly=anomaly)

@app.post("/anomalies/<int:id>/confirm")
def confirm_anomaly(id: int):
    anomalies_api.set_confirmation(id, True)
    return get_anomaly_rows()

@app.post("/anomalies/<int:id>/dismiss")
def dismiss_anomaly(id: int):
    anomalies_api.set_confirmation(id, False)
    return get_anomaly_rows()

@app.post("/dummy-anomaly")
def create_dummy_anomaly():
    anomaly = dto.Anomaly(
        id=0,
        transaction_id=randint(1, 1_000_000_000),
        agent_reason_suspected="hello",
        is_confirmed_by_user=choice((True, False, None)),
    )

    anomalies_api.create_anomaly(anomaly)
    return get_anomaly_rows()
