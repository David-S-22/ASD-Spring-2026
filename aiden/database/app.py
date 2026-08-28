from uuid import UUID
from flask import Blueprint, Flask, json, jsonify, request
from sqlalchemy import select, inspect
from werkzeug.exceptions import HTTPException
from .models import Anomaly, db
from .helpers import empty, set_mandatory_field, set_optional_field, try_parse_bool, try_parse_uuid


app = Flask(__name__)
anomalies = Blueprint("anomalies", __name__)


@app.get("/")
def get_index():
    return jsonify(container="anomalies-db")

@anomalies.get("/")
def get_all_anomalies():
    anomalies = db.session.scalars(select(Anomaly)).all()

    return jsonify([a.to_dto() for a in anomalies])

@anomalies.post("/")
def post_anomaly():
    data = request.get_json() or {}
    anomaly = Anomaly()

    set_mandatory_field(anomaly, data, "transaction_id", try_parse_uuid)
    set_mandatory_field(anomaly, data, "agent_reason_suspected", str)
    set_optional_field(anomaly, data, "is_confirmed_by_user", try_parse_bool)

    db.session.add(anomaly)
    db.session.commit()
    db.session.refresh(anomaly)

    return jsonify(anomaly.to_dto()), 201

@anomalies.get("/<uuid:id>")
def get_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)

    return jsonify(anomaly.to_dto())

@anomalies.patch("/<uuid:id>")
def patch_anomaly(id: UUID):
    anomaly = db.get_or_404(Anomaly, id)
    data = request.get_json() or {}

    # Only the following fields are permitted to be mutated once created
    if isinstance(is_confirmed_by_user := try_parse_bool(data.get("is_confirmed_by_user")), bool):
        anomaly.is_confirmed_by_user = is_confirmed_by_user # TODO UT

    if inspect(anomaly, raiseerr=True).modified:
        db.session.commit() # idk about this one

    db.session.refresh(anomaly)

    return jsonify(anomaly.to_dto())

@anomalies.delete("/<uuid:id>")
def delete_anomaly(id: UUID):
    deleted_count = db.session.query(Anomaly).where(Anomaly.id == id).delete()

    assert deleted_count in (0, 1)
    db.session.commit()

    return empty()

@anomalies.delete("/by-transaction/<uuid:id>")
def delete_anomaly_by_id(id: UUID):
    deleted_count = db.session.query(Anomaly).where(Anomaly.transaction_id == id).delete()

    assert deleted_count in (0, 1)
    db.session.commit()

    return empty()

@app.errorhandler(HTTPException)
def handle_exception(e):
    """Return JSON instead of HTML for HTTP errors."""

    response = e.get_response()
    response.content_type = "application/json"
    response.data = json.dumps({
        "code": e.code,
        "name": e.name,
        "description": e.description,
    })

    return response

def setup(db_path: str):
    app.register_blueprint(anomalies, url_prefix="/anomalies")

    with app.app_context():
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
        db.init_app(app)
        db.create_all()
