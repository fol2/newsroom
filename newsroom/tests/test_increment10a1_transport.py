from dataclasses import replace
import pytest
from newsroom.increment10.transport import *


def submission():
    return create_submission(authority_token(), candidate_version_id="candidate-version:increment10-fixture-001", handoff_digest="sha256:"+"1"*64, plan_digest="sha256:"+"2"*64, destination="local://increment10/evidence-intake-fixture-v1", created_epoch_seconds=10, retry=RetryPolicy(3,(1,2),100))


def test_semantic_idempotency_and_canonical_replay():
    first=submission(); second=submission()
    assert first.submission_id == second.submission_id
    assert parse_submission(first.canonical_bytes()) == first
    assert first.digest.startswith("sha256:")


def test_authority_destination_and_retry_fail_closed():
    with pytest.raises(TransportContractError):
        create_submission(object(), candidate_version_id="candidate-version:x", handoff_digest="sha256:"+"1"*64, plan_digest="sha256:"+"2"*64, destination="local://increment10/evidence-intake-fixture-v1", created_epoch_seconds=1, retry=RetryPolicy(1,(),2))
    with pytest.raises(TransportContractError):
        RetryPolicy(4,(1,2,3),100)


def test_persist_before_effect_and_exact_correlation():
    with pytest.raises(TransportContractError, match="persist-before-effect"):
        start_attempt(authority_token(), submission(), attempt_number=1, request_id="r1", persisted_epoch_seconds=20, effect_started_epoch_seconds=19)
    attempt=start_attempt(authority_token(), submission(), attempt_number=1, request_id="r1", persisted_epoch_seconds=20, effect_started_epoch_seconds=21)
    with pytest.raises(TransportContractError, match="correlation"):
        observe(authority_token(), attempt, state=AttemptState.ACCEPTED, observed_epoch_seconds=22, response_request_id="other", acknowledgement_id="ack")
    accepted=observe(authority_token(), attempt, state=AttemptState.ACCEPTED, observed_epoch_seconds=22, response_request_id="r1", acknowledgement_id="ack")
    assert accepted.terminal
    with pytest.raises(TransportContractError, match="immutable"):
        observe(authority_token(), accepted, state=AttemptState.REJECTED, observed_epoch_seconds=23)


def test_lost_response_reconciles_once_and_conflict_is_rejected():
    attempt=start_attempt(authority_token(), submission(), attempt_number=1, request_id="r1", persisted_epoch_seconds=20)
    timed=observe(authority_token(), attempt, state=AttemptState.TIMED_OUT, observed_epoch_seconds=30, reason="lost response")
    reconciled=reconcile(authority_token(), timed, acknowledgement_id="ack", observed_epoch_seconds=40, authoritative_request_id="r1")
    assert reconciled.state is AttemptState.RECONCILED
    with pytest.raises(TransportContractError):
        reconcile(authority_token(), reconciled, acknowledgement_id="conflict", observed_epoch_seconds=41, authoritative_request_id="r1")


def test_duplicate_unknown_tampered_or_noncanonical_fields_rejected():
    raw=submission().canonical_bytes()
    for changed in (raw.replace(b'"schema_version"',b'"unknown"',1), b'{"x":1,"x":2}', b'{ "x":1}'):
        with pytest.raises(TransportContractError): parse_submission(changed)
    changed=replace(submission(), submission_id="sha256:"+"0"*64)
    with pytest.raises(TransportContractError, match="identity differs"): parse_submission(changed.canonical_bytes())


def test_acknowledgement_has_no_evidence_or_publication_authority():
    attempt=start_attempt(authority_token(), submission(), attempt_number=1, request_id="r1", persisted_epoch_seconds=20)
    accepted=observe(authority_token(), attempt, state=AttemptState.ACCEPTED, observed_epoch_seconds=21, response_request_id="r1", acknowledgement_id="ack")
    assert not hasattr(accepted,"evidence") and not hasattr(accepted,"publication_authority")
