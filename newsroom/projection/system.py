"""Public engine-neutral projection facade.

Mutation-capable composition remains owned by :mod:`newsroom.authority`; this
module exposes only the authenticated public facade and constructor.
"""

from newsroom.authority.projection_system import (
    NativeProjectionAuthoritySystem,
    NativeProjections,
    open_native_projection_authority_system,
)

__all__ = [
    "NativeProjectionAuthoritySystem",
    "NativeProjections",
    "open_native_projection_authority_system",
]
