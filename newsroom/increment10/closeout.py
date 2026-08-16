"""Closed-world Increment 10 exact-main closeout construction and verification."""
from __future__ import annotations
import json,subprocess
from pathlib import Path
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.authority.increment10_canary_migrations import CHECKSUM,SCHEMA_VERSION
from newsroom.increment10.plan import EXPECTED_PLAN_DIGEST,load_plan
from newsroom.increment10.requalification import EXPECTED_RESIDUAL_GATES,EXPECTED_ZERO_TOLERANCE
class CloseoutError(ValueError):pass
SUBJECT_SOURCES={"increment10-plan.json":"newsroom/increment10/plan_v1.json","increment10-transport-deployment.json":"newsroom/increment10/authority_v1.json","increment10-run-inventory.json":"newsroom/increment10/sealed_inventory_v1.json","increment10-review-metric-decision.json":"newsroom/increment10/decision_v1.json"}
EXPECTED_DIGESTS={"increment10-plan.json":EXPECTED_PLAN_DIGEST,"increment10-transport-deployment.json":"sha256:b28dd704cbf5eebefd262109762a195359f988815973893e6c5bba96e2d83d64","increment10-run-inventory.json":"sha256:84bd7e619e9345f07f2d9b4749663240ec54cf6078aed0fec406e1cf7b95bfdb","increment10-review-metric-decision.json":"sha256:054a0ae42fe2070823a8a6e17ffbf71039b7b66d18da6af31b58feee60bb3720"}

def _load(path:Path)->dict[str,object]:
 try:v=json.loads(path.read_bytes())
 except (OSError,ValueError,UnicodeError) as exc:raise CloseoutError(f"cannot read {path.name}") from exc
 if type(v) is not dict or path.read_bytes()!=canonical_json_bytes(v):raise CloseoutError(f"{path.name} is not canonical")
 return v

def _read_issue(path:Path)->dict[str,object]:
 try:v=json.loads(path.read_bytes())
 except (OSError,ValueError,UnicodeError) as exc:raise CloseoutError(f"cannot read {path.name}") from exc
 if type(v) is not dict:raise CloseoutError(f"{path.name} is not an issue object")
 return v

