from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import UtcTimestamp
from newsroom.checks.types import (
    CheckAttemptId,
    CheckRequestId,
    ObservableTransitionId,
)
from newsroom.discovery.types import (
    DiscoverySignalId,
    GateDecisionId,
    NewsLeadId,
)
from newsroom.sources.types import (
    CheckOutcomeId,
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from newsroom.projection.discovery_lineage import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    discovery_lineage_contract_registry,
)
from newsroom.projection.health import (
    DiscoveryHealthAssessment,
    HealthEvidenceReference,
    HealthPolicy,
    ProjectionHealthInput,
    assess_projection_health,
)
from newsroom.projection.mapping import canonical_governed_node_id
from newsroom.projection.models import (
    ProjectionDeadLetterView,
    ProjectionGapView,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationValidationView,
    ProjectionStatusMetadata,
    ProjectionStateError,
)
from newsroom.projection.ontology import ProjectionNodeType
from .models import (
    Neo4jConnectionError,
    Neo4jReadError,
    StructuralActiveReadRequest,
    StructuralReadAuthoritySelection,
    StructuralReadResponse,
)


DiscoveryLineageIdentifier: TypeAlias = (
    SourceDefinitionId
    | SourceDefinitionVersionId
    | SourceItemId
    | SourceRevisionId
    | DiscoveryRepresentationId
    | DiscoveryOccurrenceId
    | CheckRequestId
    | CheckAttemptId
    | CheckOutcomeId
    | ObservableTransitionId
    | DiscoverySignalId
    | GateDecisionId
    | NewsLeadId
)

_IDENTIFIER_SPECS: tuple[
    tuple[type[object], ProjectionNodeType], ...
] = (
    (SourceDefinitionId, ProjectionNodeType.SOURCE_DEFINITION),
    (SourceDefinitionVersionId, ProjectionNodeType.SOURCE_DEFINITION_VERSION),
    (SourceItemId, ProjectionNodeType.SOURCE_ITEM),
    (SourceRevisionId, ProjectionNodeType.SOURCE_REVISION),
    (DiscoveryRepresentationId, ProjectionNodeType.SOURCE_REPRESENTATION),
    (DiscoveryOccurrenceId, ProjectionNodeType.DISCOVERY_OCCURRENCE),
    (CheckRequestId, ProjectionNodeType.CHECK_REQUEST),
    (CheckAttemptId, ProjectionNodeType.CHECK_ATTEMPT),
    (CheckOutcomeId, ProjectionNodeType.CHECK_OUTCOME),
    (ObservableTransitionId, ProjectionNodeType.OBSERVABLE_TRANSITION),
    (DiscoverySignalId, ProjectionNodeType.SIGNAL),
    (GateDecisionId, ProjectionNodeType.GATE_DECISION),
    (NewsLeadId, ProjectionNodeType.LEAD),
)


