from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.editorial_relation_migrations import (
    EDITORIAL_PREDICATE_REGISTRY_CANONICAL_BYTES,
    EDITORIAL_PREDICATE_REGISTRY_DIGEST,
    EDITORIAL_PREDICATE_REGISTRY_VERSION,
    EDITORIAL_RELATION_MIGRATION_CHECKSUM,
    EDITORIAL_RELATION_MIGRATION_NAME,
    EDITORIAL_RELATION_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.relations.editorial_models import EDITORIAL_PREDICATE_REGISTRY_V1

from .editorial_relation_4c_migration_helpers import (
    downgrade_empty_editorial_relation_schema_to_v14,
)
from .entity_4b_helpers import (
    EN_MENTION_ID,
    mention_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof


EDITORIAL_RELATION_TABLES = {
    "editorial_predicate_contracts",
    "editorial_predicate_endpoint_pairs",
    "editorial_predicate_registries",
    "editorial_relation_assertion_heads",
    "editorial_relation_assertions",
    "editorial_relation_decision_heads",
    "editorial_relation_decisions",
    "editorial_relation_endpoints",
    "editorial_relation_evidence_items",
    "editorial_relation_extraction_evidence",
    "editorial_relation_projection_events",
    "editorial_relation_proposal_heads",
    "editorial_relation_proposal_versions",
    "editorial_relation_proposals",
    "editorial_relation_resolution_dependencies",
    "editorial_relation_supersessions",
    "editorial_relation_workflow_evidence",
}

REQUIRED_EDITORIAL_RELATION_TRIGGERS = {
    "editorial_relation_proposal_contract_guard",
    "editorial_relation_proposal_version_chain_guard",
    "editorial_relation_decision_chain_guard",
    "editorial_relation_assertion_admission_guard",
    "editorial_relation_supersession_guard",
    "editorial_relation_projection_event_guard",
    "editorial_extraction_evidence_kind_guard",
    "editorial_workflow_evidence_kind_guard",
    "immutable_editorial_relation_proposals_update",
    "immutable_editorial_relation_decisions_update",
    "immutable_editorial_relation_assertions_update",
}


def test_fresh_schema_v15_history_registry_tables_and_view_are_exact(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    conn = sqlite3.connect(state.extraction.database)
    try:
        assert EDITORIAL_RELATION_SCHEMA_VERSION == 15
        assert SCHEMA_VERSION == 20
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(conn) == EXPECTED_SCHEMA_FINGERPRINT
        assert conn.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=?",
            (EDITORIAL_RELATION_SCHEMA_VERSION,),
        ).fetchone() == (
            EDITORIAL_RELATION_MIGRATION_NAME,
            EDITORIAL_RELATION_MIGRATION_CHECKSUM,
        )
        assert conn.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)

        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'editorial_%'"
            ).fetchall()
        }
        assert tables == EDITORIAL_RELATION_TABLES
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name='editorial_current_admitted_relations'"
        ).fetchone() == ("editorial_current_admitted_relations",)
        triggers = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert REQUIRED_EDITORIAL_RELATION_TRIGGERS <= triggers

        assert conn.execute(
            "SELECT registry_version,canonical_bytes,canonical_digest "
            "FROM editorial_predicate_registries"
        ).fetchone() == (
            EDITORIAL_PREDICATE_REGISTRY_VERSION,
            EDITORIAL_PREDICATE_REGISTRY_CANONICAL_BYTES,
            EDITORIAL_PREDICATE_REGISTRY_DIGEST,
        )
        assert EDITORIAL_PREDICATE_REGISTRY_V1.digest == (
            EDITORIAL_PREDICATE_REGISTRY_DIGEST
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_predicate_contracts"
        ).fetchone()[0] == 9
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_predicate_endpoint_pairs"
        ).fetchone()[0] == sum(
            len(contract.allowed_endpoint_pairs)
            for contract in EDITORIAL_PREDICATE_REGISTRY_V1.contracts
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_checked_v14_to_v15_upgrade_preserves_extraction_and_entity_authority(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="relation-migration-preserved-mention",
            ),
            proof=extraction_proof(),
        )

    before = sqlite3.connect(state.extraction.database)
    try:
        retained_counts = {
            table: before.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "extraction_runs",
                "extraction_run_versions",
                "extraction_outputs",
                "extraction_proposals",
                "entity_mentions",
                "ledger_events",
            )
        }
    finally:
        before.close()

    downgrade_empty_editorial_relation_schema_to_v14(state.extraction.database)
    downgraded = sqlite3.connect(state.extraction.database)
    try:
        assert downgraded.execute("PRAGMA user_version").fetchone()[0] == 14
        assert downgraded.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=15"
        ).fetchone()[0] == 0
        assert downgraded.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='editorial_relation_proposals'"
        ).fetchone()[0] == 0
    finally:
        downgraded.close()

    with open_entity_system(state):
        pass

    after = sqlite3.connect(state.extraction.database)
    try:
        assert after.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(after) == EXPECTED_SCHEMA_FINGERPRINT
        assert {
            table: after.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in retained_counts
        } == retained_counts
        assert after.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=15"
        ).fetchone() == (
            EDITORIAL_RELATION_MIGRATION_NAME,
            EDITORIAL_RELATION_MIGRATION_CHECKSUM,
        )
        assert after.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        after.close()


def test_failed_v15_upgrade_rolls_back_without_partial_relation_schema(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    downgrade_empty_editorial_relation_schema_to_v14(state.extraction.database)
    conn = sqlite3.connect(state.extraction.database, isolation_level=None)
    try:
        conn.execute(
            "CREATE TABLE editorial_predicate_registries(conflict TEXT) STRICT"
        )
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            apply_pending_migrations(
                conn,
                applied_at="2042-03-12T10:00:00.000000Z",
            )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=15"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='editorial_relation_proposals'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='editorial_predicate_registries'"
        ).fetchone()[0] == (
            "CREATE TABLE editorial_predicate_registries(conflict TEXT) STRICT"
        )
    finally:
        conn.close()


def test_v15_registry_is_immutable_and_tampering_fails_checked_open(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    conn = sqlite3.connect(state.extraction.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE editorial_predicate_registries "
                "SET canonical_digest=?",
                ("sha256:" + "0" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            conn.execute(
                "DELETE FROM editorial_predicate_contracts "
                "WHERE predicate='DEVELOPMENT_OF'"
            )
    finally:
        conn.close()

    tampered = seed_entity_fixture(tmp_path / "history")
    conn = sqlite3.connect(tampered.extraction.database)
    try:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
            ("immutable_authority_migrations_update",),
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_update")
        conn.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=15",
            ("sha256:" + "0" * 64,),
        )
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="migration history"):
        open_entity_system(tampered)

    schema_tampered = seed_entity_fixture(tmp_path / "schema")
    conn = sqlite3.connect(schema_tampered.extraction.database)
    try:
        conn.execute("DROP TRIGGER editorial_relation_proposal_contract_guard")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="schema fingerprint"):
        open_entity_system(schema_tampered)
