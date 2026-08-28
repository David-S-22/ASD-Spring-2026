from dataclasses import fields, is_dataclass
from typing import Any, Optional, Type, TypeVar, get_args, get_origin, Union
from uuid import UUID

T = TypeVar("T")

def serialize(dto: Any) -> dict:
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

def try_deserialize(cls: Type[T], data: dict) -> Optional[T]:
    """Safely reconstructs a flat dataclass from a dict, converting strings back to UUIDs."""

    if not is_dataclass(cls):
        raise TypeError("Expected a dataclass type.")

    kwargs = {}

    for field in fields(cls):
        if (field_name := field.name) not in data:
            continue

        field_value = data[field_name]
        field_type = field.type

        assert get_origin(field_type) is not Union # not dealing with this
        
        # Unwrap Optional[...] to just ...
        if get_origin(field_type) is Optional:
            types = get_args(field_type)
            field_type = types[0] if types[1] is type(None) else types[1]

        # Try reconstruct UUID
        if field_type is UUID and isinstance(field_value, str):
            try:
                field_value = UUID(field_value)
            except ValueError:
                return

        kwargs[field_name] = field_value

    return cls(**kwargs)