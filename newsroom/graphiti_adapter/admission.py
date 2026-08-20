"""Explicit Graphiti proposal admission before admitted Neo4j projector writes.

Graphiti remains proposal-only (GRAG-020). Entity and relation proposals need a
typed admit, reject, or hold decision before any Increment 4 admitted projector
write (GRAG-023). Graphiti vectors stay out of the admitted OD-006 1,024-d index.
EVALUATION only; the adapter never writes the ledger or admitted labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.types import UUIDv4Id
from newsroom.entities.types import EntityResolutionDecisionAction
from newsroom.extraction.models import ProposalDraft
from newsroom.extraction.types import ExtractionProposalKind
from .evaluation_packet import GRAPHITI_WORKSPACE_GROUP
from .types import (
    GraphitiAdapterContractError,
    GraphitiExecutionProfile,
    digest,
    token,
)
from newsroom.relations.models import RelationDecisionAction


ADMITTED_OD006_VECTOR_DIMENSIONS = 1024
GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID = "graph.increment4.admitted"
ADMITTED_NEO4J_LABELS = (
    "NewsroomAdmittedRelationEndpoint",
    "NewsroomAdmittedRelationIdentity",
)
_PROJECTABLE_KINDS = frozenset(
    {
        ExtractionProposalKind.ENTITY_MENTION,
        ExtractionProposalKind.ENTITY_EQUIVALENCE,
        ExtractionProposalKind.RELATION,
    }
)


class GraphitiProposalAdmissionError(GraphitiAdapterContractError):
    """Graphiti proposals cannot enter admitted projectors without a typed decision."""


class GraphitiProposalAdmissionDecisionId(UUIDv4Id):
    pass


class GraphitiProposalAdmissionAction(StrEnum):
    ADMIT = "ADMIT"
    REJECT = "REJECT"
    HOLD = "HOLD"

    @property
    def may_write_admitted_projector(self) -> bool:
        return self is GraphitiProposalAdmissionAction.ADMIT


@dataclass(frozen=True, slots=True)
class GraphitiProposalAdmissionDecision:
    decision_id: GraphitiProposalAdmissionDecisionId
    proposal_digest: str
    proposal_kind: ExtractionProposalKind
    proposal_local_id: str
    action: GraphitiProposalAdmissionAction
    reason_code: str
    workspace_group: str = GRAPHITI_WORKSPACE_GROUP
    execution_profile: GraphitiExecutionProfile = GraphitiExecutionProfile.EVALUATION

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, GraphitiProposalAdmissionDecisionId):
            raise GraphitiProposalAdmissionError("admission decision identity must be typed")
        digest(self.proposal_digest, field="graphiti_admission_proposal_digest")
        if not isinstance(self.proposal_kind, ExtractionProposalKind):
            raise GraphitiProposalAdmissionError("admission proposal kind must be typed")
        if self.proposal_kind not in _PROJECTABLE_KINDS:
            raise GraphitiProposalAdmissionError(
                "only Graphiti entity and relation proposals may be admitted"
            )
        token(self.proposal_local_id, field="graphiti_admission_proposal_local_id")
        if not isinstance(self.action, GraphitiProposalAdmissionAction):
            raise GraphitiProposalAdmissionError("admission action must be typed")
        token(self.reason_code, field="graphiti_admission_reason_code")
        token(self.workspace_group, field="graphiti_admission_workspace_group")
        if self.workspace_group != GRAPHITI_WORKSPACE_GROUP:
            raise GraphitiProposalAdmissionError(
                "Graphiti admission is bound to disposable group newsroom-eval-proposal"
            )
        if not isinstance(self.execution_profile, GraphitiExecutionProfile):
            raise GraphitiProposalAdmissionError("admission execution profile must be typed")
        if self.execution_profile is not GraphitiExecutionProfile.EVALUATION:
            raise GraphitiProposalAdmissionError(
                "Graphiti admission is authorised only under EVALUATION"
            )

    @property
    def may_write_admitted_projector(self) -> bool:
        return self.action.may_write_admitted_projector

    def entity_resolution_action(self) -> EntityResolutionDecisionAction:
        if self.proposal_kind is ExtractionProposalKind.RELATION:
            raise GraphitiProposalAdmissionError(
                "relation proposals use the relation admission seam"
            )
        return {
            GraphitiProposalAdmissionAction.ADMIT: EntityResolutionDecisionAction.ACCEPT,
            GraphitiProposalAdmissionAction.REJECT: EntityResolutionDecisionAction.REJECT,
            GraphitiProposalAdmissionAction.HOLD: EntityResolutionDecisionAction.HOLD,
        }[self.action]

    def relation_admission_action(self) -> RelationDecisionAction:
        if self.proposal_kind is not ExtractionProposalKind.RELATION:
            raise GraphitiProposalAdmissionError(
                "entity proposals use the entity resolution seam"
            )
        return {
            GraphitiProposalAdmissionAction.ADMIT: RelationDecisionAction.ADMIT,
            GraphitiProposalAdmissionAction.REJECT: RelationDecisionAction.REJECT,
            GraphitiProposalAdmissionAction.HOLD: RelationDecisionAction.HOLD,
        }[self.action]


@dataclass(frozen=True, slots=True)
class AdmittedGraphitiProjectorWrite:
    """Proposal artifacts eligible for the existing Increment 4 admitted projector."""

    proposals: tuple[ProposalDraft, ...]
    decisions: tuple[GraphitiProposalAdmissionDecision, ...]
    workspace_group: str = GRAPHITI_WORKSPACE_GROUP
    projector_family_id: str = GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID
    admitted_vector_dimensions_excluded: int = ADMITTED_OD006_VECTOR_DIMENSIONS

    def __post_init__(self) -> None:
        if not isinstance(self.proposals, tuple) or any(
            not isinstance(item, ProposalDraft) for item in self.proposals
        ):
            raise GraphitiProposalAdmissionError(
                "admitted projector write needs typed proposal drafts"
            )
        if not isinstance(self.decisions, tuple) or any(
            not isinstance(item, GraphitiProposalAdmissionDecision)
            for item in self.decisions
        ):
            raise GraphitiProposalAdmissionError(
                "admitted projector write needs typed admission decisions"
            )
        if len(self.proposals) != len(self.decisions):
            raise GraphitiProposalAdmissionError(
                "admitted projector write must pair each proposal with its ADMIT decision"
            )
        if self.workspace_group != GRAPHITI_WORKSPACE_GROUP:
            raise GraphitiProposalAdmissionError(
                "admitted projector write is bound to disposable group newsroom-eval-proposal"
            )
        if self.projector_family_id != GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID:
            raise GraphitiProposalAdmissionError(
                "Graphiti admission binds only the Increment 4 admitted projector family"
            )
        if self.admitted_vector_dimensions_excluded != ADMITTED_OD006_VECTOR_DIMENSIONS:
            raise GraphitiProposalAdmissionError(
                "Graphiti vectors must stay out of the admitted OD-006 1,024-d index"
            )
        expected = tuple(sorted(self.proposals, key=lambda item: item.local_id))
        if self.proposals != expected:
            raise GraphitiProposalAdmissionError(
                "admitted projector proposals must be sorted by local identity"
            )
        for proposal, decision in zip(self.proposals, self.decisions, strict=True):
            if decision.proposal_digest != proposal.digest:
                raise GraphitiProposalAdmissionError(
                    "admitted projector write decision does not bind its proposal"
                )
            if not decision.may_write_admitted_projector:
                raise GraphitiProposalAdmissionError(
                    "admitted projector write cannot carry reject or hold decisions"
                )

    @property
    def may_write_admitted_projector(self) -> bool:
        return bool(self.proposals)


def admit_graphiti_proposals_for_projectors(
    *,
    proposals: tuple[ProposalDraft, ...],
    decisions: tuple[GraphitiProposalAdmissionDecision, ...],
) -> AdmittedGraphitiProjectorWrite:
    """Return ADMIT-only artifacts for existing projector seams. Fail closed otherwise."""

    if not isinstance(proposals, tuple) or not proposals:
        raise GraphitiProposalAdmissionError("Graphiti admission needs typed proposals")
    if any(not isinstance(item, ProposalDraft) for item in proposals):
        raise GraphitiProposalAdmissionError("Graphiti admission needs typed proposal drafts")
    if not isinstance(decisions, tuple) or any(
        not isinstance(item, GraphitiProposalAdmissionDecision) for item in decisions
    ):
        raise GraphitiProposalAdmissionError("Graphiti admission needs typed decisions")
    if len(decisions) != len(proposals):
        raise GraphitiProposalAdmissionError(
            "each Graphiti proposal needs exactly one admission decision"
        )
    by_digest = {item.digest: item for item in proposals}
    if len(by_digest) != len(proposals):
        raise GraphitiProposalAdmissionError("Graphiti proposal digests must be unique")
    seen_ids: set[str] = set()
    seen_digests: set[str] = set()
    admitted: list[tuple[ProposalDraft, GraphitiProposalAdmissionDecision]] = []
    for decision in decisions:
        identity = str(decision.decision_id)
        if identity in seen_ids:
            raise GraphitiProposalAdmissionError("admission decision identities must be unique")
        seen_ids.add(identity)
        if decision.proposal_digest in seen_digests:
            raise GraphitiProposalAdmissionError(
                "each proposal may have only one admission decision"
            )
        seen_digests.add(decision.proposal_digest)
        proposal = by_digest.get(decision.proposal_digest)
        if proposal is None:
            raise GraphitiProposalAdmissionError("admission decision names an unknown proposal")
        if (
            proposal.local_id != decision.proposal_local_id
            or proposal.kind is not decision.proposal_kind
        ):
            raise GraphitiProposalAdmissionError(
                "admission decision does not bind the exact proposal identity"
            )
        if decision.may_write_admitted_projector:
            admitted.append((proposal, decision))
    if seen_digests != set(by_digest):
        raise GraphitiProposalAdmissionError(
            "each Graphiti proposal needs exactly one admission decision"
        )
    admitted.sort(key=lambda item: item[0].local_id)
    return AdmittedGraphitiProjectorWrite(
        proposals=tuple(item[0] for item in admitted),
        decisions=tuple(item[1] for item in admitted),
    )


def require_admitted_projector_write(
    admission: AdmittedGraphitiProjectorWrite,
) -> AdmittedGraphitiProjectorWrite:
    if not isinstance(admission, AdmittedGraphitiProjectorWrite):
        raise GraphitiProposalAdmissionError("admitted projector write must be typed")
    if not admission.may_write_admitted_projector:
        raise GraphitiProposalAdmissionError(
            "admitted projector write requires an ADMIT decision"
        )
    return admission


def increment4_batches_for_admitted_graphiti(
    *,
    admission: AdmittedGraphitiProjectorWrite,
    snapshot: object,
    generation_id: object,
    family: object,
) -> tuple[object, ...]:
    """Gate existing Increment 4 projector mapping behind an ADMIT decision."""

    require_admitted_projector_write(admission)
    from newsroom.increment4.contracts import INCREMENT4_ADMITTED_FAMILY_ID
    from newsroom.increment4.models import Increment4AdmittedProjectionSnapshot
    from newsroom.increment4.projection import build_increment4_admitted_batches
    from newsroom.projection.models import ProjectionFamilyDefinition, ProjectionGenerationId

    if INCREMENT4_ADMITTED_FAMILY_ID != GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID:
        raise GraphitiProposalAdmissionError(
            "Graphiti admission projector family drifted from Increment 4"
        )
    if not isinstance(snapshot, Increment4AdmittedProjectionSnapshot):
        raise GraphitiProposalAdmissionError(
            "admitted projector write requires a typed Increment 4 snapshot"
        )
    if not isinstance(generation_id, ProjectionGenerationId):
        raise GraphitiProposalAdmissionError(
            "admitted projector write requires a typed projection generation"
        )
    if not isinstance(family, ProjectionFamilyDefinition):
        raise GraphitiProposalAdmissionError(
            "admitted projector write requires a typed projection family"
        )
    if family.family_id != INCREMENT4_ADMITTED_FAMILY_ID:
        raise GraphitiProposalAdmissionError(
            "Graphiti admission binds only the Increment 4 admitted projector family"
        )
    return build_increment4_admitted_batches(
        snapshot,
        generation_id=generation_id,
        family=family,
    )


__all__ = [
    "ADMITTED_NEO4J_LABELS",
    "ADMITTED_OD006_VECTOR_DIMENSIONS",
    "AdmittedGraphitiProjectorWrite",
    "GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID",
    "GraphitiProposalAdmissionAction",
    "GraphitiProposalAdmissionDecision",
    "GraphitiProposalAdmissionDecisionId",
    "GraphitiProposalAdmissionError",
    "admit_graphiti_proposals_for_projectors",
    "increment4_batches_for_admitted_graphiti",
    "require_admitted_projector_write",
]
