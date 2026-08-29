from uuid import uuid4
import random
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
    anomaly = dto.Anomaly(
        id=uuid4(),
        transactfion_id=uuid4(),
        agent_reason_suspected="hello",
        is_confirmed_by_user=random.choice((True, False, None)),
    )

    anomalies_api.create_anomaly(anomaly)
    return get_anomaly_rows()
