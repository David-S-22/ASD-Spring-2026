"""JSON API routes for payments; each write recomputes and stores the owning bill's status."""
from flask import Blueprint, jsonify

from sophia.backend.json_body import json_body
from sophia.backend.services import payments as payments_service

bp = Blueprint("payments", __name__, url_prefix="/api")


@bp.post("/payments")
def create_payment():
    return jsonify(payments_service.create_payment(json_body())), 201


@bp.put("/payments/<int:payment_id>")
def update_payment(payment_id):
    return jsonify(payments_service.update_payment(payment_id, json_body()))


@bp.delete("/payments/<int:payment_id>")
def delete_payment(payment_id):
    return jsonify(payments_service.delete_payment(payment_id))
