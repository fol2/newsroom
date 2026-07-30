from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.types import EventId, TrustScope, UtcTimestamp
from newsroom.sources.types import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ProposalEnvelopeId,
    ProposalSetId,
)

from .types import (
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityContractError,
    EntityKind,
    EntityLineageDecisionKind,
    EntityMergeDecisionId,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionId,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalVersionId,
    EntityResolutionState,
    EntityReversalDecisionId,
    EntityReversalTargetKind,
    EntityScript,
    EntitySplitDecisionId,
    bounded_int,
    bounded_text,
    bounded_token,
    canonical_digest,
    sorted_text_tuple,
    ENTITY_NORMALISATION_CONTRACT_DIGEST,
    classify_entity_script,
    require_normalized_entity_text,
)


def _require_typed(value: object, expected: type, *, field: str) -> None:
    if not isinstance(value, expected):
        raise EntityContractError(f"{field} must be typed")


def _require_sorted_ids(
    values: tuple[object, ...],
    expected: type,
    *,
    field: str,
    minimum: int = 1,
    maximum: int = 128,
) -> None:
    if not isinstance(values, tuple):
        raise EntityContractError(f"{field} must be an immutable tuple")
    if not minimum <= len(values) <= maximum:
        raise EntityContractError(
            f"{field} must contain between {minimum} and {maximum} identities"
        )
    if any(not isinstance(value, expected) for value in values):
        raise EntityContractError(f"{field} contains an untyped identity")
    texts = tuple(str(value) for value in values)
    if texts != tuple(sorted(set(texts))):
        raise EntityContractError(f"{field} must be sorted and unique")


