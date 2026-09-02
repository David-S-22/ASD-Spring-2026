from random import choice, randint

from flask import Flask, jsonify, render_template, request

from shared.backend import dto
from . import config
from .helpers import deserialise_or_abort, empty
from .services import anomalies_api, ollama_api, agent_api, transaction_api


app = Flask(__name__)

@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.get("/fact")
def get_fact():
    return ollama_api.prompt(
        system_prompt="You are a helpful assistant",
        user_prompt="tell me a random fact",
        model=config.OLLAMA_MODEL,
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
    all_anomalies = anomalies_api.get_all_anomalies()
    all_transactions = transaction_api.get_all_transactions()

    app.logger.info("Checking transaction %s (merchant=%r, amount=%s)", transaction.id, transaction.merchant, transaction.amount)
    anomaly = agent_api.review_new_transaction(transaction, all_anomalies, all_transactions)

    if anomaly is None:
        app.logger.warning("Transaction %s cleared (no anomaly) -> 204", transaction.id)
        return empty()

    app.logger.warning("Transaction %s flagged as anomalous: %s",
                       transaction.id, anomaly.agent_reason_suspected)

    # Save new anomaly to the database
    anomalies_api.create_anomaly(anomaly)

    return render_template("alert.jinja", anomaly=anomaly)

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
