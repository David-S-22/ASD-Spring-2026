import os
import requests
from flask import Flask, abort, jsonify, render_template, request
from shared.backend import dto

from .helpers import object_to_hook


def setup_app(db_url: str) -> Flask:
    app = Flask(__name__)
    db_url = db_url.rstrip("/")

    @app.route("/")
    def home():
        return "<p>Savings Backend</p>", 200

    @app.route("/goals")
    def get_goals():
        resp = requests.get(f"{db_url}/goals")
        resp.raise_for_status()
        goals = resp.json(object_hook=object_to_hook)
        return render_template("goals-table.jinja", goals=goals), 200

    @app.route("/goal", methods=["POST"])
    def create_goal():
        payload = request.get_json(silent=True) or request.form.to_dict()
        try:
            goal = object_to_hook(payload)
            if not isinstance(goal, dto.Goal):
                return jsonify({"error": "Missing goal fields"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        resp = requests.post(f"{db_url}/goal", json=payload)
        resp.raise_for_status()
        return get_goals()

    @app.route("/goal/<int:id>")
    def get_goal(id: int):
        resp = requests.get(f"{db_url}/goal/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        goal = resp.json(object_hook=object_to_hook)
        return render_template("goal-row.jinja", goal=goal), 200

    @app.route("/goal/<int:id>/edit")
    def edit_goal(id: int):
        resp = requests.get(f"{db_url}/goal/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        goal = resp.json(object_hook=object_to_hook)
        return render_template("goal-row-edit.jinja", goal=goal), 200

    @app.route("/goal/<int:id>", methods=["PATCH"])
    def update_goal(id: int):
        payload = request.get_json(silent=True) or request.form.to_dict()
        resp = requests.patch(f"{db_url}/goal/{id}", json=payload)
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        goal = resp.json(object_hook=object_to_hook)
        return render_template("goal-row.jinja", goal=goal), 200

    @app.route("/goal/<int:id>", methods=["DELETE"])
    def delete_goal(id: int):
        resp = requests.delete(f"{db_url}/goal/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        return get_goals()

    @app.route("/suggestions")
    def get_suggestions():
        resp = requests.get(f"{db_url}/suggestions")
        resp.raise_for_status()
        suggestions = resp.json(object_hook=object_to_hook)
        return render_template("suggestions-table.jinja", suggestions=suggestions), 200

    @app.route("/suggestion", methods=["POST"])
    def create_suggestion():
        payload = request.get_json(silent=True) or request.form.to_dict()
        suggestion = object_to_hook(payload)
        if not isinstance(suggestion, dto.Suggestion):
            return jsonify({"error": "Missing suggestion fields"}), 400

        resp = requests.post(f"{db_url}/suggestion", json=payload)
        resp.raise_for_status()
        return get_suggestions()

    @app.route("/suggestion/<int:id>")
    def get_suggestion(id: int):
        resp = requests.get(f"{db_url}/suggestion/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        suggestion = resp.json(object_hook=object_to_hook)
        return render_template("suggestion-row.jinja", suggestion=suggestion), 200

    @app.route("/suggestion/<int:id>/edit")
    def edit_suggestion(id: int):
        resp = requests.get(f"{db_url}/suggestion/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        suggestion = resp.json(object_hook=object_to_hook)
        return render_template("suggestion-row-edit.jinja", suggestion=suggestion), 200

    @app.route("/suggestion/<int:id>", methods=["PATCH"])
    def update_suggestion(id: int):
        payload = request.get_json(silent=True) or request.form.to_dict()
        resp = requests.patch(f"{db_url}/suggestion/{id}", json=payload)
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        suggestion = resp.json(object_hook=object_to_hook)
        return render_template("suggestion-row.jinja", suggestion=suggestion), 200

    @app.route("/suggestion/<int:id>", methods=["DELETE"])
    def delete_suggestion(id: int):
        resp = requests.delete(f"{db_url}/suggestion/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        return get_suggestions()

    @app.route("/feedback")
    def get_feedback():
        resp = requests.get(f"{db_url}/feedbacks")
        resp.raise_for_status()
        feedbacks = resp.json(object_hook=object_to_hook)
        return render_template("feedback-table.jinja", feedbacks=feedbacks), 200

    @app.route("/feedback", methods=["POST"])
    def create_feedback():
        payload = request.get_json(silent=True) or request.form.to_dict()
        feedback = object_to_hook(payload)
        if not isinstance(feedback, dto.Feedback) or not str(feedback.feedback).strip():
            return jsonify({"error": "Missing feedback field"}), 400

        resp = requests.post(f"{db_url}/feedback", json=payload)
        resp.raise_for_status()
        return get_feedback()

    @app.route("/feedback/<int:id>")
    def get_single_feedback(id: int):
        resp = requests.get(f"{db_url}/feedback/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        feedback = resp.json(object_hook=object_to_hook)
        return render_template("feedback-row.jinja", feedback=feedback), 200

    @app.route("/feedback/<int:id>/edit")
    def edit_feedback(id: int):
        resp = requests.get(f"{db_url}/feedback/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        feedback = resp.json(object_hook=object_to_hook)
        return render_template("feedback-row-edit.jinja", feedback=feedback), 200

    @app.route("/feedback/<int:id>", methods=["PATCH"])
    def update_feedback(id: int):
        payload = request.get_json(silent=True) or request.form.to_dict()
        resp = requests.patch(f"{db_url}/feedback/{id}", json=payload)
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        feedback = resp.json(object_hook=object_to_hook)
        return render_template("feedback-row.jinja", feedback=feedback), 200

    @app.route("/feedback/<int:id>", methods=["DELETE"])
    def delete_feedback(id: int):
        resp = requests.delete(f"{db_url}/feedback/{id}")
        if resp.status_code == 404:
            abort(404)
        resp.raise_for_status()
        return get_feedback()

    @app.route("/ai-suggestion")
    def get_ai_suggestion():
        stub_suggestion = "Based on your recent savings goals, you are on track to save an extra $200 by end of quarter."
        return render_template("ai-suggestion.jinja", suggestion=stub_suggestion), 200

    @app.route("/ai-suggestion/accept", methods=["POST"])
    def accept_ai_suggestion():
        stub_suggestion = "Based on your recent savings goals, you are on track to save an extra $200 by end of quarter."
        requests.post(
            f"{db_url}/suggestion",
            json={"suggestion": stub_suggestion, "accepted": True},
        )
        resp = requests.get(f"{db_url}/suggestions")
        suggestions = resp.json(object_hook=object_to_hook) if resp.ok else []
        return render_template(
            "ai-suggestion.jinja",
            suggestion="Suggestion accepted! Added to the Suggestions table.",
            suggestions=suggestions,
        ), 200

    @app.route("/ai-suggestion/reject", methods=["POST"])
    def reject_ai_suggestion():
        stub_suggestion = "Based on your recent savings goals, you are on track to save an extra $200 by end of quarter."
        requests.post(
            f"{db_url}/suggestion",
            json={"suggestion": stub_suggestion, "accepted": False},
        )
        resp = requests.get(f"{db_url}/suggestions")
        suggestions = resp.json(object_hook=object_to_hook) if resp.ok else []
        return render_template(
            "ai-suggestion.jinja",
            suggestion="Suggestion rejected. Recorded in the Suggestions table.",
            suggestions=suggestions,
        ), 200

    return app

if __name__ == "__main__":
    app = setup_app(os.environ.get("DB_URL", "http://localhost:6002"))
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))
