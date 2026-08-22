from flask import Flask, jsonify, request
from models import db, Anomaly
from uuid import UUID

app = Flask(__name__)
app.config["SQLITE_DATABASE_URI"] = "sqlite:///aiden.db"


@app.get("/")
def get_index():
    return jsonify("index page")


@app.get("/anomaly/<uuid:id>")
def get_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)

    return anomaly.to_json()

@app.patch("/anomaly/<uuid:id>")
def patch_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)
    data = request.get_json() or {}

    # Only the following fields are permitted to be mutated once created
    if (isinstance(is_confirmed_by_user := data.get("is_confirmed_by_user"), bool)): # I have no idea if this checks the type correctly but I will UT it later I promise
        anomaly.is_confirmed_by_user = is_confirmed_by_user

    return anomaly.to_json()

@app.delete("/anomaly/<uuid:id>")
def delete_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)

    db.session.delete(anomaly)
    db.session.commit()

    return jsonify(deleted=True)


if __name__ == "__main__":
    with app.app_context():
        db.init_app(app)
        db.create_all()

    app.run()
