from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment6.candidates import StoryCandidateVersion
from newsroom.increment6.feedback import (
    EVALUATION_FEEDBACK,
    EvaluationFeedback,
    EvaluationFeedbackOutcome,
    EvaluationFeedbackReason,
    FeedbackContractError,
    FeedbackCorrelationOutcome,
    RECONCILIATION_DISPOSITION,
    RECONCILIATION_OBLIGATION,
    ReconciliationDisposition,
    ReconciliationDispositionOutcome,
    ReconciliationDispositionReason,
    ReconciliationObligation,
    ReconciliationObligationKind,
    append_reconciliation_disposition,
    correlate_evaluation_feedback,
    create_evaluation_feedback,
    create_reconciliation_obligation,
    reconciliation_is_open,
    validate_reconciliation_history,
)
from newsroom.increment6.handoffs import (
    Acknowledgement,
    AcknowledgementOutcome,
    HandoffState,
    correlate_acknowledgement,
    create_handoff,
    mark_attempt_ambiguous,
    mark_attempt_sent,
    persist_attempt,
    request_retry,
)
from newsroom.increment6.work_items import (
    SupplementalDiscoveryReentry,
    SupplementalLineageBinding,
)
from newsroom.tests.test_increment6e2_candidates import _eligible_current, _manifest


D = "sha256:" + "1" * 64
DETAIL = "sha256:" + "2" * 64
ACTOR = "sha256:" + "3" * 64
SINK = "evaluation-sink:feedback-contract"


def _candidate_version(tmp_path) -> StoryCandidateVersion:
    candidate_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    collision_path = tmp_path / "collision"
    collision_path.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(_eligible_current(collision_path, candidate_id))
    return StoryCandidateVersion(
        version_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate_id=candidate_id,
        ordinal=1,
        previous_version_id=None,
        previous_version_digest=None,
        committed_admission_decision_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        governing_manifest=manifest,
    )


def _acknowledged_handoff(version: StoryCandidateVersion):
    handoff = create_handoff(
        version.version_id,
        version.governing_manifest.canonical_digest,
        SINK,
    )
    handoff = persist_attempt(handoff)
    attempt = handoff.attempts[0]
    handoff = mark_attempt_sent(handoff, attempt.attempt_id)
    acknowledgement = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=attempt.attempt_id,
        candidate_version_id=version.version_id,
        governing_manifest_digest=version.governing_manifest.canonical_digest,
        sink_id=SINK,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "4" * 64,
    )
    return correlate_acknowledgement(handoff, acknowledgement), attempt, acknowledgement


def _feedback(tmp_path, **overrides):
    version = _candidate_version(tmp_path)
    handoff, attempt, acknowledgement = _acknowledged_handoff(version)
    values = {
        "handoff": handoff,
        "attempt": attempt,
        "acknowledgement": acknowledgement,
        "candidate_version": version,
        "source_feedback_id": "evaluation-feedback:fixture-001",
        "outcome": EvaluationFeedbackOutcome.ACCEPTED,
        "reason": EvaluationFeedbackReason.INTAKE_ACCEPTED,
        "detail_digest": DETAIL,
        "request_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "actor_identity_digest": ACTOR,
        "idempotency_key": "feedback-request:fixture-001",
    }
    values.update(overrides)
    return create_evaluation_feedback(**values), handoff, version


def _obligation(tmp_path, **feedback_overrides):
    feedback, _, _ = _feedback(tmp_path, **feedback_overrides)
    return create_reconciliation_obligation(
        feedback,
        request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        actor_identity_digest=ACTOR,
        idempotency_key="obligation-request:fixture-001",
    )


