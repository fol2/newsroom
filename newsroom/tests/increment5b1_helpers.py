from __future__ import annotations

from pathlib import Path
import sqlite3

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5.branch_contracts import (
    CANDIDATE_COLLISION_POLICY_ID,
    EXACT_BRANCH_POLICY_ID,
    BranchReceiptId,
    BranchRequestId,
    CandidateCollisionRequest,
    ExactBranchRequest,
    ExactLookupKind,
)
from newsroom.increment5.decision import INCREMENT_5A_CONTRACT_DIGEST
from newsroom.increment5.exact_retriever import SQLiteExactRetriever
from newsroom.increment5.receipt_journal import BranchReceiptJournal


NOW = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
EARLIER = UtcTimestamp.parse("2042-03-11T12:00:00.000000Z")
LATER = UtcTimestamp.parse("2042-03-13T12:00:00.000000Z")


def _digest(label: str) -> str:
    return digest_canonical({"label": label})


def _create_authority(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE ledger_events(
                ledger_seq INTEGER PRIMARY KEY,
                recorded_at TEXT NOT NULL
            ) STRICT;
            CREATE TABLE source_definition_versions(
                version_id TEXT NOT NULL,
                definition_id TEXT NOT NULL,
                allowed_use TEXT NOT NULL,
                lifecycle_stage TEXT NOT NULL,
                PRIMARY KEY(version_id,definition_id)
            ) WITHOUT ROWID, STRICT;
            CREATE TABLE source_definition_version_heads(
                definition_id TEXT PRIMARY KEY,
                current_version_id TEXT NOT NULL
            ) STRICT;
            CREATE TABLE source_items(
                item_id TEXT PRIMARY KEY,
                definition_id TEXT NOT NULL,
                definition_version_id TEXT NOT NULL,
                source_native_id TEXT,
                identity_digest TEXT NOT NULL,
                authority_event_id TEXT NOT NULL
            ) STRICT;
            CREATE TABLE source_revisions(
                revision_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                definition_id TEXT NOT NULL,
                definition_version_id TEXT NOT NULL,
                source_native_revision_token TEXT,
                revision_identity_digest TEXT NOT NULL
            ) STRICT;
            CREATE TABLE discovery_representations(
                representation_id TEXT PRIMARY KEY,
                revision_id TEXT NOT NULL,
                definition_id TEXT NOT NULL,
                definition_version_id TEXT NOT NULL,
                representation_identity_digest TEXT NOT NULL
            ) STRICT;
            CREATE TABLE canonical_entities(
                entity_id TEXT PRIMARY KEY,
                authority_event_id TEXT NOT NULL,
                canonical_digest TEXT NOT NULL
            ) STRICT;
            CREATE TABLE canonical_entity_heads(
                entity_id TEXT PRIMARY KEY,
                lifecycle TEXT NOT NULL
            ) STRICT;
            CREATE TABLE entity_aliases(
                alias_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                alias_text TEXT NOT NULL,
                resolution_decision_id TEXT NOT NULL,
                canonical_digest TEXT NOT NULL,
                valid_from TEXT,
                valid_until TEXT
            ) STRICT;
            CREATE TABLE development_candidates_v2(
                candidate_id TEXT PRIMARY KEY,
                semantic_collision_digest TEXT NOT NULL UNIQUE
            ) STRICT;
            CREATE TABLE development_candidate_versions_v2(
                candidate_version_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                canonical_process_id TEXT NOT NULL,
                canonical_digest TEXT NOT NULL
            ) STRICT;
            """
        )
        connection.executemany(
            "INSERT INTO ledger_events(ledger_seq,recorded_at) VALUES(?,?)",
            [(1, EARLIER.to_text()), (2, EARLIER.to_text()), (3, NOW.to_text())],
        )
        connection.executemany(
            "INSERT INTO source_definition_versions VALUES(?,?,?,?)",
            [
                ("source-v1", "source-a", "RETRIEVAL_ALLOWED", "PRODUCTION_ELIGIBLE"),
                ("source-v2", "source-b", "PROHIBITED", "RETIRED"),
            ],
        )
        connection.executemany(
            "INSERT INTO source_definition_version_heads VALUES(?,?)",
            [("source-a", "source-v1"), ("source-b", "source-v2")],
        )
        connection.executemany(
            "INSERT INTO source_items VALUES(?,?,?,?,?,?)",
            [
                ("item-a", "source-a", "source-v1", "native-42", _digest("item-a"), "event-a"),
                ("item-blocked", "source-b", "source-v2", "blocked-42", _digest("item-b"), "event-b"),
            ],
        )
        connection.executemany(
            "INSERT INTO source_revisions VALUES(?,?,?,?,?,?)",
            [
                ("revision-a", "item-a", "source-a", "source-v1", "native-revision-a", _digest("revision-a")),
                ("revision-b", "item-a", "source-a", "source-v1", "revision-a", _digest("revision-b")),
            ],
        )
        connection.execute(
            "INSERT INTO discovery_representations VALUES(?,?,?,?,?)",
            ("representation-a", "revision-a", "source-a", "source-v1", _digest("representation-a")),
        )
        connection.executemany(
            "INSERT INTO canonical_entities VALUES(?,?,?)",
            [
                ("entity-active", "event-entity-a", _digest("entity-active")),
                ("entity-retired", "event-entity-r", _digest("entity-retired")),
            ],
        )
        connection.executemany(
            "INSERT INTO canonical_entity_heads VALUES(?,?)",
            [("entity-active", "ACTIVE"), ("entity-retired", "RETIRED")],
        )
        connection.executemany(
            "INSERT INTO entity_aliases VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    "alias-active",
                    "entity-active",
                    "synthetic authority",
                    "Synthetic Authority",
                    "resolution-a",
                    _digest("alias-active"),
                    EARLIER.to_text(),
                    LATER.to_text(),
                ),
                (
                    "alias-retired",
                    "entity-retired",
                    "synthetic authority",
                    "Synthetic Authority",
                    "resolution-r",
                    _digest("alias-retired"),
                    EARLIER.to_text(),
                    LATER.to_text(),
                ),
            ],
        )
        connection.execute(
            "INSERT INTO development_candidates_v2 VALUES(?,?)",
            ("candidate-a", _digest("collision-a")),
        )
        connection.execute(
            "INSERT INTO development_candidate_versions_v2 VALUES(?,?,?,?)",
            ("candidate-version-a", "candidate-a", "formal-process-a", _digest("candidate-version-a")),
        )


def _request(
    *,
    key: str = "exact-request-a",
    kind: ExactLookupKind = ExactLookupKind.SOURCE_NATIVE_ID,
    value: str = "native-42",
    policy_id: str = EXACT_BRANCH_POLICY_ID,
    contract_digest: str = INCREMENT_5A_CONTRACT_DIGEST,
    query_valid_time: UtcTimestamp = NOW,
    authority_scope_id: str | None = None,
    minimum_ledger_seq: int = 3,
) -> ExactBranchRequest:
    return ExactBranchRequest(
        request_id=BranchRequestId.parse("00000000-0000-4000-8000-000000005101"),
        idempotency_key=key,
        actor_id="retrieval_worker",
        purpose="exact_identity_lookup",
        policy_id=policy_id,
        contract_digest=contract_digest,
        lookup_kind=kind,
        lookup_value=value,
        authority_scope_id=(
            authority_scope_id
            if authority_scope_id is not None
            else "source-a"
            if kind is ExactLookupKind.SOURCE_NATIVE_ID
            else "item-a"
            if kind is ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN
            else None
        ),
        query_valid_time=query_valid_time,
        serving_time=NOW,
        minimum_ledger_seq=minimum_ledger_seq,
    )


def _collision_request(
    *,
    key: str = "collision-request-a",
    digest: str | None = None,
    minimum_ledger_seq: int = 3,
) -> CandidateCollisionRequest:
    return CandidateCollisionRequest(
        request_id=BranchRequestId.parse("00000000-0000-4000-8000-000000005102"),
        idempotency_key=key,
        actor_id="candidate_controller",
        purpose="candidate_collision_check",
        policy_id=CANDIDATE_COLLISION_POLICY_ID,
        contract_digest=INCREMENT_5A_CONTRACT_DIGEST,
        semantic_collision_digest=digest or _digest("collision-a"),
        query_valid_time=NOW,
        serving_time=NOW,
        minimum_ledger_seq=minimum_ledger_seq,
    )


def _system(tmp_path: Path) -> tuple[Path, Path, SQLiteExactRetriever]:
    authority = tmp_path / "authority.sqlite3"
    journal_path = tmp_path / "receipts.sqlite3"
    _create_authority(authority)
    journal = BranchReceiptJournal(journal_path)
    ids = iter(
        [
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005201"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005202"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005203"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005204"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005205"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005206"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005207"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005208"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005209"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005210"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005211"),
            BranchReceiptId.parse("00000000-0000-4000-8000-000000005212"),
        ]
    )
    system = SQLiteExactRetriever(
        authority_database=authority,
        journal=journal,
        receipt_id_factory=lambda: next(ids),
    )
    return authority, journal_path, system
