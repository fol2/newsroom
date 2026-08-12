"""Checked v24 Story Candidate authority migration and exact-v23 backup gate."""
# ruff: noqa: E701,E702 - keep the immutable migration within #401's line cap

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import event_hypothesis_lineage_migrations as predecessor
from .canonical import digest_canonical

STORY_CANDIDATE_SCHEMA_VERSION = 24
STORY_CANDIDATE_MIGRATION_NAME = "story_candidate_authority_v24"
STORY_CANDIDATE_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:6c24d402f246f4e82a49a9772d70677d922282aae3b6dde93c62c0ef9b1b7a72"
)
STORY_CANDIDATE_PREDECESSOR_FINGERPRINT = (
    "sha256:c341333cf54d724bb4d2092bb9da81e9f3a434ddb03e6ddc14a51fdf2c6c1b52"
)


StoryCandidateBackupError = predecessor.EventHypothesisLineageBackupError
StoryCandidateBackupReceipt = predecessor.EventHypothesisLineageBackupReceipt
StoryCandidateMigrationRecord = predecessor.EventHypothesisLineageMigrationRecord


# fmt: off
def story_candidate_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database); backup = source.with_name(source.name + ".pre-v24.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> StoryCandidateBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256"); digest = predecessor._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise StoryCandidateBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (target.execute("PRAGMA user_version").fetchone()[0] != 23
            or predecessor._schema_fingerprint(target) != STORY_CANDIDATE_PREDECESSOR_FINGERPRINT
            or predecessor._logical_database_digest(target) != logical):
            raise StoryCandidateBackupError("backup differs from source")
    finally: target.close()
    return StoryCandidateBackupReceipt(path, digest_path, digest, logical)


