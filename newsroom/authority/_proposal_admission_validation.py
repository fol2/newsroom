from __future__ import annotations

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import TimePrecision
from newsroom.checks.admission_models import (
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
    deterministic_uuid4,
)
from newsroom.checks.check_models import CheckOutcomeRequest
from newsroom.checks.transition_models import ObservableTransitionRequest
from newsroom.checks.types import (
    CheckOutcomeKind,
    QuarantineDisposition,
    TriggerKind,
)
from newsroom.discovery_adapters import ParsedItem
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationId,
    DiscoveryRepresentationRequest,
    IdentityComponent,
    SourceDefinitionVersion,
    SourceItemId,
    SourceItemIdentityKind,
    SourceItemRequest,
    SourceRevision,
    SourceRevisionId,
    SourceRevisionRequest,
    sorted_identity_components,
)



_COMPLETE_CONFIRMATION_KINDS = frozenset(
    {
        CheckOutcomeKind.SUCCESS_EMPTY,
        CheckOutcomeKind.SUCCESS_UNCHANGED,
        CheckOutcomeKind.SUCCESS_CHANGED,
    }
)
from ._proposal_admission_models import (
    _field_map,
    _identity_component_name,
    _source_time,
    _version_token,
)


class _ProposalAdmissionValidationMixin:
    @staticmethod
    def _validate_adapter_contract(
        request: ProposalAdmissionRequest,
        version: SourceDefinitionVersion,
        *,
        retained_request,
        retained_attempt,
    ) -> None:
        adapter = request.adapter_request
        source = version.request
        if (
            retained_request.request.definition_id
            != adapter.source_definition_id
            or retained_request.request.definition_version_id
            != adapter.source_definition_version_id
            or retained_request.request.adapter_request_digest
            != adapter.digest
            or retained_request.request.producer_slot_digest
            != adapter.producer_slot_digest
            or retained_request.request.validator_policy
            != adapter.validator_contract
            or retained_attempt.request.request_id
            != retained_request.request.request_id
            or retained_attempt.request.adapter_request_id
            != adapter.request_id
            or retained_attempt.request.adapter_request_digest
            != adapter.digest
        ):
            raise ProposalAdmissionConflict(
                "adapter proposal differs from retained Check Request or Attempt"
            )
        if (
            source.version_id != adapter.source_definition_version_id
            or source.definition_id != adapter.source_definition_id
            or source.observation_model is not adapter.observation_model
            or source.adapter_contract.policy_id
            != adapter.adapter.adapter_id
            or source.adapter_contract.policy_version
            != adapter.adapter.adapter_version
        ):
            raise ProposalAdmissionConflict(
                "adapter request differs from exact Source Definition Version"
            )

    def _validate_transition_evidence_preflight(
        self,
        transitions: tuple[ObservableTransitionRequest, ...],
        *,
        pending_outcome: CheckOutcomeRequest,
        retained_request,
    ) -> None:
        for transition in transitions:
            if transition.check_outcome_id != pending_outcome.outcome_id:
                raise ProposalAdmissionConflict(
                    "planned transition differs from pending Check Outcome"
                )
            if transition.observed_at != pending_outcome.completed_at:
                raise ProposalAdmissionConflict(
                    "planned transition observation time differs from pending Outcome"
                )
            guard = transition.absence_guard or transition.agenda_guard
            if guard is None:
                continue
            references = guard.confirmation_outcomes
            if pending_outcome.outcome_id not in {
                reference.outcome_id for reference in references
            }:
                raise ProposalAdmissionConflict(
                    "transition guard omits its pending Check Outcome"
                )

            request_ids = set()
            current_complete = None
            for reference in references:
                if reference.outcome_id == pending_outcome.outcome_id:
                    outcome = pending_outcome
                    parent = retained_request.request
                else:
                    retained_outcome = self._store.check_outcome(
                        reference.outcome_id
                    )
                    retained_parent = self._store.check_request(
                        reference.request_id
                    )
                    if retained_outcome is None or retained_parent is None:
                        raise ProposalAdmissionConflict(
                            "transition guard references unretained Check authority"
                        )
                    outcome = retained_outcome.request
                    parent = retained_parent.request
                if (
                    outcome.request_id != reference.request_id
                    or parent.request_id != reference.request_id
                    or parent.adapter_request_digest
                    != reference.adapter_request_digest
                ):
                    raise ProposalAdmissionConflict(
                        "transition guard confirmation differs from exact Check authority"
                    )
                if parent.request_id in request_ids:
                    raise ProposalAdmissionConflict(
                        "transition guard cannot count retries as separate confirmations"
                    )
                request_ids.add(parent.request_id)
                if (
                    outcome.definition_id != transition.definition_id
                    or outcome.definition_version_id
                    != transition.definition_version_id
                ):
                    raise ProposalAdmissionConflict(
                        "transition guard confirmation belongs to another source version"
                    )
                if outcome.completed_at.value > transition.observed_at.value:
                    raise ProposalAdmissionConflict(
                        "transition guard confirmation occurs after the transition"
                    )
                complete = (
                    not outcome.incomplete
                    and outcome.kind in _COMPLETE_CONFIRMATION_KINDS
                    and outcome.quarantine is QuarantineDisposition.NONE
                )
                if outcome.outcome_id == pending_outcome.outcome_id:
                    current_complete = complete
                if transition.absence_guard is not None:
                    current_parent = retained_request.request
                    if (
                        parent.coverage != current_parent.coverage
                        or parent.producer_slot_digest
                        != current_parent.producer_slot_digest
                        or parent.validator_policy
                        != current_parent.validator_policy
                    ):
                        raise ProposalAdmissionConflict(
                            "absence confirmation differs from the exact "
                            "snapshot Check contract"
                        )
                    if transition.absence_guard.authorizes_ending and not complete:
                        raise ProposalAdmissionConflict(
                            "absence ending cites incomplete or failed confirmation"
                        )
                else:
                    assert transition.agenda_guard is not None
                    if (
                        parent.trigger.kind is not TriggerKind.PLANNED_WINDOW
                        or parent.trigger.expected_window_digest
                        != transition.agenda_guard.expected_window_digest
                    ):
                        raise ProposalAdmissionConflict(
                            "Agenda confirmation differs from the exact planned window"
                        )
                    if not complete:
                        raise ProposalAdmissionConflict(
                            "Agenda miss cites incomplete or failed confirmation"
                        )

            if transition.absence_guard is not None:
                if (
                    current_complete is None
                    or current_complete
                    != transition.absence_guard.successful_complete_outcome
                ):
                    raise ProposalAdmissionConflict(
                        "absence guard completeness differs from pending Outcome"
                    )
            else:
                assert transition.agenda_guard is not None
                trigger = retained_request.request.trigger
                if (
                    trigger.kind is not TriggerKind.PLANNED_WINDOW
                    or trigger.expected_window_digest
                    != transition.agenda_guard.expected_window_digest
                ):
                    raise ProposalAdmissionConflict(
                        "Agenda miss guard differs from planned-window Check Request"
                    )

    @staticmethod
    def _validate_item_key(
        request: ProposalAdmissionRequest,
        item: ParsedItem,
    ) -> tuple[IdentityComponent, ...]:
        shape = request.adapter_request.shape_contract
        values = _field_map(item)
        if shape.singleton_identity is not None:
            identity: object = {
                "singleton_identity": shape.singleton_identity,
            }
            raw = (
                IdentityComponent(
                    "singleton_identity",
                    shape.singleton_identity,
                ),
            )
        else:
            locator_names = {"locator", "url", "uri", "link"}
            if set(shape.identity_fields) <= locator_names:
                raise ProposalAdmissionConflict(
                    "a changing locator cannot be the sole Source Item identity"
                )
            try:
                identity = [
                    (name, values[name])
                    for name in shape.identity_fields
                ]
            except KeyError as exc:
                raise ProposalAdmissionConflict(
                    "parsed item lacks an exact identity field"
                ) from exc
            raw = tuple(
                IdentityComponent(_identity_component_name(name), values[name])
                for name in shape.identity_fields
            )
        expected = digest_canonical(
            {
                "source_definition_id": str(
                    request.adapter_request.source_definition_id
                ),
                "identity": identity,
            }
        )
        if expected != item.item_key:
            raise ProposalAdmissionConflict(
                "parsed item key differs from exact shape identity"
            )
        return sorted_identity_components(
            (
                IdentityComponent(
                    "identity_basis",
                    "increment-3b-item-key-v1",
                ),
                *raw,
            )
        )

    @staticmethod
    def _validate_permitted_fields(
        item: ParsedItem,
        version: SourceDefinitionVersion,
    ) -> None:
        allowed = set(version.request.extraction_scope)
        actual = {field.name for field in item.fields}
        unexpected = actual - allowed
        if unexpected:
            raise ProposalAdmissionConflict(
                "parsed fields exceed the exact source extraction scope: "
                + ",".join(sorted(unexpected))
            )

    def _item_request(
        self,
        admission: ProposalAdmissionRequest,
        version: SourceDefinitionVersion,
        item: ParsedItem,
    ) -> SourceItemRequest:
        components = self._validate_item_key(admission, item)
        item_id = deterministic_uuid4(
            SourceItemId,
            namespace="increment-3c-source-item-v1",
            semantic_value={
                "definition_id": str(version.request.definition_id),
                "item_key": item.item_key,
            },
        )
        return SourceItemRequest(
            item_id=item_id,
            definition_id=version.request.definition_id,
            definition_version_id=version.request.version_id,
            identity_kind=SourceItemIdentityKind.COMPOSITE,
            identity_policy=version.request.item_identity_policy,
            source_native_id=None,
            identity_components=components,
            uncertainties=item.uncertainties,
            idempotency_key=f"proposal-item:{item_id}",
        )

    @staticmethod
    def _permitted_state_digest(item: ParsedItem) -> str:
        return digest_canonical(
            {
                "fields": [field.canonical_value() for field in item.fields],
                "uncertainties": list(item.uncertainties),
            }
        )

    def _revision_request(
        self,
        admission: ProposalAdmissionRequest,
        version: SourceDefinitionVersion,
        item: ParsedItem,
        *,
        source_item: SourceItemRequest,
        prior: SourceRevision | None,
        state_digest: str,
    ) -> SourceRevisionRequest:
        prior_id = None if prior is None else prior.request.revision_id
        revision_id = deterministic_uuid4(
            SourceRevisionId,
            namespace="increment-3c-source-revision-v1",
            semantic_value={
                "item_id": str(source_item.item_id),
                "permitted_state_digest": state_digest,
            },
        )
        return SourceRevisionRequest(
            revision_id=revision_id,
            item_id=source_item.item_id,
            definition_version_id=version.request.version_id,
            prior_revision_id=prior_id,
            source_native_revision_token=None,
            permitted_state_digest=state_digest,
            revision_policy=version.request.revision_policy,
            canonicalizer_version=_version_token(
                "source-state",
                version.request.canonicalization_policy.canonical_value(),
            ),
            source_published_time=_source_time(
                item,
                "source_published_time",
            ),
            source_updated_time=_source_time(
                item,
                "source_updated_time",
            ),
            observed_at=admission.completed_at,
            idempotency_key=f"proposal-revision:{revision_id}",
        )

    def _representation_request(
        self,
        admission: ProposalAdmissionRequest,
        version: SourceDefinitionVersion,
        item: ParsedItem,
        *,
        revision_id: SourceRevisionId,
    ) -> DiscoveryRepresentationRequest:
        adapter = admission.adapter_request.adapter
        field_names = tuple(field.name for field in item.fields)
        permitted_fields_digest = digest_canonical(
            {
                "definition_version_id": str(version.request.version_id),
                "extraction_scope": list(version.request.extraction_scope),
                "represented_fields": list(field_names),
            }
        )
        provisional = DiscoveryRepresentationRequest(
            representation_id=DiscoveryRepresentationId.new(),
            revision_id=revision_id,
            definition_version_id=version.request.version_id,
            adapter_version=_version_token(
                "adapter",
                {
                    "adapter_id": adapter.adapter_id,
                    "adapter_version": adapter.adapter_version,
                },
            ),
            parser_version=adapter.parser_version,
            normalizer_version=adapter.normalizer_version,
            extraction_scope_version=_version_token(
                "scope",
                {
                    "definition_version_id": str(version.request.version_id),
                    "extraction_scope": list(version.request.extraction_scope),
                },
            ),
            permitted_fields_digest=permitted_fields_digest,
            representation_digest=item.digest,
            produced_at=admission.completed_at,
            idempotency_key="proposal-representation-provisional",
        )
        representation_id = deterministic_uuid4(
            DiscoveryRepresentationId,
            namespace="increment-3c-discovery-representation-v1",
            semantic_value={
                "revision_id": str(revision_id),
                "producer_slot_digest": provisional.producer_slot_digest,
            },
        )
        return DiscoveryRepresentationRequest(
            representation_id=representation_id,
            revision_id=provisional.revision_id,
            definition_version_id=provisional.definition_version_id,
            adapter_version=provisional.adapter_version,
            parser_version=provisional.parser_version,
            normalizer_version=provisional.normalizer_version,
            extraction_scope_version=provisional.extraction_scope_version,
            permitted_fields_digest=provisional.permitted_fields_digest,
            representation_digest=provisional.representation_digest,
            produced_at=provisional.produced_at,
            idempotency_key=f"proposal-representation:{representation_id}",
        )

    @staticmethod
    def _occurrence_kind(
        trigger_kind: TriggerKind,
        *,
        first_observation: bool,
    ) -> DiscoveryOccurrenceKind:
        if trigger_kind is TriggerKind.DELIVERED_INPUT:
            return DiscoveryOccurrenceKind.DELIVERED
        if first_observation:
            return DiscoveryOccurrenceKind.FIRST_OBSERVED
        return DiscoveryOccurrenceKind.REOBSERVED

    def _occurrence_request(
        self,
        admission: ProposalAdmissionRequest,
        parsed_item: ParsedItem,
        *,
        trigger_kind: TriggerKind,
        revision_id: SourceRevisionId,
        representation_id: DiscoveryRepresentationId,
        first_observation: bool,
    ) -> DiscoveryOccurrenceRequest:
        receipt = admission.proposal.receipt
        if receipt is None:
            raise ProposalAdmissionConflict(
                "parsed source observation lacks an exact transport receipt"
            )
        kind = self._occurrence_kind(
            trigger_kind,
            first_observation=first_observation,
        )
        occurrence_id = deterministic_uuid4(
            DiscoveryOccurrenceId,
            namespace="increment-3c-discovery-occurrence-v1",
            semantic_value={
                "outcome_id": str(admission.outcome_id),
                "revision_id": str(revision_id),
                "representation_id": str(representation_id),
                "kind": kind.value,
            },
        )
        updated = _source_time(parsed_item, "source_updated_time")
        published = _source_time(parsed_item, "source_published_time")
        source_asserted_time = (
            updated
            if updated.precision is not TimePrecision.UNKNOWN
            else published
        )
        return DiscoveryOccurrenceRequest(
            occurrence_id=occurrence_id,
            check_outcome_id=admission.outcome_id,
            revision_id=revision_id,
            representation_id=representation_id,
            definition_version_id=(
                admission.adapter_request.source_definition_version_id
            ),
            kind=kind,
            observed_at=admission.completed_at,
            receipt_digest=receipt.digest,
            source_asserted_time=source_asserted_time,
            idempotency_key=f"proposal-occurrence:{occurrence_id}",
        )



__all__ = ["_ProposalAdmissionValidationMixin"]
