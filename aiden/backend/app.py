from random import choice, randint

from flask import Flask, jsonify, render_template, request

from shared.backend import dto
from .helpers import deserialise_or_abort, get_env
from .services import anomalies_api, ollama_api
from . import review_queue


app = Flask(__name__)

review_queue.start_worker(app)

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

    return render_template("anomalies.jinja", anomalies=anomalies)

@app.post("/check-transaction")
def check_transaction():
    data = request.get_json() or {}
    transaction = deserialise_or_abort(dto.Transaction, data)

    review_queue.enqueue(transaction)
    app.logger.info("Queued transaction %s for anomaly review", transaction.id)

    return jsonify(status="queued", transaction_id=transaction.id), 202

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
