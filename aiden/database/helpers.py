from typing import Callable, Optional
from uuid import UUID

from flask import abort
from flask_sqlalchemy.model import Model


def set_mandatory_field(model: Model, data: dict, field_name: str, field_parser: Callable):
    _set_field(model=model, data=data, field_name=field_name, field_parser=field_parser, allow_missing=False)

def set_optional_field(model: Model, data: dict, field_name: str, field_parser: Callable):
    _set_field(model=model, data=data, field_name=field_name, field_parser=field_parser, allow_missing=True)


def _set_field(model: Model, data: dict, field_name: str, field_parser: Callable, allow_missing: bool):
    if field_name not in data.keys() and not allow_missing:
        return abort(400, f"Missing required field {field_name}")

    raw_value = data[field_name]

    try:
        value = field_parser(raw_value)
    except:
        return abort(400, f"Field {field_name} expected {field_parser.__name__} but was {type(raw_value).__name__}")

    setattr(model, field_name, value)

def try_parse_uuid(value: str) -> Optional[UUID]:
    try:
        return UUID(value)
    except:
        return None

def try_parse_bool(value: str) -> Optional[bool]:
    if value.lower() == "true":
        return True

    elif value.lower() == "false":
        return False
