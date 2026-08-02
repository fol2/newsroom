"""Repository entry point for the accepted-on-merge Increment 5A contract."""

from __future__ import annotations

from pathlib import Path

from .contracts import Increment5AContract, load_increment5a_contract


CONTRACT_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_retrieval_contract_v1.json"
)


def load_repository_contract() -> Increment5AContract:
    return load_increment5a_contract(CONTRACT_PATH)


INCREMENT_5A_CONTRACT = load_repository_contract()
INCREMENT_5A_CONTRACT_DIGEST = INCREMENT_5A_CONTRACT.contract_digest
