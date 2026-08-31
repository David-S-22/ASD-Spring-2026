from flask import abort
from flask import jsonify
from flask import request
from .models import Goal, Feedback, Suggestion, db
from .helpers import try_parse_bool
from flask import Flask
import os
import datetime

def setup_app(database_path) -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database_path}"
    db.init_app(app)
    with app.app_context():
        db.create_all()
    
    @app.route("/goals")
    def get_goals():
        goals = db.session.execute(db.select(Goal)).scalars().all()
        return jsonify([goal.to_dto() for goal in goals])

    @app.route("/suggestions")
    def get_suggestions():
        suggestions = db.session.execute(db.select(Suggestion)).scalars().all()
        return jsonify([suggestion.to_dto() for suggestion in suggestions])

    @app.route("/feedbacks")
    def get_feedbacks():
        feedbacks = db.session.execute(db.select(Feedback)).scalars().all()
        return jsonify([feedback.to_dto() for feedback in feedbacks])

    @app.route("/goal/<int:id>")
    def get_goal(id: int):
        return jsonify(db.get_or_404(Goal, id).to_dto())

    @app.route("/suggestion/<int:id>")
    def get_suggestion(id: int):
        return jsonify(db.get_or_404(Suggestion, id).to_dto())

    @app.route("/feedback/<int:id>")
    def get_feedback(id: int):
        return jsonify(db.get_or_404(Feedback, id).to_dto())

    @app.route("/goal", methods=["POST"])
    def add_goal_route():
        payload = request.get_json()

        if "name" not in payload:
            return jsonify({"error": "Missing goal field: name"}), 400
        if "cost" not in payload:
            return jsonify({"error": "Missing goal field: amount"}), 400
        if "date" not in payload:
            return jsonify({"error": "Missing goal field: date"}), 400

        goal = Goal(
            name = payload["name"],
            cost = int(payload["cost"]),
            date = datetime.datetime.fromisoformat(payload["date"])
        )

        db.session.add(goal)
        db.session.commit()
        return jsonify(goal.to_dto()), 201


    @app.route("/suggestion", methods=["POST"])
    def add_suggestion_route():
        payload = request.get_json()

        if not payload or "suggestion" not in payload:
            return jsonify({"error": "Missing suggestion field"}), 400

        accepted_val = try_parse_bool(payload.get("accepted"))
        if accepted_val is None:
            return jsonify({"error": "Missing accepted field"}), 400

        suggestion = Suggestion(
            suggestion=payload["suggestion"],
            accepted=accepted_val,
        )
        db.session.add(suggestion)
        db.session.commit()
        return jsonify(suggestion.to_dto()), 201


    @app.route("/feedback", methods=["POST"])
    def add_feedback_route():
        payload = request.get_json()

        if "feedback" not in payload:
            return jsonify({"error": "Missing feedback field"}), 400

        feedback = Feedback(feedback=payload["feedback"])
        db.session.add(feedback)
        db.session.commit()
        return jsonify(feedback.to_dto()), 201


    @app.route("/feedback/<int:id>", methods=["PATCH"])
    def update_feedback(id: int):
        feedback_to_update = db.session.get(Feedback, id)
        if not feedback_to_update:
            return abort(404)

        updated_feedback = request.get_json() or {}
        if "feedback" not in updated_feedback:
            return jsonify({"error": "Missing feedback field"}), 400

        feedback_to_update.feedback = updated_feedback["feedback"]
        db.session.commit()
        return jsonify(feedback_to_update.to_dto()), 200


    @app.route("/suggestion/<int:id>", methods=["PATCH"])
    def update_suggestion(id: int):
        suggestion_to_update = db.session.get(Suggestion, id)
        if not suggestion_to_update:
            return abort(404)

        updated_suggestion = request.get_json() or {}
        if "suggestion" not in updated_suggestion and "accepted" not in updated_suggestion:
            return jsonify({"error": "Missing suggestion or accepted field"}), 400

        if "suggestion" in updated_suggestion:
            suggestion_to_update.suggestion = updated_suggestion["suggestion"]

        if "accepted" in updated_suggestion:
            accepted_val = try_parse_bool(updated_suggestion["accepted"])
            if accepted_val is None:
                return jsonify({"error": "Invalid accepted field"}), 400
            suggestion_to_update.accepted = accepted_val

        db.session.commit()
        return jsonify(suggestion_to_update.to_dto()), 200


    @app.route("/goal/<int:id>", methods=["PATCH"])
    def update_goal(id: int):
        goal_to_update = db.session.get(Goal, id)
        if not goal_to_update:
            return abort(404)

        updated_goal = request.get_json()
        if "name" not in updated_goal and "amount" not in updated_goal and "date" not in updated_goal and "cost" not in updated_goal:
            return jsonify({"error": "No valid fields provided"}), 400

        if "name" in updated_goal:
            goal_to_update.name = updated_goal["name"]
        if "cost" in updated_goal:
            goal_to_update.cost = int(updated_goal["cost"])
        if "date" in updated_goal:
            goal_to_update.date = datetime.datetime.fromisoformat(updated_goal["date"])

        db.session.commit()
        return jsonify(goal_to_update.to_dto()), 200


    @app.route("/goal/<int:id>", methods=["DELETE"])
    def delete_goal_route(id: int):
        goal = db.session.get(Goal, id)
        if goal is None:
            return abort(404)

        db.session.delete(goal)
        db.session.commit()
        return "", 204


    @app.route("/suggestion/<int:id>", methods=["DELETE"])
    def delete_suggestion_route(id: int):
        suggestion = db.session.get(Suggestion, id)
        if suggestion is None:
            return abort(404)

        db.session.delete(suggestion)
        db.session.commit()
        return "", 204


    @app.route("/feedback/<int:id>", methods=["DELETE"])
    def delete_feedback_route(id: int):
        feedback = db.session.get(Feedback, id)
        if feedback is None:
            return abort(404)

        db.session.delete(feedback)
        db.session.commit()
        return "", 204

    return app

if __name__ == "__main__":
    app = setup_app(os.environ.get("DB_PATH", "savings.db"))
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 6002)))
