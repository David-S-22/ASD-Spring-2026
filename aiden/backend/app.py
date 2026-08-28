import os
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
    abort(418)

def get_env(name: str) -> str:
    return os.environ[name]
