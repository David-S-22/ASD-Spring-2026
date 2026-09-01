from dataclasses import is_dataclass
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar
import os

from flask import abort, Response
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

    try:
        return _adapter(cls).validate_python(data)
    except ValidationError:
        return None

def get_env(name: str) -> str:
    return os.environ[name]
