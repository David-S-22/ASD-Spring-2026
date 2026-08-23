from flask import abort
from flask import jsonify
from models import Goal, Feedback, Suggestion, db
from flask import Flask
import os

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

    return jsonify(goals)

@app.route("/suggestions")
def get_suggestions():
    suggestions = db.session.execute(db.select(Suggestion)).scalars().all()
    if (len(suggestions) == 0):
        return abort(404)

    return jsonify(suggestions)

@app.route("/feedbacks")
def get_feedbacks():
    feedbacks = db.session.execute(db.select(feedbacks)).scalars().all()
    if (len(feedbacks) == 0):
        return abort(404)

    return jsonify(feedbacks)

@app.route("/goal/<int:id>")
def get_goal(id: int):
    return db.get_or_404(Goal, id).to_dict()

@app.route("/suggestion/<int:id>")
def get_suggestion(id: int):
    db.get_or_404(Suggestion, id).to_dict()

@app.route("/feedback/<int:id>")
def get_feedback(id: int):
    db.get_or_404(Feedback, id).to_dict()

app.run(host="0.0.0.0", port=5002)
