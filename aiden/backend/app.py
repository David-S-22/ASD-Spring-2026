import os
from flask import Flask, abort, jsonify
from shared.backend import dto
from .services import anomalies_api

app = Flask(__name__)

@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.get("/all-anomalies")
def get_all_anomalies():
    app.logger.warning("getting anomalies")
    for anomaly in anomalies_api.get_all_anomalies():
        app.logger.debug("got anomaly", anomaly)

    abort(418)

@app.post("/dummy-anomaly")
def create_dummy_anomaly():
    abort(418)

def get_env(name: str) -> str:
    return os.environ[name]
