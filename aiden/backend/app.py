from flask import Flask, abort, jsonify, render_template
from shared.backend import dto
from .services import anomalies_api

app = Flask(__name__)

@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.get("/anomalies")
def get_anomaly_rows():
    anomalies = anomalies_api.get_all_anomalies()

    return render_template("anomalies.jinja", anomalies=anomalies)

@app.post("/dummy-anomaly")
def create_dummy_anomaly():
    model = dto.Anomaly(transaction_id="dummy-transaction-id", agent_reason_suspected="hello")
    anomalies_api.create_anomaly(model)

    return get_anomaly_rows()
