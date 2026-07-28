from __future__ import annotations

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import digest_canonical
from newsroom.checks.baseline_models import BaselineDecisionRequest
from newsroom.checks.policy import (
    CHECK_BASELINE_DECIDE_COMMAND,
    OBSERVABLE_TRANSITION_RECORD_COMMAND,
)
from newsroom.checks.record_models import (
    BaselineDecision,
    ObservableTransition,
)
from newsroom.checks.transition_models import ObservableTransitionRequest
from newsroom.checks.types import (
    BaselineDecisionKind,
    BaselineDisposition,
    CheckIdentifierReuse,
    CheckSemanticCollision,
    CheckStateError,
    CheckVersionConflict,
    ObservableTransitionKind,
)


class _CheckStoreCommitDecisionMixin:
    def commit_baseline_decision(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: BaselineDecisionRequest,
    ) -> BaselineDecision:
        if not isinstance(request, BaselineDecisionRequest):
            raise TypeError("Baseline Decision commit requires a typed request")
        self._require_check_grant(
            grant,
            command_type=CHECK_BASELINE_DECIDE_COMMAND,
            aggregate_id=str(request.decision_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn,
                    grant,
                    recorded_at=self._clock().to_text(),
                )
                return self._baseline_decision_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            version = self._require_current_version(
                conn,
                definition_id=request.definition_id,
                version_id=request.definition_version_id,
            )
            parent = self._check_request_row(
                conn,
                str(request.check_request_id),
            )
            outcome = self._check_outcome_row(
                conn,
                str(request.check_outcome_id),
            )
            if (
                str(parent["definition_id"]) != str(request.definition_id)
                or str(parent["definition_version_id"])
                != str(request.definition_version_id)
                or str(outcome["request_id"])
                != str(request.check_request_id)
                or str(outcome["definition_id"])
                != str(request.definition_id)
                or str(outcome["definition_version_id"])
                != str(request.definition_version_id)
                or str(outcome["completed_at"])
                != request.decided_at.to_text()
                or str(version["observation_model"])
                != request.observation_model.value
                or str(version["baseline_policy_id"])
                != request.baseline_policy.policy_id
                or str(version["baseline_policy_version"])
                != request.baseline_policy.policy_version
                or str(parent["baseline_policy_id"])
                != request.baseline_policy.policy_id
                or str(parent["baseline_policy_version"])
                != request.baseline_policy.policy_version
            ):
                raise CheckVersionConflict(
                    "Baseline Decision differs from exact source and Check lineage"
                )
            if request.disposition is not BaselineDisposition.MANUAL_HOLD:
                if (
                    bool(outcome["incomplete"])
                    or str(outcome["kind"])
                    not in {
                        "SUCCESS_EMPTY",
                        "SUCCESS_UNCHANGED",
                        "SUCCESS_CHANGED",
                    }
                    or outcome["source_body_digest"]
                    != request.source_body_digest
                    or outcome["producer_slot_digest"]
                    != request.producer_slot_digest
                    or outcome["representation_digest"]
                    != request.representation_digest
                    or outcome["validator_digest"]
                    != request.validator_digest
                ):
                    raise CheckVersionConflict(
                        "Baseline Decision does not consume exact complete Outcome"
                    )
            evidence_error = self._baseline_evidence_error(conn, request)
            if evidence_error is not None:
                raise CheckVersionConflict(evidence_error)
            head = conn.execute(
                "SELECT current_decision_id FROM baseline_decision_heads "
                "WHERE definition_id=?",
                (str(request.definition_id),),
            ).fetchone()
            current = None if head is None else str(head["current_decision_id"])
            expected = (
                None
                if request.previous_decision_id is None
                else str(request.previous_decision_id)
            )
            if request.kind is BaselineDecisionKind.ESTABLISH:
                if current is not None or expected is not None:
                    raise CheckVersionConflict(
                        "baseline establishment cannot replace retained head"
                    )
            elif current is None or current != expected:
                raise CheckVersionConflict(
                    "baseline reset or rebuild does not extend exact head"
                )
            self._check_identifier_absent(
                conn,
                table="baseline_decisions",
                column="decision_id",
                identifier=str(request.decision_id),
                identity="Baseline Decision identity",
            )
            self._check_semantic_absent(
                conn,
                table="baseline_decisions",
                semantic_digest=request.semantic_digest,
                identity="Baseline Decision semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=recorded_at,
            )
            if committed.replayed:
                return self._baseline_decision_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            conn.execute(
                "INSERT INTO baseline_decisions("
                "decision_id,definition_id,definition_version_id,"
                "check_request_id,check_outcome_id,kind,disposition,"
                "observation_model,baseline_policy_id,"
                "baseline_policy_version,previous_decision_id,"
                "source_body_digest,producer_slot_digest,"
                "representation_digest,validator_digest,reason_codes_bytes,"
                "item_keys_digest,decided_at,semantic_digest,"
                "authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.decision_id),
                    str(request.definition_id),
                    str(request.definition_version_id),
                    str(request.check_request_id),
                    str(request.check_outcome_id),
                    request.kind.value,
                    request.disposition.value,
                    request.observation_model.value,
                    request.baseline_policy.policy_id,
                    request.baseline_policy.policy_version,
                    expected,
                    request.source_body_digest,
                    request.producer_slot_digest,
                    request.representation_digest,
                    request.validator_digest,
                    self._json_blob(list(request.reason_codes)),
                    request.item_keys_digest,
                    request.decided_at.to_text(),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            for entry in request.entries:
                canonical = entry.canonical_value()
                conn.execute(
                    "INSERT INTO baseline_manifest_entries("
                    "decision_id,item_key,disposition,reason_code,item_id,"
                    "revision_id,canonical_bytes,canonical_digest) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        str(request.decision_id),
                        entry.item_key,
                        entry.disposition.value,
                        entry.reason_code,
                        None if entry.item_id is None else str(entry.item_id),
                        (
                            None
                            if entry.revision_id is None
                            else str(entry.revision_id)
                        ),
                        self._json_blob(canonical),
                        digest_canonical(canonical),
                    ),
                )
            return self._baseline_decision_for_event(
                conn,
                committed.event_id,
                replayed=False,
            )

    def commit_observable_transition(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ObservableTransitionRequest,
    ) -> ObservableTransition:
        if not isinstance(request, ObservableTransitionRequest):
            raise TypeError(
                "Observable Transition commit requires a typed request"
            )
        self._require_check_grant(
            grant,
            command_type=OBSERVABLE_TRANSITION_RECORD_COMMAND,
            aggregate_id=str(request.transition_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn,
                    grant,
                    recorded_at=self._clock().to_text(),
                )
                return self._observable_transition_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            version = self._require_current_version(
                conn,
                definition_id=request.definition_id,
                version_id=request.definition_version_id,
            )
            outcome = self._check_outcome_row(
                conn,
                str(request.check_outcome_id),
            )
            parent = self._check_request_row(
                conn,
                str(outcome["request_id"]),
            )
            item = self._item_row(conn, str(request.item_id))
            if (
                str(version["observation_model"])
                != request.observation_model.value
                or str(outcome["definition_id"])
                != str(request.definition_id)
                or str(outcome["definition_version_id"])
                != str(request.definition_version_id)
                or str(item["definition_id"]) != str(request.definition_id)
                or str(parent["transition_policy_id"])
                != request.transition_policy.policy_id
                or str(parent["transition_policy_version"])
                != request.transition_policy.policy_version
            ):
                raise CheckVersionConflict(
                    "Observable Transition differs from exact Check or source contract"
                )
            if (
                bool(outcome["incomplete"])
                and request.kind
                is not ObservableTransitionKind.AMBIGUOUS_ABSENCE
                and request.current_revision_id is None
            ):
                raise CheckVersionConflict(
                    "incomplete Outcome cannot infer state without a current Revision"
                )
            if request.prior_revision_id is not None:
                prior = self._revision_row(
                    conn,
                    str(request.prior_revision_id),
                )
                if str(prior["item_id"]) != str(request.item_id):
                    raise CheckStateError(
                        "prior Revision belongs to another Source Item"
                    )
            if request.current_revision_id is not None:
                current = self._revision_row(
                    conn,
                    str(request.current_revision_id),
                )
                if str(current["item_id"]) != str(request.item_id):
                    raise CheckStateError(
                        "current Revision belongs to another Source Item"
                    )
                representation = self._representation_row(
                    conn,
                    str(request.representation_id),
                )
                if (
                    str(representation["revision_id"])
                    != str(request.current_revision_id)
                ):
                    raise CheckStateError(
                        "Transition Representation differs from current Revision"
                    )
            if request.related_item_id is not None:
                related = self._item_row(conn, str(request.related_item_id))
                if str(related["definition_id"]) != str(request.definition_id):
                    raise CheckStateError(
                        "related Source Item belongs to another definition"
                    )
            evidence_error = self._transition_evidence_error(conn, request)
            if evidence_error is not None:
                raise CheckVersionConflict(evidence_error)
            classified = conn.execute(
                "SELECT transition_id,semantic_digest "
                "FROM observable_transitions "
                "WHERE check_outcome_id=? AND item_id=?",
                (str(request.check_outcome_id), str(request.item_id)),
            ).fetchone()
            if classified is not None:
                raise CheckSemanticCollision(
                    "one Check Outcome cannot classify two transitions for one item"
                )
            self._check_identifier_absent(
                conn,
                table="observable_transitions",
                column="transition_id",
                identifier=str(request.transition_id),
                identity="Observable Transition identity",
            )
            self._check_semantic_absent(
                conn,
                table="observable_transitions",
                semantic_digest=request.semantic_digest,
                identity="Observable Transition semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=recorded_at,
            )
            if committed.replayed:
                return self._observable_transition_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            conn.execute(
                "INSERT INTO observable_transitions("
                "transition_id,definition_id,definition_version_id,"
                "check_outcome_id,item_id,kind,basis,observation_model,"
                "prior_revision_id,current_revision_id,representation_id,"
                "related_item_id,change_facets_bytes,transition_policy_id,"
                "transition_policy_version,absence_guard_bytes,"
                "agenda_guard_bytes,source_asserted_time_bytes,observed_at,"
                "transition_discriminator,semantic_digest,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.transition_id),
                    str(request.definition_id),
                    str(request.definition_version_id),
                    str(request.check_outcome_id),
                    str(request.item_id),
                    request.kind.value,
                    request.basis.value,
                    request.observation_model.value,
                    (
                        None
                        if request.prior_revision_id is None
                        else str(request.prior_revision_id)
                    ),
                    (
                        None
                        if request.current_revision_id is None
                        else str(request.current_revision_id)
                    ),
                    (
                        None
                        if request.representation_id is None
                        else str(request.representation_id)
                    ),
                    (
                        None
                        if request.related_item_id is None
                        else str(request.related_item_id)
                    ),
                    self._json_blob(list(request.change_facets)),
                    request.transition_policy.policy_id,
                    request.transition_policy.policy_version,
                    (
                        None
                        if request.absence_guard is None
                        else self._json_blob(
                            request.absence_guard.canonical_value()
                        )
                    ),
                    (
                        None
                        if request.agenda_guard is None
                        else self._json_blob(
                            request.agenda_guard.canonical_value()
                        )
                    ),
                    self._json_blob(
                        request.source_asserted_time.canonical_value()
                    ),
                    request.observed_at.to_text(),
                    request.transition_discriminator,
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._observable_transition_for_event(
                conn,
                committed.event_id,
                replayed=False,
            )


__all__ = ["_CheckStoreCommitDecisionMixin"]