@dataclass(frozen=True, slots=True)
class EntityMentionAdmissionRequest:
    mention_id: EntityMentionId
    source_proposal_id: ProposalEnvelopeId
    expected_source_proposal_digest: str
    entity_kind: EntityKind
    language: str
    script: EntityScript
    normalized_text: str
    normalization_contract_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_typed(self.mention_id, EntityMentionId, field="mention_id")
        _require_typed(
            self.source_proposal_id,
            ProposalEnvelopeId,
            field="source_proposal_id",
        )
        canonical_digest(
            self.expected_source_proposal_digest,
            field="expected_source_proposal_digest",
        )
        _require_typed(self.entity_kind, EntityKind, field="entity_kind")
        bounded_token(self.language, field="entity_mention_language")
        _require_typed(self.script, EntityScript, field="entity_script")
        bounded_text(
            self.normalized_text,
            field="entity_mention_normalized_text",
            maximum_bytes=4096,
        )
        canonical_digest(
            self.normalization_contract_digest,
            field="normalization_contract_digest",
        )
        if self.normalization_contract_digest != ENTITY_NORMALISATION_CONTRACT_DIGEST:
            raise EntityContractError(
                "entity mention uses an unapproved normalisation contract"
            )
        require_normalized_entity_text(
            self.normalized_text, field="entity_mention_normalized_text"
        )
        bounded_text(
            self.idempotency_key,
            field="entity_mention_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "mention_id": str(self.mention_id),
            "source_proposal_id": str(self.source_proposal_id),
            "expected_source_proposal_digest": self.expected_source_proposal_digest,
            "entity_kind": self.entity_kind.value,
            "language": self.language,
            "script": self.script.value,
            "normalized_text": self.normalized_text,
            "normalization_contract_digest": self.normalization_contract_digest,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityMention:
    mention_id: EntityMentionId
    source_proposal_id: ProposalEnvelopeId
    proposal_set_id: ProposalSetId
    output_id: ExtractionOutputId
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    item_id: SourceItemId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId
    passage_id: ExtractionPassageId
    start_byte: int
    end_byte: int
    evidence_text_digest: str
    mention_text: str
    normalized_text: str
    normalization_contract_digest: str
    language: str
    script: EntityScript
    entity_kind: EntityKind
    confidence_basis_points: int | None
    uncertainty_codes: tuple[str, ...]
    rationale_codes: tuple[str, ...]
    source_proposal_digest: str
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("mention_id", EntityMentionId),
            ("source_proposal_id", ProposalEnvelopeId),
            ("proposal_set_id", ProposalSetId),
            ("output_id", ExtractionOutputId),
            ("run_id", ExtractionRunId),
            ("run_version_id", ExtractionRunVersionId),
            ("definition_id", SourceDefinitionId),
            ("definition_version_id", SourceDefinitionVersionId),
            ("item_id", SourceItemId),
            ("revision_id", SourceRevisionId),
            ("representation_id", DiscoveryRepresentationId),
            ("passage_id", ExtractionPassageId),
            ("authority_event_id", EventId),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        bounded_int(
            self.start_byte,
            field="mention_start_byte",
            minimum=0,
            maximum=2**31 - 1,
        )
        bounded_int(
            self.end_byte,
            field="mention_end_byte",
            minimum=1,
            maximum=2**31 - 1,
        )
        if self.end_byte <= self.start_byte:
            raise EntityContractError("mention evidence range must be non-empty")
        canonical_digest(
            self.evidence_text_digest,
            field="mention_evidence_text_digest",
        )
        bounded_text(self.mention_text, field="mention_text", maximum_bytes=4096)
        bounded_text(
            self.normalized_text,
            field="mention_normalized_text",
            maximum_bytes=4096,
        )
        canonical_digest(
            self.normalization_contract_digest,
            field="mention_normalization_contract_digest",
        )
        if self.normalization_contract_digest != ENTITY_NORMALISATION_CONTRACT_DIGEST:
            raise EntityContractError(
                "retained mention uses an unapproved normalisation contract"
            )
        require_normalized_entity_text(
            self.normalized_text, field="mention_normalized_text"
        )
        bounded_token(self.language, field="mention_language")
        _require_typed(self.script, EntityScript, field="mention_script")
        if self.script is not classify_entity_script(self.mention_text):
            raise EntityContractError("mention script differs from exact text")
        _require_typed(self.entity_kind, EntityKind, field="mention_entity_kind")
        if self.confidence_basis_points is not None:
            bounded_int(
                self.confidence_basis_points,
                field="mention_confidence_basis_points",
                minimum=0,
                maximum=10_000,
            )
        normalized_uncertainties = sorted_text_tuple(
            self.uncertainty_codes,
            field="mention_uncertainty_codes",
        )
        normalized_rationales = sorted_text_tuple(
            self.rationale_codes,
            field="mention_rationale_codes",
            allow_empty=False,
        )
        if normalized_uncertainties != self.uncertainty_codes:
            raise EntityContractError("mention uncertainty codes must be sorted")
        if normalized_rationales != self.rationale_codes:
            raise EntityContractError("mention rationale codes must be sorted")
        canonical_digest(
            self.source_proposal_digest,
            field="mention_source_proposal_digest",
        )
        bounded_int(
            self.authority_ledger_seq,
            field="mention_authority_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )
        _require_typed(self.recorded_at, UtcTimestamp, field="mention_recorded_at")
        if not isinstance(self.replayed, bool):
            raise EntityContractError("mention replay flag must be boolean")
        text_bytes = self.mention_text.encode("utf-8")
        if digest_bytes(text_bytes) != self.evidence_text_digest:
            raise EntityContractError(
                "mention text must match the exact retained evidence digest"
            )
        if len(text_bytes) != self.end_byte - self.start_byte:
            raise EntityContractError(
                "mention text length must match its exact byte range"
            )

    @property
    def trust_scope(self) -> TrustScope:
        return TrustScope.PROPOSED

    def canonical_value(self) -> dict[str, object]:
        return {
            "mention_id": str(self.mention_id),
            "source_proposal_id": str(self.source_proposal_id),
            "proposal_set_id": str(self.proposal_set_id),
            "output_id": str(self.output_id),
            "run_id": str(self.run_id),
            "run_version_id": str(self.run_version_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "item_id": str(self.item_id),
            "revision_id": str(self.revision_id),
            "representation_id": str(self.representation_id),
            "passage_id": str(self.passage_id),
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "evidence_text_digest": self.evidence_text_digest,
            "mention_text": self.mention_text,
            "normalized_text": self.normalized_text,
            "normalization_contract_digest": self.normalization_contract_digest,
            "language": self.language,
            "script": self.script.value,
            "entity_kind": self.entity_kind.value,
            "confidence_basis_points": self.confidence_basis_points,
            "uncertainty_codes": list(self.uncertainty_codes),
            "rationale_codes": list(self.rationale_codes),
            "source_proposal_digest": self.source_proposal_digest,
            "trust_scope": self.trust_scope.value,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                "source_proposal_id": str(self.source_proposal_id),
                "source_proposal_digest": self.source_proposal_digest,
                "passage_id": str(self.passage_id),
                "start_byte": self.start_byte,
                "end_byte": self.end_byte,
                "mention_text": self.mention_text,
                "normalized_text": self.normalized_text,
                "normalization_contract_digest": (
                    self.normalization_contract_digest
                ),
                "language": self.language,
                "script": self.script.value,
                "entity_kind": self.entity_kind.value,
            }
        )


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    entity_id: CanonicalEntityId
    entity_kind: EntityKind
    created_by_decision_id: EntityResolutionDecisionId
    initial_version_id: CanonicalEntityVersionId
    authority_event_id: EventId
    authority_ledger_seq: int
    created_at: UtcTimestamp

    def __post_init__(self) -> None:
        _require_typed(self.entity_id, CanonicalEntityId, field="entity_id")
        _require_typed(self.entity_kind, EntityKind, field="entity_kind")
        _require_typed(
            self.created_by_decision_id,
            EntityResolutionDecisionId,
            field="created_by_decision_id",
        )
        _require_typed(
            self.initial_version_id,
            CanonicalEntityVersionId,
            field="initial_version_id",
        )
        _require_typed(
            self.authority_event_id,
            EventId,
            field="entity_authority_event_id",
        )
        bounded_int(
            self.authority_ledger_seq,
            field="entity_authority_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )
        _require_typed(self.created_at, UtcTimestamp, field="entity_created_at")

    def canonical_value(self) -> dict[str, object]:
        return {
            "entity_id": str(self.entity_id),
            "entity_kind": self.entity_kind.value,
            "created_by_decision_id": str(self.created_by_decision_id),
            "initial_version_id": str(self.initial_version_id),
            "trust_scope": TrustScope.ADMITTED.value,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class CanonicalEntityVersion:
    entity_version_id: CanonicalEntityVersionId
    entity_id: CanonicalEntityId
    version_number: int
    previous_entity_version_id: CanonicalEntityVersionId | None
    entity_kind: EntityKind
    lifecycle: CanonicalEntityLifecycle
    lineage_decision_kind: EntityLineageDecisionKind | None
    lineage_decision_id: str | None
    preferred_continuation_entity_id: CanonicalEntityId | None
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        _require_typed(
            self.entity_version_id,
            CanonicalEntityVersionId,
            field="entity_version_id",
        )
        _require_typed(self.entity_id, CanonicalEntityId, field="entity_id")
        bounded_int(
            self.version_number,
            field="entity_version_number",
            minimum=1,
            maximum=1_000_000,
        )
        if self.version_number == 1:
            if self.previous_entity_version_id is not None:
                raise EntityContractError(
                    "initial entity version cannot name a predecessor"
                )
        else:
            _require_typed(
                self.previous_entity_version_id,
                CanonicalEntityVersionId,
                field="previous_entity_version_id",
            )
        _require_typed(self.entity_kind, EntityKind, field="entity_kind")
        _require_typed(
            self.lifecycle,
            CanonicalEntityLifecycle,
            field="entity_lifecycle",
        )
        if self.lineage_decision_kind is None:
            if self.lineage_decision_id is not None:
                raise EntityContractError(
                    "entity version cannot name a lineage decision without its kind"
                )
        else:
            _require_typed(
                self.lineage_decision_kind,
                EntityLineageDecisionKind,
                field="lineage_decision_kind",
            )
            bounded_text(
                self.lineage_decision_id or "",
                field="lineage_decision_id",
                maximum_bytes=36,
            )
        if self.lifecycle is CanonicalEntityLifecycle.ACTIVE:
            if self.preferred_continuation_entity_id not in {None, self.entity_id}:
                raise EntityContractError(
                    "active entity version cannot prefer another entity"
                )
        elif self.preferred_continuation_entity_id is not None:
            _require_typed(
                self.preferred_continuation_entity_id,
                CanonicalEntityId,
                field="preferred_continuation_entity_id",
            )
        _require_typed(
            self.authority_event_id,
            EventId,
            field="entity_version_authority_event_id",
        )
        bounded_int(
            self.authority_ledger_seq,
            field="entity_version_authority_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )
        _require_typed(
            self.recorded_at,
            UtcTimestamp,
            field="entity_version_recorded_at",
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "entity_version_id": str(self.entity_version_id),
            "entity_id": str(self.entity_id),
            "version_number": self.version_number,
            "previous_entity_version_id": (
                None
                if self.previous_entity_version_id is None
                else str(self.previous_entity_version_id)
            ),
            "entity_kind": self.entity_kind.value,
            "lifecycle": self.lifecycle.value,
            "lineage_decision_kind": (
                None
                if self.lineage_decision_kind is None
                else self.lineage_decision_kind.value
            ),
            "lineage_decision_id": self.lineage_decision_id,
            "preferred_continuation_entity_id": (
                None
                if self.preferred_continuation_entity_id is None
                else str(self.preferred_continuation_entity_id)
            ),
            "trust_scope": TrustScope.ADMITTED.value,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityAlias:
    alias_id: EntityAliasId
    entity_id: CanonicalEntityId
    entity_version_id: CanonicalEntityVersionId
    alias_text: str
    normalized_text: str
    normalization_contract_digest: str
    language: str
    script: EntityScript
    alias_kind: EntityAliasKind
    valid_from: UtcTimestamp | None
    valid_until: UtcTimestamp | None
    provenance_mention_id: EntityMentionId
    resolution_decision_id: EntityResolutionDecisionId
    uncertainty_codes: tuple[str, ...]
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("alias_id", EntityAliasId),
            ("entity_id", CanonicalEntityId),
            ("entity_version_id", CanonicalEntityVersionId),
            ("script", EntityScript),
            ("alias_kind", EntityAliasKind),
            ("provenance_mention_id", EntityMentionId),
            ("resolution_decision_id", EntityResolutionDecisionId),
            ("authority_event_id", EventId),
            ("recorded_at", UtcTimestamp),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        bounded_text(self.alias_text, field="alias_text", maximum_bytes=4096)
        bounded_text(
            self.normalized_text,
            field="alias_normalized_text",
            maximum_bytes=4096,
        )
        canonical_digest(
            self.normalization_contract_digest,
            field="alias_normalization_contract_digest",
        )
        if self.normalization_contract_digest != ENTITY_NORMALISATION_CONTRACT_DIGEST:
            raise EntityContractError(
                "entity alias uses an unapproved normalisation contract"
            )
        require_normalized_entity_text(
            self.normalized_text, field="alias_normalized_text"
        )
        if self.script is not classify_entity_script(self.alias_text):
            raise EntityContractError("alias script differs from exact text")
        bounded_token(self.language, field="alias_language")
        if self.valid_from is not None:
            _require_typed(self.valid_from, UtcTimestamp, field="alias_valid_from")
        if self.valid_until is not None:
            _require_typed(self.valid_until, UtcTimestamp, field="alias_valid_until")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until.value <= self.valid_from.value
        ):
            raise EntityContractError("alias validity interval must be increasing")
        normalized = sorted_text_tuple(
            self.uncertainty_codes,
            field="alias_uncertainty_codes",
        )
        if normalized != self.uncertainty_codes:
            raise EntityContractError("alias uncertainty codes must be sorted")
        bounded_int(
            self.authority_ledger_seq,
            field="alias_authority_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )

    @property
    def trust_scope(self) -> TrustScope:
        return TrustScope.ADMITTED

    def canonical_value(self) -> dict[str, object]:
        return {
            "alias_id": str(self.alias_id),
            "entity_id": str(self.entity_id),
            "entity_version_id": str(self.entity_version_id),
            "alias_text": self.alias_text,
            "normalized_text": self.normalized_text,
            "normalization_contract_digest": self.normalization_contract_digest,
            "language": self.language,
            "script": self.script.value,
            "alias_kind": self.alias_kind.value,
            "valid_from": (
                None if self.valid_from is None else self.valid_from.to_text()
            ),
            "valid_until": (
                None if self.valid_until is None else self.valid_until.to_text()
            ),
            "provenance_mention_id": str(self.provenance_mention_id),
            "resolution_decision_id": str(self.resolution_decision_id),
            "uncertainty_codes": list(self.uncertainty_codes),
            "trust_scope": self.trust_scope.value,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityResolutionProposalRequest:
    proposal_id: EntityResolutionProposalId
    proposal_version_id: EntityResolutionProposalVersionId
    version_number: int
    expected_previous_version_id: EntityResolutionProposalVersionId | None
    source_proposal_id: ProposalEnvelopeId
    expected_source_proposal_digest: str
    kind: EntityResolutionProposalKind
    subject_mention_id: EntityMentionId
    object_mention_id: EntityMentionId | None
    candidate_entity_id: CanonicalEntityId | None
    candidate_entity_version_id: CanonicalEntityVersionId | None
    confidence_basis_points: int | None
    uncertainty_codes: tuple[str, ...]
    basis_codes: tuple[str, ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("proposal_id", EntityResolutionProposalId),
            ("proposal_version_id", EntityResolutionProposalVersionId),
            ("source_proposal_id", ProposalEnvelopeId),
            ("kind", EntityResolutionProposalKind),
            ("subject_mention_id", EntityMentionId),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        bounded_int(
            self.version_number,
            field="resolution_proposal_version_number",
            minimum=1,
            maximum=1_000_000,
        )
        if self.version_number == 1:
            if self.expected_previous_version_id is not None:
                raise EntityContractError(
                    "initial resolution proposal cannot name a predecessor"
                )
        else:
            _require_typed(
                self.expected_previous_version_id,
                EntityResolutionProposalVersionId,
                field="expected_previous_version_id",
            )
        canonical_digest(
            self.expected_source_proposal_digest,
            field="expected_source_proposal_digest",
        )
        if self.kind is EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY:
            if any(
                value is not None
                for value in (
                    self.object_mention_id,
                    self.candidate_entity_id,
                    self.candidate_entity_version_id,
                )
            ):
                raise EntityContractError(
                    "new-entity proposal cannot name an existing target"
                )
        elif self.kind in {
            EntityResolutionProposalKind.MENTION_TO_ENTITY,
            EntityResolutionProposalKind.ALIAS_TO_ENTITY,
        }:
            _require_typed(
                self.candidate_entity_id,
                CanonicalEntityId,
                field="candidate_entity_id",
            )
            _require_typed(
                self.candidate_entity_version_id,
                CanonicalEntityVersionId,
                field="candidate_entity_version_id",
            )
            if self.object_mention_id is not None:
                raise EntityContractError(
                    "entity-target proposal cannot also name an object mention"
                )
        elif self.kind is EntityResolutionProposalKind.MENTION_EQUIVALENCE:
            _require_typed(
                self.object_mention_id,
                EntityMentionId,
                field="object_mention_id",
            )
            if self.object_mention_id == self.subject_mention_id:
                raise EntityContractError(
                    "mention equivalence cannot target the same mention"
                )
            if self.candidate_entity_id is not None or self.candidate_entity_version_id is not None:
                raise EntityContractError(
                    "mention equivalence cannot name an entity target"
                )
        if self.confidence_basis_points is not None:
            bounded_int(
                self.confidence_basis_points,
                field="resolution_confidence_basis_points",
                minimum=0,
                maximum=10_000,
            )
        normalized_uncertainty = sorted_text_tuple(
            self.uncertainty_codes,
            field="resolution_uncertainty_codes",
        )
        normalized_basis = sorted_text_tuple(
            self.basis_codes,
            field="resolution_basis_codes",
            allow_empty=False,
        )
        if normalized_uncertainty != self.uncertainty_codes:
            raise EntityContractError("resolution uncertainty codes must be sorted")
        if normalized_basis != self.basis_codes:
            raise EntityContractError("resolution basis codes must be sorted")
        bounded_text(
            self.idempotency_key,
            field="resolution_proposal_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "proposal_version_id": str(self.proposal_version_id),
            "version_number": self.version_number,
            "expected_previous_version_id": (
                None
                if self.expected_previous_version_id is None
                else str(self.expected_previous_version_id)
            ),
            "source_proposal_id": str(self.source_proposal_id),
            "expected_source_proposal_digest": self.expected_source_proposal_digest,
            "kind": self.kind.value,
            "subject_mention_id": str(self.subject_mention_id),
            "object_mention_id": (
                None
                if self.object_mention_id is None
                else str(self.object_mention_id)
            ),
            "candidate_entity_id": (
                None
                if self.candidate_entity_id is None
                else str(self.candidate_entity_id)
            ),
            "candidate_entity_version_id": (
                None
                if self.candidate_entity_version_id is None
                else str(self.candidate_entity_version_id)
            ),
            "confidence_basis_points": self.confidence_basis_points,
            "uncertainty_codes": list(self.uncertainty_codes),
            "basis_codes": list(self.basis_codes),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def stable_semantic_digest(self) -> str:
        return digest_canonical(
            {
                "source_proposal_id": str(self.source_proposal_id),
                "expected_source_proposal_digest": (
                    self.expected_source_proposal_digest
                ),
                "kind": self.kind.value,
                "subject_mention_id": str(self.subject_mention_id),
                "object_mention_id": (
                    None
                    if self.object_mention_id is None
                    else str(self.object_mention_id)
                ),
                "candidate_entity_id": (
                    None
                    if self.candidate_entity_id is None
                    else str(self.candidate_entity_id)
                ),
                "candidate_entity_version_id": (
                    None
                    if self.candidate_entity_version_id is None
                    else str(self.candidate_entity_version_id)
                ),
                "basis_codes": list(self.basis_codes),
            }
        )


@dataclass(frozen=True, slots=True)
class EntityResolutionProposalVersion:
    proposal_id: EntityResolutionProposalId
    proposal_version_id: EntityResolutionProposalVersionId
    version_number: int
    previous_proposal_version_id: EntityResolutionProposalVersionId | None
    source_proposal_id: ProposalEnvelopeId
    source_proposal_digest: str
    kind: EntityResolutionProposalKind
    subject_mention_id: EntityMentionId
    object_mention_id: EntityMentionId | None
    candidate_entity_id: CanonicalEntityId | None
    candidate_entity_version_id: CanonicalEntityVersionId | None
    confidence_basis_points: int | None
    uncertainty_codes: tuple[str, ...]
    basis_codes: tuple[str, ...]
    stable_semantic_digest: str
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        request = EntityResolutionProposalRequest(
            proposal_id=self.proposal_id,
            proposal_version_id=self.proposal_version_id,
            version_number=self.version_number,
            expected_previous_version_id=self.previous_proposal_version_id,
            source_proposal_id=self.source_proposal_id,
            expected_source_proposal_digest=self.source_proposal_digest,
            kind=self.kind,
            subject_mention_id=self.subject_mention_id,
            object_mention_id=self.object_mention_id,
            candidate_entity_id=self.candidate_entity_id,
            candidate_entity_version_id=self.candidate_entity_version_id,
            confidence_basis_points=self.confidence_basis_points,
            uncertainty_codes=self.uncertainty_codes,
            basis_codes=self.basis_codes,
            idempotency_key="retained.resolution.proposal",
        )
        canonical_digest(
            self.stable_semantic_digest,
            field="resolution_stable_semantic_digest",
        )
        if request.stable_semantic_digest != self.stable_semantic_digest:
            raise EntityContractError(
                "retained resolution proposal semantic digest is inconsistent"
            )
        _require_typed(
            self.authority_event_id,
            EventId,
            field="resolution_proposal_authority_event_id",
        )
        bounded_int(
            self.authority_ledger_seq,
            field="resolution_proposal_authority_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )
        _require_typed(
            self.recorded_at,
            UtcTimestamp,
            field="resolution_proposal_recorded_at",
        )
        if not isinstance(self.replayed, bool):
            raise EntityContractError("resolution proposal replay flag must be boolean")

    @property
    def trust_scope(self) -> TrustScope:
        return TrustScope.PROPOSED

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "proposal_version_id": str(self.proposal_version_id),
            "version_number": self.version_number,
            "previous_proposal_version_id": (
                None
                if self.previous_proposal_version_id is None
                else str(self.previous_proposal_version_id)
            ),
            "source_proposal_id": str(self.source_proposal_id),
            "source_proposal_digest": self.source_proposal_digest,
            "kind": self.kind.value,
            "subject_mention_id": str(self.subject_mention_id),
            "object_mention_id": (
                None
                if self.object_mention_id is None
                else str(self.object_mention_id)
            ),
            "candidate_entity_id": (
                None
                if self.candidate_entity_id is None
                else str(self.candidate_entity_id)
            ),
            "candidate_entity_version_id": (
                None
                if self.candidate_entity_version_id is None
                else str(self.candidate_entity_version_id)
            ),
            "confidence_basis_points": self.confidence_basis_points,
            "uncertainty_codes": list(self.uncertainty_codes),
            "basis_codes": list(self.basis_codes),
            "stable_semantic_digest": self.stable_semantic_digest,
            "trust_scope": self.trust_scope.value,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityResolutionDecisionRequest:
    proposal_id: EntityResolutionProposalId
    expected_proposal_version_id: EntityResolutionProposalVersionId
    expected_proposal_digest: str
    action: EntityResolutionDecisionAction
    expected_decision_version: int
    expected_previous_decision_id: EntityResolutionDecisionId | None
    accepted_entity_id: CanonicalEntityId | None
    accepted_entity_version_id: CanonicalEntityVersionId | None
    alias_id: EntityAliasId | None
    alias_kind: EntityAliasKind | None
    reason_code: str
    decision_policy_version: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("proposal_id", EntityResolutionProposalId),
            ("expected_proposal_version_id", EntityResolutionProposalVersionId),
            ("action", EntityResolutionDecisionAction),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        canonical_digest(
            self.expected_proposal_digest,
            field="expected_resolution_proposal_digest",
        )
        bounded_int(
            self.expected_decision_version,
            field="expected_resolution_decision_version",
            minimum=0,
            maximum=1_000_000,
        )
        if self.expected_decision_version == 0:
            if self.expected_previous_decision_id is not None:
                raise EntityContractError(
                    "initial resolution decision cannot name a predecessor"
                )
        else:
            _require_typed(
                self.expected_previous_decision_id,
                EntityResolutionDecisionId,
                field="expected_previous_decision_id",
            )
        if self.action is EntityResolutionDecisionAction.ACCEPT:
            for field_name, expected in (
                ("accepted_entity_id", CanonicalEntityId),
                ("accepted_entity_version_id", CanonicalEntityVersionId),
                ("alias_id", EntityAliasId),
                ("alias_kind", EntityAliasKind),
            ):
                _require_typed(getattr(self, field_name), expected, field=field_name)
        elif any(
            value is not None
            for value in (
                self.accepted_entity_id,
                self.accepted_entity_version_id,
                self.alias_id,
                self.alias_kind,
            )
        ):
            raise EntityContractError(
                "non-accept resolution decision cannot allocate admitted identity"
            )
        bounded_token(self.reason_code, field="resolution_decision_reason_code")
        bounded_token(
            self.decision_policy_version,
            field="resolution_decision_policy_version",
        )
        bounded_text(
            self.idempotency_key,
            field="resolution_decision_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "expected_proposal_version_id": str(
                self.expected_proposal_version_id
            ),
            "expected_proposal_digest": self.expected_proposal_digest,
            "action": self.action.value,
            "expected_decision_version": self.expected_decision_version,
            "expected_previous_decision_id": (
                None
                if self.expected_previous_decision_id is None
                else str(self.expected_previous_decision_id)
            ),
            "accepted_entity_id": (
                None
                if self.accepted_entity_id is None
                else str(self.accepted_entity_id)
            ),
            "accepted_entity_version_id": (
                None
                if self.accepted_entity_version_id is None
                else str(self.accepted_entity_version_id)
            ),
            "alias_id": None if self.alias_id is None else str(self.alias_id),
            "alias_kind": (
                None if self.alias_kind is None else self.alias_kind.value
            ),
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityResolutionDecision:
    decision_id: EntityResolutionDecisionId
    proposal_id: EntityResolutionProposalId
    proposal_version_id: EntityResolutionProposalVersionId
    proposal_digest: str
    action: EntityResolutionDecisionAction
    decision_version: int
    previous_decision_id: EntityResolutionDecisionId | None
    accepted_entity_id: CanonicalEntityId | None
    accepted_entity_version_id: CanonicalEntityVersionId | None
    alias_id: EntityAliasId | None
    reason_code: str
    decision_policy_version: str
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("decision_id", EntityResolutionDecisionId),
            ("proposal_id", EntityResolutionProposalId),
            ("proposal_version_id", EntityResolutionProposalVersionId),
            ("action", EntityResolutionDecisionAction),
            ("authority_event_id", EventId),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        canonical_digest(self.proposal_digest, field="resolution_proposal_digest")
        bounded_int(
            self.decision_version,
            field="resolution_decision_version",
            minimum=1,
            maximum=1_000_000,
        )
        if self.decision_version == 1:
            if self.previous_decision_id is not None:
                raise EntityContractError(
                    "initial resolution decision cannot have a predecessor"
                )
        else:
            _require_typed(
                self.previous_decision_id,
                EntityResolutionDecisionId,
                field="previous_decision_id",
            )
        if self.action is EntityResolutionDecisionAction.ACCEPT:
            for field_name, expected in (
                ("accepted_entity_id", CanonicalEntityId),
                ("accepted_entity_version_id", CanonicalEntityVersionId),
                ("alias_id", EntityAliasId),
            ):
                _require_typed(getattr(self, field_name), expected, field=field_name)
        elif any(
            value is not None
            for value in (
                self.accepted_entity_id,
                self.accepted_entity_version_id,
                self.alias_id,
            )
        ):
            raise EntityContractError(
                "non-accept retained decision cannot carry admitted identity"
            )
        bounded_token(self.reason_code, field="resolution_decision_reason_code")
        bounded_token(
            self.decision_policy_version,
            field="resolution_decision_policy_version",
        )
        bounded_int(
            self.authority_ledger_seq,
            field="resolution_decision_authority_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )
        _require_typed(
            self.recorded_at,
            UtcTimestamp,
            field="resolution_decision_recorded_at",
        )
        if not isinstance(self.replayed, bool):
            raise EntityContractError("resolution decision replay flag must be boolean")

    @property
    def current_state(self) -> EntityResolutionState:
        return {
            EntityResolutionDecisionAction.ACCEPT: EntityResolutionState.ACCEPTED,
            EntityResolutionDecisionAction.REJECT: EntityResolutionState.REJECTED,
            EntityResolutionDecisionAction.HOLD: EntityResolutionState.HELD,
            EntityResolutionDecisionAction.UNRESOLVED: EntityResolutionState.UNRESOLVED,
        }[self.action]

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": str(self.decision_id),
            "proposal_id": str(self.proposal_id),
            "proposal_version_id": str(self.proposal_version_id),
            "proposal_digest": self.proposal_digest,
            "action": self.action.value,
            "decision_version": self.decision_version,
            "previous_decision_id": (
                None
                if self.previous_decision_id is None
                else str(self.previous_decision_id)
            ),
            "accepted_entity_id": (
                None
                if self.accepted_entity_id is None
                else str(self.accepted_entity_id)
            ),
            "accepted_entity_version_id": (
                None
                if self.accepted_entity_version_id is None
                else str(self.accepted_entity_version_id)
            ),
            "alias_id": None if self.alias_id is None else str(self.alias_id),
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
            "current_state": self.current_state.value,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityMergeDecisionRequest:
    merge_decision_id: EntityMergeDecisionId
    predecessor_entity_ids: tuple[CanonicalEntityId, ...]
    expected_predecessor_version_ids: tuple[CanonicalEntityVersionId, ...]
    successor_entity_id: CanonicalEntityId
    successor_entity_version_id: CanonicalEntityVersionId
    preferred_continuation_entity_id: CanonicalEntityId
    basis_resolution_proposal_ids: tuple[EntityResolutionProposalId, ...]
    reason_code: str
    decision_policy_version: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_typed(
            self.merge_decision_id,
            EntityMergeDecisionId,
            field="merge_decision_id",
        )
        _require_sorted_ids(
            self.predecessor_entity_ids,
            CanonicalEntityId,
            field="predecessor_entity_ids",
            minimum=2,
        )
        _require_sorted_ids(
            self.expected_predecessor_version_ids,
            CanonicalEntityVersionId,
            field="expected_predecessor_version_ids",
            minimum=2,
        )
        if len(self.predecessor_entity_ids) != len(
            self.expected_predecessor_version_ids
        ):
            raise EntityContractError(
                "merge predecessors and expected versions must align"
            )
        _require_typed(
            self.successor_entity_id,
            CanonicalEntityId,
            field="successor_entity_id",
        )
        _require_typed(
            self.successor_entity_version_id,
            CanonicalEntityVersionId,
            field="successor_entity_version_id",
        )
        _require_typed(
            self.preferred_continuation_entity_id,
            CanonicalEntityId,
            field="preferred_continuation_entity_id",
        )
        if self.preferred_continuation_entity_id not in self.predecessor_entity_ids:
            raise EntityContractError(
                "merge preferred continuation must be one predecessor"
            )
        _require_sorted_ids(
            self.basis_resolution_proposal_ids,
            EntityResolutionProposalId,
            field="merge_basis_resolution_proposal_ids",
            minimum=1,
        )
        bounded_token(self.reason_code, field="merge_reason_code")
        bounded_token(
            self.decision_policy_version,
            field="merge_decision_policy_version",
        )
        bounded_text(
            self.idempotency_key,
            field="merge_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "merge_decision_id": str(self.merge_decision_id),
            "predecessor_entity_ids": [
                str(value) for value in self.predecessor_entity_ids
            ],
            "expected_predecessor_version_ids": [
                str(value) for value in self.expected_predecessor_version_ids
            ],
            "successor_entity_id": str(self.successor_entity_id),
            "successor_entity_version_id": str(
                self.successor_entity_version_id
            ),
            "preferred_continuation_entity_id": str(
                self.preferred_continuation_entity_id
            ),
            "basis_resolution_proposal_ids": [
                str(value) for value in self.basis_resolution_proposal_ids
            ],
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntitySplitAllocation:
    mention_id: EntityMentionId
    successor_entity_id: CanonicalEntityId

    def __post_init__(self) -> None:
        _require_typed(self.mention_id, EntityMentionId, field="split_mention_id")
        _require_typed(
            self.successor_entity_id,
            CanonicalEntityId,
            field="split_successor_entity_id",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "mention_id": str(self.mention_id),
            "successor_entity_id": str(self.successor_entity_id),
        }


@dataclass(frozen=True, slots=True)
class EntitySplitDecisionRequest:
    split_decision_id: EntitySplitDecisionId
    source_entity_id: CanonicalEntityId
    expected_source_version_id: CanonicalEntityVersionId
    successor_entity_ids: tuple[CanonicalEntityId, ...]
    successor_entity_version_ids: tuple[CanonicalEntityVersionId, ...]
    allocations: tuple[EntitySplitAllocation, ...]
    reason_code: str
    decision_policy_version: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("split_decision_id", EntitySplitDecisionId),
            ("source_entity_id", CanonicalEntityId),
            ("expected_source_version_id", CanonicalEntityVersionId),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        _require_sorted_ids(
            self.successor_entity_ids,
            CanonicalEntityId,
            field="split_successor_entity_ids",
            minimum=2,
        )
        _require_sorted_ids(
            self.successor_entity_version_ids,
            CanonicalEntityVersionId,
            field="split_successor_entity_version_ids",
            minimum=2,
        )
        if len(self.successor_entity_ids) != len(
            self.successor_entity_version_ids
        ):
            raise EntityContractError(
                "split successors and versions must align"
            )
        if self.source_entity_id in self.successor_entity_ids:
            raise EntityContractError(
                "split successor identities must be distinct from the source"
            )
        if not isinstance(self.allocations, tuple) or len(self.allocations) < 2:
            raise EntityContractError("split requires at least two mention allocations")
        if any(not isinstance(item, EntitySplitAllocation) for item in self.allocations):
            raise EntityContractError("split allocations must be typed")
        ordered = tuple(
            sorted(
                self.allocations,
                key=lambda item: (str(item.mention_id), str(item.successor_entity_id)),
            )
        )
        if ordered != self.allocations:
            raise EntityContractError("split allocations must be sorted")
        if len({item.mention_id for item in self.allocations}) != len(
            self.allocations
        ):
            raise EntityContractError("split mention allocations must be unique")
        if not {item.successor_entity_id for item in self.allocations}.issubset(
            set(self.successor_entity_ids)
        ):
            raise EntityContractError(
                "split allocation names an unknown successor entity"
            )
        if {item.successor_entity_id for item in self.allocations} != set(
            self.successor_entity_ids
        ):
            raise EntityContractError(
                "every split successor requires an explicit mention allocation"
            )
        bounded_token(self.reason_code, field="split_reason_code")
        bounded_token(
            self.decision_policy_version,
            field="split_decision_policy_version",
        )
        bounded_text(
            self.idempotency_key,
            field="split_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "split_decision_id": str(self.split_decision_id),
            "source_entity_id": str(self.source_entity_id),
            "expected_source_version_id": str(self.expected_source_version_id),
            "successor_entity_ids": [
                str(value) for value in self.successor_entity_ids
            ],
            "successor_entity_version_ids": [
                str(value) for value in self.successor_entity_version_ids
            ],
            "allocations": [item.canonical_value() for item in self.allocations],
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityReversalDecisionRequest:
    reversal_decision_id: EntityReversalDecisionId
    target_kind: EntityReversalTargetKind
    target_decision_id: str
    expected_current_entity_version_ids: tuple[CanonicalEntityVersionId, ...]
    restored_entity_ids: tuple[CanonicalEntityId, ...]
    restored_entity_version_ids: tuple[CanonicalEntityVersionId, ...]
    reason_code: str
    decision_policy_version: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_typed(
            self.reversal_decision_id,
            EntityReversalDecisionId,
            field="reversal_decision_id",
        )
        _require_typed(self.target_kind, EntityReversalTargetKind, field="target_kind")
        bounded_text(
            self.target_decision_id,
            field="reversal_target_decision_id",
            maximum_bytes=36,
        )
        _require_sorted_ids(
            self.expected_current_entity_version_ids,
            CanonicalEntityVersionId,
            field="reversal_expected_current_versions",
        )
        _require_sorted_ids(
            self.restored_entity_ids,
            CanonicalEntityId,
            field="reversal_restored_entity_ids",
        )
        _require_sorted_ids(
            self.restored_entity_version_ids,
            CanonicalEntityVersionId,
            field="reversal_restored_entity_version_ids",
        )
        if len(self.restored_entity_ids) != len(self.restored_entity_version_ids):
            raise EntityContractError(
                "reversal restored entities and versions must align"
            )
        bounded_token(self.reason_code, field="reversal_reason_code")
        bounded_token(
            self.decision_policy_version,
            field="reversal_decision_policy_version",
        )
        bounded_text(
            self.idempotency_key,
            field="reversal_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "reversal_decision_id": str(self.reversal_decision_id),
            "target_kind": self.target_kind.value,
            "target_decision_id": self.target_decision_id,
            "expected_current_entity_version_ids": [
                str(value) for value in self.expected_current_entity_version_ids
            ],
            "restored_entity_ids": [
                str(value) for value in self.restored_entity_ids
            ],
            "restored_entity_version_ids": [
                str(value) for value in self.restored_entity_version_ids
            ],
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class EntityPreferredIdentity:
    entity_id: CanonicalEntityId
    current_entity_version_id: CanonicalEntityVersionId
    preferred_entity_id: CanonicalEntityId
    lifecycle: CanonicalEntityLifecycle
    decided_by_kind: EntityLineageDecisionKind | None
    decided_by_id: str | None
    projected_through_ledger_seq: int

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("entity_id", CanonicalEntityId),
            ("current_entity_version_id", CanonicalEntityVersionId),
            ("preferred_entity_id", CanonicalEntityId),
            ("lifecycle", CanonicalEntityLifecycle),
        ):
            _require_typed(getattr(self, field_name), expected, field=field_name)
        if self.decided_by_kind is None:
            if self.decided_by_id is not None:
                raise EntityContractError(
                    "preferred identity cannot name a decision without its kind"
                )
        else:
            _require_typed(
                self.decided_by_kind,
                EntityLineageDecisionKind,
                field="preferred_identity_decision_kind",
            )
            bounded_text(
                self.decided_by_id or "",
                field="preferred_identity_decision_id",
                maximum_bytes=36,
            )
        bounded_int(
            self.projected_through_ledger_seq,
            field="preferred_identity_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )


@dataclass(frozen=True, slots=True)
class EntityAdmissionGuard:
    proposal_id: EntityResolutionProposalId
    proposal_version_id: EntityResolutionProposalVersionId
    state: EntityResolutionState
    materially_unresolved: bool
    checked_at_ledger_seq: int

    def __post_init__(self) -> None:
        _require_typed(
            self.proposal_id,
            EntityResolutionProposalId,
            field="guard_proposal_id",
        )
        _require_typed(
            self.proposal_version_id,
            EntityResolutionProposalVersionId,
            field="guard_proposal_version_id",
        )
        _require_typed(self.state, EntityResolutionState, field="guard_state")
        if not isinstance(self.materially_unresolved, bool):
            raise EntityContractError("guard unresolved state must be boolean")
        bounded_int(
            self.checked_at_ledger_seq,
            field="guard_ledger_seq",
            minimum=1,
            maximum=2**63 - 1,
        )
        expected = self.state not in {
            EntityResolutionState.ACCEPTED,
            EntityResolutionState.REJECTED,
            EntityResolutionState.REVERSED,
        }
        if self.materially_unresolved != expected:
            raise EntityContractError(
                "dependent-admission guard disagrees with resolution state"
            )

    def require_resolved(self) -> None:
        if self.materially_unresolved:
            raise EntityContractError(
                "materially unresolved entity identity blocks dependent admission"
            )
