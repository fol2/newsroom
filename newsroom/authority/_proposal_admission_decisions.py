from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import AggregateId, TimePrecision
from newsroom.checks.admission_models import (
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
    deterministic_uuid4,
)
from newsroom.checks.baseline_models import (
    BaselineDecisionRequest,
    BaselineManifestEntry,
)
from newsroom.checks.policy import (
    CHECK_BASELINE_DECIDE_COMMAND,
    OBSERVABLE_TRANSITION_RECORD_COMMAND,
)
from newsroom.checks.transition_models import ObservableTransitionRequest
from newsroom.checks.transition_planning import (
    BaselineAction,
    TransitionDirective,
)
from newsroom.checks.types import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    BaselineEntryDisposition,
    ObservableTransitionId,
    ObservableTransitionKind,
    TransitionBasis,
    TriggerKind,
    is_agenda_transition,
    is_ending_transition,
)
from newsroom.discovery_adapters import ObservationProposalOutcome
from newsroom.sources import (
    BaselinePolicyKind,
    ObservationModel,
    SourceItemId,
    SourceTime,
)

from ._proposal_admission_models import (
    _AuthorizedDecisionPlan,
    _DecisionPlan,
    _ObservationPlan,
    _field_map,
    _source_time,
)


_COMPLETE_OUTCOMES = frozenset(
    {
        ObservationProposalOutcome.SUCCESS_EMPTY,
        ObservationProposalOutcome.SUCCESS_UNCHANGED,
        ObservationProposalOutcome.SUCCESS_CHANGED,
    }
)
_ENDING_KINDS = frozenset(
    {
        ObservableTransitionKind.RESOLVED_OR_CLEARED,
        ObservableTransitionKind.EXPIRED,
        ObservableTransitionKind.CANCELLED,
        ObservableTransitionKind.WITHDRAWN,
    }
)