class DiscoveryLineageReadError(ProjectionStateError):
    """The fixed discovery-lineage serving view is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class DiscoveryLineageSubject:
    identifier: DiscoveryLineageIdentifier

    def __post_init__(self) -> None:
        if not any(
            isinstance(self.identifier, identifier_type)
            for identifier_type, _node_type in _IDENTIFIER_SPECS
        ):
            raise TypeError(
                "discovery-lineage subject requires a governed lifecycle identity"
            )

    @property
    def node_type(self) -> ProjectionNodeType:
        for identifier_type, node_type in _IDENTIFIER_SPECS:
            if isinstance(self.identifier, identifier_type):
                return node_type
        raise AssertionError("validated discovery-lineage subject is untyped")

    @property
    def canonical_id(self) -> str:
        node_type = self.node_type
        return canonical_governed_node_id(
            node_type,
            node_type.value.lower(),
            str(self.identifier),
        )


@dataclass(frozen=True, slots=True)
class DiscoveryLineageReadRequest:
    subjects: tuple[DiscoveryLineageSubject, ...]
    query_valid_time: UtcTimestamp
    limit: int = 100

    def __post_init__(self) -> None:
        if (
            not isinstance(self.subjects, tuple)
            or not self.subjects
            or len(self.subjects) > 64
            or any(
                not isinstance(subject, DiscoveryLineageSubject)
                for subject in self.subjects
            )
        ):
            raise TypeError(
                "discovery-lineage read requires a bounded tuple of typed subjects"
            )
        canonical_ids = tuple(subject.canonical_id for subject in self.subjects)
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ValueError("discovery-lineage read subjects must be unique")
        if not isinstance(self.query_valid_time, UtcTimestamp):
            raise TypeError("discovery-lineage read time must be typed")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("discovery-lineage read limit must be an integer")
        if self.limit < len(self.subjects) or self.limit > 500:
            raise ValueError("discovery-lineage read limit is outside policy bounds")

    def active_request(self) -> StructuralActiveReadRequest:
        return StructuralActiveReadRequest(
            family_id=DISCOVERY_LINEAGE_FAMILY_ID,
            canonical_ids=tuple(
                sorted(subject.canonical_id for subject in self.subjects)
            ),
            query_valid_time=self.query_valid_time,
            limit=self.limit,
        )


class DiscoveryLineageProjectionFacade:
    """Fixed-family, typed read and health facade over projection authority."""

    __slots__ = (
        "__active_read",
        "__status",
        "__validation",
        "__gaps",
        "__dead_letters",
        "__eligibility",
    )

    def __init__(
        self,
        *,
        active_read: Callable[
            [StructuralActiveReadRequest, AuthenticationProof],
            StructuralReadResponse,
        ],
        status: Callable[[str, AuthenticationProof], ProjectionStatusMetadata],
        validation: Callable[
            [ProjectionGenerationId, AuthenticationProof],
            ProjectionGenerationValidationView,
        ],
        gaps: Callable[
            [ProjectionGenerationId, int, AuthenticationProof],
            tuple[ProjectionGapView, ...],
        ],
        dead_letters: Callable[
            [ProjectionGenerationId, int, AuthenticationProof],
            tuple[ProjectionDeadLetterView, ...],
        ],
        eligibility: Callable[[tuple[object, ...], AuthenticationProof], None],
    ) -> None:
        self.__active_read = active_read
        self.__status = status
        self.__validation = validation
        self.__gaps = gaps
        self.__dead_letters = dead_letters
        self.__eligibility = eligibility

    @classmethod
    def from_system(cls, system: object) -> DiscoveryLineageProjectionFacade:
        structural = getattr(system, "structural")
        projections = getattr(system, "projections")
        return cls(
            active_read=lambda request, proof: structural.read_active(
                request, proof=proof
            ),
            status=lambda family_id, proof: projections.status(
                family_id, proof=proof
            ),
            validation=lambda generation_id, proof: projections.validation(
                generation_id, proof=proof
            ),
            gaps=lambda generation_id, limit, proof: projections.gaps(
                generation_id, limit=limit, proof=proof
            ),
            dead_letters=lambda generation_id, limit, proof: (
                projections.dead_letters(
                    generation_id, limit=limit, proof=proof
                )
            ),
            eligibility=lambda identifiers, proof: (
                system.health.require_lineage_eligible(
                    identifiers, proof=proof
                )
            ),
        )

    @staticmethod
    def _current_family():
        return discovery_lineage_contract_registry().family(
            DISCOVERY_LINEAGE_FAMILY_ID
        )

    @classmethod
    def _current_ontology(cls):
        registry = discovery_lineage_contract_registry()
        family = registry.family(DISCOVERY_LINEAGE_FAMILY_ID)
        return registry.ontologies.resolve_digest(
            family.ontology_contract_digest
        )

    @classmethod
    def _validate_status(
        cls,
        status: ProjectionStatusMetadata,
        *,
        require_fresh: bool,
    ) -> None:
        family = cls._current_family()
        if status.family_id != DISCOVERY_LINEAGE_FAMILY_ID:
            raise DiscoveryLineageReadError(
                "discovery-lineage status selected another projection family"
            )
        if (
            status.projector_version != family.projector_version
            or status.ontology_contract_digest
            != family.ontology_contract_digest
            or status.mapping_contract_digest != family.mapping_contract_digest
        ):
            raise DiscoveryLineageReadError(
                "discovery-lineage projection contract is not current"
            )
        if status.generation_id is None or status.generation_state is None:
            raise DiscoveryLineageReadError(
                "discovery-lineage projection has no serving generation"
            )
        if status.generation_state is not ProjectionGenerationState.ACTIVE:
            raise DiscoveryLineageReadError(
                "discovery-lineage projection generation is not active"
            )
        if require_fresh and (
            status.open_gap_count
            or status.dead_letter_count
            or status.contiguous_ledger_seq
            < status.authority_watermark_ledger_seq
        ):
            raise DiscoveryLineageReadError(
                "discovery-lineage projection is incomplete or stale"
            )

    @classmethod
    def _validate_response(
        cls,
        request: DiscoveryLineageReadRequest,
        response: StructuralReadResponse,
        *,
        status: ProjectionStatusMetadata,
    ) -> None:
        cls._validate_status(status, require_fresh=False)
        family = cls._current_family()
        metadata = response.metadata
        if (
            metadata.family_id != DISCOVERY_LINEAGE_FAMILY_ID
            or metadata.family_definition_version
            != family.definition_version
            or metadata.projector_version != family.projector_version
            or metadata.ontology_contract_digest
            != family.ontology_contract_digest
            or metadata.mapping_contract_digest != family.mapping_contract_digest
            or metadata.generation_id != status.generation_id
            or metadata.generation_state is not ProjectionGenerationState.ACTIVE
            or metadata.authority_selection
            is not StructuralReadAuthoritySelection.AUTHORITY_SELECTED_ACTIVE
            or metadata.contiguous_ledger_seq != status.contiguous_ledger_seq
            or metadata.open_gap_count != status.open_gap_count
            or metadata.dead_letter_count != status.dead_letter_count
        ):
            raise DiscoveryLineageReadError(
                "discovery-lineage read metadata differs from authority"
            )

        ontology = cls._current_ontology()
        if any(node.node_type not in ontology.node_types for node in response.nodes):
            raise DiscoveryLineageReadError(
                "discovery-lineage read returned an unexpected node type"
            )
        if any(
            relation.relation_type not in ontology.relation_types
            for relation in response.relations
        ):
            raise DiscoveryLineageReadError(
                "discovery-lineage read returned an unexpected relation type"
            )
        if any(
            node.identity_source
            != (
                "EVENT"
                if node.node_type is ProjectionNodeType.LEDGER_EVENT
                else "GOVERNED_ID"
            )
            for node in response.nodes
        ):
            raise DiscoveryLineageReadError(
                "discovery-lineage read returned an invalid identity source"
            )

        nodes_by_id = {node.canonical_id: node for node in response.nodes}
        if len(nodes_by_id) != len(response.nodes):
            raise DiscoveryLineageReadError(
                "discovery-lineage read returned duplicate nodes"
            )
        for subject in request.subjects:
            node = nodes_by_id.get(subject.canonical_id)
            if node is None:
                raise DiscoveryLineageReadError(
                    "discovery-lineage read is missing a governed subject"
                )
            if (
                node.node_type is not subject.node_type
                or node.identity_source != "GOVERNED_ID"
            ):
                raise DiscoveryLineageReadError(
                    "discovery-lineage subject identity is inconsistent"
                )

        known_ids = set(nodes_by_id)
        if any(
            relation.source_canonical_id not in known_ids
            or relation.target_canonical_id not in known_ids
            for relation in response.relations
        ):
            raise DiscoveryLineageReadError(
                "discovery-lineage relation endpoint is missing"
            )
        relation_contracts = {
            item.relation_type: item for item in ontology.relations
        }
        for relation in response.relations:
            contract = relation_contracts[relation.relation_type]
            source = nodes_by_id[relation.source_canonical_id]
            target = nodes_by_id[relation.target_canonical_id]
            if (
                source.node_type not in contract.source_types
                or target.node_type not in contract.target_types
            ):
                raise DiscoveryLineageReadError(
                    "discovery-lineage relation endpoints violate the ontology"
                )
        if len(response.nodes) > request.limit or len(response.relations) > request.limit:
            raise DiscoveryLineageReadError(
                "discovery-lineage read exceeded its bounded result limit"
            )

    def read(
        self,
        request: DiscoveryLineageReadRequest,
        *,
        proof: AuthenticationProof,
    ) -> StructuralReadResponse:
        if not isinstance(request, DiscoveryLineageReadRequest):
            raise TypeError("discovery-lineage read requires a typed request")
        try:
            self.__eligibility(
                tuple(subject.identifier for subject in request.subjects),
                proof,
            )
        except ProjectionStateError as exc:
            raise DiscoveryLineageReadError(
                "discovery-lineage subject is not currently eligible"
            ) from exc
        status = self.status(proof=proof)
        self._validate_status(status, require_fresh=True)
        response = self.__active_read(request.active_request(), proof)
        self._validate_response(request, response, status=status)
        return response

    def status(self, *, proof: AuthenticationProof) -> ProjectionStatusMetadata:
        return self.__status(DISCOVERY_LINEAGE_FAMILY_ID, proof)

    def gaps(
        self,
        *,
        limit: int = 100,
        proof: AuthenticationProof,
    ) -> tuple[ProjectionGapView, ...]:
        status = self.status(proof=proof)
        if status.generation_id is None:
            raise DiscoveryLineageReadError(
                "discovery-lineage projection has no generation"
            )
        self._require_limit(limit, field="projection gap read")
        return self.__gaps(status.generation_id, limit, proof)

    def dead_letters(
        self,
        *,
        limit: int = 100,
        proof: AuthenticationProof,
    ) -> tuple[ProjectionDeadLetterView, ...]:
        status = self.status(proof=proof)
        if status.generation_id is None:
            raise DiscoveryLineageReadError(
                "discovery-lineage projection has no generation"
            )
        self._require_limit(limit, field="projection dead-letter read")
        return self.__dead_letters(status.generation_id, limit, proof)

    @staticmethod
    def _require_limit(limit: int, *, field: str) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError(f"{field} limit must be an integer")
        if not 0 < limit <= 500:
            raise ValueError(f"{field} limit is outside policy bounds")

    def assess_projection(
        self,
        request: DiscoveryLineageReadRequest,
        *,
        policy: HealthPolicy,
        assessed_at: UtcTimestamp,
        proof: AuthenticationProof,
    ) -> DiscoveryHealthAssessment:
        if not isinstance(request, DiscoveryLineageReadRequest):
            raise TypeError("projection health requires a typed lineage request")
        try:
            self.__eligibility(
                tuple(subject.identifier for subject in request.subjects),
                proof,
            )
        except ProjectionStateError as exc:
            raise DiscoveryLineageReadError(
                "discovery-lineage health subject is not currently eligible"
            ) from exc
        status = self.status(proof=proof)
        family = self._current_family()
        contracts_current = (
            status.projector_version == family.projector_version
            and status.ontology_contract_digest
            == family.ontology_contract_digest
            and status.mapping_contract_digest == family.mapping_contract_digest
        )

        validation: ProjectionGenerationValidationView | None = None
        if status.generation_id is not None:
            try:
                validation = self.__validation(status.generation_id, proof)
            except ProjectionStateError:
                validation = None
            except AuthorityPersistenceError as exc:
                if "projection validation evidence is absent" not in str(exc):
                    raise
                validation = None
        reconciliation_valid = (
            None
            if validation is None
            else (
                validation.generation_id == status.generation_id
                and validation.checkpoint_ledger_seq
                == status.contiguous_ledger_seq
                and validation.definition_digest == family.digest
                and validation.ontology_contract_digest
                == family.ontology_contract_digest
                and validation.mapping_contract_digest
                == family.mapping_contract_digest
                and validation.projector_version == family.projector_version
            )
        )

        service_available: bool | None = None
        query_valid: bool | None = None
        if status.generation_state is ProjectionGenerationState.ACTIVE:
            try:
                response = self.__active_read(request.active_request(), proof)
            except Neo4jConnectionError:
                service_available = False
                query_valid = False
            except (Neo4jReadError, ProjectionStateError):
                service_available = True
                query_valid = False
            else:
                service_available = True
                try:
                    self._validate_response(request, response, status=status)
                except DiscoveryLineageReadError:
                    query_valid = False
                else:
                    query_valid = True

        evidence: list[HealthEvidenceReference] = []
        if status.generation_id is not None:
            evidence.append(
                HealthEvidenceReference(
                    "PROJECTION_STATUS",
                    str(status.generation_id),
                    status.serving_time,
                    digest_canonical(
                        {
                            "family_id": status.family_id,
                            "generation_id": str(status.generation_id),
                            "generation_state": (
                                None
                                if status.generation_state is None
                                else status.generation_state.value
                            ),
                            "contiguous_ledger_seq": status.contiguous_ledger_seq,
                            "authority_watermark_ledger_seq": (
                                status.authority_watermark_ledger_seq
                            ),
                            "open_gap_count": status.open_gap_count,
                            "dead_letter_count": status.dead_letter_count,
                        }
                    ),
                )
            )
        if validation is not None:
            evidence.append(
                HealthEvidenceReference(
                    "PROJECTION_VALIDATION",
                    validation.validation_digest,
                    validation.recorded_at,
                    validation.projection_state_digest,
                )
            )
        if status.generation_id is not None and status.open_gap_count:
            for gap in self.__gaps(
                status.generation_id,
                min(status.open_gap_count, 100),
                proof,
            ):
                evidence.append(
                    HealthEvidenceReference(
                        "PROJECTION_GAP",
                        str(gap.gap_id),
                        gap.recorded_at,
                        digest_canonical(
                            {
                                "ledger_seq_start": gap.ledger_seq_start,
                                "ledger_seq_end": gap.ledger_seq_end,
                                "required": gap.required,
                                "state": gap.state.value,
                                "reason_code": gap.reason_code,
                            }
                        ),
                    )
                )
        if status.generation_id is not None and status.dead_letter_count:
            for item in self.__dead_letters(
                status.generation_id,
                min(status.dead_letter_count, 100),
                proof,
            ):
                evidence.append(
                    HealthEvidenceReference(
                        "PROJECTION_DEAD_LETTER",
                        str(item.dead_letter_id),
                        item.recorded_at,
                        digest_canonical(
                            {
                                "ledger_seq": item.ledger_seq,
                                "attempts": item.attempts,
                                "reason_code": item.reason_code,
                            }
                        ),
                    )
                )

        return assess_projection_health(
            ProjectionHealthInput(
                family_id=DISCOVERY_LINEAGE_FAMILY_ID,
                generation_id=status.generation_id,
                generation_state=status.generation_state,
                service_available=service_available,
                query_valid=query_valid,
                contracts_current=contracts_current,
                reconciliation_valid=reconciliation_valid,
                contiguous_ledger_seq=status.contiguous_ledger_seq,
                authority_watermark_ledger_seq=(
                    status.authority_watermark_ledger_seq
                ),
                open_gap_count=status.open_gap_count,
                dead_letter_count=status.dead_letter_count,
                evidence=tuple(evidence),
            ),
            policy=policy,
            assessed_at=assessed_at,
        )


__all__ = [
    "DiscoveryLineageIdentifier",
    "DiscoveryLineageProjectionFacade",
    "DiscoveryLineageReadError",
    "DiscoveryLineageReadRequest",
    "DiscoveryLineageSubject",
]