def _supplemental_reentry() -> SupplementalDiscoveryReentry:
    ids = tuple(f"{index:08x}-0000-4000-8000-000000000000" for index in range(1, 15))
    trigger = "evaluation-feedback:bounded-public-source-check"
    chain_ids = (trigger, *ids[4:10])
    kinds = (
        "TRIGGER",
        "CHECK_REQUEST",
        "CHECK_OUTCOME",
        "SIGNAL",
        "GATE",
        "LEAD",
        "QUEUED_DISPOSITION",
    )
    bindings = tuple(
        SupplementalLineageBinding(
            kind,
            identifier,
            digest_bytes(canonical_json_bytes({"kind": kind, "id": identifier})),
            None if index == 0 else chain_ids[index - 1],
            None if index == 0 else ids[index + 7],
            None if index == 0 else 1,
        )
        for index, (kind, identifier) in enumerate(zip(kinds, chain_ids, strict=True))
    )
    return SupplementalDiscoveryReentry(
        source_work_item_id=ids[0],
        source_version_id=ids[1],
        source_version_digest=D,
        source_lead_disposition_id=ids[2],
        source_lead_disposition_digest="sha256:" + "5" * 64,
        source_lead_disposition_event_id=ids[3],
        source_lead_disposition_aggregate_version=1,
        source_lead_disposition_outcome="LEAD_SUPPLEMENTAL_DISCOVERY",
        source_approval_route="REQUEST_SUPPLEMENTAL_DISCOVERY",
        trigger_id=trigger,
        check_request_id=ids[4],
        check_outcome_id=ids[5],
        signal_id=ids[6],
        gate_decision_id=ids[7],
        lead_id=ids[8],
        queued_disposition_id=ids[9],
        target_work_item_id=ids[10],
        target_version_id=ids[11],
        lineage_bindings=bindings,
    )


def test_feedback_contract_names_are_exact() -> None:
    assert EVALUATION_FEEDBACK == "newsroom.increment6.evaluation-feedback.v1"
    assert (
        RECONCILIATION_OBLIGATION == "newsroom.increment6.reconciliation-obligation.v1"
    )
    assert (
        RECONCILIATION_DISPOSITION
        == "newsroom.increment6.reconciliation-disposition.v1"
    )


def test_exact_acknowledged_candidate_feedback_is_canonical_and_effect_free(
    tmp_path,
) -> None:
    feedback, handoff, version = _feedback(tmp_path)

    assert feedback.feedback_id.startswith("feedback:sha256:")
    assert feedback.handoff_id == handoff.handoff_id
    assert feedback.candidate_version_id == version.version_id
    assert feedback.candidate_version_digest == version.canonical_digest
    assert feedback.governing_manifest_digest == handoff.governing_manifest_digest
    assert EvaluationFeedback.from_canonical_bytes(feedback.canonical_bytes) == feedback
    assert feedback.canonical_digest == digest_bytes(feedback.canonical_bytes)
    assert feedback.evaluation_only is True
    assert feedback.publication_authority is False
    assert feedback.evidence_authority is False
    assert feedback.candidate_authority is False
    with pytest.raises(FrozenInstanceError):
        feedback.reason = EvaluationFeedbackReason.RIGHTS_BLOCK  # type: ignore[misc]


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (EvaluationFeedbackOutcome.ACCEPTED, EvaluationFeedbackReason.RIGHTS_BLOCK),
        (
            EvaluationFeedbackOutcome.REJECTED,
            EvaluationFeedbackReason.INSUFFICIENT_PUBLIC_EVIDENCE,
        ),
        (
            EvaluationFeedbackOutcome.INCONCLUSIVE,
            EvaluationFeedbackReason.CANDIDATE_CLOSED,
        ),
    ],
)
def test_feedback_outcome_reason_matrix_is_closed(tmp_path, outcome, reason) -> None:
    base, _, _ = _feedback(tmp_path)
    with pytest.raises(FeedbackContractError, match="outcome and reason"):
        replace(base, outcome=outcome, reason=reason)

    with pytest.raises(FeedbackContractError, match="duplicate or merged"):
        replace(
            base,
            outcome=EvaluationFeedbackOutcome.REJECTED,
            reason=EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE,
        )
    duplicate = replace(
        base,
        outcome=EvaluationFeedbackOutcome.REJECTED,
        reason=EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE,
        duplicate_or_merged_candidate_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
    )
    assert duplicate.duplicate_or_merged_candidate_id is not None


