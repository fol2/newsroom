from __future__ import annotations

import sqlite3
from typing import Any, Callable, TypeVar

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import AggregateId
from newsroom.checks.admission_models import (
    AdmissionRecordState,
    AdmittedSourceObservation,
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
    ProposalAdmissionResult,
)
from newsroom.checks.policy import CHECK_OUTCOME_RECORD_COMMAND
from newsroom.checks.types import (
    CheckIdentifierReuse,
    CheckSemanticCollision,
    CheckStateError,
)
from newsroom.sources import (
    SourceIdentifierReuse,
    SourceSemanticCollision,
    SourceStateError,
)

from ._proposal_admission_models import (
    _AuthorizedDecisionPlan,
    _AuthorizedFindingPlan,
    _AuthorizedPlan,
)


_Record = TypeVar("_Record")


class _ProposalAdmissionCommitMixin:
    @staticmethod
    def _committed_state(record: Any) -> AdmissionRecordState:
        return (
            AdmissionRecordState.REPLAYED
            if record.replayed
            else AdmissionRecordState.CREATED
        )

    def _commit_or_reload(
        self,
        *,
        request: Any,
        grant: _AuthorizedCommandGrant,
        commit: Callable[..., _Record],
        reload: Callable[[], _Record | None],
        identity: str,
    ) -> tuple[_Record, AdmissionRecordState]:
        try:
            record = commit(grant, request=request)
            return record, self._committed_state(record)
        except (
            SourceIdentifierReuse,
            SourceSemanticCollision,
            SourceStateError,
            sqlite3.IntegrityError,
        ) as exc:
            existing = reload()
            if existing is None:
                raise ProposalAdmissionConflict(
                    f"{identity} conflicted and cannot be resolved"
                ) from exc
            return existing, AdmissionRecordState.REUSED

    def _commit_plan(
        self,
        authorized: _AuthorizedPlan,
    ) -> AdmittedSourceObservation:
        plan = authorized.plan
        if plan.item is not None:
            item = plan.item
            item_state = AdmissionRecordState.REUSED
        else:
            assert plan.item_request is not None
            assert authorized.item_grant is not None
            item, item_state = self._commit_or_reload(
                request=plan.item_request,
                grant=authorized.item_grant,
                commit=self._store.commit_source_item,
                reload=lambda: self._store.source_item_by_identity_digest(
                    plan.item_request.definition_id,
                    plan.item_request.identity_digest,
                ),
                identity="Source Item",
            )
            if (
                item.request.item_id != plan.item_request.item_id
                or item.request.identity_digest
                != plan.item_request.identity_digest
                or item.request.identity_policy
                != plan.item_request.identity_policy
            ):
                raise ProposalAdmissionConflict(
                    "concurrent Source Item resolution changed exact identity"
                )

        if plan.revision is not None:
            revision = plan.revision
            revision_state = AdmissionRecordState.REUSED
        else:
            assert plan.revision_request is not None
            assert authorized.revision_grant is not None
            revision, revision_state = self._commit_or_reload(
                request=plan.revision_request,
                grant=authorized.revision_grant,
                commit=self._store.commit_source_revision,
                reload=lambda: self._store.source_revision_by_identity_digest(
                    item.request.item_id,
                    plan.revision_request.revision_identity_digest,
                ),
                identity="Source Revision",
            )
            if (
                revision.request.revision_id
                != plan.revision_request.revision_id
                or revision.request.revision_identity_digest
                != plan.revision_request.revision_identity_digest
            ):
                raise ProposalAdmissionConflict(
                    "concurrent Revision resolution changed exact source state"
                )

        if plan.representation is not None:
            representation = plan.representation
            representation_state = AdmissionRecordState.REUSED
        else:
            assert plan.representation_request is not None
            assert authorized.representation_grant is not None
            representation, representation_state = self._commit_or_reload(
                request=plan.representation_request,
                grant=authorized.representation_grant,
                commit=self._store.commit_discovery_representation,
                reload=lambda: self._store.representation_by_producer_slot(
                    revision.request.revision_id,
                    plan.representation_request.producer_slot_digest,
                ),
                identity="Discovery Representation",
            )
            if (
                representation.request.representation_id
                != plan.representation_request.representation_id
                or representation.request.producer_slot_digest
                != plan.representation_request.producer_slot_digest
                or representation.request.representation_digest
                != plan.representation_request.representation_digest
            ):
                raise ProposalAdmissionConflict(
                    "concurrent Representation resolution changed exact output"
                )

        if plan.occurrence is not None:
            occurrence = plan.occurrence
            occurrence_state = AdmissionRecordState.REPLAYED
        else:
            assert authorized.occurrence_grant is not None
            occurrence, occurrence_state = self._commit_or_reload(
                request=plan.occurrence_request,
                grant=authorized.occurrence_grant,
                commit=self._store.commit_discovery_occurrence,
                reload=lambda: self._store.discovery_occurrence_by_identity(
                    plan.occurrence_request.occurrence_id
                ),
                identity="Discovery Occurrence",
            )
            if (
                occurrence.request.occurrence_id
                != plan.occurrence_request.occurrence_id
                or occurrence.request.semantic_digest
                != plan.occurrence_request.semantic_digest
            ):
                raise ProposalAdmissionConflict(
                    "concurrent Occurrence resolution changed exact observation"
                )

        return AdmittedSourceObservation(
            item_key=plan.parsed_item.item_key,
            item=item,
            revision=revision,
            representation=representation,
            occurrence=occurrence,
            item_state=item_state,
            revision_state=revision_state,
            representation_state=representation_state,
            occurrence_state=occurrence_state,
        )

    def _commit_finding(
        self,
        authorized: _AuthorizedFindingPlan,
    ):
        plan = authorized.plan
        finding = plan.finding
        if plan.finding_request is not None:
            assert authorized.finding_grant is not None
            try:
                finding = self._store.commit_operational_finding(
                    authorized.finding_grant,
                    request=plan.finding_request,
                )
            except (
                CheckIdentifierReuse,
                CheckSemanticCollision,
                CheckStateError,
                sqlite3.IntegrityError,
            ) as exc:
                finding = self._store.operational_finding(
                    plan.finding_request.finding_id
                )
                if (
                    finding is None
                    or finding.request.semantic_digest
                    != plan.finding_request.semantic_digest
                ):
                    raise ProposalAdmissionConflict(
                        "Operational Finding conflicted with retained authority"
                    ) from exc

        occurrence = plan.occurrence
        if plan.occurrence_request is not None:
            assert authorized.occurrence_grant is not None
            try:
                occurrence = self._store.commit_operational_finding_occurrence(
                    authorized.occurrence_grant,
                    request=plan.occurrence_request,
                )
            except (
                CheckIdentifierReuse,
                CheckSemanticCollision,
                CheckStateError,
                sqlite3.IntegrityError,
            ) as exc:
                occurrence = self._store.finding_occurrence_by_identity(
                    plan.occurrence_request.occurrence_id
                )
                if (
                    occurrence is None
                    or occurrence.request.digest
                    != plan.occurrence_request.digest
                ):
                    raise ProposalAdmissionConflict(
                        "Finding occurrence conflicted with retained authority"
                    ) from exc
        findings = () if finding is None else (finding,)
        occurrences = () if occurrence is None else (occurrence,)
        return findings, occurrences

    def _commit_decisions(
        self,
        authorized: _AuthorizedDecisionPlan,
    ):
        plan = authorized.plan
        baseline = plan.baseline
        if plan.baseline_request is not None:
            assert authorized.baseline_grant is not None
            try:
                baseline = self._store.commit_baseline_decision(
                    authorized.baseline_grant,
                    request=plan.baseline_request,
                )
            except (
                CheckIdentifierReuse,
                CheckSemanticCollision,
                CheckStateError,
                sqlite3.IntegrityError,
            ) as exc:
                baseline = self._store.baseline_decision(
                    plan.baseline_request.decision_id
                )
                if (
                    baseline is None
                    or baseline.request.digest
                    != plan.baseline_request.digest
                ):
                    raise ProposalAdmissionConflict(
                        "Baseline Decision conflicted with retained authority"
                    ) from exc

        transitions = list(plan.transitions)
        for request, grant in zip(
            plan.transition_requests,
            authorized.transition_grants,
            strict=True,
        ):
            try:
                transition = self._store.commit_observable_transition(
                    grant,
                    request=request,
                )
            except (
                CheckIdentifierReuse,
                CheckSemanticCollision,
                CheckStateError,
                sqlite3.IntegrityError,
            ) as exc:
                transition = self._store.observable_transition(
                    request.transition_id
                )
                if (
                    transition is None
                    or transition.request.digest != request.digest
                ):
                    raise ProposalAdmissionConflict(
                        "Observable Transition conflicted with retained authority"
                    ) from exc
            transitions.append(transition)
        return baseline, tuple(
            sorted(
                transitions,
                key=lambda item: str(item.request.transition_id),
            )
        )

    def _commit_outcome(
        self,
        request,
        grant: _AuthorizedCommandGrant,
    ):
        try:
            return self._store.commit_check_outcome(
                grant,
                request=request,
            )
        except (
            CheckIdentifierReuse,
            CheckSemanticCollision,
            CheckStateError,
            sqlite3.IntegrityError,
        ) as exc:
            existing = self._store.check_outcome(request.outcome_id)
            if (
                existing is None
                or existing.request.digest != request.digest
            ):
                raise ProposalAdmissionConflict(
                    "Check Outcome conflicted with different retained authority"
                ) from exc
            return existing

    def admit(
        self,
        request: ProposalAdmissionRequest,
        proof: AuthenticationProof,
    ) -> ProposalAdmissionResult:
        if not isinstance(request, ProposalAdmissionRequest):
            raise TypeError("proposal admission requires a typed request")
        outcome_request = request.outcome_request()
        outcome_grant = self._authorize(
            outcome_request,
            proof,
            command_type=CHECK_OUTCOME_RECORD_COMMAND,
            aggregate_id=AggregateId(outcome_request.outcome_id.value),
        )
        retained_request = self._store.check_request(
            request.check_request_id
        )
        retained_attempt = self._store.check_attempt(
            request.check_attempt_id
        )
        if retained_request is None or retained_attempt is None:
            raise ProposalAdmissionConflict(
                "proposal admission requires retained Check Request and Attempt"
            )
        version = self._store.source_definition_version(
            request.adapter_request.source_definition_version_id
        )
        current_version = self._store.current_source_definition_version(
            request.adapter_request.source_definition_id
        )
        if (
            version is None
            or current_version is None
            or current_version.request.version_id != version.request.version_id
        ):
            raise ProposalAdmissionConflict(
                "proposal admission requires the exact current source version"
            )
        self._validate_adapter_contract(
            request,
            version,
            retained_request=retained_request,
            retained_attempt=retained_attempt,
        )
        plans = tuple(
            self._plan_observation(
                request,
                version,
                item,
                trigger_kind=retained_request.request.trigger.kind,
            )
            for item in request.parsed_items
        )
        authorized = tuple(
            self._authorize_plan(plan, proof)
            for plan in plans
        )
        decision_plan = self._plan_decisions(
            request,
            plans,
            version=version,
            retained_request=retained_request,
        )
        authorized_decisions = self._authorize_decisions(
            decision_plan,
            proof,
        )
        finding_plan = self._plan_finding(request)
        authorized_finding = self._authorize_finding(
            finding_plan,
            proof,
        )
        outcome = self._commit_outcome(
            outcome_request,
            outcome_grant,
        )
        observations = tuple(
            sorted(
                (
                    self._commit_plan(plan)
                    for plan in authorized
                ),
                key=lambda item: item.item_key,
            )
        )
        baseline, transitions = self._commit_decisions(
            authorized_decisions
        )
        findings, finding_occurrences = self._commit_finding(
            authorized_finding
        )
        return ProposalAdmissionResult(
            request=request,
            outcome=outcome,
            observations=observations,
            baseline=baseline,
            transitions=transitions,
            findings=findings,
            finding_occurrences=finding_occurrences,
        )


__all__ = ["_ProposalAdmissionCommitMixin"]
