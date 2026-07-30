from __future__ import annotations

import dataclasses
from datetime import timedelta
import json
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
)
from newsroom.extraction import (
    DeterministicFixtureExtractor,
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
)

from .extraction_4a_helpers import (
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)
from .source_3a_helpers import SOURCE_NOW


def _seed_complete(tmp_path: Path):
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        result = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
    assert result.output is not None
    assert result.proposal_set is not None
    return state, result


def _seed_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state, timeout_ms=10)
    current = [SOURCE_NOW]
    original_produce = DeterministicFixtureExtractor.produce

    def slow_produce(self, *, contract, request):
        produced = original_produce(self, contract=contract, request=request)
        current[0] = dataclasses.replace(
            current[0], value=current[0].value + timedelta(milliseconds=11)
        )
        return produced

    monkeypatch.setattr(
        DeterministicFixtureExtractor,
        "produce",
        slow_produce,
    )
    with open_extraction_system(state, clock=lambda: current[0]) as system:
        system.extraction.register_contract(
            contract, proof=extraction_proof()
        )
        result = system.extraction.execute(request, proof=extraction_proof())
    assert result.outcome is ExtractionOutcome.RETRYABLE_FAILURE
    assert result.failure_code is ExtractionFailureCode.EXECUTION_TIMEOUT
    return state, result


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    conn.execute(f'DROP TRIGGER "{name}"')
    return str(row[0])


def _expect_reopen_failure(state, match: str) -> None:
    with pytest.raises(
        (AuthorityPersistenceError, AuthoritySchemaError, ExtractionContractError),
        match=match,
    ):
        open_extraction_system(state)


@pytest.mark.parametrize(
    ("trigger", "statement", "match"),
    (
        (
            "immutable_extractor_contract_update",
            "UPDATE extractor_contracts SET producer_kind='TAMPERED'",
            "immutable extractor contract",
        ),
        (
            "immutable_extraction_run_update",
            "UPDATE extraction_runs SET contract_id=contract_id",
            "immutable extraction run",
        ),
        (
            "immutable_extraction_passage_update",
            "UPDATE extraction_run_passages SET language='en-US'",
            "immutable extraction passage",
        ),
        (
            "immutable_extraction_run_version_update",
            "UPDATE extraction_run_versions SET elapsed_ms=2",
            "immutable extraction run version",
        ),
        (
            "immutable_extraction_output_update",
            "UPDATE extraction_outputs SET retained_at=retained_at",
            "immutable extraction output",
        ),
        (
            "immutable_extraction_proposal_set_update",
            "UPDATE extraction_proposal_sets SET retained_at=retained_at",
            "immutable extraction proposal set",
        ),
        (
            "immutable_extraction_proposal_update",
            "UPDATE extraction_proposals SET retained_at=retained_at",
            "immutable extraction proposal",
        ),
        (
            "immutable_extraction_evidence_update",
            "UPDATE extraction_proposal_evidence SET end_byte=end_byte",
            "immutable extraction proposal evidence",
        ),
    ),
)
def test_sqlite_immutable_guards_reject_mutation(
    tmp_path: Path,
    trigger: str,
    statement: str,
    match: str,
) -> None:
    state, _result = _seed_complete(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
            (trigger,),
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match=match):
            conn.execute(statement)
    finally:
        conn.close()


def test_timeout_failure_guard_and_reopen_integrity_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, result = _seed_timeout(tmp_path, monkeypatch)
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(
            conn, "immutable_extraction_run_version_update"
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            conn.execute(
                "UPDATE extraction_run_versions SET outcome='BLOCKING_FAILURE' "
                "WHERE run_version_id=?",
                (str(result.request.run_version_id),),
            )

        row = conn.execute(
            "SELECT canonical_bytes FROM extraction_run_versions "
            "WHERE run_version_id=?",
            (str(result.request.run_version_id),),
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row[0]).decode("utf-8"))
        value["outcome"] = "BLOCKING_FAILURE"
        data = canonical_json_bytes(value)
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(
            "UPDATE extraction_run_versions SET outcome=?,canonical_bytes=?,"
            "canonical_digest=? WHERE run_version_id=?",
            (
                "BLOCKING_FAILURE",
                data,
                digest_bytes(data),
                str(result.request.run_version_id),
            ),
        )
        conn.execute(trigger)
        conn.execute("PRAGMA ignore_check_constraints=OFF")
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(
        state,
        "CHECK constraint failed in extraction_run_versions|"
        "incompatible with its outcome",
    )


