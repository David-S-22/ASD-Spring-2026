from dataclasses import fields, is_dataclass
from typing import Any, Optional, Type, TypeVar, get_args, get_origin, Union
from uuid import UUID
import os

from flask import abort, Response

T = TypeVar("T")

def empty() -> Response:
    return Response(status=204)

def serialise(dto: Any) -> dict:
    """Serializes a flat dataclass into a dict, converting all UUIDs to strings."""

    if not is_dataclass(dto):
        raise TypeError("Expected a dataclass instance.")
        
    result = {}
    for field in fields(dto):
        value = getattr(dto, field.name)

        if isinstance(value, UUID):
            result[field.name] = str(value)
        else:
            result[field.name] = value

    return result

def deserialise_or_abort(cls: Type[T], data: dict) -> T:
    dto = deserialise_safe(cls, data)

    if dto is None:
        abort(500, "Schema mismatch between backend and database")

    return dto

def deserialise_safe(cls: Type[T], data: dict) -> Optional[T]:
    """Safely reconstructs a flat dataclass from a dict, converting strings back to UUIDs."""

    if not is_dataclass(cls):
        raise TypeError("Expected a dataclass type.")

    kwargs = {}

    for field in fields(cls):
        if (field_name := field.name) not in data:
            continue

        field_value = data[field_name]
        field_type = field.type

        # Unwrap Optional[...] / Union[..., None] to the underlying type
        if get_origin(field_type) is Union:
            non_none = [arg for arg in get_args(field_type) if arg is not type(None)]
            if len(non_none) == 1:
                field_type = non_none[0]

        # Try reconstruct UUID
        if field_type is UUID and isinstance(field_value, str):
            try:
                field_value = UUID(field_value)
            except ValueError:
                return None

        kwargs[field_name] = field_value

    return cls(**kwargs)

def get_env(name: str) -> str:
    return os.environ[name]
