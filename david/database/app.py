from dataclasses import asdict
from flask import abort
from flask import jsonify
from flask import request
from models import Goal, Feedback, Suggestion, db
from flask import Flask
import os
import datetime

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(os.getcwd(), "savings.db")}"
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route("/goals")
def get_goals():
    goals = db.session.execute(db.select(Goal)).scalars().all()
    if (len(goals) == 0):
        return abort(404)

    return jsonify([asdict(goal) for goal in goals])

@app.route("/suggestions")
def get_suggestions():
    suggestions = db.session.execute(db.select(Suggestion)).scalars().all()
    if (len(suggestions) == 0):
        return abort(404)

    return jsonify([asdict(suggestion) for suggestion in suggestions])

@app.route("/feedbacks")
def get_feedbacks():
    feedbacks = db.session.execute(db.select(Feedback)).scalars().all()
    if (len(feedbacks) == 0):
        return abort(404)

    return jsonify([asdict(feedback) for feedback in feedbacks])

@app.route("/goal/<int:id>")
def get_goal(id: int):
    return jsonify(asdict(db.get_or_404(Goal, id)))

@app.route("/suggestion/<int:id>")
def get_suggestion(id: int):
    return jsonify(asdict(db.get_or_404(Suggestion, id)))

@app.route("/feedback/<int:id>")
def get_feedback(id: int):
    return jsonify(asdict(db.get_or_404(Feedback, id)))

@app.route("/goal/add", methods=["POST"])
def add_goal_route():
    payload = request.get_json()

    if "name" not in payload:
        return jsonify({"error": "Missing goal field: name"}), 400
    if "amount" not in payload:
        return jsonify({"error": "Missing goal field: amount"}), 400
    if "date" not in payload:
        return jsonify({"error": "Missing goal field: date"}), 400

    goal = Goal(
        name=payload["name"],
        amount=int(payload["amount"]),
        date=datetime.datetime.fromisoformat(payload["date"])
    )

    db.session.add(goal)
    db.session.commit()
    return jsonify(asdict(goal)), 201


@app.route("/suggestion/add", methods=["POST"])
def add_suggestion_route():
    payload = request.get_json()

    if "suggestion" not in payload:
        return jsonify({"error": "Missing suggestion field"}), 400

    suggestion = Suggestion(suggestion=payload["suggestion"])
    db.session.add(suggestion)
    db.session.commit()
    return jsonify(asdict(suggestion)), 201


@app.route("/feedback/add", methods=["POST"])
def add_feedback_route():
    payload = request.get_json()

    if "feedback" not in payload:
        return jsonify({"error": "Missing feedback field"}), 400

    feedback = Feedback(feedback=payload["feedback"])
    db.session.add(feedback)
    db.session.commit()
    return jsonify(asdict(feedback)), 201


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
    return jsonify(asdict(feedback_to_update)), 200


@app.route("/suggestion/<int:id>", methods=["PATCH"])
def update_suggestion(id: int):
    suggestion_to_update = db.session.get(Suggestion, id)
    if not suggestion_to_update:
        return abort(404)

    updated_suggestion = request.get_json() or {}
    if "suggestion" not in updated_suggestion:
        return jsonify({"error": "Missing suggestion field"}), 400

    suggestion_to_update.suggestion = updated_suggestion["suggestion"]
    db.session.commit()
    return jsonify(asdict(suggestion_to_update)), 200


@app.route("/goal/<int:id>", methods=["PATCH"])
def update_goal(id: int):
    goal_to_update = db.session.get(Goal, id)
    if not goal_to_update:
        return abort(404)

    updated_goal = request.get_json() or {}
    if "name" not in updated_goal and "amount" not in updated_goal and "date" not in updated_goal:
        return jsonify({"error": "No valid fields provided"}), 400

    if "name" in updated_goal:
        goal_to_update.name = updated_goal["name"]
    if "amount" in updated_goal:
        goal_to_update.amount = updated_goal["amount"]
    if "date" in updated_goal:
        goal_to_update.date = datetime.datetime.fromisoformat(updated_goal["date"])

    db.session.commit()
    return jsonify(asdict(goal_to_update)), 200


@app.route("/goal/delete/<int:id>", methods=["DELETE"])
def delete_goal_route(id: int):
    goal = db.session.get(Goal, id)
    if goal is None:
        return abort(404)

    db.session.delete(goal)
    db.session.commit()
    return "", 204


@app.route("/suggestion/delete/<int:id>", methods=["DELETE"])
def delete_suggestion_route(id: int):
    suggestion = db.session.get(Suggestion, id)
    if suggestion is None:
        return abort(404)

    db.session.delete(suggestion)
    db.session.commit()
    return "", 204


@app.route("/feedback/delete/<int:id>", methods=["DELETE"])
def delete_feedback_route(id: int):
    feedback = db.session.get(Feedback, id)
    if feedback is None:
        return abort(404)

    db.session.delete(feedback)
    db.session.commit()
    return "", 204

app.run(host="0.0.0.0", port=5002)
