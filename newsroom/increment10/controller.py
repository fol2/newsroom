"""Bounded fixture/replay controller qualification; runtime execution is absent."""
from __future__ import annotations
import sqlite3
from dataclasses import asdict,dataclass
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.increment10.epoch import CanaryEpoch,Outcome,checkpoint
from newsroom.increment10.scope import FROZEN_SCOPE
from newsroom.increment10.transport import *
from newsroom.increment10.transport_store import TransportStore

class ControllerError(ValueError):pass
@dataclass(frozen=True,slots=True)
class QualificationReceipt:
 epoch_digest:str; case_outcomes:tuple[tuple[str,str],...]; checkpoint_digests:tuple[str,...]; denominator:int; production_before:str; production_after:str; publication_before:str; publication_after:str; kill_propagation_ms:int; teardown_rebuild:bool; decision_bearing:bool=False
 @property
 def digest(self)->str:return digest_bytes(canonical_json_bytes(asdict(self)))

class FixtureController:
 def __init__(self,epoch:CanaryEpoch,store:TransportStore):self.epoch=epoch;self._store=store
 def qualify(self,*,production_digest:str,publication_digest:str)->QualificationReceipt:
  if self.epoch.execution_authorised:raise ControllerError("qualification epoch must not carry execution authority")
  outcomes=[]; digests=[]
  for index,candidate in enumerate(self.epoch.cohort,1):
   submission=create_submission(authority_token(),candidate_version_id=candidate,handoff_digest="sha256:"+format(index,"064x"),plan_digest=self.epoch.plan_digest,destination=str(FROZEN_SCOPE.scope["destination"]),created_epoch_seconds=self.epoch.opens_at,retry=RetryPolicy(3,(1,2),self.epoch.closes_at))
   self._store.put_submission(submission,retry_due_epoch=self.epoch.opens_at)
   attempt=start_attempt(authority_token(),submission,attempt_number=1,request_id=f"fixture-request-{index}",persisted_epoch_seconds=self.epoch.opens_at,effect_started_epoch_seconds=self.epoch.opens_at)
   accepted=observe(authority_token(),attempt,state=AttemptState.ACCEPTED,observed_epoch_seconds=self.epoch.opens_at+1,response_request_id=attempt.request_id,acknowledgement_id=f"fixture-ack-{index}")
   self._store.put_attempt(accepted)
   cp=checkpoint(self.epoch,candidate_version_id=candidate,sequence=index,state="FIXTURE_REPLAY_COMPLETE",watermark=index,outcome=Outcome.COMPLETE)
   digests.append(digest_bytes(canonical_json_bytes({**asdict(cp),"outcome":cp.outcome.value}))); outcomes.append((candidate,Outcome.COMPLETE.value))
  return QualificationReceipt(self.epoch.digest,tuple(outcomes),tuple(digests),len(outcomes),production_digest,production_digest,publication_digest,publication_digest,0,True,False)
 def execute(self)->None:raise ControllerError("decision-bearing execution requires separate #533 authority")

def validate_receipt(receipt:QualificationReceipt)->None:
 if receipt.denominator!=3 or len(receipt.case_outcomes)!=3 or any(v!=Outcome.COMPLETE.value for _,v in receipt.case_outcomes):raise ControllerError("qualification denominator differs")
 if receipt.production_before!=receipt.production_after or receipt.publication_before!=receipt.publication_after or receipt.decision_bearing:raise ControllerError("qualification created a prohibited effect")
 if receipt.kill_propagation_ms>1000 or not receipt.teardown_rebuild:raise ControllerError("containment qualification differs")
