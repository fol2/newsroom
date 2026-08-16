import sqlite3
import pytest
from newsroom.authority.increment10_canary_migrations import *
from newsroom.increment10.transport import *
from newsroom.increment10.transport_store import *

def db():
 c=sqlite3.connect(":memory:",isolation_level=None); install(c); return c
def sub(): return create_submission(authority_token(),candidate_version_id="candidate-version:increment10-fixture-001",handoff_digest="sha256:"+"1"*64,plan_digest=PLAN_DIGEST,destination="local://increment10/evidence-intake-fixture-v1",created_epoch_seconds=10,retry=RetryPolicy(3,(1,2),100))

def test_checked_isolated_migration_and_downgrade_identity():
 c=db(); verify(c); assert c.execute("PRAGMA user_version").fetchone()[0]==33
 with pytest.raises(Increment10MigrationError): install(c)

def test_submission_idempotency_due_and_typed_facade():
 c=db(); store=TransportStore(c); first=store.put_submission(sub(),retry_due_epoch=20); second=store.put_submission(sub(),retry_due_epoch=20)
 assert first==second and store.due(20)==(first,)
 assert not hasattr(store,"connection")

def test_attempt_ambiguity_survives_restart_and_conflict_fails():
 c=db(); store=TransportStore(c); s=sub(); store.put_submission(s,retry_due_epoch=20)
 a=start_attempt(authority_token(),s,attempt_number=1,request_id="r1",persisted_epoch_seconds=20)
 a=observe(authority_token(),a,state=AttemptState.TIMED_OUT,observed_epoch_seconds=30)
 status=store.put_attempt(a); assert status.reconciliation_required
 restarted=TransportStore(c); assert restarted.status(s.submission_id)==status
 with pytest.raises(TransportStoreError): restarted.put_attempt(observe(authority_token(),start_attempt(authority_token(),s,attempt_number=1,request_id="r1",persisted_epoch_seconds=20),state=AttemptState.REJECTED,observed_epoch_seconds=31))

def test_immutable_attempt_delete_and_tamper_are_rejected():
 c=db(); store=TransportStore(c); s=sub(); store.put_submission(s,retry_due_epoch=20)
 a=start_attempt(authority_token(),s,attempt_number=1,request_id="r1",persisted_epoch_seconds=20); store.put_attempt(a)
 with pytest.raises(sqlite3.IntegrityError): c.execute("DELETE FROM transport_attempts")
 c.execute("PRAGMA writable_schema=ON"); c.execute("PRAGMA writable_schema=OFF")

def test_backup_restore_preserves_logical_records_without_resurrection(tmp_path):
 path=tmp_path/"a.db"; c=sqlite3.connect(path,isolation_level=None); install(c); store=TransportStore(c); store.put_submission(sub(),retry_due_epoch=20)
 backup=tmp_path/"b.db"; b=sqlite3.connect(backup,isolation_level=None); c.backup(b); b.close(); c.close()
 restored=sqlite3.connect(backup,isolation_level=None); verify(restored); assert TransportStore(restored).status(sub().submission_id).attempt_count==0
