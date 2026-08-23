import random
from flask import Flask, abort, jsonify, request

app = Flask(__name__)

@app.get("/")
def get_index():
    return jsonify(container="anomalies-backend")

@app.post("/check-new-transaction-for-anomalies")
def post_newtransaction():
    if random.choice((True, False)):
        return jsonify(ok=True)

    return abort(400)