def test_duplicate_delayed_out_of_order_and_ambiguous_feedback_are_deterministic(
    tmp_path,
) -> None:
    feedback, handoff, version = _feedback(tmp_path)
    assert (
        correlate_evaluation_feedback(handoff, version, feedback, ())
        is FeedbackCorrelationOutcome.READY
    )
    assert (
        correlate_evaluation_feedback(handoff, version, feedback, (feedback,))
        is FeedbackCorrelationOutcome.EXACT_REPLAY
    )
    divergent = replace(feedback, detail_digest="sha256:" + "9" * 64)
    assert (
        correlate_evaluation_feedback(handoff, version, divergent, (feedback,))
        is FeedbackCorrelationOutcome.BINDING_CONFLICT
    )

    pending = create_handoff(
        version.version_id,
        version.governing_manifest.canonical_digest,
        SINK,
    )
    pending = mark_attempt_sent(
        persist_attempt(pending), persist_attempt(pending).attempts[0].attempt_id
    )
    assert (
        correlate_evaluation_feedback(pending, version, feedback, ())
        is FeedbackCorrelationOutcome.PENDING_ACKNOWLEDGEMENT
    )
    ambiguous = mark_attempt_ambiguous(pending, pending.attempts[0].attempt_id)
    assert ambiguous.state is HandoffState.AMBIGUOUS
    assert (
        correlate_evaluation_feedback(ambiguous, version, feedback, ())
        is FeedbackCorrelationOutcome.AMBIGUOUS_ACKNOWLEDGEMENT
    )

    retry = persist_attempt(request_retry(ambiguous))
    retry = mark_attempt_sent(retry, retry.attempts[-1].attempt_id)
    delayed_ack = Acknowledgement.create(
        handoff_id=retry.handoff_id,
        attempt_id=retry.attempts[0].attempt_id,
        candidate_version_id=version.version_id,
        governing_manifest_digest=version.governing_manifest.canonical_digest,
        sink_id=SINK,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest=feedback.acknowledgement_response_digest,
    )
    delayed = correlate_acknowledgement(retry, delayed_ack)
    delayed_feedback = replace(
        feedback,
        acknowledgement_id=delayed_ack.acknowledgement_id,
    )
    assert (
        correlate_evaluation_feedback(delayed, version, delayed_feedback, ())
        is FeedbackCorrelationOutcome.DELAYED_READY
    )


def test_feedback_parser_rejects_malformed_unknown_and_duplicate_fields(
    tmp_path,
) -> None:
    feedback, _, _ = _feedback(tmp_path)
    document = json.loads(feedback.canonical_bytes)
    document["feedback"]["unknown"] = "value"
    with pytest.raises(FeedbackContractError, match="fields are not exact"):
        EvaluationFeedback.from_canonical_bytes(canonical_json_bytes(document))

    duplicate = (
        b'{"feedback":'
        + canonical_json_bytes(json.loads(feedback.canonical_bytes)["feedback"])
        + b',"schema_version":"'
        + EVALUATION_FEEDBACK.encode()
        + b'","schema_version":"'
        + EVALUATION_FEEDBACK.encode()
        + b'"}'
    )
    with pytest.raises(FeedbackContractError, match="duplicate"):
        EvaluationFeedback.from_canonical_bytes(duplicate)
    with pytest.raises(FeedbackContractError):
        EvaluationFeedback.from_canonical_bytes(b'{"schema_version":NaN}')
    with pytest.raises(FeedbackContractError):
        EvaluationFeedback.from_canonical_bytes(b"[]")


