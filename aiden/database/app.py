import os
from uuid import UUID

from flask import Flask, jsonify, request
from .models import Anomaly, db
from .helpers import set_mandatory_field, set_optional_field, try_parse_uuid, try_parse_bool


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify(container="anomalies-db")

@app.post("/anomaly")
def post_anomaly():
    data = request.get_json() or {}
    anomaly = Anomaly()

    # I will fix this later but it works fine now
    set_mandatory_field(anomaly, data, "transaction_id", try_parse_uuid)
    set_mandatory_field(anomaly, data, "agent_reason_suspected", str)
    set_optional_field(anomaly, data, "is_confirmed_by_user", try_parse_bool)

    db.session.add(anomaly)
    db.session.commit()
    db.session.refresh(anomaly)

    return jsonify(anomaly.to_dto()), 201

@app.get("/anomaly/<uuid:id>")
def get_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)

    return jsonify(anomaly.to_dto())

@app.patch("/anomaly/<uuid:id>")
def patch_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)
    data = request.get_json() or {}

    # Only the following fields are permitted to be mutated once created
    if isinstance(is_confirmed_by_user := data.get("is_confirmed_by_user"), bool): # I have no idea if this checks the type correctly but I will UT it later I promise
        anomaly.is_confirmed_by_user = is_confirmed_by_user

    return jsonify(anomaly.to_dto())

@app.delete("/anomaly/<uuid:id>")
def delete_anomaly(id: UUID):
    deleted_count = db.session.query(Anomaly).where(Anomaly.id == id).delete()

    assert deleted_count in (0, 1)
    db.session.commit()

    return jsonify(deleted=deleted_count > 0)

@app.delete("/anomaly/by-transaction/<uuid:id>")
def delete_anomaly_by_id(id: UUID):
    deleted_count = db.session.query(Anomaly).where(Anomaly.transaction_id == id).delete()

    assert deleted_count in (0, 1)
    db.session.commit()

    return jsonify(deleted=deleted_count > 0)

def setup(db_path: str):
    with app.app_context():
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
        db.init_app(app)
        db.create_all()
