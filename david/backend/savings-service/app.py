from flask import render_template
from datetime import datetime
import os
import requests
from flask import Flask, jsonify
from shared.backend import dto
from .helpers import object_to_hook

def setup_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def home():
        return "<p>Savings Backend<p>", 200

    @app.route("/goals")
    def get_goals():
        db_url = os.environ.get("DB_URL", "http://localhost:6002")
        resp = requests.get(f"{db_url}/goals")
        resp.raise_for_status()
        goals = resp.json(object_hook=object_to_hook)
        return render_template("goals-table.jinja", goals=goals), 200

    @app.route("/goal", methods=["POST"])
    def create_dummy_goal():
        dummy_goal = dto.Goal(
            id=0,
            name="Emergency Fund",
            cost=1000,
            date=datetime(2026, 12, 31),
        )
        db_url = os.environ.get("DB_URL", "http://localhost:6002")
        payload = {
            "name": dummy_goal.name,
            "cost": dummy_goal.cost,
            "date": dummy_goal.date.isoformat(),
        }
        resp = requests.post(f"{db_url}/goal", json=payload)
        resp.raise_for_status()
        created_goal = resp.json(object_hook=object_to_hook)
        return jsonify(created_goal), 201

    @app.route("/feedback")
    def get_feedback():
        db_url = os.environ.get("DB_URL", "http://localhost:6002")
        resp = requests.get(f"{db_url}/feedbacks")
        resp.raise_for_status()
        feedbacks = resp.json(object_hook=object_to_hook)
        return jsonify(feedbacks), 200

    @app.route("/feedback", methods=["POST"])
    def create_dummy_feedback():
        dummy_feedback = dto.Feedback(
            id=0,
            feedback="Great app for tracking goals!",
        )
        db_url = os.environ.get("DB_URL", "http://localhost:6002")
        payload = {
            "feedback": dummy_feedback.feedback,
        }
        resp = requests.post(f"{db_url}/feedback", json=payload)
        resp.raise_for_status()
        created_feedback = resp.json(object_hook=object_to_hook)
        return jsonify(created_feedback), 201

    @app.route("/suggestions")
    def get_suggestion():
        db_url = os.environ.get("DB_URL", "http://localhost:6002")
        resp = requests.get(f"{db_url}/suggestions")
        resp.raise_for_status()
        suggestions = resp.json(object_hook=object_to_hook)
        return jsonify(suggestions), 200

    @app.route("/suggestion", methods=["POST"])
    def create_dummy_suggestion():
        dummy_suggestion = dto.Suggestion(
            id=0,
            suggestion="Save 10% of income every month",
        )
        db_url = os.environ.get("DB_URL", "http://localhost:6002")
        payload = {
            "suggestion": dummy_suggestion.suggestion,
        }
        resp = requests.post(f"{db_url}/suggestion", json=payload)
        resp.raise_for_status()
        created_suggestion = resp.json(object_hook=object_to_hook)
        return jsonify(created_suggestion), 201

    return app

if __name__ == "__main__":
    app = setup_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))
