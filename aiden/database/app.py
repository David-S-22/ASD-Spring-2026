from uuid import UUID
from flask import Flask, Response, abort, jsonify, request
from .models import Anomaly, db


app = Flask(__name__)

# TODO custom error handlers for abort


@app.get("/")
def get_index():
    return jsonify(container="anomalies-db")

@app.post("/anomaly")
def post_anomaly():
    data = request.get_json() or {}
    anomaly = Anomaly()

    if "transaction_id" not in data:
        abort(400, "Missing required field transaction_id")
    try:
        anomaly.transaction_id = UUID(data["transaction_id"])
    except (AttributeError, TypeError, ValueError):
        abort(400, "Field transaction_id expected UUID")

    if "agent_reason_suspected" not in data:
        abort(400, "Missing required field agent_reason_suspected")
    anomaly.agent_reason_suspected = data["agent_reason_suspected"]

    if "is_confirmed_by_user" in data:
        raw_confirmation = data["is_confirmed_by_user"]

        if isinstance(raw_confirmation, bool):
            anomaly.is_confirmed_by_user = raw_confirmation
        else:
            abort(400, "Field is_confirmed_by_user expected bool")

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

    return empty()

@app.delete("/anomaly/by-transaction/<uuid:id>")
def delete_anomaly_by_id(id: UUID):
    deleted_count = db.session.query(Anomaly).where(Anomaly.transaction_id == id).delete()

    assert deleted_count in (0, 1)
    db.session.commit()

    return empty()

def setup(db_path: str):
    with app.app_context():
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
        db.init_app(app)
        db.create_all()

def empty():
    return Response(status=204)
