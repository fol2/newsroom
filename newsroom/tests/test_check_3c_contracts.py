from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.checks import (
    CheckAttemptId,
    CheckAttemptKind,
    CheckContractError,
    CheckOutcomeKind,
    QuarantineDisposition,
    TriggerKind,
    TriggerRef,
    discovery_check_command_definitions,
    discovery_check_payload_contracts,
)
from newsroom.tests.check_3c_helpers import (
    ATTEMPT_ID,
    DIGEST_A,
    check_attempt,
    check_request,
    changed_outcome,
    replace_request_time,
)


def test_check_request_semantic_identity_excludes_record_identity_and_time() -> None:
    original = check_request()
    replay = replace_request_time(original)

    assert replay.semantic_digest == original.semantic_digest
    assert replay.digest != original.digest

    changed = replace(
        original,
        trigger=TriggerRef(
            TriggerKind.FIXTURE_MANUAL,
            "fixture-trigger",
            "v2",
        ),
    )
    assert changed.semantic_digest != original.semantic_digest


def test_planned_window_trigger_requires_only_its_exact_window_digest() -> None:
    planned = TriggerRef(
        TriggerKind.PLANNED_WINDOW,
        "fixture-window",
        "v1",
        DIGEST_A,
    )
    assert check_request(trigger=planned).trigger.expected_window_digest == DIGEST_A

    with pytest.raises(CheckContractError):
        TriggerRef(TriggerKind.PLANNED_WINDOW, "fixture-window", "v1")

    with pytest.raises(CheckContractError):
        TriggerRef(
            TriggerKind.FIXTURE_MANUAL,
            "fixture-trigger",
            "v1",
            DIGEST_A,
        )


def test_attempt_ordinals_and_predecessors_are_exact() -> None:
    first = check_attempt()
    assert first.attempt_number == 1
    assert first.prior_attempt_id is None

    with pytest.raises(CheckContractError):
        check_attempt(kind=CheckAttemptKind.RETRY)

    with pytest.raises(CheckContractError):
        check_attempt(attempt_number=2, kind=CheckAttemptKind.RETRY)

    retry_id = CheckAttemptId.parse(
        "00000000-0000-4000-8000-000000006102"
    )
    retry = check_attempt(
        attempt_id=retry_id,
        attempt_number=2,
        kind=CheckAttemptKind.RETRY,
        prior_attempt_id=ATTEMPT_ID,
    )
    assert retry.prior_attempt_id == ATTEMPT_ID
    assert retry.semantic_digest != first.semantic_digest

    with pytest.raises(CheckContractError):
        check_attempt(
            attempt_id=retry_id,
            attempt_number=2,
            kind=CheckAttemptKind.RETRY,
            prior_attempt_id=retry_id,
        )


def test_outcome_kind_controls_candidate_incompleteness_and_evidence_shape() -> None:
    changed = changed_outcome()
    assert changed.kind is CheckOutcomeKind.SUCCESS_CHANGED
    assert changed.incomplete is False

    partial = changed_outcome(
        kind=CheckOutcomeKind.SUCCESS_PARTIAL,
        incomplete=True,
    )
    assert partial.incomplete is True

    with pytest.raises(CheckContractError):
        changed_outcome(
            kind=CheckOutcomeKind.SUCCESS_PARTIAL,
            incomplete=False,
        )

    with pytest.raises(CheckContractError):
        changed_outcome(candidates=())

    blocked = replace(
        changed,
        kind=CheckOutcomeKind.BLOCKED,
        reason_codes=("PREFLIGHT_BLOCKED",),
        incomplete=True,
        receipt_digest=None,
        capture_digest=None,
        parser_result_digest=None,
        source_body_digest=None,
        producer_slot_digest=None,
        representation_digest=None,
        candidate_observations=(),
    )
    assert blocked.receipt_digest is None

    with pytest.raises(CheckContractError):
        replace(blocked, receipt_digest=DIGEST_A)

    with pytest.raises(CheckContractError):
        replace(changed, parser_result_digest=None)

    with pytest.raises(CheckContractError):
        replace(
            changed,
            kind=CheckOutcomeKind.SHAPE_DRIFT,
            reason_codes=("SHAPE_DRIFT",),
            incomplete=True,
            candidate_observations=(),
            quarantine=QuarantineDisposition.NONE,
        )

    reviewed_drift = replace(
        changed,
        kind=CheckOutcomeKind.SHAPE_DRIFT,
        reason_codes=("SHAPE_DRIFT",),
        incomplete=True,
        candidate_observations=(),
        quarantine=QuarantineDisposition.REVIEW,
    )
    assert reviewed_drift.quarantine is QuarantineDisposition.REVIEW


def test_payload_and_command_contracts_are_complete_and_executable() -> None:
    contracts = discovery_check_payload_contracts()
    definitions = discovery_check_command_definitions()

    assert len(contracts) == 7
    assert len(definitions) == 7
    assert len({item.schema_version for item in contracts}) == 7
    assert len({item.command_type for item in definitions}) == 7

    for contract in contracts:
        for vector in contract.golden_vectors:
            assert contract.canonicalize(vector.value) == vector.expected_bytes

    first = contracts[0]
    invalid = dict(first.golden_vectors[0].value)
    invalid["unexpected"] = True
    with pytest.raises(PayloadSchemaValidationError):
        first.canonicalize(invalid)
