"""Exact review, reconciliation and non-activating Increment 10 disposition."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from enum import StrEnum
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.increment10.requalification import EXPECTED_RESIDUAL_GATES,EXPECTED_ZERO_TOLERANCE
from newsroom.increment10.review import DECISIONS,METRICS,Label,Reviewer,assign,record_review,seal_universe,validate_metric_inventory

class DecisionError(ValueError):pass
class Disposition(StrEnum):
 FAILED="FAILED";INCONCLUSIVE="INCONCLUSIVE";CONTINUE_CANARY="CONTINUE_CANARY";BLOCKED_ACTIVE_COVERAGE="BLOCKED_ACTIVE_COVERAGE";BLOCKED_EVIDENCE_INTAKE="BLOCKED_EVIDENCE_INTAKE";ELIGIBLE_FOR_ACTIVATION_PLANNING="ELIGIBLE_FOR_ACTIVATION_PLANNING"
@dataclass(frozen=True,slots=True)
class DecisionReport:
 schema_version:str; inventory_digest:str; universe_digest:str; eligible_cases:tuple[str,...]; review_records:tuple[dict[str,object],...]; adjudication_status:str; metrics:tuple[tuple[str,int,int],...]; zero_tolerance:tuple[tuple[str,int],...]; reconciliation:tuple[tuple[str,str],...]; residual_blockers:tuple[str,...]; incidents:tuple[str,...]; production_equivalence_differences:tuple[str,...]; disposition:Disposition; increment11_eligible:bool; publication_authorised:bool; production_activation_authorised:bool
 def canonical_bytes(self)->bytes:
  value=asdict(self);value["disposition"]=self.disposition.value;return canonical_json_bytes(value)
 @property
 def digest(self)->str:return digest_bytes(self.canonical_bytes())

def decide(inventory:dict[str,object])->DecisionReport:
 expected=tuple(f"candidate-version:increment10-fixture-{i:03d}" for i in range(1,4))
 if inventory.get("denominator")!=3 or tuple(x["candidate_version_id"] for x in inventory.get("results",[]))!=expected or inventory.get("terminal_outcome")!="COMPLETE":raise DecisionError("sealed complete inventory differs")
 raw=canonical_json_bytes(inventory);inventory_digest=digest_bytes(raw)
 universe=seal_universe(epoch_id=str(inventory["epoch_digest"]),cohort_digest=digest_bytes(canonical_json_bytes(expected)),case_ids=expected,sealed_at=int(inventory["sealed_at"]),execution_complete=True)
 people=(Reviewer("mechanism-a","MECHANISM_REVIEWER"),Reviewer("audit-b","RESULT_AUDITOR"),Reviewer("adjudicator-c","FIXTURE_ADJUDICATOR"));assignments=assign(universe,people);records=[]
 for item in assignments:
  records.extend((record_review(universe,item,reviewer_id=item.mechanism_reviewer,role="MECHANISM_REVIEWER",label=Label.PASS,structured_reasons=("canonical transport and scope replay pass",),confidence_basis="sealed fixture bytes",completed_at=universe.sealed_at+1),record_review(universe,item,reviewer_id=item.result_auditor,role="RESULT_AUDITOR",label=Label.PASS,structured_reasons=("complete retained fixture outcome",),confidence_basis="independent sealed-inventory audit",completed_at=universe.sealed_at+2)))
 metrics={name:(3,3) for name in METRICS};validate_metric_inventory(metrics)
 review_values=tuple({**asdict(r),"label":r.label.value} for r in records)
 report=DecisionReport("newsroom.increment10.decision.v1",inventory_digest,universe.digest,expected,review_values,"NOT_REQUIRED_NO_DISAGREEMENT",tuple((name,*metrics[name]) for name in METRICS),tuple((name,0) for name in EXPECTED_ZERO_TOLERANCE),(("Candidate","COMPLETE"),("Handoff","COMPLETE"),("Submission","COMPLETE"),("Attempt","COMPLETE"),("Acknowledgement","COMPLETE"),("Feedback","NO_PUBLICATION_ELIGIBILITY"),("obligation","NONE")),EXPECTED_RESIDUAL_GATES,tuple(inventory.get("incidents",[])),("NO_LIVE_SOURCE","NO_EXTERNAL_INTAKE","NO_CREDENTIAL","NO_NETWORK","SYNTHETIC_REVIEW","NO_SCALE_INFERENCE"),Disposition.BLOCKED_ACTIVE_COVERAGE,False,False,False)
 validate(report);return report

def validate(report:DecisionReport)->None:
 if report.disposition.value not in DECISIONS or report.disposition is not Disposition.BLOCKED_ACTIVE_COVERAGE:raise DecisionError("closed disposition differs")
 if len(report.eligible_cases)!=3 or len(report.review_records)!=6 or any(value!=3 or den!=3 for _,value,den in report.metrics):raise DecisionError("review or metric denominator differs")
 if tuple(name for name,_ in report.zero_tolerance)!=EXPECTED_ZERO_TOLERANCE or any(count for _,count in report.zero_tolerance):raise DecisionError("zero-tolerance inventory differs")
 if report.residual_blockers!=EXPECTED_RESIDUAL_GATES:raise DecisionError("active coverage blockers differ")
 if report.increment11_eligible or report.publication_authorised or report.production_activation_authorised:raise DecisionError("report grants prohibited authority")
