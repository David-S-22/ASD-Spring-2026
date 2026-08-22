from uuid import UUID

from flask import Flask, abort, jsonify, request
from flask_sqlalchemy.model import Model
from models import Anomaly, db


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify("index page")

@app.post("/anomaly")
def post_anomaly():
    data = request.get_json() or {}
    anomaly = Anomaly()

    set_field_or_error(anomaly, data, "transaction_id", UUID)
    set_field_or_error(anomaly, data, "agent_reason_suspected", str)

    db.session.add(anomaly)
    db.session.commit()
    db.session.refresh(anomaly)

    return anomaly.to_json()

@app.get("/anomaly/<uuid:id>")
def get_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)

    return anomaly.to_json()

@app.patch("/anomaly/<uuid:id>")
def patch_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)
    data = request.get_json() or {}

    # Only the following fields are permitted to be mutated once created
    if isinstance(is_confirmed_by_user := data.get("is_confirmed_by_user"), bool): # I have no idea if this checks the type correctly but I will UT it later I promise
        anomaly.is_confirmed_by_user = is_confirmed_by_user

    return anomaly.to_json()

@app.delete("/anomaly/<uuid:id>")
def delete_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)

    db.session.delete(anomaly)
    db.session.commit()

    return jsonify(deleted=True)

def set_field_or_error(model: Model, data: dict, field_name: str, field_type: type):
    if field_name not in data.keys():
        abort(400, f"Missing required field {field_name}")
    elif not isinstance(value := data.get(field_name), field_type):
        abort(400, f"Field {field_name} expected {field_type.__name__} but was {type(value).__name__}")
    else:
        setattr(model, field_name, value)


if __name__ == "__main__":
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///anomalies.db"

    with app.app_context():
        db.init_app(app)
        db.create_all()

    app.run()
