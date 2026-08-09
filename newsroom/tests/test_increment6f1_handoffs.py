from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import permutations

import pytest

from newsroom.increment6.handoffs import (
    Acknowledgement,
    AcknowledgementOutcome,
    HandoffContractError,
    HandoffAttempt,
    HandoffState,
    EVALUATION_HANDOFF,
    HANDOFF_ACKNOWLEDGEMENT,
    HANDOFF_ATTEMPT,
    HANDOFF_TRANSPORT_STATE,
    correlate_acknowledgement,
    create_handoff,
    mark_attempt_ambiguous,
    mark_attempt_sent,
    persist_attempt,
    request_retry,
)


CANDIDATE_VERSION_ID = "candidate-version:01JZX7V7G8Q6XKNR4M8J5TH9WD"
MANIFEST_DIGEST = "sha256:" + "a" * 64
SINK_ID = "evaluation-sink:fixture-v1"


def _handoff(*, max_attempts: int = 3):
    return create_handoff(
        candidate_version_id=CANDIDATE_VERSION_ID,
        governing_manifest_digest=MANIFEST_DIGEST,
        sink_id=SINK_ID,
        max_attempts=max_attempts,
    )


def _ack(
    handoff,
    attempt,
    *,
    outcome=AcknowledgementOutcome.ACKNOWLEDGED,
    response_digest="sha256:" + "b" * 64,
    **overrides,
):
    values = {
        "handoff_id": handoff.handoff_id,
        "attempt_id": attempt.attempt_id,
        "candidate_version_id": handoff.candidate_version_id,
        "governing_manifest_digest": handoff.governing_manifest_digest,
        "sink_id": handoff.sink_id,
    }
    values.update(overrides)
    return Acknowledgement.create(
        outcome=outcome,
        response_digest=response_digest,
        **values,
    )


def test_logical_identity_is_immutable_semantic_and_exactly_bound() -> None:
    first = _handoff()
    replay = _handoff()

    assert first == replay
    assert first.schema_identity == EVALUATION_HANDOFF
    assert HandoffAttempt.schema_identity == HANDOFF_ATTEMPT
    assert Acknowledgement.schema_identity == HANDOFF_ACKNOWLEDGEMENT
    assert HANDOFF_TRANSPORT_STATE == tuple(item.value for item in HandoffState)
    assert first.handoff_id.startswith("handoff:sha256:")
    assert first.candidate_version_id == CANDIDATE_VERSION_ID
    assert first.governing_manifest_digest == MANIFEST_DIGEST
    assert first.evaluation_only is True
    assert first.publication_authority is False
    assert first.evidence_authority is False
    with pytest.raises(FrozenInstanceError):
        first.sink_id = "evaluation-sink:other"  # type: ignore[misc]

    changed_version = create_handoff(
        candidate_version_id=CANDIDATE_VERSION_ID + ":2",
        governing_manifest_digest=MANIFEST_DIGEST,
        sink_id=SINK_ID,
    )
    changed_manifest = create_handoff(
        candidate_version_id=CANDIDATE_VERSION_ID,
        governing_manifest_digest="sha256:" + "c" * 64,
        sink_id=SINK_ID,
    )
    assert len({first.handoff_id, changed_version.handoff_id, changed_manifest.handoff_id}) == 3


def test_binding_and_evaluation_only_semantics_are_fail_closed() -> None:
    with pytest.raises(HandoffContractError, match="candidate_version_id"):
        create_handoff("", MANIFEST_DIGEST, SINK_ID)
    with pytest.raises(HandoffContractError, match="governing_manifest_digest"):
        create_handoff(CANDIDATE_VERSION_ID, "a" * 64, SINK_ID)
    with pytest.raises(HandoffContractError, match="sink_id"):
        create_handoff(CANDIDATE_VERSION_ID, MANIFEST_DIGEST, "publication:discord")
    with pytest.raises(HandoffContractError, match="evaluation_only"):
        replace(_handoff(), evaluation_only=False)
    with pytest.raises(HandoffContractError, match="publication_authority"):
        replace(_handoff(), publication_authority=True)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (HandoffState.ACKNOWLEDGED, None),
        (HandoffState.REJECTED, None),
        (HandoffState.AMBIGUOUS, "target_outcome_unknown"),
        (HandoffState.RETRY, None),
    ],
)
def test_public_handoff_rejects_state_not_derived_from_records(
    state: HandoffState,
    reason: str | None,
) -> None:
    with pytest.raises(HandoffContractError, match="Handoff state"):
        replace(_handoff(), state=state, ambiguity_reason=reason)


