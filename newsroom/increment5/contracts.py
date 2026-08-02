"""Public API for the reviewed Increment 5A contract.

Source review and merge to ``main`` decide authorization.  These modules only identify
and parse the exact reviewed bytes; they never inspect GitHub or mint runtime authority.
"""

from .contract_loader import load_increment5a_contract
from .contract_types import (
    ComponentDisposition,
    ContractEffect,
    ContractStatus,
    Increment5AContract,
    Increment5ContractError,
    RetrievalComponentContract,
    RetrievalComponentKind,
    RetrievalMode,
    RetrievalProfileKind,
)

__all__ = [
    "ComponentDisposition",
    "ContractEffect",
    "ContractStatus",
    "Increment5AContract",
    "Increment5ContractError",
    "RetrievalComponentContract",
    "RetrievalComponentKind",
    "RetrievalMode",
    "RetrievalProfileKind",
    "load_increment5a_contract",
]
