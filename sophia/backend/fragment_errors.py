"""Shared error-fragment handlers for the HTMX (/ui/*) blueprints."""
from flask import render_template

from sophia.backend.services.errors import ServiceError


def _service_error(error):
    """A ServiceError keeps a 5xx status and otherwise becomes a 422 fragment."""
    status = error.status if error.status >= 500 else 422
    return render_template("error_fragment.html", message=error.message), status


def _unexpected_error(error):
    """Any other exception is a 500 fragment with generic copy, never the upstream text."""
    return render_template("error_fragment.html", message="Something went wrong — try again."), 500


def register_fragment_error_handlers(blueprint):
    """ServiceError keeps a 5xx status or becomes 422; anything else is a 500 with generic copy."""
    blueprint.register_error_handler(ServiceError, _service_error)
    blueprint.register_error_handler(Exception, _unexpected_error)
