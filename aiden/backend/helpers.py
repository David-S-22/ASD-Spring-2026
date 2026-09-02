from dataclasses import is_dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar

from flask import Response, abort
from pydantic import TypeAdapter, ValidationError

T = TypeVar("T")

def empty() -> Response:
    return Response(status=204)

@lru_cache(maxsize=None)
def _adapter(cls: type) -> TypeAdapter:
    """Builds (and caches) a pydantic TypeAdapter for a plain dataclass.

    pydantic validates the stdlib dataclass directly from its annotations, so the
    DTOs stay ordinary @dataclass definitions with no BaseModel involvement.
    """

    return TypeAdapter(cls)

def serialise(dto: Any) -> dict:
    """Serialises a flat dataclass into a JSON-compatible dict.

    Field values are validated against their declared types and datetimes are
    rendered as ISO strings by pydantic's JSON serialisation.
    """

    if not is_dataclass(dto) or isinstance(dto, type):
        raise TypeError("Expected a dataclass instance.")

    return _adapter(type(dto)).dump_python(dto, mode="json")

def deserialise_or_abort(cls: Type[T], data: dict) -> T:
    dto = deserialise_safe(cls, data)

    if dto is None:
        abort(500, "Schema mismatch between backend and database")

    return dto

def deserialise_safe(cls: Type[T], data: dict) -> Optional[T]:
    """Safely reconstructs a flat dataclass from a dict.

    pydantic coerces and validates each value against the declared field types
    (e.g. an ISO string to datetime). Returns None if validation fails.
    """

    if not is_dataclass(cls) or not isinstance(cls, type):
        raise TypeError("Expected a dataclass type.")

    parsed_data = dict(data)
    for key, value in parsed_data.items():
        if "date" in key and isinstance(value, str):
            parsed_data[key] = deserialise_datetime_or_throw(value)

    try:
        return _adapter(cls).validate_python(parsed_data)
    except ValidationError:
        return None

def deserialise_datetime_or_throw(value: str) -> datetime:
    """Parses a datetime string from either RFC 2822/GMT or ISO 8601 form."""

    if not isinstance(value, str):
        raise TypeError("Datetime value must be a string.")

    candidate = value.strip()
    if not candidate:
        raise ValueError("Datetime value is empty.")

    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(candidate)
        if dt is not None:
            return dt
    except (TypeError, ValueError):
        pass

    raise ValueError(f"Unsupported datetime format: {value!r}")
