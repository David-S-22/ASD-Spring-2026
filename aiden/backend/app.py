import random
from flask import Flask, abort, jsonify, request

app = Flask(__name__)

@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.get("/all-anomalies")
def get_all_anomalies():
    abort(418)

@app.post("/dummy-anomaly")
def create_dummy_anomaly():
    abort(418)
