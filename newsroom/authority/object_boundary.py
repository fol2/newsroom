"""Public governed-object facades.

Only authenticated request facades and non-authoritative views are public.  The
SQLite writer, CAS writer, policy evaluators, capabilities and lifecycle command
construction remain private modules.
"""

from ._object_system import (
    GovernedObjectAuthoritySystem,
    GovernedObjects,
    HydratedObject,
    ObjectAdmissionResult,
    open_governed_object_authority_system,
)

__all__ = [
    "GovernedObjectAuthoritySystem",
    "GovernedObjects",
    "HydratedObject",
    "ObjectAdmissionResult",
    "open_governed_object_authority_system",
]
