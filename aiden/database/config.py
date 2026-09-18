"""Environment configuration for the anomalies database.

Values are resolved lazily from the environment: reading an attribute of
``config`` raises a ``RuntimeError`` if the corresponding variable is not set
(or cannot be parsed). Call :meth:`config.check_all` to validate every variable
up front.
"""
import os
from typing import Any, Callable


def _resolve(name: str, parser: Callable[[str], Any]) -> Any:
    try:
        raw = os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set"
        ) from None

    try:
        return parser(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Environment variable {name!r} has an invalid value {raw!r}: {exc}"
        ) from exc


class _Config:
    """Lazily-resolved anomalies database configuration.

    Each setting is a property so IDEs and type checkers see its concrete
    return type. When adding a property, also add its name to the list in
    :meth:`check_all` so it is validated.
    """

    @property
    def PORT(self) -> int:
        return _resolve("PORT", int)

    @property
    def DB_PATH(self) -> str:
        return _resolve("DB_PATH", str)

    def check_all(self) -> None:
        """Resolve every configured variable, raising if any is missing or invalid.

        Errors are aggregated so a single call reports every problem at once.
        """
        errors = []
        for name in ("PORT", "DB_PATH"):
            try:
                getattr(self, name)
            except RuntimeError as exc:
                errors.append(str(exc))

        if errors:
            raise RuntimeError(
                "Invalid anomalies database configuration:\n  - "
                + "\n  - ".join(errors)
            )


config = _Config()