def prepare_story_candidate_backup(connection: sqlite3.Connection, backup_path: Path) -> StoryCandidateBackupReceipt:
    if (connection.in_transaction or connection.execute("PRAGMA user_version").fetchone()[0] != 23
        or predecessor._schema_fingerprint(connection) != STORY_CANDIDATE_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path) or not backup_path.is_absolute()):
        raise StoryCandidateBackupError("backup requires checked schema v23")
    source = Path(next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"))
    digest_path = backup_path.with_name(backup_path.name + ".sha256"); logical = predecessor._logical_database_digest(connection)
    if not source or source.resolve() == backup_path.resolve() or backup_path.exists() != digest_path.exists():
        raise StoryCandidateBackupError("backup boundary differs")
    if not backup_path.exists():
        backup_path.open("xb").close(); target = sqlite3.connect(backup_path, isolation_level=None)
        try: connection.backup(target)
        finally: target.close()
        digest_path.write_text(predecessor._file_digest(backup_path) + "\n", encoding="ascii")
    receipt = _checked_backup(backup_path, logical)
    connection.execute("CREATE TEMP TABLE IF NOT EXISTS story_candidate_backup_gate(backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT")
    connection.execute("DELETE FROM story_candidate_backup_gate")
    connection.execute("INSERT INTO story_candidate_backup_gate VALUES(?,?,?)", (str(backup_path), receipt.backup_digest, logical))
    if connection.in_transaction: connection.commit()
    return receipt


def require_story_candidate_backup(connection: sqlite3.Connection, *, expected_history: tuple[tuple[int, str, str], ...]) -> StoryCandidateBackupReceipt:
    try: row = connection.execute("SELECT backup_path,backup_digest,logical_digest FROM temp.story_candidate_backup_gate").fetchone()
    except sqlite3.OperationalError as exc: raise StoryCandidateBackupError("v23 to v24 requires prepared backup") from exc
    if row is None or predecessor._logical_database_digest(connection) != row[2]:
        raise StoryCandidateBackupError("v23 to v24 requires prepared backup")
    receipt = _checked_backup(Path(row[0]), str(row[2])); target = sqlite3.connect(f"file:{receipt.backup_path}?mode=ro", uri=True, isolation_level=None)
    try: history = target.execute("SELECT version,name,checksum FROM authority_migrations ORDER BY version").fetchall()
    finally: target.close()
    if receipt.backup_digest != row[1] or history != list(expected_history):
        raise StoryCandidateBackupError("prepared backup is not exact v23")
    return receipt
# fmt: on


D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
U = "length({0})=36 AND substr({0},15,1)='4' AND lower(substr({0},20,1)) IN ('8','9','a','b')"
G = "length({0})=36 AND substr({0},15,1) IN ('1','2','3','4','5') AND lower(substr({0},20,1)) IN ('8','9','a','b')"
STORY_CANDIDATE_MIGRATION_STATEMENTS = (
    f"""CREATE TABLE story_candidate_admission_receipts_v2(
admission_digest TEXT PRIMARY KEY CHECK({D.format("admission_digest")}),request_id TEXT NOT NULL UNIQUE CHECK({U.format("request_id")}),request_digest TEXT NOT NULL UNIQUE CHECK({D.format("request_digest")}),actor_identity_digest TEXT NOT NULL CHECK({D.format("actor_identity_digest")}),idempotency_key TEXT NOT NULL,authority_aggregate_id TEXT NOT NULL CHECK({U.format("authority_aggregate_id")}),authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),committed_admission_decision_id TEXT NOT NULL UNIQUE CHECK({U.format("committed_admission_decision_id")}),admission_bytes BLOB NOT NULL,candidate_id TEXT NOT NULL CHECK({U.format("candidate_id")}),candidate_bytes BLOB,version_id TEXT NOT NULL UNIQUE CHECK({U.format("version_id")}),version_ordinal INTEGER NOT NULL CHECK(version_ordinal BETWEEN 1 AND 9007199254740991),version_bytes BLOB NOT NULL,version_digest TEXT NOT NULL UNIQUE CHECK({D.format("version_digest")}),previous_version_id TEXT,previous_version_digest TEXT CHECK(previous_version_digest IS NULL OR {D.format("previous_version_digest")}),manifest_material_digest TEXT NOT NULL CHECK({D.format("manifest_material_digest")}),semantic_scope_digest TEXT NOT NULL CHECK({D.format("semantic_scope_digest")}),hypothesis_version_id TEXT NOT NULL CHECK({G.format("hypothesis_version_id")}),relationship_assessment_digest TEXT NOT NULL CHECK({D.format("relationship_assessment_digest")}),disposition_ids_bytes BLOB NOT NULL,collision_request_bytes BLOB NOT NULL,collision_request_digest TEXT NOT NULL CHECK({D.format("collision_request_digest")}),collision_decision_bytes BLOB NOT NULL,collision_decision_digest TEXT NOT NULL CHECK({D.format("collision_decision_digest")}),comparator_collision_request_bytes BLOB,comparator_collision_request_digest TEXT CHECK(comparator_collision_request_digest IS NULL OR {D.format("comparator_collision_request_digest")}),comparator_collision_decision_bytes BLOB,comparator_collision_decision_digest TEXT CHECK(comparator_collision_decision_digest IS NULL OR {D.format("comparator_collision_decision_digest")}),recorded_at TEXT NOT NULL,UNIQUE(actor_identity_digest,idempotency_key),UNIQUE(candidate_id,version_ordinal),UNIQUE(candidate_id,version_id),FOREIGN KEY(candidate_id,previous_version_id) REFERENCES story_candidate_admission_receipts_v2(candidate_id,version_id),CHECK(authority_aggregate_id=candidate_id),CHECK(committed_admission_decision_id NOT IN(authority_event_id,candidate_id,version_id)),CHECK(version_id!=candidate_id),CHECK((version_ordinal=1 AND candidate_bytes IS NOT NULL) OR (version_ordinal>1 AND candidate_bytes IS NULL)),CHECK((version_ordinal=1 AND previous_version_id IS NULL AND previous_version_digest IS NULL) OR (version_ordinal>1 AND previous_version_id IS NOT NULL AND previous_version_digest IS NOT NULL)),CHECK((comparator_collision_request_bytes IS NULL AND comparator_collision_request_digest IS NULL AND comparator_collision_decision_bytes IS NULL AND comparator_collision_decision_digest IS NULL) OR (comparator_collision_request_bytes IS NOT NULL AND comparator_collision_request_digest IS NOT NULL AND comparator_collision_decision_bytes IS NOT NULL AND comparator_collision_decision_digest IS NOT NULL))) STRICT""",
    f"""CREATE TABLE story_candidate_collision_bindings(collision_namespace TEXT NOT NULL,collision_key_digest TEXT NOT NULL CHECK({D.format("collision_key_digest")}),candidate_id TEXT NOT NULL CHECK({U.format("candidate_id")}),semantic_scope_digest TEXT NOT NULL CHECK({D.format("semantic_scope_digest")}),admission_digest TEXT NOT NULL UNIQUE REFERENCES story_candidate_admission_receipts_v2(admission_digest),initial_request_digest TEXT NOT NULL CHECK({D.format("initial_request_digest")}),initial_decision_digest TEXT NOT NULL CHECK({D.format("initial_decision_digest")}),initial_decision_bytes BLOB NOT NULL,PRIMARY KEY(collision_namespace,collision_key_digest),UNIQUE(candidate_id),UNIQUE(semantic_scope_digest)) STRICT""",
    f"""CREATE TABLE story_candidate_heads(candidate_id TEXT PRIMARY KEY CHECK({U.format("candidate_id")}),candidate_bytes BLOB NOT NULL,semantic_scope_digest TEXT NOT NULL UNIQUE CHECK({D.format("semantic_scope_digest")}),current_version_id TEXT NOT NULL UNIQUE CHECK({U.format("current_version_id")}),current_version_ordinal INTEGER NOT NULL CHECK(current_version_ordinal BETWEEN 1 AND 9007199254740991),current_version_digest TEXT NOT NULL UNIQUE CHECK({D.format("current_version_digest")}),current_admission_digest TEXT NOT NULL UNIQUE REFERENCES story_candidate_admission_receipts_v2(admission_digest),collision_namespace TEXT NOT NULL,collision_key_digest TEXT NOT NULL CHECK({D.format("collision_key_digest")}),updated_at TEXT NOT NULL,FOREIGN KEY(collision_namespace,collision_key_digest) REFERENCES story_candidate_collision_bindings(collision_namespace,collision_key_digest)) STRICT""",
    "CREATE TRIGGER immutable_candidate_receipt BEFORE UPDATE ON story_candidate_admission_receipts_v2 BEGIN SELECT RAISE(ABORT,'immutable Candidate receipt'); END",
    "CREATE TRIGGER retained_candidate_receipt BEFORE DELETE ON story_candidate_admission_receipts_v2 BEGIN SELECT RAISE(ABORT,'retained Candidate receipt'); END",
    "CREATE TRIGGER immutable_candidate_collision BEFORE UPDATE ON story_candidate_collision_bindings BEGIN SELECT RAISE(ABORT,'immutable Candidate collision'); END",
    "CREATE TRIGGER retained_candidate_collision BEFORE DELETE ON story_candidate_collision_bindings BEGIN SELECT RAISE(ABORT,'retained Candidate collision'); END",
    "CREATE TRIGGER retained_candidate_head BEFORE DELETE ON story_candidate_heads BEGIN SELECT RAISE(ABORT,'retained Candidate head'); END",
    "CREATE TRIGGER candidate_head_insert_guard BEFORE INSERT ON story_candidate_heads WHEN NOT EXISTS(SELECT 1 FROM story_candidate_admission_receipts_v2 r JOIN story_candidate_collision_bindings b ON b.admission_digest=r.admission_digest WHERE r.admission_digest=NEW.current_admission_digest AND r.candidate_id=NEW.candidate_id AND r.candidate_bytes=NEW.candidate_bytes AND r.version_id=NEW.current_version_id AND r.version_ordinal=1 AND r.version_digest=NEW.current_version_digest AND r.semantic_scope_digest=NEW.semantic_scope_digest AND r.recorded_at=NEW.updated_at AND b.candidate_id=NEW.candidate_id AND b.collision_namespace=NEW.collision_namespace AND b.collision_key_digest=NEW.collision_key_digest) BEGIN SELECT RAISE(ABORT,'Candidate head admission differs'); END",
    "CREATE TRIGGER candidate_head_update_guard BEFORE UPDATE ON story_candidate_heads WHEN NEW.candidate_id!=OLD.candidate_id OR NEW.candidate_bytes!=OLD.candidate_bytes OR NEW.semantic_scope_digest!=OLD.semantic_scope_digest OR NEW.collision_namespace!=OLD.collision_namespace OR NEW.collision_key_digest!=OLD.collision_key_digest OR NEW.current_version_ordinal!=OLD.current_version_ordinal+1 OR NOT EXISTS(SELECT 1 FROM story_candidate_admission_receipts_v2 r WHERE r.admission_digest=NEW.current_admission_digest AND r.candidate_id=NEW.candidate_id AND r.version_id=NEW.current_version_id AND r.version_ordinal=NEW.current_version_ordinal AND r.version_digest=NEW.current_version_digest AND r.semantic_scope_digest=NEW.semantic_scope_digest AND r.previous_version_id=OLD.current_version_id AND r.previous_version_digest=OLD.current_version_digest AND r.recorded_at=NEW.updated_at) BEGIN SELECT RAISE(ABORT,'Candidate head transition differs'); END",
)
STORY_CANDIDATE_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": 24,
        "name": STORY_CANDIDATE_MIGRATION_NAME,
        "statements": list(STORY_CANDIDATE_MIGRATION_STATEMENTS),
    }
)
STORY_CANDIDATE_MIGRATION = StoryCandidateMigrationRecord(
    24, STORY_CANDIDATE_MIGRATION_NAME, STORY_CANDIDATE_MIGRATION_CHECKSUM
)
__all__ = [
    n
    for n in globals()
    if n.startswith(("STORY_", "Story", "story_", "prepare_", "require_"))
]
