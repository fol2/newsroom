"""Transactional isolated persistence for Increment 10 transport records."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.increment10.transport import Attempt,AttemptState,Submission,TransportContractError,parse_submission

class TransportStoreError(ValueError): pass
@dataclass(frozen=True,slots=True)
class TransportStatus:
    submission_id:str; state:AttemptState; attempt_count:int; retry_due_epoch:int; expiry_epoch:int; reconciliation_required:bool; receipt_digests:tuple[str,...]

class TransportStore:
    def __init__(self,connection:sqlite3.Connection):
        if not isinstance(connection,sqlite3.Connection): raise TransportStoreError("SQLite connection required")
        self.__connection=connection
    def put_submission(self,submission:Submission,*,retry_due_epoch:int)->TransportStatus:
        raw=submission.canonical_bytes(); digest=digest_bytes(raw)
        try:
            self.__connection.execute("BEGIN IMMEDIATE")
            row=self.__connection.execute("SELECT canonical_bytes FROM transport_submissions WHERE semantic_key=?",(submission.semantic_idempotency_key,)).fetchone()
            if row is not None:
                if bytes(row[0])!=raw: raise TransportStoreError("semantic duplicate conflicts")
                self.__connection.rollback(); return self.status(submission.submission_id)
            self.__connection.execute("INSERT INTO transport_submissions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(submission.submission_id,submission.semantic_idempotency_key,raw,digest,submission.candidate_version_id,submission.handoff_digest,submission.plan_digest,submission.destination,submission.created_epoch_seconds,retry_due_epoch,submission.retry.expiry_epoch_seconds,AttemptState.NOT_STARTED.value))
            self._audit("SUBMISSION_RECORDED",submission.submission_id,{"digest":digest},submission.created_epoch_seconds)
            self.__connection.commit(); return self.status(submission.submission_id)
        except (sqlite3.Error,TransportStoreError) as exc:
            if self.__connection.in_transaction:self.__connection.rollback()
            if isinstance(exc,TransportStoreError):raise
            raise TransportStoreError("submission transaction failed") from exc
    def put_attempt(self,attempt:Attempt)->TransportStatus:
        raw=attempt.canonical_bytes(); digest=digest_bytes(raw); ambiguous=attempt.state in {AttemptState.AMBIGUOUS,AttemptState.TIMED_OUT,AttemptState.PARTIAL,AttemptState.UNAVAILABLE}
        try:
            self.__connection.execute("BEGIN IMMEDIATE")
            existing=self.__connection.execute("SELECT canonical_bytes FROM transport_attempts WHERE submission_id=? AND attempt_number=?",(attempt.submission_id,attempt.attempt_number)).fetchone()
            if existing:
                if bytes(existing[0])!=raw: raise TransportStoreError("attempt coordinate conflicts")
                self.__connection.rollback(); return self.status(attempt.submission_id)
            self.__connection.execute("INSERT INTO transport_attempts VALUES(?,?,?,?,?,?,?,?,?,?)",(f"{attempt.submission_id}:{attempt.attempt_number}",attempt.submission_id,attempt.attempt_number,attempt.request_id,raw,digest,attempt.state.value,attempt.observed_epoch_seconds,attempt.acknowledgement_id,int(ambiguous)))
            self.__connection.execute("UPDATE transport_submissions SET status=? WHERE submission_id=?",(attempt.state.value,attempt.submission_id))
            self._audit("ATTEMPT_RECORDED",attempt.submission_id,{"attempt_digest":digest,"state":attempt.state.value},attempt.observed_epoch_seconds or attempt.persisted_epoch_seconds)
            self.__connection.commit(); return self.status(attempt.submission_id)
        except (sqlite3.Error,TransportStoreError) as exc:
            if self.__connection.in_transaction:self.__connection.rollback()
            if isinstance(exc,TransportStoreError):raise
            raise TransportStoreError("attempt transaction failed") from exc
    def _audit(self,kind:str,subject:str,value:dict[str,object],at:int)->None:
        raw=canonical_json_bytes({"event_kind":kind,"subject_id":subject,"value":value,"recorded_epoch":at})
        self.__connection.execute("INSERT INTO transport_audit(event_kind,subject_id,event_bytes,event_digest,recorded_epoch) VALUES(?,?,?,?,?)",(kind,subject,raw,digest_bytes(raw),at))
    def status(self,submission_id:str)->TransportStatus:
        row=self.__connection.execute("SELECT status,retry_due_epoch,expiry_epoch,canonical_bytes FROM transport_submissions WHERE submission_id=?",(submission_id,)).fetchone()
        if row is None: raise TransportStoreError("submission is absent")
        try: submission=parse_submission(bytes(row[3]))
        except TransportContractError as exc: raise TransportStoreError("retained submission is corrupt") from exc
        attempts=self.__connection.execute("SELECT canonical_digest,reconciliation_required FROM transport_attempts WHERE submission_id=? ORDER BY attempt_number",(submission_id,)).fetchall()
        return TransportStatus(submission.submission_id,AttemptState(row[0]),len(attempts),row[1],row[2],any(r[1] for r in attempts),tuple(r[0] for r in attempts))
    def due(self,now_epoch:int)->tuple[TransportStatus,...]:
        ids=[r[0] for r in self.__connection.execute("SELECT submission_id FROM transport_submissions WHERE status NOT IN ('ACCEPTED','REJECTED','RECONCILED') AND retry_due_epoch<=? AND expiry_epoch>? ORDER BY retry_due_epoch,submission_id",(now_epoch,now_epoch))]
        return tuple(self.status(i) for i in ids)