def build(*,repo_root:Path,issue_directory:Path,sdlc_decision:Path,observed_at:str,output_directory:Path)->dict[str,object]:
 decision=_load(sdlc_decision); context=decision.get("context")
 if decision.get("result")!="PASS" or not isinstance(context,dict) or context.get("event_name")!="workflow_dispatch" or context.get("ref")!="refs/heads/main":raise CloseoutError("SDLC decision is not exact-main PASS")
 sha=str(context.get("evaluated_sha"));tree=str(context.get("evaluated_tree_sha"))
 observed_sha=subprocess.check_output(("git","rev-parse","HEAD"),cwd=repo_root,text=True).strip();observed_tree=subprocess.check_output(("git","rev-parse","HEAD^{tree}"),cwd=repo_root,text=True).strip()
 if (sha,tree)!=(observed_sha,observed_tree):raise CloseoutError("checked-out exact-main identity differs")
 issues=[]
 for number in range(526,537):
  issue=_read_issue(issue_directory/f"issue-{number}.json")
  if set(issue)!={"closedAt","number","state","title","url"} or issue["number"]!=number or issue["state"]!="CLOSED" or issue["url"]!=f"https://github.com/fol2/newsroom/issues/{number}":raise CloseoutError(f"issue {number} is not immutably closed")
  issues.append(issue)
 output_directory.mkdir(parents=True,exist_ok=False)
 inventory={"schema_version":"newsroom.increment10.issue-inventory.v1","issues":issues};(output_directory/"increment10-issue-inventory.json").write_bytes(canonical_json_bytes(inventory))
 subjects={"increment10-issue-inventory.json":digest_bytes(canonical_json_bytes(inventory))}
 for name,relative in SUBJECT_SOURCES.items():
  src=repo_root/relative;value=_load(src);digest=digest_bytes(src.read_bytes())
  if digest!=EXPECTED_DIGESTS[name]:raise CloseoutError(f"{name} reviewed digest differs")
  (output_directory/name).write_bytes(canonical_json_bytes(value));subjects[name]=digest
 plan=load_plan(repo_root/SUBJECT_SOURCES["increment10-plan.json"]);run=_load(repo_root/SUBJECT_SOURCES["increment10-run-inventory.json"]);report=_load(repo_root/SUBJECT_SOURCES["increment10-review-metric-decision.json"])
 if run.get("denominator")!=3 or run.get("terminal_outcome")!="COMPLETE" or report.get("disposition")!="BLOCKED_ACTIVE_COVERAGE" or report.get("increment11_eligible") is not False:raise CloseoutError("Increment 10 result binding differs")
 receipt={"schema_version":"newsroom.increment10.closeout.v1","source":{"commit":sha,"tree":tree,"sdlc_decision_digest":digest_bytes(sdlc_decision.read_bytes())},"observed_at":observed_at,"schema":{"version":SCHEMA_VERSION,"migration_checksum":CHECKSUM},"subjects":subjects,"plan_digest":plan.plan_digest,"cohort":{"denominator":3,"sealed_inventory_digest":EXPECTED_DIGESTS["increment10-run-inventory.json"]},"review":{"metric_count":11,"review_record_count":6,"zero_tolerance":list((name,0) for name in EXPECTED_ZERO_TOLERANCE)},"residual_blockers":list(EXPECTED_RESIDUAL_GATES),"disposition":"BLOCKED_ACTIVE_COVERAGE","increment11_eligible":False,"non_effects":{"publication":False,"public_dispatch":False,"production_mutation":False,"production_activation":False,"legacy_retirement":False},"production_equivalence_differences":report["production_equivalence_differences"]}
 raw=canonical_json_bytes(receipt);(output_directory/"increment10g-final-closeout.json").write_bytes(raw);subjects["increment10g-final-closeout.json"]=digest_bytes(raw)
 manifest={"schema_version":"newsroom.increment10.subject-manifest.v1","source_commit":sha,"source_tree":tree,"subjects":subjects};(output_directory/"increment10-subject-manifest.json").write_bytes(canonical_json_bytes(manifest));verify(repo_root=repo_root,subject_directory=output_directory,sdlc_decision=sdlc_decision);return receipt

def verify(*,repo_root:Path,subject_directory:Path,sdlc_decision:Path,current_issue_directory:Path|None=None)->None:
 decision=_load(sdlc_decision);context=decision.get("context")
 if not isinstance(context,dict):raise CloseoutError("SDLC context differs")
 manifest=_load(subject_directory/"increment10-subject-manifest.json");subjects=manifest.get("subjects")
 if not isinstance(subjects,dict):raise CloseoutError("subject manifest differs")
 for name,digest in subjects.items():
  path=subject_directory/name
  if digest_bytes(path.read_bytes())!=digest:_load(path);raise CloseoutError(f"{name} digest differs")
  _load(path)
 for name,relative in SUBJECT_SOURCES.items():
  if (subject_directory/name).read_bytes()!=(repo_root/relative).read_bytes():raise CloseoutError(f"{name} differs from checked-out source")
 if manifest.get("source_commit")!=context.get("evaluated_sha") or manifest.get("source_tree")!=context.get("evaluated_tree_sha"):raise CloseoutError("manifest source differs")
 receipt=_load(subject_directory/"increment10g-final-closeout.json")
 if receipt.get("disposition")!="BLOCKED_ACTIVE_COVERAGE" or receipt.get("increment11_eligible") is not False or any(receipt.get("non_effects",{}).values()):raise CloseoutError("closeout authority differs")
 if current_issue_directory:
  retained=_load(subject_directory/"increment10-issue-inventory.json")["issues"]
  current=[_read_issue(current_issue_directory/f"issue-{n}.json") for n in range(526,537)]
  if retained!=current:raise CloseoutError("live issue closure differs from retained subject")
