#!/usr/bin/env python3
"""Execute the single authorised local-fixture Increment 10 canary."""
from __future__ import annotations
import argparse,json,sqlite3
from dataclasses import asdict,dataclass
from pathlib import Path
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.authority.increment10_canary_migrations import verify
from newsroom.increment10.epoch import CanaryEpoch
from newsroom.increment10.transport import *
from newsroom.increment10.transport_store import TransportStore

AUTHORISATION="https://github.com/fol2/newsroom/issues/533#issuecomment-5306912137"
PLAN_DIGEST="sha256:1f5088e1397bb394e60f3ed883517cec803442572cccba3892c9f8f6ab8abc89"
DEPLOYMENT_DIGEST="sha256:4c61024dc0b1884302dd74ae96de16bcd55f6920d26489c73930aecd1e47c232"
EPOCH_DIGEST="sha256:1e05bba7e057684a36c6704558955ba698e65677f981344d4c650275a7f1081d"
COHORT=tuple(f"candidate-version:increment10-fixture-{i:03d}" for i in range(1,4))
DESTINATION="local://increment10/evidence-intake-fixture-v1"

class CanaryExecutionError(ValueError):pass
@dataclass(frozen=True,slots=True)
class CaseResult:
 candidate_version_id:str; handoff_digest:str; submission_id:str; request_id:str; acknowledgement_id:str; evidence_package_digest:str; transport_receipts:tuple[str,...]; outcome:str; external_requests:int; cost_gbp_minor:int
@dataclass(frozen=True,slots=True)
class SealedInventory:
 schema_version:str; authorisation:str; plan_digest:str; deployment_digest:str; epoch_digest:str; cohort:tuple[str,...]; denominator:int; results:tuple[CaseResult,...]; terminal_outcome:str; incidents:tuple[str,...]; residual_obligations:tuple[str,...]; production_before:str; production_after:str; publication_before:str; publication_after:str; sealed_at:int
 def canonical_bytes(self)->bytes:return canonical_json_bytes(asdict(self))
 @property
 def digest(self)->str:return digest_bytes(self.canonical_bytes())

def _fixture_intake(candidate:str,index:int)->tuple[str,str]:
 package={"schema_version":"increment10-evidence-intake-fixture-v1","candidate_version_id":candidate,"evidence":[{"fixture_id":f"evidence-{index}","provenance":"REPOSITORY_AUTHORED_SYNTHETIC","claim":"fixture observation"}],"publication_eligible":False}
 return digest_bytes(canonical_json_bytes(package)),f"fixture-ack-{index}"

def execute(store:TransportStore,epoch:CanaryEpoch,*,production_digest:str,publication_digest:str,sealed_at:int)->SealedInventory:
 if epoch.digest!=EPOCH_DIGEST or epoch.plan_digest!=PLAN_DIGEST or epoch.deployment_digest!=DEPLOYMENT_DIGEST or epoch.cohort!=COHORT or epoch.execution_authorised:raise CanaryExecutionError("execution authority identity differs")
 if sealed_at<epoch.opens_at or sealed_at>=epoch.closes_at:raise CanaryExecutionError("seal time is outside prospective window")
 results=[]
 for index,candidate in enumerate(COHORT,1):
  handoff="sha256:"+format(index,"064x")
  submission=create_submission(authority_token(),candidate_version_id=candidate,handoff_digest=handoff,plan_digest=PLAN_DIGEST,destination=DESTINATION,created_epoch_seconds=epoch.opens_at,retry=RetryPolicy(3,(1,2),epoch.closes_at))
  store.put_submission(submission,retry_due_epoch=epoch.opens_at)
  request_id=f"fixture-request-{index}"; attempt=start_attempt(authority_token(),submission,attempt_number=1,request_id=request_id,persisted_epoch_seconds=epoch.opens_at,effect_started_epoch_seconds=epoch.opens_at)
  evidence_digest,ack=_fixture_intake(candidate,index)
  accepted=observe(authority_token(),attempt,state=AttemptState.ACCEPTED,observed_epoch_seconds=epoch.opens_at+index,response_request_id=request_id,acknowledgement_id=ack)
  status=store.put_attempt(accepted)
  results.append(CaseResult(candidate,handoff,submission.submission_id,request_id,ack,evidence_digest,status.receipt_digests,"ACCEPTED",0,0))
 inventory=SealedInventory("newsroom.increment10.sealed-inventory.v1",AUTHORISATION,PLAN_DIGEST,DEPLOYMENT_DIGEST,EPOCH_DIGEST,COHORT,3,tuple(results),"COMPLETE",(),(),production_digest,production_digest,publication_digest,publication_digest,sealed_at)
 validate(inventory); return inventory

def validate(value:SealedInventory)->None:
 if value.denominator!=3 or tuple(r.candidate_version_id for r in value.results)!=COHORT or len(value.results)!=3:raise CanaryExecutionError("complete cohort denominator differs")
 if any(r.outcome!="ACCEPTED" or r.external_requests or r.cost_gbp_minor or len(r.transport_receipts)!=1 for r in value.results):raise CanaryExecutionError("case outcome or budget differs")
 if value.production_before!=value.production_after or value.publication_before!=value.publication_after:raise CanaryExecutionError("public or production mutation observed")
 if value.terminal_outcome!="COMPLETE" or value.incidents or value.residual_obligations:raise CanaryExecutionError("terminal inventory differs")

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--authority-input",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
 source=json.loads(args.authority_input.read_text()); e=source["epoch"]; e["cohort"]=tuple(e["cohort"]); epoch=CanaryEpoch(**e)
 if source["deployment_digest"]!=DEPLOYMENT_DIGEST or source["epoch_digest"]!=EPOCH_DIGEST:raise CanaryExecutionError("retained authority input differs")
 db=Path(source["deployment"]["authority_path"]); connection=sqlite3.connect(db,isolation_level=None);verify(connection)
 try: inventory=execute(TransportStore(connection),epoch,production_digest=source["deployment"]["production_digest_before"],publication_digest=source["deployment"]["public_surface_digest_before"],sealed_at=epoch.opens_at+10)
 finally:connection.close()
 args.output.write_bytes(inventory.canonical_bytes());print(json.dumps({"status":"COMPLETE","inventory_digest":inventory.digest,"denominator":inventory.denominator,"external_requests":0,"gross_gbp_minor":0},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