def test_attempt_is_persisted_before_it_can_be_sent_and_replay_is_idempotent() -> None:
    handoff = _handoff()
    assert handoff.state is HandoffState.PENDING
    assert handoff.attempts == ()

    persisted = persist_attempt(handoff)
    attempt = persisted.attempts[0]
    assert attempt.persisted_before_send is True
    assert attempt.attempt_number == 1
    assert attempt.semantic_idempotency_key == handoff.handoff_id
    assert persist_attempt(persisted) == persisted

    sent = mark_attempt_sent(persisted, attempt.attempt_id)
    assert sent.attempts[0].sent is True
    assert mark_attempt_sent(sent, attempt.attempt_id) == sent
    with pytest.raises(HandoffContractError, match="unknown attempt"):
        mark_attempt_sent(handoff, "attempt:sha256:" + "0" * 64)


def test_lost_ack_becomes_ambiguous_then_retry_reuses_logical_identity() -> None:
    first = persist_attempt(_handoff())
    first = mark_attempt_sent(first, first.attempts[0].attempt_id)
    ambiguous = mark_attempt_ambiguous(first, first.attempts[0].attempt_id)
    assert ambiguous.state is HandoffState.AMBIGUOUS

    retry = request_retry(ambiguous)
    assert retry.state is HandoffState.RETRY
    second = persist_attempt(retry)
    assert second.state is HandoffState.PENDING
    assert second.handoff_id == first.handoff_id
    assert second.attempts[1].attempt_number == 2
    assert second.attempts[1].attempt_id != second.attempts[0].attempt_id
    assert second.attempts[1].semantic_idempotency_key == first.handoff_id


def test_retry_is_bounded_and_exhaustion_remains_truthfully_ambiguous() -> None:
    handoff = persist_attempt(_handoff(max_attempts=1))
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)
    handoff = mark_attempt_ambiguous(handoff, handoff.attempts[0].attempt_id)

    exhausted = request_retry(handoff)
    assert exhausted.state is HandoffState.AMBIGUOUS
    assert exhausted.retry_exhausted is True
    assert persist_attempt(exhausted) == exhausted


def test_exact_acknowledgement_and_duplicate_replay_are_idempotent() -> None:
    handoff = persist_attempt(_handoff())
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)
    acknowledgement = _ack(handoff, handoff.attempts[0])

    acknowledged = correlate_acknowledgement(handoff, acknowledgement)
    assert acknowledged.state is HandoffState.ACKNOWLEDGED
    assert acknowledged.acknowledgements == (acknowledgement,)
    assert correlate_acknowledgement(acknowledged, acknowledgement) == acknowledged


def test_rejected_acknowledgement_is_a_distinct_terminal_outcome() -> None:
    handoff = persist_attempt(_handoff())
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)

    rejected = correlate_acknowledgement(
        handoff,
        _ack(handoff, handoff.attempts[0], outcome=AcknowledgementOutcome.REJECTED),
    )
    assert rejected.state is HandoffState.REJECTED
    with pytest.raises(HandoffContractError, match="terminal"):
        request_retry(rejected)


def test_delayed_ack_for_an_earlier_attempt_correlates_to_same_handoff() -> None:
    handoff = persist_attempt(_handoff())
    first_attempt = handoff.attempts[0]
    handoff = mark_attempt_sent(handoff, first_attempt.attempt_id)
    handoff = mark_attempt_ambiguous(handoff, first_attempt.attempt_id)
    handoff = persist_attempt(request_retry(handoff))
    handoff = mark_attempt_sent(handoff, handoff.attempts[1].attempt_id)

    acknowledged = correlate_acknowledgement(handoff, _ack(handoff, first_attempt))
    assert acknowledged.state is HandoffState.ACKNOWLEDGED
    assert acknowledged.handoff_id == handoff.handoff_id


def test_replayed_timeout_for_earlier_attempt_does_not_undo_active_retry() -> None:
    handoff = persist_attempt(_handoff())
    first_attempt = handoff.attempts[0]
    handoff = mark_attempt_sent(handoff, first_attempt.attempt_id)
    handoff = mark_attempt_ambiguous(handoff, first_attempt.attempt_id)
    handoff = persist_attempt(request_retry(handoff))

    assert mark_attempt_ambiguous(handoff, first_attempt.attempt_id) == handoff
    assert handoff.state is HandoffState.PENDING


def test_delayed_timeout_for_earlier_attempt_preserves_sent_active_retry() -> None:
    initial = persist_attempt(_handoff())
    first = initial.attempts[0]
    initial = mark_attempt_sent(initial, first.attempt_id)
    wrong = _ack(
        initial,
        first,
        handoff_id="handoff:sha256:" + "0" * 64,
    )

    timeout_first = correlate_acknowledgement(initial, wrong)
    timeout_first = mark_attempt_ambiguous(timeout_first, first.attempt_id)
    timeout_first = persist_attempt(request_retry(timeout_first))
    timeout_first = mark_attempt_sent(
        timeout_first, timeout_first.attempts[1].attempt_id
    )

    retry_first = correlate_acknowledgement(initial, wrong)
    retry_first = persist_attempt(request_retry(retry_first))
    retry_first = mark_attempt_sent(retry_first, retry_first.attempts[1].attempt_id)
    retry_first = mark_attempt_ambiguous(retry_first, first.attempt_id)

    assert retry_first == timeout_first
    assert retry_first.state is HandoffState.PENDING
    assert retry_first.attempts[0].ambiguous is True
    assert retry_first.attempts[1].sent is True
    assert persist_attempt(retry_first) == retry_first
    with pytest.raises(HandoffContractError, match="retry requires ambiguous"):
        request_retry(retry_first)


