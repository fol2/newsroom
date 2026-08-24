"""Deterministic governed-relation sidecar and collapse contract (#748)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.deterministic_contract import (
    DeterministicWorkContractError,
    require_bounded_text,
)

SEMANTIC_SIDECAR_EXCLUSION_INSTRUCTION = (
    "Exclude source-registry identifiers and deterministic corpus metadata "
    "(SourceItem, SourceRevision, DERIVED_FROM, OBSERVED_IN)."
)



class SidecarRelationKind(StrEnum):
    SOURCE_ITEM_LINEAGE = "SOURCE_ITEM_LINEAGE"
    SOURCE_REGISTRY_LINEAGE = "SOURCE_REGISTRY_LINEAGE"
    REVISION_PREDECESSOR = "REVISION_PREDECESSOR"
    ORDERED_CHUNK = "ORDERED_CHUNK"
    REFERENCE_TIME = "REFERENCE_TIME"
    RIGHTS_IDENTITY = "RIGHTS_IDENTITY"
    REPRESENTATION_LINEAGE = "REPRESENTATION_LINEAGE"
    EVIDENCE_PACKAGE_LINEAGE = "EVIDENCE_PACKAGE_LINEAGE"


@dataclass(frozen=True, slots=True)
class RelationTriple:
    subject_ref: str
    predicate: str
    object_ref: str

    def __post_init__(self) -> None:
        for field_name in ("subject_ref", "predicate", "object_ref"):
            require_bounded_text(getattr(self, field_name), field=field_name)

    def canonical_value(self) -> dict[str, str]:
        return {
            "subject_ref": self.subject_ref,
            "predicate": self.predicate,
            "object_ref": self.object_ref,
        }



@dataclass(frozen=True, slots=True)
class AuthorityRecordRef:
    record_id: str
    canonical_bytes: bytes
    canonical_digest: str

    def __post_init__(self) -> None:
        require_bounded_text(self.record_id, field="authority record identity")
        if not isinstance(self.canonical_bytes, bytes):
            raise DeterministicWorkContractError(
                "authority record canonical bytes must be immutable bytes"
            )
        try:
            validate_sha256_digest(
                self.canonical_digest,
                field="authority record canonical digest",
            )
        except ValueError as exc:
            raise DeterministicWorkContractError(str(exc)) from exc
        if digest_bytes(self.canonical_bytes) != self.canonical_digest:
            raise DeterministicWorkContractError(
                "authority record canonical digest must bind the exact bytes"
            )
        try:
            decoded = json.loads(self.canonical_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeterministicWorkContractError(
                "authority record bytes must contain canonical JSON"
            ) from exc
        if canonical_json_bytes(decoded) != self.canonical_bytes:
            raise DeterministicWorkContractError(
                "authority record bytes must use canonical JSON encoding"
            )
        if not isinstance(decoded, dict) or decoded.get("record_id") != self.record_id:
            raise DeterministicWorkContractError(
                "authority record identity must match the canonical bytes"
            )

    def canonical_value(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "canonical_digest": self.canonical_digest,
        }

    @property
    def canonical_record(self) -> dict[str, Any]:
        record = json.loads(self.canonical_bytes)
        if not isinstance(record, dict):  # guarded by construction
            raise DeterministicWorkContractError(
                "authority record canonical bytes must contain an object"
            )
        return record


def _require_authority_field(
    authority: AuthorityRecordRef,
    field: str,
    expected: object,
) -> None:
    actual = authority.canonical_record.get(field)
    if actual != expected:
        raise DeterministicWorkContractError(
            f"{authority.record_id} must bind {field}={expected!r}; got {actual!r}"
        )


@dataclass(frozen=True, slots=True)
class DeterministicSidecarInput:
    source_definition: AuthorityRecordRef
    source_item: AuthorityRecordRef
    source_revision: AuthorityRecordRef
    predecessor_revision: AuthorityRecordRef | None
    discovery_representation: AuthorityRecordRef
    evidence_package: AuthorityRecordRef
    rights_decision: AuthorityRecordRef
    chunk: AuthorityRecordRef
    predecessor_chunk: AuthorityRecordRef | None
    reference_time: str
    chunk_ordinal: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "source_definition",
            "source_item",
            "source_revision",
            "discovery_representation",
            "evidence_package",
            "rights_decision",
            "chunk",
        ):
            if not isinstance(getattr(self, field_name), AuthorityRecordRef):
                raise DeterministicWorkContractError(
                    f"{field_name} must bind an exact authority record"
                )
        if self.predecessor_revision is not None and not isinstance(
            self.predecessor_revision, AuthorityRecordRef
        ):
            raise DeterministicWorkContractError(
                "predecessor_revision must bind an exact authority record"
            )
        if self.predecessor_chunk is not None and not isinstance(
            self.predecessor_chunk, AuthorityRecordRef
        ):
            raise DeterministicWorkContractError(
                "predecessor_chunk must bind an exact authority record"
            )
        try:
            UtcTimestamp.parse(self.reference_time)
        except ValueError as exc:
            raise DeterministicWorkContractError(
                "reference_time must be canonical UTC"
            ) from exc
        if (
            isinstance(self.chunk_ordinal, bool)
            or not isinstance(self.chunk_ordinal, int)
            or self.chunk_ordinal < 1
        ):
            raise DeterministicWorkContractError("chunk_ordinal must be positive")
        if (self.chunk_ordinal == 1) != (self.predecessor_chunk is None):
            raise DeterministicWorkContractError(
                "ordered chunks require the exact predecessor chunk authority"
            )
        for authority, record_kind in (
            (self.source_definition, "SOURCE_DEFINITION"),
            (self.source_item, "SOURCE_ITEM"),
            (self.source_revision, "SOURCE_REVISION"),
            (self.discovery_representation, "DISCOVERY_REPRESENTATION"),
            (self.evidence_package, "EVIDENCE_PACKAGE"),
            (self.rights_decision, "RIGHTS_DECISION"),
            (self.chunk, "SOURCE_CHUNK"),
        ):
            _require_authority_field(authority, "record_kind", record_kind)
        _require_authority_field(
            self.source_item,
            "source_definition_id",
            self.source_definition.record_id,
        )
        _require_authority_field(
            self.source_revision,
            "source_item_id",
            self.source_item.record_id,
        )
        _require_authority_field(
            self.source_revision,
            "predecessor_revision_id",
            None
            if self.predecessor_revision is None
            else self.predecessor_revision.record_id,
        )
        if self.predecessor_revision is not None:
            _require_authority_field(
                self.predecessor_revision,
                "record_kind",
                "SOURCE_REVISION",
            )
        for field, authority in (
            ("representation_id", self.discovery_representation),
            ("evidence_package_id", self.evidence_package),
            ("rights_decision_id", self.rights_decision),
            ("chunk_id", self.chunk),
        ):
            _require_authority_field(
                self.source_revision,
                field,
                authority.record_id,
            )
        _require_authority_field(
            self.source_revision,
            "reference_time",
            self.reference_time,
        )
        _require_authority_field(
            self.discovery_representation,
            "source_revision_id",
            self.source_revision.record_id,
        )
        _require_authority_field(
            self.discovery_representation,
            "evidence_package_id",
            self.evidence_package.record_id,
        )
        _require_authority_field(
            self.evidence_package,
            "source_revision_id",
            self.source_revision.record_id,
        )
        _require_authority_field(
            self.rights_decision,
            "source_revision_id",
            self.source_revision.record_id,
        )
        _require_authority_field(
            self.chunk,
            "source_revision_id",
            self.source_revision.record_id,
        )
        _require_authority_field(self.chunk, "chunk_ordinal", self.chunk_ordinal)
        _require_authority_field(
            self.chunk,
            "predecessor_chunk_id",
            None
            if self.predecessor_chunk is None
            else self.predecessor_chunk.record_id,
        )
        if self.predecessor_chunk is not None:
            _require_authority_field(
                self.predecessor_chunk,
                "record_kind",
                "SOURCE_CHUNK",
            )


@dataclass(frozen=True, slots=True)
class DeterministicSidecarRelationProposal:
    proposal_id: str
    kind: SidecarRelationKind
    relation: RelationTriple
    authority_bindings: tuple[AuthorityRecordRef, ...]
    attribution: str = "DETERMINISTIC_CORPUS_SIDECAR"

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "kind": self.kind.value,
            "relation": self.relation.canonical_value(),
            "authority_bindings": [
                binding.canonical_value() for binding in self.authority_bindings
            ],
            "attribution": self.attribution,
        }


@dataclass(frozen=True, slots=True)
class DeterministicSidecar:
    relation_proposals: tuple[DeterministicSidecarRelationProposal, ...]
    authority: str
    proposal_only: bool
    model_leaf_count: int
    semantic_prompt_bytes_removed: int
    semantic_output_bytes_avoided: int

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "schema_version": "newsroom.graphiti-deterministic-sidecar.v1",
                "relation_proposals": [
                    proposal.canonical_value()
                    for proposal in self.relation_proposals
                ],
                "authority": self.authority,
                "proposal_only": self.proposal_only,
                "model_leaf_count": self.model_leaf_count,
                "semantic_prompt_bytes_removed": self.semantic_prompt_bytes_removed,
                "semantic_output_bytes_avoided": self.semantic_output_bytes_avoided,
            }
        )


def _relation_proposal(
    kind: SidecarRelationKind,
    relation: RelationTriple,
    *bindings: AuthorityRecordRef,
) -> DeterministicSidecarRelationProposal:
    identity_value = {
        "schema_version": "newsroom.graphiti-deterministic-sidecar-relation.v1",
        "kind": kind.value,
        "relation": relation.canonical_value(),
        "authority_bindings": [binding.canonical_value() for binding in bindings],
    }
    return DeterministicSidecarRelationProposal(
        proposal_id=digest_canonical(identity_value),
        kind=kind,
        relation=relation,
        authority_bindings=bindings,
    )


def project_deterministic_sidecar(
    authority: DeterministicSidecarInput,
) -> DeterministicSidecar:
    """Project exact governed identities into a proposal-only sidecar."""

    if not isinstance(authority, DeterministicSidecarInput):
        raise DeterministicWorkContractError(
            "sidecar projection requires typed governed authority"
        )
    revision = authority.source_revision
    item = authority.source_item
    definition = authority.source_definition
    representation = authority.discovery_representation
    proposals = [
        _relation_proposal(
            SidecarRelationKind.SOURCE_ITEM_LINEAGE,
            RelationTriple(revision.record_id, "REVISION_OF", item.record_id),
            revision,
            item,
        ),
        _relation_proposal(
            SidecarRelationKind.SOURCE_REGISTRY_LINEAGE,
            RelationTriple(item.record_id, "SUPPLIED_BY", definition.record_id),
            item,
            definition,
        ),
    ]
    if authority.predecessor_revision is not None:
        predecessor = authority.predecessor_revision
        proposals.append(
            _relation_proposal(
                SidecarRelationKind.REVISION_PREDECESSOR,
                RelationTriple(
                    revision.record_id,
                    "PRECEDED_BY",
                    predecessor.record_id,
                ),
                revision,
                predecessor,
            )
        )
    if authority.chunk_ordinal > 1:
        predecessor_chunk = authority.predecessor_chunk
        if predecessor_chunk is None:  # guarded by DeterministicSidecarInput
            raise DeterministicWorkContractError(
                "ordered chunk predecessor authority is missing"
            )
        proposals.append(
            _relation_proposal(
                SidecarRelationKind.ORDERED_CHUNK,
                RelationTriple(
                    authority.chunk.record_id,
                    "PRECEDED_BY_CHUNK",
                    predecessor_chunk.record_id,
                ),
                authority.chunk,
                predecessor_chunk,
            )
        )
    proposals.extend(
        (
            _relation_proposal(
                SidecarRelationKind.REFERENCE_TIME,
                RelationTriple(
                    revision.record_id,
                    "GOVERNED_REFERENCE_TIME",
                    authority.reference_time,
                ),
                revision,
                representation,
            ),
            _relation_proposal(
                SidecarRelationKind.RIGHTS_IDENTITY,
                RelationTriple(
                    revision.record_id,
                    "PERMITTED_BY",
                    authority.rights_decision.record_id,
                ),
                revision,
                authority.rights_decision,
            ),
            _relation_proposal(
                SidecarRelationKind.REPRESENTATION_LINEAGE,
                RelationTriple(
                    representation.record_id,
                    "REPRESENTS",
                    revision.record_id,
                ),
                representation,
                revision,
            ),
            _relation_proposal(
                SidecarRelationKind.EVIDENCE_PACKAGE_LINEAGE,
                RelationTriple(
                    representation.record_id,
                    "IN_EVIDENCE_PACKAGE",
                    authority.evidence_package.record_id,
                ),
                representation,
                authority.evidence_package,
            ),
        )
    )
    return DeterministicSidecar(
        relation_proposals=tuple(proposals),
        authority="SQLITE_GOVERNED_RECORDS",
        proposal_only=True,
        model_leaf_count=0,
        semantic_prompt_bytes_removed=0,
        semantic_output_bytes_avoided=0,
    )


@dataclass(frozen=True, slots=True)
class SemanticRelationProposal:
    proposal_id: str
    relation: RelationTriple
    evidence_segment_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        require_bounded_text(self.proposal_id, field="proposal_id")
        if not isinstance(self.relation, RelationTriple):
            raise DeterministicWorkContractError(
                "semantic relation proposal requires a typed relation triple"
            )
        if (
            not isinstance(self.evidence_segment_ids, tuple)
            or any(
                isinstance(segment, bool)
                or not isinstance(segment, int)
                or segment < 0
                for segment in self.evidence_segment_ids
            )
        ):
            raise DeterministicWorkContractError(
                "semantic evidence segment identities must be non-negative integers"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "relation": self.relation.canonical_value(),
            "evidence_segment_ids": list(self.evidence_segment_ids),
        }


@dataclass(frozen=True, slots=True)
class CollapsedRelationProposalDuplicate:
    collapse_id: str
    sidecar_proposal_id: str
    semantic_proposal_id: str
    semantic_evidence_segment_ids: tuple[int, ...]
    authority_bindings: tuple[AuthorityRecordRef, ...]

    def canonical_value(self) -> dict[str, object]:
        return {
            "collapse_id": self.collapse_id,
            "sidecar_proposal_id": self.sidecar_proposal_id,
            "semantic_proposal_id": self.semantic_proposal_id,
            "semantic_evidence_segment_ids": list(
                self.semantic_evidence_segment_ids
            ),
            "authority_bindings": [
                binding.canonical_value() for binding in self.authority_bindings
            ],
        }


@dataclass(frozen=True, slots=True)
class SidecarCollapseResult:
    sidecar_relation_proposals: tuple[DeterministicSidecarRelationProposal, ...]
    semantic_relation_proposals: tuple[SemanticRelationProposal, ...]
    collapsed_duplicates: tuple[CollapsedRelationProposalDuplicate, ...]
    model_leaf_count: int = 0

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "schema_version": "newsroom.graphiti-sidecar-collapse.v1",
                "sidecar_relation_proposals": [
                    proposal.canonical_value()
                    for proposal in self.sidecar_relation_proposals
                ],
                "semantic_relation_proposals": [
                    proposal.canonical_value()
                    for proposal in self.semantic_relation_proposals
                ],
                "collapsed_duplicates": [
                    duplicate.canonical_value()
                    for duplicate in self.collapsed_duplicates
                ],
                "model_leaf_count": self.model_leaf_count,
            }
        )


def collapse_sidecar_duplicates(
    sidecar: DeterministicSidecar,
    semantic_relation_proposals: tuple[SemanticRelationProposal, ...],
) -> SidecarCollapseResult:
    """Collapse only exact semantic triples while retaining both attributions."""

    if not isinstance(sidecar, DeterministicSidecar):
        raise DeterministicWorkContractError("collapse requires a typed sidecar")
    sidecar_by_relation = {
        proposal.relation: proposal
        for proposal in sidecar.relation_proposals
    }
    retained: list[SemanticRelationProposal] = []
    collapsed: list[CollapsedRelationProposalDuplicate] = []
    for semantic in semantic_relation_proposals:
        if not isinstance(semantic, SemanticRelationProposal):
            raise DeterministicWorkContractError(
                "collapse requires typed semantic proposals"
            )
        deterministic = sidecar_by_relation.get(semantic.relation)
        if deterministic is None:
            retained.append(semantic)
            continue
        collapse_value = {
            "schema_version": "newsroom.graphiti-sidecar-collapse-item.v1",
            "sidecar_proposal_id": deterministic.proposal_id,
            "semantic_proposal": semantic.canonical_value(),
            "authority_bindings": [
                binding.canonical_value()
                for binding in deterministic.authority_bindings
            ],
        }
        collapsed.append(
            CollapsedRelationProposalDuplicate(
                collapse_id=digest_canonical(collapse_value),
                sidecar_proposal_id=deterministic.proposal_id,
                semantic_proposal_id=semantic.proposal_id,
                semantic_evidence_segment_ids=semantic.evidence_segment_ids,
                authority_bindings=deterministic.authority_bindings,
            )
        )
    return SidecarCollapseResult(
        sidecar_relation_proposals=sidecar.relation_proposals,
        semantic_relation_proposals=tuple(retained),
        collapsed_duplicates=tuple(collapsed),
    )


__all__ = [
    "SEMANTIC_SIDECAR_EXCLUSION_INSTRUCTION",
    "AuthorityRecordRef",
    "CollapsedRelationProposalDuplicate",
    "DeterministicSidecar",
    "DeterministicSidecarInput",
    "DeterministicSidecarRelationProposal",
    "RelationTriple",
    "SemanticRelationProposal",
    "SidecarCollapseResult",
    "SidecarRelationKind",
    "collapse_sidecar_duplicates",
    "project_deterministic_sidecar",
]