class _ProposalAdmissionDecisionMixin:
    @staticmethod
    def _observation_records(observation: _ObservationPlan):
        item = (
            observation.item.request
            if observation.item is not None
            else observation.item_request
        )
        revision = (
            observation.revision.request
            if observation.revision is not None
            else observation.revision_request
        )
        representation = (
            observation.representation.request
            if observation.representation is not None
            else observation.representation_request
        )
        if item is None or revision is None or representation is None:
            raise ProposalAdmissionConflict(
                "observation plan lacks exact source lineage"
            )
        return item, revision, representation

    @staticmethod
    def _preferred_source_time(observation: _ObservationPlan) -> SourceTime:
        for field_name in (
            "agenda_time",
            "expected_time",
            "effective_time",
            "deadline",
            "source_published_time",
            "source_updated_time",
        ):
            selected = _source_time(observation.parsed_item, field_name)
            if selected.precision is not TimePrecision.UNKNOWN:
                return selected
        return SourceTime.unknown()

    @staticmethod
    def _source_time_datetime(value: SourceTime) -> datetime | None:
        if value.precision in {TimePrecision.EXACT, TimePrecision.APPROXIMATE}:
            if value.value is None:
                return None
            try:
                return datetime.fromisoformat(value.value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if value.precision is TimePrecision.DATE_ONLY and value.value is not None:
            try:
                selected = date.fromisoformat(value.value)
            except ValueError:
                return None
            return datetime.combine(selected, datetime.min.time(), tzinfo=UTC)
        return None

    def _baseline_manifest(
        self,
        admission: ProposalAdmissionRequest,
        observations: tuple[_ObservationPlan, ...],
        *,
        observation_model: ObservationModel,
        baseline_kind: BaselinePolicyKind,
        freshness_window_seconds: int | None,
        manual_hold: bool,
    ) -> tuple[BaselineManifestEntry, ...]:
        entries: list[BaselineManifestEntry] = []
        cutoff = (
            None
            if freshness_window_seconds is None
            else admission.completed_at.value
            - timedelta(seconds=freshness_window_seconds)
        )
        for observation in observations:
            item, revision, _ = self._observation_records(observation)
            disposition = BaselineEntryDisposition.INCLUDED
            reason = "INITIAL_INCLUDED"
            if manual_hold:
                disposition = BaselineEntryDisposition.EXCLUDED
                reason = "MANUAL_HOLD"
            elif baseline_kind is BaselinePolicyKind.MAINTAINED_DOCUMENT:
                reason = "INITIAL_MAINTAINED_STATE"
            elif baseline_kind is BaselinePolicyKind.BOUNDED_BACKFILL:
                asserted = self._preferred_source_time(observation)
                asserted_at = self._source_time_datetime(asserted)
                if asserted_at is None:
                    disposition = BaselineEntryDisposition.EXCLUDED
                    reason = "UNKNOWN_SOURCE_TIME"
                elif asserted_at > admission.completed_at.value:
                    disposition = BaselineEntryDisposition.EXCLUDED
                    reason = "FUTURE_SOURCE_TIME"
                elif cutoff is not None and asserted_at < cutoff:
                    disposition = BaselineEntryDisposition.EXCLUDED
                    reason = "OUTSIDE_BACKFILL_WINDOW"
                else:
                    reason = "WITHIN_BACKFILL_WINDOW"
            elif (
                baseline_kind
                is BaselinePolicyKind.COMPLETE_STATE_FIRST_OBSERVED_ACTIVE
            ):
                reason = "FIRST_OBSERVED_ACTIVE"
            elif baseline_kind is BaselinePolicyKind.PLANNED_AGENDA_FUTURE_ONLY:
                asserted = self._preferred_source_time(observation)
                asserted_at = self._source_time_datetime(asserted)
                if asserted_at is None:
                    disposition = BaselineEntryDisposition.EXCLUDED
                    reason = "UNKNOWN_EXPECTED_TIME"
                elif asserted_at < admission.completed_at.value:
                    disposition = BaselineEntryDisposition.EXCLUDED
                    reason = "PAST_EXPECTATION"
                else:
                    reason = "FUTURE_EXPECTATION"
            elif baseline_kind is BaselinePolicyKind.EXPLICIT_DELTA_SEQUENCE:
                reason = "EXPLICIT_DELTA_SEQUENCE_HEAD"
            elif baseline_kind is BaselinePolicyKind.MANUAL_ONLY:
                disposition = BaselineEntryDisposition.EXCLUDED
                reason = "MANUAL_HOLD"
            entries.append(
                BaselineManifestEntry(
                    item_key=observation.parsed_item.item_key,
                    disposition=disposition,
                    reason_code=reason,
                    item_id=item.item_id,
                    revision_id=revision.revision_id,
                )
            )
        return tuple(
            sorted(
                entries,
                key=lambda entry: (entry.item_key, entry.disposition.value),
            )
        )

    @staticmethod
    def _baseline_disposition(
        observation_model: ObservationModel,
        *,
        manual_hold: bool,
    ) -> BaselineDisposition:
        if manual_hold:
            return BaselineDisposition.MANUAL_HOLD
        return {
            ObservationModel.MUTABLE_ITEM: (
                BaselineDisposition.MAINTAINED_BASELINE_ONLY
            ),
            ObservationModel.APPEND_ONLY: BaselineDisposition.BOUNDED_BACKFILL,
            ObservationModel.ROLLING_LIST: BaselineDisposition.BOUNDED_BACKFILL,
            ObservationModel.COMPLETE_CURRENT_STATE: (
                BaselineDisposition.FIRST_OBSERVED_ACTIVE
            ),
            ObservationModel.PLANNED_AGENDA: (
                BaselineDisposition.FUTURE_EXPECTATIONS_ONLY
            ),
            ObservationModel.EXPLICIT_DELTA: (
                BaselineDisposition.EXPLICIT_DELTA_SEQUENCE
            ),
        }[observation_model]

    def _baseline_request(
        self,
        admission: ProposalAdmissionRequest,
        observations: tuple[_ObservationPlan, ...],
        *,
        source,
        retained_request,
        current,
    ) -> BaselineDecisionRequest | None:
        control = admission.baseline_control
        complete = admission.proposal.outcome in _COMPLETE_OUTCOMES
        same_outcome = (
            current is not None
            and current.request.check_outcome_id == admission.outcome_id
        )
        if control.action is not BaselineAction.MANUAL_HOLD and not complete:
            if same_outcome:
                raise ProposalAdmissionConflict(
                    "replayed baseline control differs from retained decision"
                )
            return None
        if control.action is BaselineAction.AUTO:
            if current is not None and not same_outcome:
                return None
            kind = BaselineDecisionKind.ESTABLISH
            previous = None
        elif control.action is BaselineAction.RESET:
            if retained_request.request.trigger.kind is not TriggerKind.RESET_REBUILD:
                raise ProposalAdmissionConflict(
                    "baseline reset requires RESET_REBUILD trigger"
                )
            expected_previous = (
                None
                if current is None
                else (
                    current.request.previous_decision_id
                    if same_outcome
                    else current.request.decision_id
                )
            )
            if (
                expected_previous is None
                or control.previous_decision_id != expected_previous
            ):
                raise ProposalAdmissionConflict(
                    "baseline reset does not name exact retained predecessor"
                )
            kind = BaselineDecisionKind.RESET
            previous = expected_previous
        elif control.action is BaselineAction.REBUILD:
            if retained_request.request.trigger.kind is not TriggerKind.RESET_REBUILD:
                raise ProposalAdmissionConflict(
                    "baseline rebuild requires RESET_REBUILD trigger"
                )
            expected_previous = (
                None
                if current is None
                else (
                    current.request.previous_decision_id
                    if same_outcome
                    else current.request.decision_id
                )
            )
            if (
                expected_previous is None
                or control.previous_decision_id != expected_previous
            ):
                raise ProposalAdmissionConflict(
                    "baseline rebuild does not name exact retained predecessor"
                )
            kind = BaselineDecisionKind.REBUILD
            previous = expected_previous
        else:
            if current is None:
                kind = BaselineDecisionKind.ESTABLISH
                previous = None
            elif same_outcome:
                kind = current.request.kind
                previous = current.request.previous_decision_id
                if (
                    control.previous_decision_id is not None
                    and control.previous_decision_id != previous
                ):
                    raise ProposalAdmissionConflict(
                        "manual hold does not name exact retained predecessor"
                    )
            else:
                if (
                    control.previous_decision_id is not None
                    and control.previous_decision_id
                    != current.request.decision_id
                ):
                    raise ProposalAdmissionConflict(
                        "manual hold does not name exact retained baseline"
                    )
                kind = BaselineDecisionKind.RESET
                previous = current.request.decision_id

        manual_hold = control.action is BaselineAction.MANUAL_HOLD
        entries = self._baseline_manifest(
            admission,
            observations,
            observation_model=source.observation_model,
            baseline_kind=source.baseline_policy.kind,
            freshness_window_seconds=(
                source.baseline_policy.freshness_window_seconds
            ),
            manual_hold=manual_hold,
        )
        disposition = self._baseline_disposition(
            source.observation_model,
            manual_hold=manual_hold,
        )
        included = tuple(
            entry
            for entry in entries
            if entry.disposition is BaselineEntryDisposition.INCLUDED
        )
        if (
            disposition is BaselineDisposition.MAINTAINED_BASELINE_ONLY
            and not included
        ):
            if control.action is BaselineAction.AUTO:
                return None
            raise ProposalAdmissionConflict(
                "maintained baseline action requires one logical item"
            )
        parser = admission.proposal.parser_result
        decision_id = deterministic_uuid4(
            BaselineDecisionId,
            namespace="increment-3c-model-baseline-v1",
            semantic_value={
                "definition_version_id": str(source.version_id),
                "check_outcome_id": str(admission.outcome_id),
                "kind": kind.value,
                "disposition": disposition.value,
                "previous_decision_id": (
                    None if previous is None else str(previous)
                ),
                "entries": [entry.canonical_value() for entry in entries],
                "policy": retained_request.request.baseline_policy.canonical_value(),
                "control": control.canonical_value(),
            },
        )
        reason_codes = tuple(
            sorted(
                set(
                    control.reason_codes
                    or (
                        f"{source.baseline_policy.kind.value}_BASELINE",
                    )
                )
            )
        )
        return BaselineDecisionRequest(
            decision_id=decision_id,
            definition_id=source.definition_id,
            definition_version_id=source.version_id,
            check_request_id=admission.check_request_id,
            check_outcome_id=admission.outcome_id,
            kind=kind,
            disposition=disposition,
            observation_model=source.observation_model,
            baseline_policy=retained_request.request.baseline_policy,
            previous_decision_id=previous,
            entries=entries,
            source_body_digest=(
                None if parser is None else parser.source_body_digest
            ),
            producer_slot_digest=(
                None if parser is None else parser.producer_slot_digest
            ),
            representation_digest=(
                None if parser is None else parser.representation_digest
            ),
            validator_digest=admission.validator_digest,
            reason_codes=reason_codes,
            decided_at=admission.completed_at,
            idempotency_key=f"proposal-baseline:{decision_id}",
        )

    def _item_id_for_key(
        self,
        admission: ProposalAdmissionRequest,
        item_key: str,
    ) -> SourceItemId:
        return deterministic_uuid4(
            SourceItemId,
            namespace="increment-3c-source-item-v1",
            semantic_value={
                "definition_id": str(
                    admission.adapter_request.source_definition_id
                ),
                "item_key": item_key,
            },
        )

    def _resolved_item_for_key(
        self,
        admission: ProposalAdmissionRequest,
        observations_by_key: dict[str, _ObservationPlan],
        item_key: str,
    ):
        observation = observations_by_key.get(item_key)
        if observation is not None:
            item, revision, representation = self._observation_records(observation)
            return observation, item, revision, representation
        item_id = self._item_id_for_key(admission, item_key)
        item = self._store.source_item(item_id)
        if item is None:
            raise ProposalAdmissionConflict(
                "transition directive item key does not resolve to source authority"
            )
        revision_record = self._store.latest_observed_source_revision(item_id)
        if revision_record is None:
            raise ProposalAdmissionConflict(
                "transition directive item has no observed Source Revision"
            )
        representation_record = self._store.latest_representation_for_revision(
            revision_record.request.revision_id
        )
        return (
            None,
            item.request,
            revision_record.request,
            None if representation_record is None else representation_record.request,
        )

    @staticmethod
    def _basis_for(
        observation_model: ObservationModel,
        directive: TransitionDirective,
    ) -> TransitionBasis:
        if is_agenda_transition(directive.kind):
            return TransitionBasis.AGENDA_EXPECTATION
        if directive.absence_guard is not None:
            return TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE
        if observation_model is ObservationModel.EXPLICIT_DELTA:
            return TransitionBasis.EXPLICIT_DELTA
        return TransitionBasis.REVISION

    @staticmethod
    def _validate_directive_model(
        observation_model: ObservationModel,
        directive: TransitionDirective,
        *,
        incomplete: bool,
        has_current_observation: bool,
    ) -> None:
        kind = directive.kind
        if observation_model is ObservationModel.PLANNED_AGENDA:
            if not is_agenda_transition(kind):
                raise ProposalAdmissionConflict(
                    "Planned Agenda source requires Agenda transition directive"
                )
        elif is_agenda_transition(kind):
            raise ProposalAdmissionConflict(
                "Agenda transition directive requires Planned Agenda source"
            )
        if directive.absence_guard is not None:
            if has_current_observation:
                raise ProposalAdmissionConflict(
                    "absence transition directive cannot target present item"
                )
            if observation_model in {
                ObservationModel.APPEND_ONLY,
                ObservationModel.ROLLING_LIST,
            }:
                if kind is not ObservableTransitionKind.AMBIGUOUS_ABSENCE:
                    raise ProposalAdmissionConflict(
                        "append-only or rolling disappearance remains ambiguous"
                    )
            elif observation_model is not ObservationModel.COMPLETE_CURRENT_STATE:
                raise ProposalAdmissionConflict(
                    "snapshot absence inference requires complete-current-state source"
                )
        if kind is ObservableTransitionKind.AGENDA_MISSED_EXPECTATION:
            if has_current_observation:
                raise ProposalAdmissionConflict(
                    "missed Agenda expectation cannot target present occurrence"
                )
        elif (
            not has_current_observation
            and directive.absence_guard is None
        ):
            raise ProposalAdmissionConflict(
                "non-absence transition directive requires current observation"
            )
        if incomplete and kind is not ObservableTransitionKind.AMBIGUOUS_ABSENCE:
            if is_ending_transition(kind) or kind is ObservableTransitionKind.AGENDA_MISSED_EXPECTATION:
                raise ProposalAdmissionConflict(
                    "incomplete Outcome cannot establish ending or clean Agenda miss"
                )
        if observation_model is ObservationModel.EXPLICIT_DELTA:
            if directive.absence_guard is not None:
                raise ProposalAdmissionConflict(
                    "explicit delta cannot infer state from absence"
                )

    def _directive_transition_request(
        self,
        admission: ProposalAdmissionRequest,
        directive: TransitionDirective,
        *,
        source,
        retained_request,
        observations_by_key: dict[str, _ObservationPlan],
    ) -> ObservableTransitionRequest:
        observation, item, current_revision, current_representation = (
            self._resolved_item_for_key(
                admission,
                observations_by_key,
                directive.item_key,
            )
        )
        has_current = observation is not None
        self._validate_directive_model(
            source.observation_model,
            directive,
            incomplete=admission.proposal.incomplete,
            has_current_observation=has_current,
        )
        kind = directive.kind
        prior_revision_id = None
        current_revision_id = None
        representation_id = None
        if has_current:
            assert observation is not None
            current_revision_id = current_revision.revision_id
            if current_representation is None:
                raise ProposalAdmissionConflict(
                    "current transition observation lacks Representation"
                )
            representation_id = current_representation.representation_id
            prior_record = observation.prior_revision
            if kind in {
                ObservableTransitionKind.FIRST_OBSERVED,
                ObservableTransitionKind.ACTIVATED,
                ObservableTransitionKind.AGENDA_CREATED,
            }:
                if observation.prior_item_occurrence_count != 0:
                    raise ProposalAdmissionConflict(
                        "first or activation directive targets previously observed item"
                    )
            elif kind is ObservableTransitionKind.REOBSERVED:
                prior_record = observation.prior_revision
                if (
                    prior_record is None
                    or prior_record.request.revision_id != current_revision_id
                    or observation.prior_revision_occurrence_count == 0
                ):
                    raise ProposalAdmissionConflict(
                        "re-observation directive requires previously observed exact Revision"
                    )
                prior_revision_id = current_revision_id
            else:
                if prior_record is None:
                    raise ProposalAdmissionConflict(
                        "state transition directive lacks prior observed Revision"
                    )
                prior_revision_id = prior_record.request.revision_id
                if prior_revision_id == current_revision_id:
                    raise ProposalAdmissionConflict(
                        "state transition directive requires distinct source state"
                    )
        else:
            prior_revision_id = current_revision.revision_id
            current_revision_id = None
            representation_id = None

        if kind is ObservableTransitionKind.REACTIVATED:
            latest = self._store.latest_observable_transition_for_item(item.item_id)
            if latest is None or latest.request.kind not in _ENDING_KINDS:
                raise ProposalAdmissionConflict(
                    "reactivation directive requires retained ending transition"
                )
        related_item_id = None
        if directive.related_item_key is not None:
            _, related, _, _ = self._resolved_item_for_key(
                admission,
                observations_by_key,
                directive.related_item_key,
            )
            related_item_id = related.item_id

        asserted = directive.source_asserted_time
        if (
            asserted.precision is TimePrecision.UNKNOWN
            and observation is not None
        ):
            asserted = observation.occurrence_request.source_asserted_time
            if asserted.precision is TimePrecision.UNKNOWN:
                asserted = current_revision.source_updated_time
        basis = self._basis_for(source.observation_model, directive)
        transition_id = deterministic_uuid4(
            ObservableTransitionId,
            namespace="increment-3c-classified-transition-v1",
            semantic_value={
                "definition_version_id": str(source.version_id),
                "check_outcome_id": str(admission.outcome_id),
                "item_id": str(item.item_id),
                "kind": kind.value,
                "basis": basis.value,
                "prior_revision_id": (
                    None if prior_revision_id is None else str(prior_revision_id)
                ),
                "current_revision_id": (
                    None if current_revision_id is None else str(current_revision_id)
                ),
                "representation_id": (
                    None if representation_id is None else str(representation_id)
                ),
                "related_item_id": (
                    None if related_item_id is None else str(related_item_id)
                ),
                "directive": directive.canonical_value(),
                "policy": retained_request.request.transition_policy.canonical_value(),
            },
        )
        return ObservableTransitionRequest(
            transition_id=transition_id,
            definition_id=source.definition_id,
            definition_version_id=source.version_id,
            check_outcome_id=admission.outcome_id,
            item_id=item.item_id,
            kind=kind,
            basis=basis,
            observation_model=source.observation_model,
            prior_revision_id=prior_revision_id,
            current_revision_id=current_revision_id,
            representation_id=representation_id,
            related_item_id=related_item_id,
            change_facets=directive.change_facets,
            transition_policy=retained_request.request.transition_policy,
            absence_guard=directive.absence_guard,
            agenda_guard=directive.agenda_guard,
            source_asserted_time=asserted,
            observed_at=admission.completed_at,
            transition_discriminator=directive.transition_discriminator,
            idempotency_key=f"proposal-transition:{transition_id}",
        )

    def _default_transition_request(
        self,
        admission: ProposalAdmissionRequest,
        observation: _ObservationPlan,
        *,
        source,
        retained_request,
    ) -> ObservableTransitionRequest | None:
        _, revision, representation = self._observation_records(observation)
        new_item = observation.prior_item_occurrence_count == 0
        new_revision = (
            observation.prior_revision is not None
            and observation.prior_revision.request.revision_id
            != revision.revision_id
        )
        if not new_item and not new_revision:
            return None
        if source.observation_model is ObservationModel.EXPLICIT_DELTA:
            raise ProposalAdmissionConflict(
                "explicit-delta source change requires typed transition directive"
            )
        if source.observation_model is ObservationModel.PLANNED_AGENDA:
            if new_item:
                kind = ObservableTransitionKind.AGENDA_CREATED
                basis = TransitionBasis.AGENDA_EXPECTATION
            else:
                raise ProposalAdmissionConflict(
                    "Agenda revision requires reschedule/cancel classification"
                )
        elif source.observation_model is ObservationModel.COMPLETE_CURRENT_STATE:
            kind = (
                ObservableTransitionKind.ACTIVATED
                if new_item
                else ObservableTransitionKind.REVISED
            )
            basis = TransitionBasis.REVISION
        elif source.observation_model is ObservationModel.MUTABLE_ITEM:
            if new_item:
                raise ProposalAdmissionConflict(
                    "maintained-document source changed logical item identity"
                )
            kind = ObservableTransitionKind.REVISED
            basis = TransitionBasis.REVISION
        else:
            kind = (
                ObservableTransitionKind.FIRST_OBSERVED
                if new_item
                else ObservableTransitionKind.REVISED
            )
            basis = TransitionBasis.REVISION
        prior_revision_id = (
            None
            if new_item
            else observation.prior_revision.request.revision_id
        )
        facets = () if new_item else ("PERMITTED_STATE_DIGEST",)
        transition_id = deterministic_uuid4(
            ObservableTransitionId,
            namespace="increment-3c-default-transition-v1",
            semantic_value={
                "definition_version_id": str(source.version_id),
                "check_outcome_id": str(admission.outcome_id),
                "item_id": str(revision.item_id),
                "kind": kind.value,
                "prior_revision_id": (
                    None if prior_revision_id is None else str(prior_revision_id)
                ),
                "current_revision_id": str(revision.revision_id),
                "representation_id": str(representation.representation_id),
                "policy": retained_request.request.transition_policy.canonical_value(),
            },
        )
        asserted = observation.occurrence_request.source_asserted_time
        if asserted.precision is TimePrecision.UNKNOWN:
            asserted = revision.source_updated_time
        return ObservableTransitionRequest(
            transition_id=transition_id,
            definition_id=source.definition_id,
            definition_version_id=source.version_id,
            check_outcome_id=admission.outcome_id,
            item_id=revision.item_id,
            kind=kind,
            basis=basis,
            observation_model=source.observation_model,
            prior_revision_id=prior_revision_id,
            current_revision_id=revision.revision_id,
            representation_id=representation.representation_id,
            related_item_id=None,
            change_facets=facets,
            transition_policy=retained_request.request.transition_policy,
            absence_guard=None,
            agenda_guard=None,
            source_asserted_time=asserted,
            observed_at=admission.completed_at,
            transition_discriminator=(
                "first-observed"
                if new_item
                else "revision-state-change"
            ),
            idempotency_key=f"proposal-transition:{transition_id}",
        )

    def _baseline_activation_requests(
        self,
        admission: ProposalAdmissionRequest,
        observations: tuple[_ObservationPlan, ...],
        baseline_request: BaselineDecisionRequest,
        *,
        source,
        retained_request,
    ) -> tuple[ObservableTransitionRequest, ...]:
        included = {
            entry.item_key
            for entry in baseline_request.entries
            if entry.disposition is BaselineEntryDisposition.INCLUDED
        }
        if baseline_request.kind is not BaselineDecisionKind.ESTABLISH:
            return ()
        if source.observation_model not in {
            ObservationModel.COMPLETE_CURRENT_STATE,
            ObservationModel.PLANNED_AGENDA,
        }:
            return ()
        kind = (
            ObservableTransitionKind.ACTIVATED
            if source.observation_model is ObservationModel.COMPLETE_CURRENT_STATE
            else ObservableTransitionKind.AGENDA_CREATED
        )
        basis = (
            TransitionBasis.REVISION
            if source.observation_model is ObservationModel.COMPLETE_CURRENT_STATE
            else TransitionBasis.AGENDA_EXPECTATION
        )
        results: list[ObservableTransitionRequest] = []
        for observation in observations:
            if observation.parsed_item.item_key not in included:
                continue
            item, revision, representation = self._observation_records(observation)
            transition_id = deterministic_uuid4(
                ObservableTransitionId,
                namespace="increment-3c-baseline-activation-v1",
                semantic_value={
                    "baseline_decision_id": str(baseline_request.decision_id),
                    "item_id": str(item.item_id),
                    "revision_id": str(revision.revision_id),
                    "kind": kind.value,
                    "policy": retained_request.request.transition_policy.canonical_value(),
                },
            )
            results.append(
                ObservableTransitionRequest(
                    transition_id=transition_id,
                    definition_id=source.definition_id,
                    definition_version_id=source.version_id,
                    check_outcome_id=admission.outcome_id,
                    item_id=item.item_id,
                    kind=kind,
                    basis=basis,
                    observation_model=source.observation_model,
                    prior_revision_id=None,
                    current_revision_id=revision.revision_id,
                    representation_id=representation.representation_id,
                    related_item_id=None,
                    change_facets=(),
                    transition_policy=retained_request.request.transition_policy,
                    absence_guard=None,
                    agenda_guard=None,
                    source_asserted_time=self._preferred_source_time(observation),
                    observed_at=admission.completed_at,
                    transition_discriminator=(
                        "first-observed-active"
                        if kind is ObservableTransitionKind.ACTIVATED
                        else "agenda-created"
                    ),
                    idempotency_key=f"proposal-transition:{transition_id}",
                )
            )
        return tuple(results)

    def _plan_decisions(
        self,
        admission: ProposalAdmissionRequest,
        observations: tuple[_ObservationPlan, ...],
        *,
        version,
        retained_request,
    ) -> _DecisionPlan:
        source = version.request
        current = self._store.current_baseline_decision(source.definition_id)
        baseline_request = self._baseline_request(
            admission,
            observations,
            source=source,
            retained_request=retained_request,
            current=current,
        )
        same_outcome_baseline = (
            current is not None
            and current.request.check_outcome_id == admission.outcome_id
        )
        baseline = current if same_outcome_baseline else None
        if baseline_request is not None:
            if same_outcome_baseline:
                assert current is not None
                if current.request.digest != baseline_request.digest:
                    raise ProposalAdmissionConflict(
                        "replayed baseline classification differs from retained decision"
                    )
                baseline = current
                baseline_request = None
            else:
                baseline = self._store.baseline_decision(
                    baseline_request.decision_id
                )
                if baseline is not None:
                    if baseline.request.digest != baseline_request.digest:
                        raise ProposalAdmissionConflict(
                            "retained baseline differs from exact admission"
                        )
                    baseline_request = None

        transitions: list = []
        transition_requests: list[ObservableTransitionRequest] = []
        observations_by_key = {
            observation.parsed_item.item_key: observation
            for observation in observations
        }
        reset_or_hold = admission.baseline_control.action in {
            BaselineAction.RESET,
            BaselineAction.REBUILD,
            BaselineAction.MANUAL_HOLD,
        }
        establishing = (
            same_outcome_baseline
            or (
                current is None
                and (baseline_request is not None or baseline is not None)
            )
        )
        if establishing:
            selected_baseline = (
                baseline.request if baseline is not None else baseline_request
            )
            assert selected_baseline is not None
            transition_requests.extend(
                self._baseline_activation_requests(
                    admission,
                    observations,
                    selected_baseline,
                    source=source,
                    retained_request=retained_request,
                )
            )
        elif not reset_or_hold and current is not None:
            directive_keys = {
                directive.item_key
                for directive in admission.transition_directives
            }
            for observation in observations:
                directive = admission.transition_directive_for(
                    observation.parsed_item.item_key
                )
                request = (
                    self._directive_transition_request(
                        admission,
                        directive,
                        source=source,
                        retained_request=retained_request,
                        observations_by_key=observations_by_key,
                    )
                    if directive is not None
                    else self._default_transition_request(
                        admission,
                        observation,
                        source=source,
                        retained_request=retained_request,
                    )
                )
                if request is not None:
                    transition_requests.append(request)
            for directive in admission.transition_directives:
                if directive.item_key in observations_by_key:
                    continue
                transition_requests.append(
                    self._directive_transition_request(
                        admission,
                        directive,
                        source=source,
                        retained_request=retained_request,
                        observations_by_key=observations_by_key,
                    )
                )
            if source.observation_model is ObservationModel.EXPLICIT_DELTA:
                changed_keys = {
                    observation.parsed_item.item_key
                    for observation in observations
                    if observation.prior_item_occurrence_count == 0
                    or (
                        observation.prior_revision is not None
                        and self._observation_records(observation)[1].revision_id
                        != observation.prior_revision.request.revision_id
                    )
                }
                if changed_keys - directive_keys:
                    raise ProposalAdmissionConflict(
                        "explicit-delta candidate lacks transition directive"
                    )

        unique_requests: dict[str, ObservableTransitionRequest] = {}
        for request in transition_requests:
            existing = self._store.observable_transition(request.transition_id)
            if existing is not None:
                if existing.request.digest != request.digest:
                    raise ProposalAdmissionConflict(
                        "retained transition differs from exact classification"
                    )
                transitions.append(existing)
                continue
            key = request.semantic_digest
            prior = unique_requests.get(key)
            if prior is not None and prior.digest != request.digest:
                raise ProposalAdmissionConflict(
                    "one admission produced conflicting transition semantics"
                )
            unique_requests[key] = request
        pending = tuple(
            sorted(
                unique_requests.values(),
                key=lambda item: str(item.transition_id),
            )
        )
        return _DecisionPlan(
            baseline=baseline,
            baseline_request=baseline_request,
            transitions=tuple(
                sorted(
                    transitions,
                    key=lambda item: str(item.request.transition_id),
                )
            ),
            transition_requests=pending,
        )

    def _authorize_decisions(
        self,
        plan: _DecisionPlan,
        proof: AuthenticationProof,
    ) -> _AuthorizedDecisionPlan:
        return _AuthorizedDecisionPlan(
            plan=plan,
            baseline_grant=(
                None
                if plan.baseline_request is None
                else self._authorize(
                    plan.baseline_request,
                    proof,
                    command_type=CHECK_BASELINE_DECIDE_COMMAND,
                    aggregate_id=AggregateId(
                        plan.baseline_request.decision_id.value
                    ),
                )
            ),
            transition_grants=tuple(
                self._authorize(
                    request,
                    proof,
                    command_type=OBSERVABLE_TRANSITION_RECORD_COMMAND,
                    aggregate_id=AggregateId(request.transition_id.value),
                )
                for request in plan.transition_requests
            ),
        )


__all__ = ["_ProposalAdmissionDecisionMixin"]
