"""JSON API routes for bills: list/create/read/update/delete, payments, confirm."""
from flask import Blueprint, jsonify, request

from sophia.backend.json_body import json_body
from sophia.backend.services import bills as bills_service

bp = Blueprint("bills", __name__, url_prefix="/api")


@bp.get("/bills")
def list_bills():
    return jsonify(bills_service.list_bills(request.args.get("type"), request.args.get("status")))


@bp.post("/bills")
def create_bill():
    return jsonify(bills_service.create_bill(json_body())), 201


@bp.get("/bills/<int:bill_id>")
def get_bill(bill_id):
    return jsonify(bills_service.get_bill(bill_id))


@bp.put("/bills/<int:bill_id>")
def update_bill(bill_id):
    return jsonify(bills_service.update_bill(bill_id, json_body()))


@bp.delete("/bills/<int:bill_id>")
def delete_bill(bill_id):
    return jsonify(bills_service.delete_bill(bill_id))


@bp.get("/bills/<int:bill_id>/payments")
def list_bill_payments(bill_id):
    return jsonify(bills_service.list_bill_payments(bill_id))


@bp.post("/bills/<int:bill_id>/confirm")
def confirm_bill(bill_id):
    return jsonify(bills_service.confirm_bill(bill_id))
