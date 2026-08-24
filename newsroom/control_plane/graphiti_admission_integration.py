"""Concrete governed authority integration for Graphiti admission work.

The corpus receipt deliberately does not manufacture authority identities.  A
planner must bind it to proposal records already retained by the extraction
authority; this adapter then executes the existing authenticated entity and
editorial-relation commands and translates only their retained receipts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.authority.editorial_relation_system import GovernedEditorialRelations
from newsroom.authority.entity_system import GovernedEntityRecords
from newsroom.control_plane.governed_context import (
    AuthorityContextBinding,
    GovernedAuthorityContext,
)
from newsroom.control_plane.graphiti_admission import (
    GraphitiAdmissionConsumerError,
    GraphitiAdmissionRequest,
    GraphitiGovernedDecision,
)
from newsroom.entities.models import (
    EntityMentionAdmissionRequest,
    EntityResolutionDecision,
    EntityResolutionDecisionRequest,
    EntityResolutionProposalRequest,
)
from newsroom.entities.types import (
    CanonicalEntityLifecycle,
    EntityResolutionDecisionAction,
    EntityResolutionProposalId,
)
from newsroom.extraction.types import ExtractionProposalKind
from newsroom.graphiti_adapter.admission import GraphitiProposalAdmissionAction
from newsroom.relations.editorial_models import (
    EditorialRelationDecisionRequest,
    EditorialRelationProposalRequest,
    endpoint_canonical_value,
)
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionLifecycle,
    EditorialRelationDecisionAction,
)


@dataclass(frozen=True, slots=True)
class GraphitiEntityAdmissionPlan:
    """Typed commands bound to one exact retained Graphiti proposal."""

    graphiti_proposal_digest: str
    graphiti_proposal_local_id: str
    mention_requests: tuple[EntityMentionAdmissionRequest, ...]
    proposal_request: EntityResolutionProposalRequest
    decision_request: EntityResolutionDecisionRequest

    def __post_init__(self) -> None:
        if not self.mention_requests:
            raise GraphitiAdmissionConsumerError(
                "entity plan requires governed mention admission"
            )
        if any(
            not isinstance(item, EntityMentionAdmissionRequest)
            for item in self.mention_requests
        ):
            raise GraphitiAdmissionConsumerError(
                "entity plan mention commands must be typed"
            )


@dataclass(frozen=True, slots=True)
class GraphitiRelationAdmissionPlan:
    """Typed relation commands plus the two authority endpoint bindings."""

    graphiti_proposal_digest: str
    graphiti_proposal_local_id: str
    proposal_request: EditorialRelationProposalRequest
    decision_request: EditorialRelationDecisionRequest
    endpoint_resolution_proposal_ids: tuple[EntityResolutionProposalId, ...]
    resolved_endpoint_names: tuple[str, ...]


EntityPlanBuilder = Callable[
    [
        GraphitiAdmissionRequest,
        GraphitiProposalAdmissionAction | None,
        str,
    ],
    GraphitiEntityAdmissionPlan,
]
RelationPlanBuilder = Callable[
    [
        GraphitiAdmissionRequest,
        GraphitiProposalAdmissionAction | None,
        str,
    ],
    GraphitiRelationAdmissionPlan,
]


_ENTITY_ACTIONS = {
    EntityResolutionDecisionAction.ACCEPT: GraphitiProposalAdmissionAction.ADMIT,
    EntityResolutionDecisionAction.REJECT: GraphitiProposalAdmissionAction.REJECT,
    EntityResolutionDecisionAction.HOLD: GraphitiProposalAdmissionAction.HOLD,
}
_RELATION_ACTIONS = {
    EditorialRelationDecisionAction.ACCEPT: GraphitiProposalAdmissionAction.ADMIT,
    EditorialRelationDecisionAction.REJECT: GraphitiProposalAdmissionAction.REJECT,
    EditorialRelationDecisionAction.HOLD: GraphitiProposalAdmissionAction.HOLD,
}


class ExistingGovernedGraphitiAdmissionAuthority:
    """Route admission through existing authenticated authority facades."""

    def __init__(
        self,
        *,
        entities: GovernedEntityRecords,
        relations: GovernedEditorialRelations,
        proof: AuthenticationProof,
        entity_plan: EntityPlanBuilder,
        relation_plan: RelationPlanBuilder,
    ) -> None:
        self._entities = entities
        self._relations = relations
        self._proof = proof
        self._entity_plan = entity_plan
        self._relation_plan = relation_plan

    @staticmethod
    def _require_binding(
        request: GraphitiAdmissionRequest,
        *,
        digest: str,
        local_id: str,
    ) -> None:
        if (
            digest != request.proposal.digest
            or local_id != request.proposal.local_id
        ):
            raise GraphitiAdmissionConsumerError(
                "authority plan does not bind the exact Graphiti proposal"
            )

    @staticmethod
    def _require_action(
        action: GraphitiProposalAdmissionAction,
        required: GraphitiProposalAdmissionAction | None,
    ) -> None:
        if required is not None and action is not required:
            raise GraphitiAdmissionConsumerError(
                "authority plan did not honour the required admission action"
            )

    def decide_entity_resolution(
        self,
        request: GraphitiAdmissionRequest,
        *,
        required_action: GraphitiProposalAdmissionAction | None,
        idempotency_key: str,
    ) -> GraphitiGovernedDecision:
        if request.proposal.kind is ExtractionProposalKind.RELATION:
            raise GraphitiAdmissionConsumerError(
                "relation proposal cannot use entity resolution authority"
            )
        plan = self._entity_plan(request, required_action, idempotency_key)
        self._require_binding(
            request,
            digest=plan.graphiti_proposal_digest,
            local_id=plan.graphiti_proposal_local_id,
        )
        planned_action = _ENTITY_ACTIONS.get(plan.decision_request.action)
        if planned_action is None:
            raise GraphitiAdmissionConsumerError(
                "entity plan contains a non-admission decision"
            )
        self._require_action(planned_action, required_action)
        for mention in plan.mention_requests:
            self._entities.admit_mention(mention, proof=self._proof)
        proposed = self._entities.propose_resolution(
            plan.proposal_request, proof=self._proof
        )
        if (
            proposed.proposal_id != plan.decision_request.proposal_id
            or proposed.proposal_version_id
            != plan.decision_request.expected_proposal_version_id
            or proposed.canonical_digest
            != plan.decision_request.expected_proposal_digest
        ):
            raise GraphitiAdmissionConsumerError(
                "entity decision command differs from the retained authority proposal"
            )
        decided = self._entities.decide_resolution(
            plan.decision_request, proof=self._proof
        )
        if not isinstance(decided, EntityResolutionDecision):
            raise GraphitiAdmissionConsumerError(
                "entity authority returned an untyped decision"
            )
        action = _ENTITY_ACTIONS.get(decided.action)
        if action is None:
            raise GraphitiAdmissionConsumerError(
                "entity authority returned a non-admission decision"
            )
        self._require_action(action, required_action)
        return GraphitiGovernedDecision(
            proposal_key=request.proposal_key,
            proposal_digest=request.proposal.digest,
            proposal_kind=request.proposal.kind,
            proposal_local_id=request.proposal.local_id,
            action=action,
            decision_id=str(decided.decision_id),
            authority_ledger_seq=decided.authority_ledger_seq,
            reason_code=decided.reason_code,
            authority_receipt_digest=digest_canonical(decided.canonical_value()),
        )

    def decide_relation_admission(
        self,
        request: GraphitiAdmissionRequest,
        *,
        required_action: GraphitiProposalAdmissionAction | None,
        idempotency_key: str,
    ) -> GraphitiGovernedDecision:
        if request.proposal.kind is not ExtractionProposalKind.RELATION:
            raise GraphitiAdmissionConsumerError(
                "entity proposal cannot use relation admission authority"
            )
        plan = self._relation_plan(request, required_action, idempotency_key)
        self._require_binding(
            request,
            digest=plan.graphiti_proposal_digest,
            local_id=plan.graphiti_proposal_local_id,
        )
        if (
            len(plan.endpoint_resolution_proposal_ids) != 2
            or len(set(plan.endpoint_resolution_proposal_ids)) != 2
            or plan.resolved_endpoint_names != request.proposed_endpoints
        ):
            raise GraphitiAdmissionConsumerError(
                "relation plan lacks two exact governed endpoint bindings"
            )
        planned_action = _RELATION_ACTIONS.get(plan.decision_request.action)
        if planned_action is None:
            raise GraphitiAdmissionConsumerError(
                "relation plan contains a lifecycle decision"
            )
        self._require_action(planned_action, required_action)
        endpoint_decisions = []
        for proposal_id in plan.endpoint_resolution_proposal_ids:
            decision = self._entities.decision(proposal_id, proof=self._proof)
            if (
                decision is None
                or decision.action is not EntityResolutionDecisionAction.ACCEPT
            ):
                raise GraphitiAdmissionConsumerError(
                    "relation endpoint resolution is not governed-current"
                )
            endpoint_decisions.append(decision)
        proposed = self._relations.propose(
            plan.proposal_request, proof=self._proof
        )
        if (
            proposed.proposal_id != plan.decision_request.proposal_id
            or proposed.proposal_version_id
            != plan.decision_request.proposal_version_id
            or proposed.canonical_digest
            != plan.decision_request.expected_proposal_version_digest
        ):
            raise GraphitiAdmissionConsumerError(
                "relation decision command differs from the retained authority proposal"
            )
        decided = self._relations.decide(
            plan.decision_request, proof=self._proof
        )
        action = _RELATION_ACTIONS.get(decided.action)
        if action is None:
            raise GraphitiAdmissionConsumerError(
                "relation authority returned a lifecycle decision"
            )
        self._require_action(action, required_action)
        endpoint_binding = tuple(
            (
                proposal_id,
                str(decision.decision_id),
                name,
            )
            for proposal_id, decision, name in zip(
                plan.endpoint_resolution_proposal_ids,
                endpoint_decisions,
                plan.resolved_endpoint_names,
                strict=True,
            )
        )
        return GraphitiGovernedDecision(
            proposal_key=request.proposal_key,
            proposal_digest=request.proposal.digest,
            proposal_kind=request.proposal.kind,
            proposal_local_id=request.proposal.local_id,
            action=action,
            decision_id=str(decided.decision_id),
            authority_ledger_seq=decided.authority_ledger_seq,
            reason_code=decided.reason_code,
            authority_receipt_digest=decided.canonical_digest,
            endpoint_resolution_decision_ids=tuple(
                item[1] for item in endpoint_binding
            ) if action is GraphitiProposalAdmissionAction.ADMIT else (),
            resolved_endpoint_names=plan.resolved_endpoint_names
            if action is GraphitiProposalAdmissionAction.ADMIT
            else (),
        )

    def relation_endpoint_resolutions_current(
        self,
        request: GraphitiAdmissionRequest,
        decision: GraphitiGovernedDecision,
    ) -> bool:
        try:
            plan = self._relation_plan(
                request,
                decision.action,
                f"graphiti-admit:{request.proposal_key}",
            )
        except Exception:
            return False
        if (
            plan.graphiti_proposal_digest != request.proposal.digest
            or plan.graphiti_proposal_local_id != request.proposal.local_id
            or plan.resolved_endpoint_names != request.proposed_endpoints
            or len(plan.endpoint_resolution_proposal_ids) != 2
        ):
            return False
        current_ids: list[str] = []
        current_names: list[str] = []
        for proposal_id, expected_decision_id, name in zip(
            plan.endpoint_resolution_proposal_ids,
            decision.endpoint_resolution_decision_ids,
            plan.resolved_endpoint_names,
            strict=True,
        ):
            current = self._entities.decision(proposal_id, proof=self._proof)
            if (
                current is None
                or current.action is not EntityResolutionDecisionAction.ACCEPT
                or str(current.decision_id) != expected_decision_id
            ):
                return False
            current_ids.append(str(current.decision_id))
            current_names.append(name)
        return (
            tuple(current_ids) == decision.endpoint_resolution_decision_ids
            and tuple(current_names) == decision.resolved_endpoint_names
            and tuple(current_names) == request.proposed_endpoints
        )


    def current_context(
        self,
        request: GraphitiAdmissionRequest,
        decision: GraphitiGovernedDecision,
    ) -> GovernedAuthorityContext | None:
        """Hydrate the exact current authority behind one admitted receipt."""

        if decision.action is not GraphitiProposalAdmissionAction.ADMIT:
            return None
        try:
            if request.proposal.kind is ExtractionProposalKind.RELATION:
                plan = self._relation_plan(
                    request,
                    GraphitiProposalAdmissionAction.ADMIT,
                    f"graphiti-admit:{request.proposal_key}",
                )
                self._require_binding(
                    request,
                    digest=plan.graphiti_proposal_digest,
                    local_id=plan.graphiti_proposal_local_id,
                )
                retained = self._relations.decision(
                    plan.proposal_request.proposal_id,
                    proof=self._proof,
                )
                if (
                    retained is None
                    or retained.action is not EditorialRelationDecisionAction.ACCEPT
                    or str(retained.decision_id) != decision.decision_id
                    or retained.authority_ledger_seq != decision.authority_ledger_seq
                    or retained.assertion_id is None
                ):
                    return None
                current = self._relations.current(
                    retained.assertion_id,
                    proof=self._proof,
                )
                assertion = current.assertion
                version = self._relations.proposal_version(
                    assertion.proposal_version_id,
                    proof=self._proof,
                )
                currentness = (
                    "CURRENT"
                    if current.lifecycle is EditorialRelationAssertionLifecycle.ACTIVE
                    and str(current.current_decision_id) == decision.decision_id
                    and current.current_decision_version == retained.decision_version
                    else "STALE"
                )
                bindings = (
                    AuthorityContextBinding(
                        authority_kind="EDITORIAL_RELATION_ASSERTION",
                        authority_id=str(assertion.assertion_id),
                        authority_version=str(version.version_number),
                    ),
                    AuthorityContextBinding(
                        authority_kind="EDITORIAL_RELATION_DECISION",
                        authority_id=str(retained.decision_id),
                        authority_version=str(retained.decision_version),
                    ),
                )
                temporal = tuple(
                    sorted(
                        {
                            "admitted_at": (
                                None
                                if assertion.admitted_at is None
                                else assertion.admitted_at.to_text()
                            ),
                            **assertion.temporal_scope.canonical_value(),
                        }.items()
                    )
                )
                return GovernedAuthorityContext(
                    bindings=bindings,
                    admitted_temporal_fields=temporal,
                    currentness_state=currentness,
                    admitted_structured_value_json=canonical_json_bytes(
                        {
                            "authority_kind": "EDITORIAL_RELATION_ASSERTION",
                            "assertion": {
                                "assertion_id": str(assertion.assertion_id),
                                "predicate": assertion.predicate.value,
                                "subject": endpoint_canonical_value(
                                    assertion.subject
                                ),
                                "object": endpoint_canonical_value(assertion.object),
                                "statement": assertion.statement,
                                "temporal_scope": (
                                    assertion.temporal_scope.canonical_value()
                                ),
                                "uncertainty_codes": list(
                                    assertion.uncertainty_codes
                                ),
                            },
                        }
                    ).decode(),
                )

            plan = self._entity_plan(
                request,
                GraphitiProposalAdmissionAction.ADMIT,
                f"graphiti-admit:{request.proposal_key}",
            )
            self._require_binding(
                request,
                digest=plan.graphiti_proposal_digest,
                local_id=plan.graphiti_proposal_local_id,
            )
            retained = self._entities.decision(
                plan.proposal_request.proposal_id,
                proof=self._proof,
            )
            if (
                retained is None
                or retained.action is not EntityResolutionDecisionAction.ACCEPT
                or str(retained.decision_id) != decision.decision_id
                or retained.authority_ledger_seq != decision.authority_ledger_seq
                or retained.accepted_entity_id is None
                or retained.accepted_entity_version_id is None
            ):
                return None
            preferred = self._entities.preferred(
                retained.accepted_entity_id,
                proof=self._proof,
            )
            version = self._entities.entity_version(
                preferred.current_entity_version_id,
                proof=self._proof,
            )
            aliases = self._entities.aliases(
                retained.accepted_entity_id,
                limit=16,
                proof=self._proof,
            )
            currentness = (
                "CURRENT"
                if version.entity_id == retained.accepted_entity_id
                and preferred.entity_id == retained.accepted_entity_id
                and preferred.preferred_entity_id == retained.accepted_entity_id
                and preferred.lifecycle is CanonicalEntityLifecycle.ACTIVE
                and version.lifecycle is CanonicalEntityLifecycle.ACTIVE
                else "STALE"
            )
            return GovernedAuthorityContext(
                bindings=(
                    AuthorityContextBinding(
                        authority_kind="CANONICAL_ENTITY",
                        authority_id=str(retained.accepted_entity_id),
                        authority_version=str(version.version_number),
                    ),
                    AuthorityContextBinding(
                        authority_kind="ENTITY_RESOLUTION_DECISION",
                        authority_id=str(retained.decision_id),
                        authority_version=str(retained.decision_version),
                    ),
                ),
                admitted_temporal_fields=(
                    ("admitted_at", retained.recorded_at.to_text()),
                ),
                currentness_state=currentness,
                admitted_structured_value_json=canonical_json_bytes(
                    {
                        "authority_kind": "CANONICAL_ENTITY",
                        "aliases": [alias.canonical_value() for alias in aliases],
                        "entity_version": version.canonical_value(),
                    }
                ).decode(),
            )
        except Exception:  # noqa: BLE001 - any authority read fault fails closed
            return None


__all__ = [
    "ExistingGovernedGraphitiAdmissionAuthority",
    "GraphitiEntityAdmissionPlan",
    "GraphitiRelationAdmissionPlan",
]