@pytest.mark.parametrize(
    ("outcome", "reason", "kind"),
    [
        (
            EvaluationFeedbackOutcome.ACCEPTED,
            EvaluationFeedbackReason.INTAKE_ACCEPTED,
            ReconciliationObligationKind.RECORD_INTAKE_ACCEPTANCE,
        ),
        (
            EvaluationFeedbackOutcome.REJECTED,
            EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE,
            ReconciliationObligationKind.RECORD_DUPLICATE_OR_MERGE,
        ),
        (
            EvaluationFeedbackOutcome.INCONCLUSIVE,
            EvaluationFeedbackReason.INSUFFICIENT_PUBLIC_EVIDENCE,
            ReconciliationObligationKind.REVIEW_INSUFFICIENT_PUBLIC_EVIDENCE,
        ),
        (
            EvaluationFeedbackOutcome.REJECTED,
            EvaluationFeedbackReason.OUT_OF_SCOPE,
            ReconciliationObligationKind.RECORD_OUT_OF_SCOPE,
        ),
        (
            EvaluationFeedbackOutcome.REJECTED,
            EvaluationFeedbackReason.RIGHTS_BLOCK,
            ReconciliationObligationKind.RECORD_RIGHTS_BLOCK,
        ),
        (
            EvaluationFeedbackOutcome.REJECTED,
            EvaluationFeedbackReason.STALE_CANDIDATE,
            ReconciliationObligationKind.RECORD_STALE_CANDIDATE,
        ),
        (
            EvaluationFeedbackOutcome.REJECTED,
            EvaluationFeedbackReason.CANDIDATE_CLOSED,
            ReconciliationObligationKind.RECORD_CANDIDATE_CLOSED,
        ),
        (
            EvaluationFeedbackOutcome.INCONCLUSIVE,
            EvaluationFeedbackReason.SUPPLEMENTAL_DISCOVERY_REQUESTED,
            ReconciliationObligationKind.GOVERN_SUPPLEMENTAL_DISCOVERY,
        ),
    ],
)
def test_every_feedback_reason_creates_one_stable_mandatory_obligation(
    tmp_path, outcome, reason, kind
) -> None:
    overrides = {"outcome": outcome, "reason": reason}
    if reason is EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE:
        overrides["duplicate_or_merged_candidate_id"] = (
            "ffffffff-ffff-4fff-8fff-ffffffffffff"
        )
    obligation = _obligation(tmp_path, **overrides)

    assert obligation.obligation_id.startswith("obligation:sha256:")
    assert obligation.kind is kind
    assert obligation.mandatory is True
    assert obligation.visible_until_fulfilled is True
    assert (
        ReconciliationObligation.from_canonical_bytes(obligation.canonical_bytes)
        == obligation
    )
    assert reconciliation_is_open(obligation, ()) is True


