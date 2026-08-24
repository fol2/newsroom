"""Shared validation for provider-free deterministic Graphiti contracts (#748)."""

from __future__ import annotations


class DeterministicWorkContractError(ValueError):
    """A deterministic proposal input is incomplete or malformed."""


def require_bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise DeterministicWorkContractError(
            f"{field} must be bounded canonical text"
        )
    return value


def require_text_tuple(
    values: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = True,
) -> None:
    if not isinstance(values, tuple) or (not allow_empty and not values):
        raise DeterministicWorkContractError(f"{field} must be a canonical tuple")
    for value in values:
        require_bounded_text(value, field=field)
    if len(set(values)) != len(values):
        raise DeterministicWorkContractError(f"{field} must not contain duplicates")


def require_ppm(value: int, *, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 1_000_000
    ):
        raise DeterministicWorkContractError(
            f"{field} must be integer parts per million"
        )
    return value


__all__ = [
    "DeterministicWorkContractError",
    "require_bounded_text",
    "require_ppm",
    "require_text_tuple",
]