def test_public_handoff_rejects_premature_retry_attempt_history() -> None:
    first = persist_attempt(_handoff())
    first = mark_attempt_sent(first, first.attempts[0].attempt_id)
    valid = mark_attempt_ambiguous(first, first.attempts[0].attempt_id)
    valid = persist_attempt(request_retry(valid))

    with pytest.raises(HandoffContractError, match="attempt history"):
        replace(first, attempts=(first.attempts[0], valid.attempts[1]))


def test_pristine_wrong_ack_is_audited_without_granting_retry_authority() -> None:
    handoff = _handoff()
    future_attempt = persist_attempt(handoff).attempts[0]
    wrong = _ack(
        handoff,
        future_attempt,
        handoff_id="handoff:sha256:" + "0" * 64,
    )

    retained = correlate_acknowledgement(handoff, wrong)

    assert retained.state is HandoffState.PENDING
    assert retained.acknowledgements == (wrong,)
    assert correlate_acknowledgement(retained, wrong) == retained
    first = persist_attempt(retained)
    assert first.state is HandoffState.PENDING
    assert len(first.attempts) == 1
    with pytest.raises(HandoffContractError, match="retry requires ambiguous"):
        request_retry(first)

    with pytest.raises(HandoffContractError, match="causal acknowledgement"):
        replace(
            handoff,
            state=HandoffState.AMBIGUOUS,
            acknowledgements=(wrong,),
            causal_acknowledgement_ids=(wrong.acknowledgement_id,),
            ambiguity_reason="acknowledgement_handoff_id_mismatch",
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("handoff_id", "handoff:sha256:" + "0" * 64, "handoff_id"),
        ("attempt_id", "attempt:sha256:" + "0" * 64, "attempt_id"),
        ("candidate_version_id", CANDIDATE_VERSION_ID + ":other", "candidate_version_id"),
        ("governing_manifest_digest", "sha256:" + "c" * 64, "governing_manifest_digest"),
        ("sink_id", "evaluation-sink:other", "sink_id"),
    ],
)
def test_uncorrelated_acknowledgements_are_retained_as_ambiguous(
    field: str, value: str, reason: str
) -> None:
    handoff = persist_attempt(_handoff())
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)
    acknowledgement = _ack(handoff, handoff.attempts[0], **{field: value})

    ambiguous = correlate_acknowledgement(handoff, acknowledgement)
    assert ambiguous.state is HandoffState.AMBIGUOUS
    assert ambiguous.ambiguity_reason == f"acknowledgement_{reason}_mismatch"
    assert ambiguous.acknowledgements == (acknowledgement,)


def test_conflicting_delayed_acknowledgement_is_ambiguous_not_overwritten() -> None:
    handoff = persist_attempt(_handoff())
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)
    accepted = _ack(handoff, handoff.attempts[0])
    handoff = correlate_acknowledgement(handoff, accepted)
    rejected = _ack(
        handoff,
        handoff.attempts[0],
        outcome=AcknowledgementOutcome.REJECTED,
        response_digest="sha256:" + "d" * 64,
    )

    result = correlate_acknowledgement(handoff, rejected)
    assert result.state is HandoffState.AMBIGUOUS
    assert result.ambiguity_reason == "conflicting_acknowledgements"


def test_conflicting_acknowledgement_arrival_orders_remain_ambiguous() -> None:
    handoff = persist_attempt(_handoff())
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)
    accepted = _ack(handoff, handoff.attempts[0])
    rejected = _ack(
        handoff,
        handoff.attempts[0],
        outcome=AcknowledgementOutcome.REJECTED,
        response_digest="sha256:" + "d" * 64,
    )
    later_accepted = _ack(
        handoff,
        handoff.attempts[0],
        response_digest="sha256:" + "e" * 64,
    )

    results = []
    for arrivals in permutations((accepted, rejected, later_accepted)):
        result = handoff
        for acknowledgement in arrivals:
            result = correlate_acknowledgement(result, acknowledgement)
        results.append(result)

    assert {item.state for item in results} == {HandoffState.AMBIGUOUS}
    assert {item.ambiguity_reason for item in results} == {
        "conflicting_acknowledgements"
    }
    assert len({item.acknowledgements for item in results}) == 1


def test_acknowledgement_identity_is_immutable_content_identity() -> None:
    handoff = persist_attempt(_handoff())
    handoff = mark_attempt_sent(handoff, handoff.attempts[0].attempt_id)
    accepted = _ack(handoff, handoff.attempts[0])

    with pytest.raises(HandoffContractError, match="acknowledgement_id"):
        replace(accepted, response_digest="sha256:" + "e" * 64)
