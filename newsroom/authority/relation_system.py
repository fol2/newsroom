"""Public composition facade for governed relation authority."""

from ._relation_system import (
    GovernedRelationAuthoritySystem,
    GovernedRelations,
    open_governed_relation_authority_system,
)

__all__ = [
    "GovernedRelationAuthoritySystem",
    "GovernedRelations",
    "open_governed_relation_authority_system",
]
