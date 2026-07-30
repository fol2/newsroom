from __future__ import annotations

from typing import Any, Callable

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.entities.models import (
    EntityMergeDecisionRequest,
    EntityLineageVersion,
    EntityMentionAdmissionRequest,
    EntityReversalDecisionRequest,
    EntityResolutionDecisionRequest,
    EntityResolutionDependencyRequest,
    EntityResolutionProposalRequest,
    EntitySplitAllocation,
    EntitySplitDecisionRequest,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityKind,
    EntityMergeDecisionId,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionId,
    EntityResolutionDependencyId,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalVersionId,
    EntityReversalDecisionId,
    EntityReversalTargetKind,
    EntityScript,
    EntitySplitDecisionId,
)
from newsroom.extraction.types import ProposalEnvelopeId


def _object(value: object, *, identity: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise AuthorityPersistenceError(f"{identity} must be a canonical object")
    return value


def _id(value: object, parser: Callable[[str], Any], *, field: str) -> Any:
    if not isinstance(value, str):
        raise AuthorityPersistenceError(f"{field} must be text")
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise AuthorityPersistenceError(f"{field} is invalid") from exc


def _optional_id(value: object, parser: Callable[[str], Any], *, field: str) -> Any:
    return None if value is None else _id(value, parser, field=field)


def _enum(value: object, enum_type: type, *, field: str) -> Any:
    if not isinstance(value, str):
        raise AuthorityPersistenceError(f"{field} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityPersistenceError(f"{field} is invalid") from exc


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise AuthorityPersistenceError(f"{field} must be text")
    return value


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthorityPersistenceError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, *, field: str) -> int | None:
    return None if value is None else _integer(value, field=field)


def _strings(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AuthorityPersistenceError(f"{field} must be a text array")
    return tuple(value)


def _ids(
    value: object,
    parser: Callable[[str], Any],
    *,
    field: str,
) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise AuthorityPersistenceError(f"{field} must be an identity array")
    return tuple(_id(item, parser, field=field) for item in value)


def _lineage_versions(value: object, *, field: str) -> tuple[EntityLineageVersion, ...]:
    if not isinstance(value, list):
        raise AuthorityPersistenceError(f"{field} must be a lineage-version array")
    results: list[EntityLineageVersion] = []
    for raw in value:
        item = _object(raw, identity=f"{field} item")
        _require_keys(
            item,
            frozenset({"entity_id", "entity_version_id"}),
            identity=f"{field} item",
        )
        results.append(
            EntityLineageVersion(
                entity_id=_id(
                    item["entity_id"], CanonicalEntityId.parse, field=f"{field}.entity_id"
                ),
                entity_version_id=_id(
                    item["entity_version_id"],
                    CanonicalEntityVersionId.parse,
                    field=f"{field}.entity_version_id",
                ),
            )
        )
    return tuple(results)


def _require_keys(value: dict[str, Any], keys: frozenset[str], *, identity: str) -> None:
    if frozenset(value) != keys:
        raise AuthorityPersistenceError(f"{identity} fields differ from the contract")


def decode_entity_mention_request(
    value: object, *, idempotency_key: str
) -> EntityMentionAdmissionRequest:
    item = _object(value, identity="entity mention request")
    keys = frozenset(
        {
            "mention_id",
            "source_proposal_id",
            "expected_source_proposal_digest",
            "entity_kind",
            "language",
            "script",
            "normalized_text",
            "normalization_contract_digest",
        }
    )
    _require_keys(item, keys, identity="entity mention request")
    request = EntityMentionAdmissionRequest(
        mention_id=_id(item["mention_id"], EntityMentionId.parse, field="mention_id"),
        source_proposal_id=_id(
            item["source_proposal_id"], ProposalEnvelopeId.parse, field="source_proposal_id"
        ),
        expected_source_proposal_digest=_text(
            item["expected_source_proposal_digest"],
            field="expected_source_proposal_digest",
        ),
        entity_kind=_enum(item["entity_kind"], EntityKind, field="entity_kind"),
        language=_text(item["language"], field="language"),
        script=_enum(item["script"], EntityScript, field="script"),
        normalized_text=_text(item["normalized_text"], field="normalized_text"),
        normalization_contract_digest=_text(
            item["normalization_contract_digest"],
            field="normalization_contract_digest",
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity mention request is not canonical")
    return request


def decode_entity_proposal_request(
    value: object, *, idempotency_key: str
) -> EntityResolutionProposalRequest:
    item = _object(value, identity="entity resolution proposal request")
    keys = frozenset(
        {
            "proposal_id",
            "proposal_version_id",
            "version_number",
            "expected_previous_version_id",
            "source_proposal_id",
            "expected_source_proposal_digest",
            "kind",
            "subject_mention_id",
            "object_mention_id",
            "candidate_entity_id",
            "candidate_entity_version_id",
            "confidence_basis_points",
            "uncertainty_codes",
            "basis_codes",
        }
    )
    _require_keys(item, keys, identity="entity resolution proposal request")
    request = EntityResolutionProposalRequest(
        proposal_id=_id(
            item["proposal_id"], EntityResolutionProposalId.parse, field="proposal_id"
        ),
        proposal_version_id=_id(
            item["proposal_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="proposal_version_id",
        ),
        version_number=_integer(item["version_number"], field="version_number"),
        expected_previous_version_id=_optional_id(
            item["expected_previous_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="expected_previous_version_id",
        ),
        source_proposal_id=_id(
            item["source_proposal_id"], ProposalEnvelopeId.parse, field="source_proposal_id"
        ),
        expected_source_proposal_digest=_text(
            item["expected_source_proposal_digest"],
            field="expected_source_proposal_digest",
        ),
        kind=_enum(item["kind"], EntityResolutionProposalKind, field="kind"),
        subject_mention_id=_id(
            item["subject_mention_id"], EntityMentionId.parse, field="subject_mention_id"
        ),
        object_mention_id=_optional_id(
            item["object_mention_id"], EntityMentionId.parse, field="object_mention_id"
        ),
        candidate_entity_id=_optional_id(
            item["candidate_entity_id"], CanonicalEntityId.parse, field="candidate_entity_id"
        ),
        candidate_entity_version_id=_optional_id(
            item["candidate_entity_version_id"],
            CanonicalEntityVersionId.parse,
            field="candidate_entity_version_id",
        ),
        confidence_basis_points=_optional_integer(
            item["confidence_basis_points"], field="confidence_basis_points"
        ),
        uncertainty_codes=_strings(item["uncertainty_codes"], field="uncertainty_codes"),
        basis_codes=_strings(item["basis_codes"], field="basis_codes"),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity resolution proposal request is not canonical")
    return request


def decode_entity_decision_request(
    value: object, *, idempotency_key: str
) -> EntityResolutionDecisionRequest:
    item = _object(value, identity="entity resolution decision request")
    keys = frozenset(
        {
            "proposal_id",
            "expected_proposal_version_id",
            "expected_proposal_digest",
            "action",
            "expected_decision_version",
            "expected_previous_decision_id",
            "accepted_entity_id",
            "accepted_entity_version_id",
            "alias_id",
            "alias_kind",
            "reason_code",
            "decision_policy_version",
        }
    )
    _require_keys(item, keys, identity="entity resolution decision request")
    request = EntityResolutionDecisionRequest(
        proposal_id=_id(
            item["proposal_id"], EntityResolutionProposalId.parse, field="proposal_id"
        ),
        expected_proposal_version_id=_id(
            item["expected_proposal_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="expected_proposal_version_id",
        ),
        expected_proposal_digest=_text(
            item["expected_proposal_digest"], field="expected_proposal_digest"
        ),
        action=_enum(
            item["action"], EntityResolutionDecisionAction, field="action"
        ),
        expected_decision_version=_integer(
            item["expected_decision_version"], field="expected_decision_version"
        ),
        expected_previous_decision_id=_optional_id(
            item["expected_previous_decision_id"],
            EntityResolutionDecisionId.parse,
            field="expected_previous_decision_id",
        ),
        accepted_entity_id=_optional_id(
            item["accepted_entity_id"], CanonicalEntityId.parse, field="accepted_entity_id"
        ),
        accepted_entity_version_id=_optional_id(
            item["accepted_entity_version_id"],
            CanonicalEntityVersionId.parse,
            field="accepted_entity_version_id",
        ),
        alias_id=_optional_id(item["alias_id"], EntityAliasId.parse, field="alias_id"),
        alias_kind=(
            None
            if item["alias_kind"] is None
            else _enum(item["alias_kind"], EntityAliasKind, field="alias_kind")
        ),
        reason_code=_text(item["reason_code"], field="reason_code"),
        decision_policy_version=_text(
            item["decision_policy_version"], field="decision_policy_version"
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity resolution decision request is not canonical")
    return request


def decode_entity_dependency_request(
    value: object, *, idempotency_key: str
) -> EntityResolutionDependencyRequest:
    item = _object(value, identity="entity resolution dependency request")
    keys = frozenset(
        {
            "dependency_id",
            "dependent_proposal_id",
            "expected_dependent_proposal_digest",
            "resolution_proposal_id",
            "expected_resolution_proposal_version_id",
            "expected_resolution_proposal_digest",
            "material",
        }
    )
    _require_keys(item, keys, identity="entity resolution dependency request")
    material = item["material"]
    if not isinstance(material, bool):
        raise AuthorityPersistenceError("dependency material flag must be boolean")
    request = EntityResolutionDependencyRequest(
        dependency_id=_id(
            item["dependency_id"],
            EntityResolutionDependencyId.parse,
            field="dependency_id",
        ),
        dependent_proposal_id=_id(
            item["dependent_proposal_id"],
            ProposalEnvelopeId.parse,
            field="dependent_proposal_id",
        ),
        expected_dependent_proposal_digest=_text(
            item["expected_dependent_proposal_digest"],
            field="expected_dependent_proposal_digest",
        ),
        resolution_proposal_id=_id(
            item["resolution_proposal_id"],
            EntityResolutionProposalId.parse,
            field="resolution_proposal_id",
        ),
        expected_resolution_proposal_version_id=_id(
            item["expected_resolution_proposal_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="expected_resolution_proposal_version_id",
        ),
        expected_resolution_proposal_digest=_text(
            item["expected_resolution_proposal_digest"],
            field="expected_resolution_proposal_digest",
        ),
        material=material,
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError(
            "entity resolution dependency request is not canonical"
        )
    return request


def decode_entity_merge_request(
    value: object, *, idempotency_key: str
) -> EntityMergeDecisionRequest:
    item = _object(value, identity="entity merge decision request")
    keys = frozenset(
        {
            "merge_decision_id",
            "predecessors",
            "successor_entity_id",
            "successor_entity_version_id",
            "preferred_continuation_entity_id",
            "basis_resolution_proposal_ids",
            "reason_code",
            "decision_policy_version",
        }
    )
    _require_keys(item, keys, identity="entity merge decision request")
    request = EntityMergeDecisionRequest(
        merge_decision_id=_id(
            item["merge_decision_id"],
            EntityMergeDecisionId.parse,
            field="merge_decision_id",
        ),
        predecessors=_lineage_versions(item["predecessors"], field="predecessors"),
        successor_entity_id=_id(
            item["successor_entity_id"],
            CanonicalEntityId.parse,
            field="successor_entity_id",
        ),
        successor_entity_version_id=_id(
            item["successor_entity_version_id"],
            CanonicalEntityVersionId.parse,
            field="successor_entity_version_id",
        ),
        preferred_continuation_entity_id=_id(
            item["preferred_continuation_entity_id"],
            CanonicalEntityId.parse,
            field="preferred_continuation_entity_id",
        ),
        basis_resolution_proposal_ids=_ids(
            item["basis_resolution_proposal_ids"],
            EntityResolutionProposalId.parse,
            field="basis_resolution_proposal_ids",
        ),
        reason_code=_text(item["reason_code"], field="reason_code"),
        decision_policy_version=_text(
            item["decision_policy_version"], field="decision_policy_version"
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity merge decision request is not canonical")
    return request


def decode_entity_split_request(
    value: object, *, idempotency_key: str
) -> EntitySplitDecisionRequest:
    item = _object(value, identity="entity split decision request")
    keys = frozenset(
        {
            "split_decision_id",
            "source_entity_id",
            "expected_source_version_id",
            "successors",
            "allocations",
            "reason_code",
            "decision_policy_version",
        }
    )
    _require_keys(item, keys, identity="entity split decision request")
    raw_allocations = item["allocations"]
    if not isinstance(raw_allocations, list):
        raise AuthorityPersistenceError("allocations must be an object array")
    allocations: list[EntitySplitAllocation] = []
    for raw in raw_allocations:
        allocation = _object(raw, identity="entity split allocation")
        _require_keys(
            allocation,
            frozenset({"mention_id", "successor_entity_id"}),
            identity="entity split allocation",
        )
        allocations.append(
            EntitySplitAllocation(
                mention_id=_id(
                    allocation["mention_id"],
                    EntityMentionId.parse,
                    field="allocation_mention_id",
                ),
                successor_entity_id=_id(
                    allocation["successor_entity_id"],
                    CanonicalEntityId.parse,
                    field="allocation_successor_entity_id",
                ),
            )
        )
    request = EntitySplitDecisionRequest(
        split_decision_id=_id(
            item["split_decision_id"],
            EntitySplitDecisionId.parse,
            field="split_decision_id",
        ),
        source_entity_id=_id(
            item["source_entity_id"],
            CanonicalEntityId.parse,
            field="source_entity_id",
        ),
        expected_source_version_id=_id(
            item["expected_source_version_id"],
            CanonicalEntityVersionId.parse,
            field="expected_source_version_id",
        ),
        successors=_lineage_versions(item["successors"], field="successors"),
        allocations=tuple(allocations),
        reason_code=_text(item["reason_code"], field="reason_code"),
        decision_policy_version=_text(
            item["decision_policy_version"], field="decision_policy_version"
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity split decision request is not canonical")
    return request


def decode_entity_reversal_request(
    value: object, *, idempotency_key: str
) -> EntityReversalDecisionRequest:
    item = _object(value, identity="entity reversal decision request")
    keys = frozenset(
        {
            "reversal_decision_id",
            "target_kind",
            "target_decision_id",
            "expected_current_entity_version_ids",
            "restorations",
            "reason_code",
            "decision_policy_version",
        }
    )
    _require_keys(item, keys, identity="entity reversal decision request")
    request = EntityReversalDecisionRequest(
        reversal_decision_id=_id(
            item["reversal_decision_id"],
            EntityReversalDecisionId.parse,
            field="reversal_decision_id",
        ),
        target_kind=_enum(
            item["target_kind"], EntityReversalTargetKind, field="target_kind"
        ),
        target_decision_id=_text(
            item["target_decision_id"], field="target_decision_id"
        ),
        expected_current_entity_version_ids=_ids(
            item["expected_current_entity_version_ids"],
            CanonicalEntityVersionId.parse,
            field="expected_current_entity_version_ids",
        ),
        restorations=_lineage_versions(item["restorations"], field="restorations"),
        reason_code=_text(item["reason_code"], field="reason_code"),
        decision_policy_version=_text(
            item["decision_policy_version"], field="decision_policy_version"
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity reversal decision request is not canonical")
    return request


__all__ = [
    "decode_entity_decision_request",
    "decode_entity_dependency_request",
    "decode_entity_merge_request",
    "decode_entity_mention_request",
    "decode_entity_proposal_request",
    "decode_entity_reversal_request",
    "decode_entity_split_request",
]
