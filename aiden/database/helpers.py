from typing import Any, Callable, Optional
from uuid import UUID

from flask import Response, abort
from flask_sqlalchemy.model import Model


def set_field(model: Model, data: dict, field_name: str, field_parser: Callable[[Any], Any | None]):
    """
    Attempts to parse a field from the input and apply a parser, before setting
    the appropriate field on the model. Aborts with 400 if the field is missing,
    or if it could not be parsed successfully.
    """

    if field_name not in data.keys():
        return abort(400, f"Missing required field {field_name}")

    raw_value = data[field_name]

    try:
        value = field_parser(raw_value)
    except:
        value = None

    if value is None:
        return abort(400, f"Field {field_name} expected {field_parser.__name__} but was {type(raw_value).__name__}")

    setattr(model, field_name, value)


def try_parse_uuid(value: Any) -> Optional[UUID]:
    if isinstance(value, UUID):
        return value

    try:
        return UUID(value)
    except:
        return None

def try_parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value

    elif value.lower() == "true":
        return True

    elif value.lower() == "false":
        return False

def empty():
    return Response(status=204)
