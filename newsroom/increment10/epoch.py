"""Immutable Epoch and outcome authority for Increment 10 fixture qualification."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from enum import StrEnum
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.increment10.deployment import DeploymentReceipt,assert_current
from newsroom.increment10.plan import INCREMENT_10_PLAN
from newsroom.increment10.scope import FROZEN_SCOPE
class EpochError(ValueError):pass
class Outcome(StrEnum):
 COMPLETE="COMPLETE"; PARTIAL="PARTIAL"; REJECTED="REJECTED"; UNAVAILABLE="UNAVAILABLE"; TIMED_OUT="TIMED_OUT"; AMBIGUOUS="AMBIGUOUS"; EARLY_STOPPED="EARLY_STOPPED"; BLOCKED="BLOCKED"; INCONCLUSIVE="INCONCLUSIVE"
@dataclass(frozen=True,slots=True)
class CanaryEpoch:
 epoch_id:str; plan_digest:str; scope_digest:str; deployment_digest:str; cohort:tuple[str,...]; denominator:int; opens_at:int; closes_at:int; gross_budget_gbp_minor:int; external_requests_max:int; execution_authorised:bool=False
 def canonical_bytes(self)->bytes:return canonical_json_bytes(asdict(self))
 @property
 def digest(self)->str:return digest_bytes(self.canonical_bytes())
@dataclass(frozen=True,slots=True)
class Checkpoint:
 epoch_digest:str; candidate_version_id:str; sequence:int; state:str; usage_requests:int; usage_bytes:int; cost_gbp_minor:int; watermark:int; outcome:Outcome|None

def create_epoch(receipt:DeploymentReceipt,*,opens_at:int,closes_at:int)->CanaryEpoch:
 assert_current(receipt)
 if opens_at>=closes_at:raise EpochError("prospective window differs")
 cohort=tuple(FROZEN_SCOPE.scope["candidate_version_ids"])
 identity=digest_bytes(canonical_json_bytes({"plan":INCREMENT_10_PLAN.plan_digest,"scope":FROZEN_SCOPE.digest,"deployment":receipt.digest,"cohort":cohort,"opens_at":opens_at,"closes_at":closes_at}))
 return CanaryEpoch("epoch:"+identity.removeprefix("sha256:"),INCREMENT_10_PLAN.plan_digest,FROZEN_SCOPE.digest,receipt.digest,cohort,3,opens_at,closes_at,0,0,False)

def checkpoint(epoch:CanaryEpoch,*,candidate_version_id:str,sequence:int,state:str,usage_requests:int=0,usage_bytes:int=0,cost_gbp_minor:int=0,watermark:int,outcome:Outcome|None=None)->Checkpoint:
 if candidate_version_id not in epoch.cohort or sequence<0 or watermark<sequence:raise EpochError("checkpoint identity or chronology differs")
 if usage_requests>epoch.external_requests_max or cost_gbp_minor>epoch.gross_budget_gbp_minor or min(usage_requests,usage_bytes,cost_gbp_minor)<0:raise EpochError("budget exceeded")
 return Checkpoint(epoch.digest,candidate_version_id,sequence,state,usage_requests,usage_bytes,cost_gbp_minor,watermark,outcome)
