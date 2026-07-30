from __future__ import annotations

from ._editorial_relation_facade import GovernedEditorialRelations
from ._editorial_relation_system import (
    GovernedEditorialRelationAuthoritySystem,
    open_governed_editorial_relation_authority_system,
)

__all__ = [
    "GovernedEditorialRelationAuthoritySystem",
    "GovernedEditorialRelations",
    "open_governed_editorial_relation_authority_system",
]