def test_disposition_history_is_contiguous_cas_bound_replayable_and_terminal(
    tmp_path,
) -> None:
    obligation = _obligation(tmp_path)
    first = append_reconciliation_disposition(
        obligation,
        (),
        outcome=ReconciliationDispositionOutcome.UNRESOLVED,
        reason=ReconciliationDispositionReason.AWAITING_RECONCILIATION,
        resolution_digest="sha256:" + "6" * 64,
        request_id="11111111-1111-4111-8111-111111111111",
        actor_identity_digest=ACTOR,
        idempotency_key="disposition-request:001",
        expected_current_disposition_id=None,
        expected_current_disposition_digest=None,
        expected_current_ordinal=0,
    )
    assert first.ordinal == 1
    assert reconciliation_is_open(obligation, (first,)) is True
    replay = append_reconciliation_disposition(
        obligation,
        (first,),
        outcome=first.outcome,
        reason=first.reason,
        resolution_digest=first.resolution_digest,
        request_id=first.request_id,
        actor_identity_digest=first.actor_identity_digest,
        idempotency_key=first.idempotency_key,
        expected_current_disposition_id=None,
        expected_current_disposition_digest=None,
        expected_current_ordinal=0,
    )
    assert replay is first

    with pytest.raises(FeedbackContractError, match="CAS"):
        append_reconciliation_disposition(
            obligation,
            (first,),
            outcome=ReconciliationDispositionOutcome.BLOCKED,
            reason=ReconciliationDispositionReason.DEPENDENCY_UNAVAILABLE,
            resolution_digest="sha256:" + "7" * 64,
            request_id="22222222-2222-4222-8222-222222222222",
            actor_identity_digest=ACTOR,
            idempotency_key="disposition-request:002",
            expected_current_disposition_id=None,
            expected_current_disposition_digest=None,
            expected_current_ordinal=0,
        )
    second = append_reconciliation_disposition(
        obligation,
        (first,),
        outcome=ReconciliationDispositionOutcome.BLOCKED,
        reason=ReconciliationDispositionReason.DEPENDENCY_UNAVAILABLE,
        resolution_digest="sha256:" + "7" * 64,
        request_id="22222222-2222-4222-8222-222222222222",
        actor_identity_digest=ACTOR,
        idempotency_key="disposition-request:002",
        expected_current_disposition_id=first.disposition_id,
        expected_current_disposition_digest=first.canonical_digest,
        expected_current_ordinal=1,
    )
    final = append_reconciliation_disposition(
        obligation,
        (first, second),
        outcome=ReconciliationDispositionOutcome.FULFILLED,
        reason=ReconciliationDispositionReason.FEEDBACK_RECORDED,
        resolution_digest="sha256:" + "8" * 64,
        request_id="33333333-3333-4333-8333-333333333333",
        actor_identity_digest=ACTOR,
        idempotency_key="disposition-request:003",
        expected_current_disposition_id=second.disposition_id,
        expected_current_disposition_digest=second.canonical_digest,
        expected_current_ordinal=2,
    )
    history = (first, second, final)
    assert validate_reconciliation_history(obligation, history) == history
    assert (
        ReconciliationDisposition.from_canonical_bytes(final.canonical_bytes) == final
    )
    assert reconciliation_is_open(obligation, history) is False
    with pytest.raises(FeedbackContractError, match="terminal"):
        append_reconciliation_disposition(
            obligation,
            history,
            outcome=ReconciliationDispositionOutcome.UNRESOLVED,
            reason=ReconciliationDispositionReason.AMBIGUOUS_RECONCILIATION,
            resolution_digest=D,
            request_id="44444444-4444-4444-8444-444444444444",
            actor_identity_digest=ACTOR,
            idempotency_key="disposition-request:004",
            expected_current_disposition_id=final.disposition_id,
            expected_current_disposition_digest=final.canonical_digest,
            expected_current_ordinal=3,
        )


def test_supplemental_fulfilment_requires_exact_governed_reentry(tmp_path) -> None:
    obligation = _obligation(
        tmp_path,
        outcome=EvaluationFeedbackOutcome.INCONCLUSIVE,
        reason=EvaluationFeedbackReason.SUPPLEMENTAL_DISCOVERY_REQUESTED,
    )
    with pytest.raises(FeedbackContractError, match="supplemental"):
        append_reconciliation_disposition(
            obligation,
            (),
            outcome=ReconciliationDispositionOutcome.FULFILLED,
            reason=ReconciliationDispositionReason.SUPPLEMENTAL_DISCOVERY_REENTERED,
            resolution_digest=D,
            request_id="55555555-5555-4555-8555-555555555555",
            actor_identity_digest=ACTOR,
            idempotency_key="supplemental:001",
            expected_current_disposition_id=None,
            expected_current_disposition_digest=None,
            expected_current_ordinal=0,
        )
    proof = _supplemental_reentry()
    proof_digest = digest_bytes(canonical_json_bytes(proof.canonical_value()))
    fulfilled = append_reconciliation_disposition(
        obligation,
        (),
        outcome=ReconciliationDispositionOutcome.FULFILLED,
        reason=ReconciliationDispositionReason.SUPPLEMENTAL_DISCOVERY_REENTERED,
        resolution_digest=proof_digest,
        request_id="55555555-5555-4555-8555-555555555555",
        actor_identity_digest=ACTOR,
        idempotency_key="supplemental:001",
        expected_current_disposition_id=None,
        expected_current_disposition_digest=None,
        expected_current_ordinal=0,
        supplemental_reentry=proof,
    )
    assert fulfilled.supplemental_reentry == proof
    assert (
        ReconciliationDisposition.from_canonical_bytes(fulfilled.canonical_bytes)
        == fulfilled
    )


