"""Public source-registry authority facade.

Only typed facade objects and the composition function are exported.  The
private SQLite store and command grants remain implementation details.
"""

from ._source_registry_system import (
    GovernedSourceRegistryAuthoritySystem,
    GovernedSources,
    open_governed_source_registry_authority_system,
)

__all__ = [
    "GovernedSourceRegistryAuthoritySystem",
    "GovernedSources",
    "open_governed_source_registry_authority_system",
]
