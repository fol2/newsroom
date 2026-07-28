"""Public combined source, Check, Signal, Gate and Lead authority facade."""

from __future__ import annotations

from ._discovery_system import (
    GovernedDiscovery,
    GovernedDiscoveryAuthoritySystem,
    open_governed_discovery_authority_system,
)

__all__ = [
    "GovernedDiscovery",
    "GovernedDiscoveryAuthoritySystem",
    "open_governed_discovery_authority_system",
]