def test_obligation_and_disposition_replay_reject_unknown_and_cross_chain(
    tmp_path,
) -> None:
    obligation = _obligation(tmp_path)
    root = json.loads(obligation.canonical_bytes)
    root["obligation"]["unknown"] = True
    with pytest.raises(FeedbackContractError, match="fields are not exact"):
        ReconciliationObligation.from_canonical_bytes(canonical_json_bytes(root))

    first = append_reconciliation_disposition(
        obligation,
        (),
        outcome=ReconciliationDispositionOutcome.UNRESOLVED,
        reason=ReconciliationDispositionReason.AWAITING_RECONCILIATION,
        resolution_digest=D,
        request_id="66666666-6666-4666-8666-666666666666",
        actor_identity_digest=ACTOR,
        idempotency_key="disposition:cross-chain",
        expected_current_disposition_id=None,
        expected_current_disposition_digest=None,
        expected_current_ordinal=0,
    )
    other = _obligation(
        tmp_path / "other",
        outcome=EvaluationFeedbackOutcome.REJECTED,
        reason=EvaluationFeedbackReason.RIGHTS_BLOCK,
    )
    with pytest.raises(FeedbackContractError):
        validate_reconciliation_history(other, (first,))


def test_cas_and_idempotency_fields_fail_closed_without_effects(tmp_path) -> None:
    feedback, _, _ = _feedback(tmp_path)
    for changes in (
        {"expected_feedback_digest": D},
        {"evaluation_only": False},
        {"publication_authority": True},
        {"evidence_authority": True},
        {"candidate_authority": True},
    ):
        with pytest.raises(FeedbackContractError):
            replace(feedback, **changes)
    obligation = _obligation(tmp_path / "obligation")
    with pytest.raises(FeedbackContractError, match="zero disposition CAS"):
        replace(obligation, expected_disposition_ordinal=1)
    first = append_reconciliation_disposition(
        obligation,
        (),
        outcome=ReconciliationDispositionOutcome.UNRESOLVED,
        reason=ReconciliationDispositionReason.AWAITING_RECONCILIATION,
        resolution_digest=D,
        request_id="77777777-7777-4777-8777-777777777777",
        actor_identity_digest=ACTOR,
        idempotency_key="disposition:idempotency",
        expected_current_disposition_id=None,
        expected_current_disposition_digest=None,
        expected_current_ordinal=0,
    )
    with pytest.raises(FeedbackContractError, match="binding conflict"):
        append_reconciliation_disposition(
            obligation,
            (first,),
            outcome=ReconciliationDispositionOutcome.BLOCKED,
            reason=ReconciliationDispositionReason.DEPENDENCY_UNAVAILABLE,
            resolution_digest="sha256:" + "a" * 64,
            request_id=first.request_id,
            actor_identity_digest=ACTOR,
            idempotency_key="different-key",
            expected_current_disposition_id=first.disposition_id,
            expected_current_disposition_digest=first.canonical_digest,
            expected_current_ordinal=1,
        )


def test_uninitialised_and_builtin_subclass_inputs_totalise_but_baseexceptions_escape(
    tmp_path,
) -> None:
    feedback, handoff, version = _feedback(tmp_path)

    class StrChild(str):
        pass

    with pytest.raises(FeedbackContractError):
        replace(feedback, source_feedback_id=StrChild(feedback.source_feedback_id))
    with pytest.raises(FeedbackContractError):
        replace(feedback, outcome=EvaluationFeedbackOutcome.ACCEPTED.value)  # type: ignore[arg-type]
    with pytest.raises(FeedbackContractError):
        correlate_evaluation_feedback(
            object.__new__(type(handoff)), version, feedback, ()
        )

    with pytest.raises(FeedbackContractError):
        correlate_evaluation_feedback(object(), object(), feedback, ())  # type: ignore[arg-type]
