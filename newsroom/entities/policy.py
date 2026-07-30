from __future__ import annotations

from typing import Any, Callable

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
)
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.extraction.policy import merge_extraction_authority_registries
from newsroom.extraction.types import ProposalEnvelopeId

from .models import (
    EntityLineageVersion,
    EntityMentionAdmissionRequest,
    EntityMergeDecisionRequest,
    EntityResolutionDecisionRequest,
    EntityResolutionDependencyRequest,
    EntityResolutionProposalRequest,
    EntityReversalDecisionRequest,
    EntitySplitAllocation,
    EntitySplitDecisionRequest,
)
from .types import (
    ENTITY_NORMALISATION_CONTRACT_DIGEST,
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

ENTITY_MENTION_ADMIT_COMMAND = "entity.mention.admit"
ENTITY_RESOLUTION_PROPOSE_COMMAND = "entity.resolution.propose"
ENTITY_RESOLUTION_DECIDE_COMMAND = "entity.resolution.decide"
ENTITY_RESOLUTION_DEPENDENCY_BIND_COMMAND = "entity.resolution.dependency.bind"
ENTITY_MERGE_DECIDE_COMMAND = "entity.merge.decide"
ENTITY_SPLIT_DECIDE_COMMAND = "entity.split.decide"
ENTITY_REVERSAL_DECIDE_COMMAND = "entity.reversal.decide"
ENTITY_COMMAND_TYPES = frozenset(
    {
        ENTITY_MENTION_ADMIT_COMMAND,
        ENTITY_RESOLUTION_PROPOSE_COMMAND,
        ENTITY_RESOLUTION_DECIDE_COMMAND,
        ENTITY_RESOLUTION_DEPENDENCY_BIND_COMMAND,
        ENTITY_MERGE_DECIDE_COMMAND,
        ENTITY_SPLIT_DECIDE_COMMAND,
        ENTITY_REVERSAL_DECIDE_COMMAND,
    }
)

_MENTION_SCHEMA = "entity_mention_admission_v1"
_PROPOSAL_SCHEMA = "entity_resolution_proposal_v1"
_DECISION_SCHEMA = "entity_resolution_decision_v1"
_DEPENDENCY_SCHEMA = "entity_resolution_dependency_v1"
_MERGE_SCHEMA = "entity_merge_decision_v1"
_SPLIT_SCHEMA = "entity_split_decision_v1"
_REVERSAL_SCHEMA = "entity_reversal_decision_v1"
_CONTRACT_VERSION = "entity-resolution-authority-contract-v1"
_DEFINITION_VERSION = "entity-resolution-authority-command-v1"


def _object(value: Any, *, field: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise PayloadSchemaValidationError(f"{field} has an invalid exact field set")
    return value


def _optional_id(value: Any, parser: Callable[[str], Any], *, field: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text or null")
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid") from exc


def _required_id(value: Any, parser: Callable[[str], Any], *, field: str) -> Any:
    parsed = _optional_id(value, parser, field=field)
    if parsed is None:
        raise PayloadSchemaValidationError(f"{field} cannot be null")
    return parsed


def _enum(value: Any, enum_type: type, *, field: str) -> Any:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid") from exc


def _string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text")
    return value


def _integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadSchemaValidationError(f"{field} must be an integer")
    return value


def _optional_integer(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field=field)


def _strings(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PayloadSchemaValidationError(f"{field} must be a text array")
    return tuple(value)


def _ids(
    value: Any,
    parser: Callable[[str], Any],
    *,
    field: str,
) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise PayloadSchemaValidationError(f"{field} must be an identifier array")
    return tuple(_required_id(item, parser, field=field) for item in value)


def _lineage_versions_payload(
    value: Any, *, field: str
) -> tuple[EntityLineageVersion, ...]:
    if not isinstance(value, list):
        raise PayloadSchemaValidationError(
            f"{field} must be a lineage-version array"
        )
    results: list[EntityLineageVersion] = []
    for raw in value:
        item = _object(
            raw,
            field=f"{field}.item",
            keys=frozenset({"entity_id", "entity_version_id"}),
        )
        results.append(
            EntityLineageVersion(
                entity_id=_required_id(
                    item["entity_id"],
                    CanonicalEntityId.parse,
                    field=f"{field}.entity_id",
                ),
                entity_version_id=_required_id(
                    item["entity_version_id"],
                    CanonicalEntityVersionId.parse,
                    field=f"{field}.entity_version_id",
                ),
            )
        )
    return tuple(results)


def _canonicalize_request(
    value: Any,
    *,
    field: str,
    keys: frozenset[str],
    build: Callable[[dict[str, Any]], Any],
) -> bytes:
    item = _object(value, field=field, keys=keys)
    try:
        request = build(item)
    except PayloadSchemaValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid: {exc}") from exc
    canonical = request.canonical_value()
    if canonical != item:
        raise PayloadSchemaValidationError(f"{field} is not canonical")
    return canonical_json_bytes(canonical)


def _mention_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntityMentionAdmissionRequest:
        return EntityMentionAdmissionRequest(
            mention_id=_required_id(
                item["mention_id"], EntityMentionId.parse, field="mention_id"
            ),
            source_proposal_id=_required_id(
                item["source_proposal_id"],
                ProposalEnvelopeId.parse,
                field="source_proposal_id",
            ),
            expected_source_proposal_digest=_string(
                item["expected_source_proposal_digest"],
                field="expected_source_proposal_digest",
            ),
            entity_kind=_enum(item["entity_kind"], EntityKind, field="entity_kind"),
            language=_string(item["language"], field="language"),
            script=_enum(item["script"], EntityScript, field="script"),
            normalized_text=_string(item["normalized_text"], field="normalized_text"),
            normalization_contract_digest=_string(
                item["normalization_contract_digest"],
                field="normalization_contract_digest",
            ),
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(
        value,
        field="entity_mention_admission",
        keys=keys,
        build=build,
    )


def _proposal_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntityResolutionProposalRequest:
        return EntityResolutionProposalRequest(
            proposal_id=_required_id(
                item["proposal_id"],
                EntityResolutionProposalId.parse,
                field="proposal_id",
            ),
            proposal_version_id=_required_id(
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
            source_proposal_id=_required_id(
                item["source_proposal_id"],
                ProposalEnvelopeId.parse,
                field="source_proposal_id",
            ),
            expected_source_proposal_digest=_string(
                item["expected_source_proposal_digest"],
                field="expected_source_proposal_digest",
            ),
            kind=_enum(
                item["kind"], EntityResolutionProposalKind, field="kind"
            ),
            subject_mention_id=_required_id(
                item["subject_mention_id"],
                EntityMentionId.parse,
                field="subject_mention_id",
            ),
            object_mention_id=_optional_id(
                item["object_mention_id"],
                EntityMentionId.parse,
                field="object_mention_id",
            ),
            candidate_entity_id=_optional_id(
                item["candidate_entity_id"],
                CanonicalEntityId.parse,
                field="candidate_entity_id",
            ),
            candidate_entity_version_id=_optional_id(
                item["candidate_entity_version_id"],
                CanonicalEntityVersionId.parse,
                field="candidate_entity_version_id",
            ),
            confidence_basis_points=_optional_integer(
                item["confidence_basis_points"], field="confidence_basis_points"
            ),
            uncertainty_codes=_strings(
                item["uncertainty_codes"], field="uncertainty_codes"
            ),
            basis_codes=_strings(item["basis_codes"], field="basis_codes"),
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(
        value,
        field="entity_resolution_proposal",
        keys=keys,
        build=build,
    )


def _decision_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntityResolutionDecisionRequest:
        return EntityResolutionDecisionRequest(
            proposal_id=_required_id(
                item["proposal_id"],
                EntityResolutionProposalId.parse,
                field="proposal_id",
            ),
            expected_proposal_version_id=_required_id(
                item["expected_proposal_version_id"],
                EntityResolutionProposalVersionId.parse,
                field="expected_proposal_version_id",
            ),
            expected_proposal_digest=_string(
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
                item["accepted_entity_id"],
                CanonicalEntityId.parse,
                field="accepted_entity_id",
            ),
            accepted_entity_version_id=_optional_id(
                item["accepted_entity_version_id"],
                CanonicalEntityVersionId.parse,
                field="accepted_entity_version_id",
            ),
            alias_id=_optional_id(
                item["alias_id"], EntityAliasId.parse, field="alias_id"
            ),
            alias_kind=(
                None
                if item["alias_kind"] is None
                else _enum(item["alias_kind"], EntityAliasKind, field="alias_kind")
            ),
            reason_code=_string(item["reason_code"], field="reason_code"),
            decision_policy_version=_string(
                item["decision_policy_version"], field="decision_policy_version"
            ),
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(
        value,
        field="entity_resolution_decision",
        keys=keys,
        build=build,
    )


def _dependency_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntityResolutionDependencyRequest:
        material = item["material"]
        if not isinstance(material, bool):
            raise PayloadSchemaValidationError("material must be boolean")
        return EntityResolutionDependencyRequest(
            dependency_id=_required_id(
                item["dependency_id"],
                EntityResolutionDependencyId.parse,
                field="dependency_id",
            ),
            dependent_proposal_id=_required_id(
                item["dependent_proposal_id"],
                ProposalEnvelopeId.parse,
                field="dependent_proposal_id",
            ),
            expected_dependent_proposal_digest=_string(
                item["expected_dependent_proposal_digest"],
                field="expected_dependent_proposal_digest",
            ),
            resolution_proposal_id=_required_id(
                item["resolution_proposal_id"],
                EntityResolutionProposalId.parse,
                field="resolution_proposal_id",
            ),
            expected_resolution_proposal_version_id=_required_id(
                item["expected_resolution_proposal_version_id"],
                EntityResolutionProposalVersionId.parse,
                field="expected_resolution_proposal_version_id",
            ),
            expected_resolution_proposal_digest=_string(
                item["expected_resolution_proposal_digest"],
                field="expected_resolution_proposal_digest",
            ),
            material=material,
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(
        value,
        field="entity_resolution_dependency",
        keys=keys,
        build=build,
    )


def _merge_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntityMergeDecisionRequest:
        return EntityMergeDecisionRequest(
            merge_decision_id=_required_id(
                item["merge_decision_id"],
                EntityMergeDecisionId.parse,
                field="merge_decision_id",
            ),
            predecessors=_lineage_versions_payload(
                item["predecessors"], field="predecessors"
            ),
            successor_entity_id=_required_id(
                item["successor_entity_id"],
                CanonicalEntityId.parse,
                field="successor_entity_id",
            ),
            successor_entity_version_id=_required_id(
                item["successor_entity_version_id"],
                CanonicalEntityVersionId.parse,
                field="successor_entity_version_id",
            ),
            preferred_continuation_entity_id=_required_id(
                item["preferred_continuation_entity_id"],
                CanonicalEntityId.parse,
                field="preferred_continuation_entity_id",
            ),
            basis_resolution_proposal_ids=_ids(
                item["basis_resolution_proposal_ids"],
                EntityResolutionProposalId.parse,
                field="basis_resolution_proposal_ids",
            ),
            reason_code=_string(item["reason_code"], field="reason_code"),
            decision_policy_version=_string(
                item["decision_policy_version"], field="decision_policy_version"
            ),
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(value, field="entity_merge_decision", keys=keys, build=build)


def _split_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntitySplitDecisionRequest:
        allocations_raw = item["allocations"]
        if not isinstance(allocations_raw, list):
            raise PayloadSchemaValidationError("allocations must be an object array")
        allocations = tuple(
            EntitySplitAllocation(
                mention_id=_required_id(
                    _object(
                        allocation,
                        field="split_allocation",
                        keys=frozenset({"mention_id", "successor_entity_id"}),
                    )["mention_id"],
                    EntityMentionId.parse,
                    field="allocation.mention_id",
                ),
                successor_entity_id=_required_id(
                    allocation["successor_entity_id"],
                    CanonicalEntityId.parse,
                    field="allocation.successor_entity_id",
                ),
            )
            for allocation in allocations_raw
        )
        return EntitySplitDecisionRequest(
            split_decision_id=_required_id(
                item["split_decision_id"],
                EntitySplitDecisionId.parse,
                field="split_decision_id",
            ),
            source_entity_id=_required_id(
                item["source_entity_id"],
                CanonicalEntityId.parse,
                field="source_entity_id",
            ),
            expected_source_version_id=_required_id(
                item["expected_source_version_id"],
                CanonicalEntityVersionId.parse,
                field="expected_source_version_id",
            ),
            successors=_lineage_versions_payload(
                item["successors"], field="successors"
            ),
            allocations=allocations,
            reason_code=_string(item["reason_code"], field="reason_code"),
            decision_policy_version=_string(
                item["decision_policy_version"], field="decision_policy_version"
            ),
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(value, field="entity_split_decision", keys=keys, build=build)


def _reversal_payload(value: Any) -> bytes:
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

    def build(item: dict[str, Any]) -> EntityReversalDecisionRequest:
        return EntityReversalDecisionRequest(
            reversal_decision_id=_required_id(
                item["reversal_decision_id"],
                EntityReversalDecisionId.parse,
                field="reversal_decision_id",
            ),
            target_kind=_enum(
                item["target_kind"], EntityReversalTargetKind, field="target_kind"
            ),
            target_decision_id=_string(
                item["target_decision_id"], field="target_decision_id"
            ),
            expected_current_entity_version_ids=_ids(
                item["expected_current_entity_version_ids"],
                CanonicalEntityVersionId.parse,
                field="expected_current_entity_version_ids",
            ),
            restorations=_lineage_versions_payload(
                item["restorations"], field="restorations"
            ),
            reason_code=_string(item["reason_code"], field="reason_code"),
            decision_policy_version=_string(
                item["decision_policy_version"], field="decision_policy_version"
            ),
            idempotency_key="payload-validation-only",
        )

    return _canonicalize_request(
        value,
        field="entity_reversal_decision",
        keys=keys,
        build=build,
    )


def _id(cls: type, suffix: int) -> Any:
    return cls.parse(f"00000000-0000-4000-8000-{suffix:012d}")


def _golden_requests() -> tuple[Any, ...]:
    mention = EntityMentionAdmissionRequest(
        mention_id=_id(EntityMentionId, 5201),
        source_proposal_id=_id(ProposalEnvelopeId, 5101),
        expected_source_proposal_digest="sha256:" + "1" * 64,
        entity_kind=EntityKind.GOVERNMENT_BODY,
        language="en-GB",
        script=EntityScript.LATIN,
        normalized_text="hong kong transport department",
        normalization_contract_digest=ENTITY_NORMALISATION_CONTRACT_DIGEST,
        idempotency_key="golden-mention",
    )
    proposal = EntityResolutionProposalRequest(
        proposal_id=_id(EntityResolutionProposalId, 5301),
        proposal_version_id=_id(EntityResolutionProposalVersionId, 5302),
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=mention.source_proposal_id,
        expected_source_proposal_digest=mention.expected_source_proposal_digest,
        kind=EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
        subject_mention_id=mention.mention_id,
        object_mention_id=None,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=8000,
        uncertainty_codes=("EDITORIAL_REVIEW_REQUIRED",),
        basis_codes=("EXACT_PASSAGE",),
        idempotency_key="golden-proposal",
    )
    dependency = EntityResolutionDependencyRequest(
        dependency_id=_id(EntityResolutionDependencyId, 5350),
        dependent_proposal_id=_id(ProposalEnvelopeId, 5102),
        expected_dependent_proposal_digest="sha256:" + "2" * 64,
        resolution_proposal_id=proposal.proposal_id,
        expected_resolution_proposal_version_id=proposal.proposal_version_id,
        expected_resolution_proposal_digest=proposal.digest,
        material=True,
        idempotency_key="golden-dependency",
    )
    entity_id = _id(CanonicalEntityId, 5401)
    version_id = _id(CanonicalEntityVersionId, 5402)
    decision = EntityResolutionDecisionRequest(
        proposal_id=proposal.proposal_id,
        expected_proposal_version_id=proposal.proposal_version_id,
        expected_proposal_digest=proposal.digest,
        action=EntityResolutionDecisionAction.ACCEPT,
        expected_decision_version=0,
        expected_previous_decision_id=None,
        accepted_entity_id=entity_id,
        accepted_entity_version_id=version_id,
        alias_id=_id(EntityAliasId, 5403),
        alias_kind=EntityAliasKind.PRIMARY_NAME,
        reason_code="EDITORIAL_ACCEPT",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="golden-decision",
    )
    predecessors = tuple(
        sorted(
            (
                EntityLineageVersion(
                    _id(CanonicalEntityId, 5501),
                    _id(CanonicalEntityVersionId, 5511),
                ),
                EntityLineageVersion(
                    _id(CanonicalEntityId, 5502),
                    _id(CanonicalEntityVersionId, 5512),
                ),
            ),
            key=lambda item: str(item.entity_id),
        )
    )
    merge = EntityMergeDecisionRequest(
        merge_decision_id=_id(EntityMergeDecisionId, 5520),
        predecessors=predecessors,
        successor_entity_id=_id(CanonicalEntityId, 5503),
        successor_entity_version_id=_id(CanonicalEntityVersionId, 5513),
        preferred_continuation_entity_id=predecessors[0].entity_id,
        basis_resolution_proposal_ids=(proposal.proposal_id,),
        reason_code="EDITORIAL_MERGE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="golden-merge",
    )
    successors = tuple(
        sorted(
            (
                EntityLineageVersion(
                    _id(CanonicalEntityId, 5602),
                    _id(CanonicalEntityVersionId, 5612),
                ),
                EntityLineageVersion(
                    _id(CanonicalEntityId, 5603),
                    _id(CanonicalEntityVersionId, 5613),
                ),
            ),
            key=lambda item: str(item.entity_id),
        )
    )
    allocations = tuple(
        sorted(
            (
                EntitySplitAllocation(mention.mention_id, successors[0].entity_id),
                EntitySplitAllocation(
                    _id(EntityMentionId, 5202), successors[1].entity_id
                ),
            ),
            key=lambda item: (str(item.mention_id), str(item.successor_entity_id)),
        )
    )
    split = EntitySplitDecisionRequest(
        split_decision_id=_id(EntitySplitDecisionId, 5620),
        source_entity_id=_id(CanonicalEntityId, 5601),
        expected_source_version_id=_id(CanonicalEntityVersionId, 5611),
        successors=successors,
        allocations=allocations,
        reason_code="EDITORIAL_SPLIT",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="golden-split",
    )
    reversal = EntityReversalDecisionRequest(
        reversal_decision_id=_id(EntityReversalDecisionId, 5630),
        target_kind=EntityReversalTargetKind.SPLIT,
        target_decision_id=str(split.split_decision_id),
        expected_current_entity_version_ids=tuple(
            sorted(
                (
                    split.expected_source_version_id,
                    *(item.entity_version_id for item in successors),
                ),
                key=str,
            )
        ),
        restorations=(
            EntityLineageVersion(
                split.source_entity_id,
                _id(CanonicalEntityVersionId, 5614),
            ),
        ),
        reason_code="EDITORIAL_REVERSAL",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="golden-reversal",
    )
    return mention, proposal, decision, dependency, merge, split, reversal


def entity_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    requests = _golden_requests()
    specifications = (
        (_MENTION_SCHEMA, "mention", _mention_payload, requests[0]),
        (_PROPOSAL_SCHEMA, "proposal", _proposal_payload, requests[1]),
        (_DECISION_SCHEMA, "decision", _decision_payload, requests[2]),
        (_DEPENDENCY_SCHEMA, "dependency", _dependency_payload, requests[3]),
        (_MERGE_SCHEMA, "merge", _merge_payload, requests[4]),
        (_SPLIT_SCHEMA, "split", _split_payload, requests[5]),
        (_REVERSAL_SCHEMA, "reversal", _reversal_payload, requests[6]),
    )
    return tuple(
        PayloadSchemaContract(
            schema_version=schema_version,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                f"entity-{name}-typed-exact-canonical-json-v1"
            ),
            canonicalizer=canonicalizer,
            golden_vectors=(
                PayloadGoldenVector(
                    name=f"entity-{name}-exact-fields",
                    input_identity=f"increment-4b-{name}-golden-v1",
                    value=request.canonical_value(),
                    expected_bytes=canonical_json_bytes(request.canonical_value()),
                ),
            ),
        )
        for schema_version, name, canonicalizer, request in specifications
    )


def entity_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {item.schema_version: item for item in entity_payload_contracts()}
    specifications = (
        (
            ENTITY_MENTION_ADMIT_COMMAND,
            "entity_mention",
            "entity.mention.admitted",
            _MENTION_SCHEMA,
            TrustScope.PROPOSED,
            "authority.entity.mention",
        ),
        (
            ENTITY_RESOLUTION_PROPOSE_COMMAND,
            "entity_resolution_proposal_version",
            "entity.resolution.proposed",
            _PROPOSAL_SCHEMA,
            TrustScope.PROPOSED,
            "authority.entity.propose",
        ),
        (
            ENTITY_RESOLUTION_DECIDE_COMMAND,
            "entity_resolution_decision",
            "entity.resolution.decided",
            _DECISION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.entity.decide",
        ),
        (
            ENTITY_RESOLUTION_DEPENDENCY_BIND_COMMAND,
            "entity_resolution_dependency",
            "entity.resolution.dependency.bound",
            _DEPENDENCY_SCHEMA,
            TrustScope.PROPOSED,
            "authority.entity.dependency",
        ),
        (
            ENTITY_MERGE_DECIDE_COMMAND,
            "entity_merge_decision",
            "entity.merge.decided",
            _MERGE_SCHEMA,
            TrustScope.ADMITTED,
            "authority.entity.merge",
        ),
        (
            ENTITY_SPLIT_DECIDE_COMMAND,
            "entity_split_decision",
            "entity.split.decided",
            _SPLIT_SCHEMA,
            TrustScope.ADMITTED,
            "authority.entity.split",
        ),
        (
            ENTITY_REVERSAL_DECIDE_COMMAND,
            "entity_reversal_decision",
            "entity.reversal.decided",
            _REVERSAL_SCHEMA,
            TrustScope.ADMITTED,
            "authority.entity.reverse",
        ),
    )
    return tuple(
        CommandDefinition(
            command_type=command_type,
            definition_version=_DEFINITION_VERSION,
            aggregate_type=aggregate_type,
            event_type=event_type,
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version=contracts[schema].schema_version,
            payload_schema_contract_version=contracts[schema].contract_version,
            payload_schema_contract_digest=contracts[schema].contract_digest,
            payload_canonicalizer_version=(
                contracts[schema].canonicalizer_implementation_version
            ),
            trust_scope=trust_scope,
            security_scope="authority.entity",
            retention_scope="authority.audit",
            required_scope=required_scope,
            max_inline_bytes=512 * 1024,
        )
        for (
            command_type,
            aggregate_type,
            event_type,
            schema,
            trust_scope,
            required_scope,
        ) in specifications
    )


def merge_entity_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    extraction_registry, extraction_schemas = merge_extraction_authority_registries(
        command_registry=command_registry,
        payload_schemas=payload_schemas,
    )
    definitions = list(extraction_registry.definitions())
    by_key = {(item.command_type, item.definition_version): item for item in definitions}
    for definition in entity_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ValueError(f"entity command identity conflict: {definition.command_type}")
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: extraction_registry.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in ENTITY_COMMAND_TYPES
    }
    current_commands.update(
        {command_type: _DEFINITION_VERSION for command_type in ENTITY_COMMAND_TYPES}
    )

    contracts = list(extraction_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    additions = entity_payload_contracts()
    for contract in additions:
        key = (contract.schema_version, contract.payload_mode, contract.contract_version)
        existing = by_schema.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ValueError(f"entity payload identity conflict: {contract.schema_version}")
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    entity_versions = {item.schema_version for item in additions}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in entity_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = extraction_schemas.resolve(
                schema_version, mode
            ).contract_version
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "ENTITY_COMMAND_TYPES",
    "ENTITY_MENTION_ADMIT_COMMAND",
    "ENTITY_MERGE_DECIDE_COMMAND",
    "ENTITY_RESOLUTION_DECIDE_COMMAND",
    "ENTITY_RESOLUTION_DEPENDENCY_BIND_COMMAND",
    "ENTITY_RESOLUTION_PROPOSE_COMMAND",
    "ENTITY_REVERSAL_DECIDE_COMMAND",
    "ENTITY_SPLIT_DECIDE_COMMAND",
    "entity_command_definitions",
    "entity_payload_contracts",
    "merge_entity_authority_registries",
]
