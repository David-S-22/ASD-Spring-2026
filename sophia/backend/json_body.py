"""Shared request-body parsing for the JSON (/api/*) routes."""
from flask import request

from sophia.backend.services.errors import ServiceError


def json_body():
    """Return the parsed JSON request body, or raise a 400 ServiceError if it isn't JSON."""
    data = request.get_json(silent=True)
    if data is None:
        raise ServiceError("expected a JSON body", status=400)
    return data
