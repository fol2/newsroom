from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError
from newsroom.authority._projection_store import _ProjectionAuthorityStore
from newsroom.projection import (
    ProjectionDeliveryOutcome, ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest, ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
)

from .projection_b1_helpers import FAMILY_ID, open_projection_system, projection_contracts, proof
from .test_projection_b1_authority import _source_command


def _seed(path):
    with open_projection_system(path) as system:
        system.projections.register_family(
            ProjectionFamilyRegistrationRequest(FAMILY_ID, "family"), proof=proof(),
        )
        sources = []
        for index in range(3):
            system.commands.execute(_source_command(key=f"source-{index}"), proof=proof())
        sources = [event for event in system.events.after(0, limit=100, proof=proof())
                   if event.event_type == "source.item.versioned"]
        for index in (1, 2):
            generation = system.projections.create_generation(
                ProjectionGenerationCreateRequest(
                    ProjectionGenerationId.parse(f"00000000-0000-4000-8000-{index:012d}"),
                    FAMILY_ID, "INITIAL_BUILD", f"generation-{index}",
                ), proof=proof(),
            )
            for source in sources:
                for ordinal, outcome in enumerate((
                    ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                    ProjectionDeliveryOutcome.APPLIED,
                ), 1):
                    current = next(item for item in system.projections.generations(FAMILY_ID, proof=proof())
                                   if item.generation_id == generation.generation_id)
                    system.projections.record_delivery(ProjectionDeliveryRequest(
                        generation.generation_id, current.authority_aggregate_version,
                        source.ledger_seq, outcome, f"delivery-{index}-{source.ledger_seq}-{ordinal}",
                        error_code="TRANSIENT" if ordinal == 1 else None,
                    ), proof=proof())


class _StreamingCursor:
    def __init__(self, cursor, connection, kind):
        self.cursor, self.connection, self.kind = cursor, connection, kind

    def __iter__(self):
        for row in self.cursor:
            self.connection.yielded[self.kind] += 1
            # Two attempts per delivery, with at most one next-group lookahead.
            assert self.connection.yielded["attempt"] <= 2 * self.connection.yielded["state"] + 1
            yield row

    def fetchall(self):
        raise AssertionError("projection delivery validation must stream rows")


class _StreamingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.yielded = {"attempt": 0, "state": 0}

    def execute(self, sql, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        for table, kind in (("projection_delivery_attempts", "attempt"), ("projection_delivery_states", "state")):
            if " ".join(sql.split()).startswith(f"SELECT * FROM {table}"):
                return _StreamingCursor(cursor, self, kind)
        return cursor


def _probe():
    probe = object.__new__(_ProjectionAuthorityStore)
    probe._projection_contracts = projection_contracts()
    return probe


def test_projection_delivery_open_streams_attempts_and_heads_together(tmp_path):
    path = tmp_path / "authority.sqlite3"
    _seed(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        streaming = _StreamingConnection(connection)
        probe = _probe()
        verified = []

        def verify_source(conn, row):
            verified.append(("attempt" if "attempt_number" in row.keys() else "state",
                             row["generation_id"], row["ledger_seq"]))
            return _ProjectionAuthorityStore._require_delivery_source_integrity(conn, row)

        probe._require_delivery_source_integrity = verify_source
        probe._validate_projection_delivery_rows(streaming)
        assert streaming.yielded == {"attempt": 12, "state": 6}
        assert len(verified) == 18
        assert len(set(verified)) == 12
    with open_projection_system(path):
        pass


@pytest.mark.parametrize("fault,reason", (
    ("attempt-source", "source provenance"),
    ("state-source", "source provenance"),
    ("mapping", "retained mapping"),
    ("required", "required flag"),
    ("gap", "not contiguous"),
    ("count", "not contiguous"),
    ("latest", "head differs"),
    ("finalized", "finalized state"),
    ("orphan", "lacks a delivery head"),
    ("missing-attempts", "not contiguous"),
))
@pytest.mark.parametrize("position", (0, 3, 5))
def test_streamed_delivery_validation_preserves_corruption_guards(tmp_path, fault, reason, position):
    path = tmp_path / "authority.sqlite3"
    _seed(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        keys = connection.execute(
            "SELECT generation_id,ledger_seq FROM projection_delivery_states ORDER BY generation_id,ledger_seq"
        ).fetchall()
        key = tuple(keys[position])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN "
            "('projection_delivery_attempts','projection_delivery_states')"
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{row[0]}"')
        changes = {
            "attempt-source": "UPDATE projection_delivery_attempts SET source_event_digest='sha256:' || printf('%064d',0)",
            "state-source": "UPDATE projection_delivery_states SET source_event_digest='sha256:' || printf('%064d',0)",
            "mapping": "UPDATE projection_delivery_attempts SET outcome='IGNORED_OPTIONAL'",
            "required": "UPDATE projection_delivery_attempts SET required=0",
            "gap": "UPDATE projection_delivery_attempts SET attempt_number=attempt_number+10",
            "count": "UPDATE projection_delivery_states SET attempt_count=attempt_count+1",
            "latest": "UPDATE projection_delivery_states SET last_error_code='FORGED'",
            "finalized": "UPDATE projection_delivery_states SET finalized=0",
            "orphan": "DELETE FROM projection_delivery_states",
            "missing-attempts": "DELETE FROM projection_delivery_attempts",
        }
        connection.execute(changes[fault] + " WHERE generation_id=? AND ledger_seq=?", key)
        with pytest.raises(AuthorityPersistenceError, match=reason):
            _probe()._validate_projection_delivery_rows(connection)
