"""Public composition facade for native projection authority."""

from ._projection_system import (
    NativeProjectionAuthoritySystem,
    NativeProjections,
    open_native_projection_authority_system,
)

__all__ = [
    "NativeProjectionAuthoritySystem",
    "NativeProjections",
    "open_native_projection_authority_system",
]
