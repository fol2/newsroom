from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import scripts.sdlc.collection_binding as collection_binding_module
from scripts.sdlc.collection_binding import (
    CollectionBindingError,
    validate_collection_decision_binding,
)
from scripts.sdlc.contracts import load_contract


def test_partial_collection_cannot_bind_authenticated_decision() -> None:
    collection = {
        "schema_version": "newsroom.sdlc.decision-collection.v1",
        "context": {"repository": "fol2/newsroom"},
        "event": {"repository": "fol2/newsroom"},
        "failure_code": None,
        "failure_result": None,
        "status": "READY",
    }
    with pytest.raises(
        CollectionBindingError,
        match="canonical SDLC evidence",
    ):
        validate_collection_decision_binding(
            collection=collection,
            decision={"context": {}, "event": {}},
            contract=load_contract(Path(__file__).resolve().parents[2]),
        )


def test_collection_binding_uses_complete_canonical_derivation() -> None:
    source = inspect.getsource(collection_binding_module)
    assert "orchestrator_module.validate_collection(" in source
    assert "orchestrator_module.validate_shadow_lane_record(" in source
    assert "shadow_decision_module.aggregate_shadow_decision(" in source
    assert "derived.as_dict() != dict(decision)" in source
    assert "normalized != dict(collection)" in source
