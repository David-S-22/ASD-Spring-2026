from flask import Flask, jsonify


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify(container="ethan-backend")
