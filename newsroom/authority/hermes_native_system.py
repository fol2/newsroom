"""Public production composition for the native Hermes authority writer."""

from ._hermes_native_system import (
    HermesNativeAuthoritySystem,
    NativeDependencyFactory,
    open_hermes_native_authority_system,
)

__all__ = [
    "HermesNativeAuthoritySystem",
    "NativeDependencyFactory",
    "open_hermes_native_authority_system",
]
