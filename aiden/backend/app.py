from random import choice
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

from shared.backend import dto
from .helpers import deserialise_or_abort, empty
from .services import anomalies_api, ollama_api, agent_api


app = Flask(__name__)

@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.get("/fact")
def get_fact():
    return ollama_api.prompt("You are a helpful assistant", "tell me a random fact")

@app.get("/anomalies")
def get_anomaly_rows():
    anomalies = anomalies_api.get_all_anomalies()

    return render_template("anomalies.jinja", anomalies=anomalies)

@app.post("/check-transaction")
def check_transaction():
    data = request.get_json() or {}
    transaction = deserialise_or_abort(dto.Transaction, data)

    anomaly = agent_api.review_transaction(transaction)

    if anomaly is None:
        return empty()

    return render_template("alert.jinja", anomaly=anomaly)

@app.post("/dummy-anomaly")
def create_dummy_anomaly():
    anomaly = dto.Anomaly(
        id=uuid4(),
        transaction_id=uuid4(),
        agent_reason_suspected="hello",
        is_confirmed_by_user=choice((True, False, None)),
    )

    anomalies_api.create_anomaly(anomaly)
    return get_anomaly_rows()
