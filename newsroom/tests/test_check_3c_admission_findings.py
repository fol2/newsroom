from __future__ import annotations

import sqlite3

import pytest

from newsroom.checks import FindingCategory, FindingSeverity
from newsroom.discovery_adapters import ObservationProposalOutcome, run_fixture_adapter

from .check_3c_authority_helpers import open_check_system, proof, scopes
from .test_check_3c_admission import (
    _adapter_request,
    _admission,
    _scenario,
    _seed_check,
    _seed_source,
)


def _malformed_admission(system, *, suffix: int):
    adapter_request = _adapter_request(suffix=suffix)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(adapter_request, suffix=suffix, body=b"\xff"),
    )
    assert proposal.outcome is ObservationProposalOutcome.MALFORMED
    check_request, attempt = _seed_check(
        system,
        adapter_request,
        suffix=suffix,
    )
    return _admission(
        check_request,
        attempt,
        adapter_request,
        proposal,
    )


def test_malformed_proposal_opens_stable_finding_and_occurrence(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)
    admission = _malformed_admission(system, suffix=10)

    result = system.checks.admit_proposal(admission, proof=proof())

    assert result.observations == ()
    assert result.baseline is None
    assert result.transitions == ()
    assert len(result.findings) == 1
    assert len(result.finding_occurrences) == 1
    finding = result.findings[0]
    occurrence = result.finding_occurrences[0]
    assert finding.request.category is FindingCategory.PARSER
    assert finding.request.severity is FindingSeverity.BLOCKING
    assert occurrence.request.code == "PROPOSAL_MALFORMED"
    assert occurrence.request.outcome_id == result.outcome.request.outcome_id

    replay = system.checks.admit_proposal(admission, proof=proof())
    assert replay.replayed is True
    assert replay.findings[0].event_id == finding.event_id
    assert replay.finding_occurrences[0].event_id == occurrence.event_id
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM operational_findings").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_finding_occurrences"
        ).fetchone()[0] == 1


def test_repeated_malformed_observations_reuse_case_and_add_occurrence(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)

    first = system.checks.admit_proposal(
        _malformed_admission(system, suffix=13),
        proof=proof(),
    )
    second = system.checks.admit_proposal(
        _malformed_admission(system, suffix=14),
        proof=proof(),
    )

    assert second.findings[0].event_id == first.findings[0].event_id
    assert (
        second.finding_occurrences[0].request.occurrence_id
        != first.finding_occurrences[0].request.occurrence_id
    )
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM operational_findings").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_finding_occurrences"
        ).fetchone()[0] == 2


def test_finding_scope_is_preflighted_before_outcome_commit(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    restricted = scopes() - frozenset({"authority.findings.manage"})
    system = open_check_system(database, granted_scopes=restricted)
    _seed_source(system)
    admission = _malformed_admission(system, suffix=11)

    with pytest.raises(PermissionError):
        system.checks.admit_proposal(admission, proof=proof())
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM operational_findings").fetchone()[0] == 0


def test_successful_empty_proposal_is_not_misclassified_as_finding(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system)
    adapter_request = _adapter_request(suffix=12)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(adapter_request, suffix=12, body=b""),
    )
    assert proposal.outcome is ObservationProposalOutcome.SUCCESS_EMPTY
    check_request, attempt = _seed_check(system, adapter_request, suffix=12)

    result = system.checks.admit_proposal(
        _admission(check_request, attempt, adapter_request, proposal),
        proof=proof(),
    )

    assert result.observations == ()
    assert result.baseline is None
    assert result.transitions == ()
    assert result.findings == ()
    assert result.finding_occurrences == ()
    system.close()
