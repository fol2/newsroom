"""Pre-registered blinded review and adjudication contracts for Increment 10."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

class ReviewContractError(ValueError): pass
class Label(StrEnum):
    PASS="PASS"; FAIL="FAIL"; UNREVIEWABLE="UNREVIEWABLE"; MISSING_EVIDENCE="MISSING_EVIDENCE"
class IncidentSeverity(StrEnum):
    ZERO_TOLERANCE="ZERO_TOLERANCE"; MATERIAL="MATERIAL"; ORDINARY="ORDINARY"

@dataclass(frozen=True, slots=True)
class Reviewer:
    reviewer_id:str; role:str; conflicts:tuple[str,...]=()
@dataclass(frozen=True, slots=True)
class SealedUniverse:
    epoch_id:str; cohort_digest:str; case_ids:tuple[str,...]; sealed_at:int; digest:str
@dataclass(frozen=True, slots=True)
class Assignment:
    case_id:str; mechanism_reviewer:str; result_auditor:str; expected_outcome_hidden:bool=True
@dataclass(frozen=True, slots=True)
class ReviewRecord:
    case_id:str; reviewer_id:str; role:str; label:Label; structured_reasons:tuple[str,...]; confidence_basis:str; completed_at:int; universe_digest:str
@dataclass(frozen=True, slots=True)
class Adjudication:
    case_id:str; adjudicator_id:str; label:Label; reason:str; input_digests:tuple[str,...]

ZERO_TOLERANCE=frozenset({"PUBLIC_EFFECT","PRODUCTION_MUTATION","RIGHTS_BREACH","CREDENTIAL_EXPOSURE","PROHIBITED_EGRESS","UNCONTAINED_AMBIGUOUS_EFFECT"})
METRICS=("transport_correctness","intake_correctness","evidence_quality","rights","sensitive_content","timeliness","correction","reconciliation","security","cost","operations")
DECISIONS=("FAILED","INCONCLUSIVE","CONTINUE_CANARY","BLOCKED_ACTIVE_COVERAGE","BLOCKED_EVIDENCE_INTAKE","ELIGIBLE_FOR_ACTIVATION_PLANNING")


def seal_universe(*, epoch_id:str, cohort_digest:str, case_ids:tuple[str,...], sealed_at:int, execution_complete:bool) -> SealedUniverse:
    if not execution_complete: raise ReviewContractError("#533 evidence inventory is not sealed")
    if len(case_ids)!=3 or len(set(case_ids))!=3 or tuple(sorted(case_ids))!=case_ids: raise ReviewContractError("case universe must be exact, unique and sorted")
    raw={"epoch_id":epoch_id,"cohort_digest":cohort_digest,"case_ids":case_ids,"sealed_at":sealed_at}
    return SealedUniverse(epoch_id,cohort_digest,case_ids,sealed_at,digest_bytes(canonical_json_bytes(raw)))


def assign(universe:SealedUniverse, reviewers:tuple[Reviewer,...]) -> tuple[Assignment,...]:
    mechanisms=sorted((r for r in reviewers if r.role=="MECHANISM_REVIEWER"),key=lambda r:r.reviewer_id)
    auditors=sorted((r for r in reviewers if r.role=="RESULT_AUDITOR"),key=lambda r:r.reviewer_id)
    if not mechanisms or not auditors: raise ReviewContractError("independent review roles are incomplete")
    result=[]
    for index,case in enumerate(universe.case_ids):
        m=mechanisms[index%len(mechanisms)]; a=auditors[index%len(auditors)]
        if m.reviewer_id==a.reviewer_id or case in m.conflicts or case in a.conflicts: raise ReviewContractError("same-role, self-review or conflict assignment")
        result.append(Assignment(case,m.reviewer_id,a.reviewer_id))
    counts={r.reviewer_id:0 for r in reviewers}
    for item in result:
        counts[item.mechanism_reviewer]+=1; counts[item.result_auditor]+=1
    if max(counts.values(),default=0)>3: raise ReviewContractError("reviewer workload exceeded")
    return tuple(result)


def record_review(universe:SealedUniverse, assignment:Assignment, *, reviewer_id:str, role:str, label:Label, structured_reasons:tuple[str,...], confidence_basis:str, completed_at:int) -> ReviewRecord:
    authorised={"MECHANISM_REVIEWER":assignment.mechanism_reviewer,"RESULT_AUDITOR":assignment.result_auditor}
    if authorised.get(role)!=reviewer_id: raise ReviewContractError("reviewer role is not authorised for case")
    if assignment.case_id not in universe.case_ids or completed_at < universe.sealed_at: raise ReviewContractError("review chronology differs")
    if not structured_reasons or not confidence_basis: raise ReviewContractError("structured reason and confidence are required")
    return ReviewRecord(assignment.case_id,reviewer_id,role,label,structured_reasons,confidence_basis,completed_at,universe.digest)


def adjudicate(universe:SealedUniverse, *, adjudicator:Reviewer, records:tuple[ReviewRecord,...], label:Label, reason:str) -> Adjudication:
    if adjudicator.role!="FIXTURE_ADJUDICATOR" or not reason: raise ReviewContractError("adjudicator authority differs")
    if len(records)!=2 or {r.role for r in records}!={"MECHANISM_REVIEWER","RESULT_AUDITOR"} or len({r.case_id for r in records})!=1: raise ReviewContractError("independent review pair is incomplete")
    if any(r.universe_digest!=universe.digest or r.reviewer_id==adjudicator.reviewer_id for r in records): raise ReviewContractError("adjudication independence or universe differs")
    digests=tuple(digest_bytes(canonical_json_bytes({"case_id":r.case_id,"reviewer_id":r.reviewer_id,"role":r.role,"label":r.label.value,"structured_reasons":r.structured_reasons,"confidence_basis":r.confidence_basis,"completed_at":r.completed_at,"universe_digest":r.universe_digest})) for r in records)
    return Adjudication(records[0].case_id,adjudicator.reviewer_id,label,reason,digests)


def incident_severity(findings:set[str]) -> IncidentSeverity:
    if findings & ZERO_TOLERANCE: return IncidentSeverity.ZERO_TOLERANCE
    if findings & {"INCOMPLETE_DENOMINATOR","LATE_CONTAINMENT","RESIDUAL_RISK"}: return IncidentSeverity.MATERIAL
    return IncidentSeverity.ORDINARY


def validate_metric_inventory(values:dict[str,tuple[int,int]]) -> None:
    if set(values)!=set(METRICS): raise ReviewContractError("metric inventory differs")
    if any(num<0 or den!=3 or num>den for num,den in values.values()): raise ReviewContractError("metric denominator or count differs")
