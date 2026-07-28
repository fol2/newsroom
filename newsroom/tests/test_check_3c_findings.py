from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.checks import (
    CheckContractError,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
)
from newsroom.tests.check_3c_helpers import (
    LATER,
    finding_occurrence,
    operational_finding,
)


def test_operational_finding_requires_exact_check_lineage() -> None:
    finding = operational_finding()
    assert finding.opened_by_outcome_id is not None

    with pytest.raises(CheckContractError):
        replace(
            finding,
            opened_by_request_id=None,
            opened_by_attempt_id=None,
            opened_by_outcome_id=None,
        )


def test_finding_case_semantics_do_not_depend_on_record_identity_or_summary() -> None:
    original = operational_finding()
    equivalent_case = replace(
        original,
        finding_id=OperationalFindingId.parse(
            "00000000-0000-4000-8000-000000006141"
        ),
        summary="A later description of the same parser case.",
        opened_at=LATER,
        idempotency_key="fixture-finding-equivalent",
    )
    assert equivalent_case.semantic_digest == original.semantic_digest
    assert equivalent_case.digest != original.digest


def test_finding_occurrences_retain_each_exact_contributing_outcome() -> None:
    original = finding_occurrence()
    later = replace(
        original,
        occurrence_id=OperationalFindingOccurrenceId.parse(
            "00000000-0000-4000-8000-000000006142"
        ),
        observed_at=LATER,
        idempotency_key="fixture-finding-occurrence-equivalent",
    )
    assert later.semantic_digest == original.semantic_digest
    assert later.digest != original.digest

    with pytest.raises(CheckContractError):
        replace(
            original,
            request_id=None,
            attempt_id=None,
            outcome_id=None,
        )
