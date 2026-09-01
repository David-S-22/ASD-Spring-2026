from typing import Any, Callable, Optional

from flask import Response, abort
from flask_sqlalchemy.model import Model


def set_mandatory_field(model: Model, data: dict, field_name: str, field_parser: Callable[[Any], Any | None]):
    _set_field(model, data, field_name, field_parser)

def set_optional_field(model: Model, data: dict, field_name: str, field_parser: Callable[[Any], Any | None]):
    if field_name in data.keys() and data[field_name] is not None:
        _set_field(model, data, field_name, field_parser)

def _set_field(model: Model, data: dict, field_name: str, field_parser: Callable[[Any], Any | None]):
    """
    Attempts to parse a field from the input and apply a parser, before setting
    the appropriate field on the model. Aborts with 400 if the field is missing,
    or if it could not be parsed successfully.
    """

    if field_name not in data.keys():
        return abort(400, f"Missing required field {field_name}")

    try:
        value = field_parser(raw_value := data[field_name])
    except:
        value = None

    if value is None:
        return abort(400, f"Field {field_name} expected {field_parser.__name__} but was {type(raw_value).__name__}")

    setattr(model, field_name, value)

def try_parse_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    try:
        return int(value)
    except:
        return None

def try_parse_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        lower = value.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False

    return None

def empty():
    return Response(status=204)
