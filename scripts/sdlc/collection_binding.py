from __future__ import annotations

from typing import Any, Mapping

from . import shadow_decision as shadow_decision_module
from . import workflow_orchestrator as orchestrator_module
from .artifact_envelope import ArtifactProvenanceError, _context_from_mapping
from .contracts import ContractError, SdlcContract
from .shadow_decision import ShadowDecisionError
from .shadow_lane import ShadowLaneError
from .workflow_event import WorkflowEvidenceError, validate_workflow_event


class CollectionBindingError(ValueError):
    """Raised when retained collection bytes do not derive the decision."""


def validate_collection_decision_binding(
    *,
    collection: Mapping[str, Any],
    decision: Mapping[str, Any],
    contract: SdlcContract,
) -> dict[str, object]:
    """Validate a complete collection and derive its exact signed decision."""

    try:
        normalized = orchestrator_module.validate_collection(
            collection,
            contract=contract,
        )
        if normalized != dict(collection):
            raise CollectionBindingError(
                "collection differs from canonical SDLC output"
            )
        context = _context_from_mapping(normalized["context"])
        event = validate_workflow_event(normalized["event"])
        core = orchestrator_module.validate_shadow_lane_record(
            normalized["core"],
            contract=contract,
        )
        service = (
            None
            if normalized["service"] is None
            else orchestrator_module.validate_shadow_lane_record(
                normalized["service"],
                contract=contract,
            )
        )
        derived = shadow_decision_module.aggregate_shadow_decision(
            context=context,
            event=event,
            core=core,
            service=service,
            contract=contract,
        )
    except (
        ArtifactProvenanceError,
        ContractError,
        WorkflowEvidenceError,
        ShadowLaneError,
        ShadowDecisionError,
        orchestrator_module.WorkflowOrchestratorError,
    ) as exc:
        raise CollectionBindingError(
            "collection is not canonical SDLC evidence"
        ) from exc
    if derived.as_dict() != dict(decision):
        raise CollectionBindingError(
            "collection does not derive the authenticated decision"
        )
    return normalized
