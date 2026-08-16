"""Checked isolated SQLite schema for Increment 10 transport authority."""
from __future__ import annotations
import sqlite3
from newsroom.authority.canonical import digest_canonical

SCHEMA_VERSION=33
APPLICATION_ID=0x4E523130
MIGRATION_NAME="increment10_isolated_transport_v33"
_D="substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
TABLES=("increment10_meta","transport_submissions","transport_attempts","transport_audit")
STATEMENTS=(
 f"""CREATE TABLE increment10_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version INTEGER NOT NULL CHECK(schema_version=33),migration_name TEXT NOT NULL,migration_checksum TEXT NOT NULL CHECK({_D.format('migration_checksum')}),plan_digest TEXT NOT NULL CHECK({_D.format('plan_digest')})) STRICT""",
 f"""CREATE TABLE transport_submissions(submission_id TEXT PRIMARY KEY,semantic_key TEXT NOT NULL UNIQUE,canonical_bytes BLOB NOT NULL,canonical_digest TEXT NOT NULL UNIQUE CHECK({_D.format('canonical_digest')}),candidate_version_id TEXT NOT NULL,handoff_digest TEXT NOT NULL CHECK({_D.format('handoff_digest')}),plan_digest TEXT NOT NULL CHECK({_D.format('plan_digest')}),destination TEXT NOT NULL CHECK(destination='local://increment10/evidence-intake-fixture-v1'),created_epoch INTEGER NOT NULL,retry_due_epoch INTEGER NOT NULL,expiry_epoch INTEGER NOT NULL,status TEXT NOT NULL CHECK(status IN('NOT_STARTED','PENDING','ACCEPTED','REJECTED','PARTIAL','UNAVAILABLE','TIMED_OUT','AMBIGUOUS','RECONCILED')),CHECK(length(canonical_bytes)>0)) STRICT""",
 f"""CREATE TABLE transport_attempts(attempt_key TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES transport_submissions(submission_id),attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3),request_id TEXT NOT NULL,canonical_bytes BLOB NOT NULL,canonical_digest TEXT NOT NULL UNIQUE CHECK({_D.format('canonical_digest')}),state TEXT NOT NULL,observed_epoch INTEGER,acknowledgement_id TEXT,reconciliation_required INTEGER NOT NULL CHECK(reconciliation_required IN(0,1)),UNIQUE(submission_id,attempt_number),UNIQUE(submission_id,request_id),CHECK(length(canonical_bytes)>0)) STRICT""",
 f"""CREATE TABLE transport_audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_kind TEXT NOT NULL,subject_id TEXT NOT NULL,event_bytes BLOB NOT NULL,event_digest TEXT NOT NULL UNIQUE CHECK({_D.format('event_digest')}),recorded_epoch INTEGER NOT NULL,CHECK(length(event_bytes)>0)) STRICT""",
 "CREATE INDEX transport_due ON transport_submissions(status,retry_due_epoch,expiry_epoch)",
 "CREATE INDEX transport_reconcile ON transport_attempts(reconciliation_required,submission_id)",
 *tuple(f"CREATE TRIGGER immutable_{t} BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'immutable Increment 10 authority record'); END" for t in ("transport_attempts","transport_audit")),
 *tuple(f"CREATE TRIGGER retained_{t} BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'retained Increment 10 authority record'); END" for t in TABLES),
)
CHECKSUM=digest_canonical({"application_id":APPLICATION_ID,"version":SCHEMA_VERSION,"name":MIGRATION_NAME,"statements":list(STATEMENTS)})
PLAN_DIGEST="sha256:1f5088e1397bb394e60f3ed883517cec803442572cccba3892c9f8f6ab8abc89"
class Increment10MigrationError(ValueError): pass

def install(connection:sqlite3.Connection)->None:
    if connection.in_transaction or connection.execute("PRAGMA user_version").fetchone()[0]!=0 or connection.execute("SELECT count(*) FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]: raise Increment10MigrationError("installation requires an empty isolated database")
    try:
        connection.execute("BEGIN EXCLUSIVE")
        for statement in STATEMENTS: connection.execute(statement)
        connection.execute("INSERT INTO increment10_meta VALUES(1,?,?,?,?)",(SCHEMA_VERSION,MIGRATION_NAME,CHECKSUM,PLAN_DIGEST))
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}"); connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}"); connection.commit()
    except sqlite3.Error as exc:
        connection.rollback(); raise Increment10MigrationError("migration failed") from exc
    verify(connection)

def verify(connection:sqlite3.Connection)->None:
    names=tuple(r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name") if r[0]!="sqlite_sequence")
    if connection.execute("PRAGMA application_id").fetchone()[0]!=APPLICATION_ID or connection.execute("PRAGMA user_version").fetchone()[0]!=SCHEMA_VERSION or names!=tuple(sorted(TABLES)): raise Increment10MigrationError("isolated schema identity differs")
    if connection.execute("SELECT schema_version,migration_name,migration_checksum,plan_digest FROM increment10_meta").fetchone()!=(SCHEMA_VERSION,MIGRATION_NAME,CHECKSUM,PLAN_DIGEST): raise Increment10MigrationError("migration receipt differs")
    if connection.execute("PRAGMA quick_check").fetchone()[0]!="ok": raise Increment10MigrationError("integrity check differs")
