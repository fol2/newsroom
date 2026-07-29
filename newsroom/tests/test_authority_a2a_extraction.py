from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

from newsroom.extraction import ExtractionOutcome

from .extraction_4a_helpers import (
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)


def test_extraction_commands_retain_exact_authority_event_envelopes(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        contract = system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        run = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )

    assert run.outcome is ExtractionOutcome.SUCCESS
    with closing(sqlite3.connect(state.database)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT c.command_type,c.aggregate_type,c.aggregate_id,"
            "c.authentication_context_id,c.authorization_request_digest,"
            "c.authorization_decision_id,c.result_digest,e.event_id,"
            "e.event_type,e.aggregate_version,e.payload_mode,e.payload_digest,"
            "e.security_scope,e.retention_scope,e.trust_scope "
            "FROM authority_commands c JOIN ledger_events e USING(command_id) "
            "WHERE c.command_type IN(?,?) ORDER BY e.ledger_seq",
            ("extraction.contract.register", "extraction.run.execute"),
        ).fetchall()

    assert len(rows) == 2
    registered, executed = rows
    assert registered["event_id"] == str(contract.event_id)
    assert registered["event_type"] == "extraction.contract.registered"
    assert registered["aggregate_type"] == "extractor_contract"
    assert registered["aggregate_version"] == 1
    assert registered["trust_scope"] == "ADMITTED"

    assert executed["event_id"] == str(run.event_id)
    assert executed["event_type"] == "extraction.run.executed"
    assert executed["aggregate_type"] == "extraction_run_version"
    assert executed["aggregate_version"] == 1
    assert executed["trust_scope"] == "PROPOSED"
    for row in rows:
        assert row["payload_mode"] == "INLINE"
        assert row["payload_digest"].startswith("sha256:")
        assert row["result_digest"].startswith("sha256:")
        assert row["authentication_context_id"]
        assert row["authorization_request_digest"].startswith("sha256:")
        assert row["authorization_decision_id"]
        assert row["security_scope"] == "authority.extraction"
        assert row["retention_scope"] == "authority.audit"