def test_reopen_rejects_output_contract_and_retention_tamper(
    tmp_path: Path,
) -> None:
    state, result = _seed_complete(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(conn, "immutable_extraction_output_update")
        conn.execute(
            "UPDATE extraction_outputs SET schema_contract_digest=?,retained_at=? "
            "WHERE output_id=?",
            (
                "sha256:" + "0" * 64,
                "2042-03-12T10:00:01.000000Z",
                str(result.output.output_id),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(state, "structured output lineage")


def test_reopen_rejects_proposal_set_contract_tamper_even_when_rehashed(
    tmp_path: Path,
) -> None:
    state, result = _seed_complete(tmp_path)
    assert result.proposal_set is not None
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(
            conn, "immutable_extraction_proposal_set_update"
        )
        row = conn.execute(
            "SELECT canonical_bytes FROM extraction_proposal_sets "
            "WHERE proposal_set_id=?",
            (str(result.proposal_set.proposal_set_id),),
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row[0]).decode("utf-8"))
        tampered_digest = "sha256:" + "1" * 64
        value["producer_contract_digest"] = tampered_digest
        data = canonical_json_bytes(value)
        conn.execute(
            "UPDATE extraction_proposal_sets SET producer_contract_digest=?,"
            "canonical_bytes=?,canonical_digest=? WHERE proposal_set_id=?",
            (
                tampered_digest,
                data,
                digest_bytes(data),
                str(result.proposal_set.proposal_set_id),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(state, "proposal-set canonical record")


def test_reopen_rejects_evidence_range_beyond_passage_even_when_rehashed(
    tmp_path: Path,
) -> None:
    state, _result = _seed_complete(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(conn, "immutable_extraction_evidence_update")
        row = conn.execute(
            "SELECT e.*,p.byte_length FROM extraction_proposal_evidence e "
            "JOIN extraction_run_passages p "
            "ON p.run_id=e.run_id AND p.passage_id=e.passage_id "
            "ORDER BY e.proposal_id,e.evidence_ordinal LIMIT 1"
        ).fetchone()
        assert row is not None
        column_names = [item[0] for item in conn.execute(
            "SELECT e.*,p.byte_length FROM extraction_proposal_evidence e "
            "JOIN extraction_run_passages p "
            "ON p.run_id=e.run_id AND p.passage_id=e.passage_id LIMIT 0"
        ).description]
        values = dict(zip(column_names, row, strict=True))
        end_byte = int(values["byte_length"]) + 1
        canonical = {
            "proposal_id": str(values["proposal_id"]),
            "evidence_ordinal": int(values["evidence_ordinal"]),
            "run_id": str(values["run_id"]),
            "passage_id": str(values["passage_id"]),
            "start_byte": int(values["start_byte"]),
            "end_byte": end_byte,
            "evidence_text_digest": str(values["evidence_text_digest"]),
        }
        data = canonical_json_bytes(canonical)
        conn.execute(
            "UPDATE extraction_proposal_evidence SET end_byte=?,"
            "canonical_bytes=?,canonical_digest=? "
            "WHERE proposal_id=? AND evidence_ordinal=?",
            (
                end_byte,
                data,
                digest_bytes(data),
                str(values["proposal_id"]),
                int(values["evidence_ordinal"]),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(state, "evidence normalized columns|exceeds")


def test_reopen_rejects_stable_run_budget_and_creation_lineage_tamper(
    tmp_path: Path,
) -> None:
    state, result = _seed_complete(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(conn, "immutable_extraction_run_update")
        budget = {"timeout_ms": 1}
        budget_bytes = canonical_json_bytes(budget)
        conn.execute(
            "UPDATE extraction_runs SET budget_bytes=?,budget_digest=?,created_at=? "
            "WHERE run_id=?",
            (
                budget_bytes,
                digest_bytes(budget_bytes),
                "2042-03-12T10:00:01.000000Z",
                str(result.request.run_id),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(
        state, "budget_digest|stable run canonical bytes|creation lineage"
    )


def test_reopen_rejects_missing_evidence_and_inconsistent_run_head(
    tmp_path: Path,
) -> None:
    missing_state, _result = _seed_complete(tmp_path / "missing")
    conn = sqlite3.connect(missing_state.database)
    try:
        trigger = _disable_trigger(conn, "immutable_extraction_evidence_delete")
        identity = conn.execute(
            "SELECT proposal_id,evidence_ordinal "
            "FROM extraction_proposal_evidence LIMIT 1"
        ).fetchone()
        assert identity is not None
        conn.execute(
            "DELETE FROM extraction_proposal_evidence "
            "WHERE proposal_id=? AND evidence_ordinal=?",
            identity,
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(missing_state, "evidence|count")

    head_state, result = _seed_complete(tmp_path / "head")
    conn = sqlite3.connect(head_state.database)
    try:
        trigger = _disable_trigger(conn, "extraction_run_head_update_guard")
        conn.execute(
            "UPDATE extraction_run_heads SET terminal=0 WHERE run_id=?",
            (str(result.request.run_id),),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()
    _expect_reopen_failure(head_state, "run head differs")


def test_proposal_records_cannot_precede_retained_output_and_set(
    tmp_path: Path,
) -> None:
    state, result = _seed_complete(tmp_path)
    assert result.proposal_set is not None
    conn = sqlite3.connect(state.database)
    conn.row_factory = sqlite3.Row
    try:
        set_row = conn.execute(
            "SELECT * FROM extraction_proposal_sets WHERE proposal_set_id=?",
            (str(result.proposal_set.proposal_set_id),),
        ).fetchone()
        assert set_row is not None
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO extraction_proposal_sets("
                "proposal_set_id,output_id,run_id,run_version_id,proposal_count,"
                "producer_contract_digest,canonical_bytes,canonical_digest,retained_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "00000000-0000-4000-8000-000000004999",
                    "00000000-0000-4000-8000-000000004998",
                    set_row["run_id"],
                    "00000000-0000-4000-8000-000000004997",
                    1,
                    set_row["producer_contract_digest"],
                    b"{}",
                    digest_bytes(b"{}"),
                    set_row["retained_at"],
                ),
            )
    finally:
        conn.close()
