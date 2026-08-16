import json,subprocess
from pathlib import Path
import pytest
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.increment10.closeout import CloseoutError,build,verify

def inputs(tmp_path:Path):
 issues=tmp_path/"issues";issues.mkdir(parents=True)
 for n in range(526,537):
  value={"number":n,"state":"CLOSED","title":f"issue {n}","closedAt":"2026-08-16T10:00:00Z","url":f"https://github.com/fol2/newsroom/issues/{n}"}
  (issues/f"issue-{n}.json").write_text(json.dumps(value,indent=2))
 sha=subprocess.check_output(("git","rev-parse","HEAD"),text=True).strip();tree=subprocess.check_output(("git","rev-parse","HEAD^{tree}"),text=True).strip()
 decision=tmp_path/"decision.json";decision.write_bytes(canonical_json_bytes({"schema_version":"newsroom.sdlc.shadow-decision.v1","result":"PASS","context":{"event_name":"workflow_dispatch","ref":"refs/heads/main","evaluated_sha":sha,"evaluated_tree_sha":tree}}))
 return issues,decision

def test_closed_world_subjects_build_and_reconstruct(tmp_path):
 issues,decision=inputs(tmp_path);out=tmp_path/"subjects"
 receipt=build(repo_root=Path.cwd(),issue_directory=issues,sdlc_decision=decision,observed_at="2026-08-16T10:30:00Z",output_directory=out)
 verify(repo_root=Path.cwd(),subject_directory=out,sdlc_decision=decision,current_issue_directory=issues)
 assert receipt["disposition"]=="BLOCKED_ACTIVE_COVERAGE" and receipt["increment11_eligible"] is False
 assert len(receipt["residual_blockers"])==20 and len(receipt["review"]["zero_tolerance"])==12
 assert set(p.name for p in out.iterdir())=={"increment10-issue-inventory.json","increment10-plan.json","increment10-transport-deployment.json","increment10-run-inventory.json","increment10-review-metric-decision.json","increment10g-final-closeout.json","increment10-subject-manifest.json"}

def test_open_dependency_exact_main_drift_and_subject_tamper_fail(tmp_path):
 issues,decision=inputs(tmp_path);value=json.loads((issues/"issue-536.json").read_text());value["state"]="OPEN";(issues/"issue-536.json").write_text(json.dumps(value))
 with pytest.raises(CloseoutError,match="issue 536"):build(repo_root=Path.cwd(),issue_directory=issues,sdlc_decision=decision,observed_at="x",output_directory=tmp_path/"bad")
 issues,decision=inputs(tmp_path/"fresh");out=tmp_path/"out";build(repo_root=Path.cwd(),issue_directory=issues,sdlc_decision=decision,observed_at="x",output_directory=out)
 path=out/"increment10-run-inventory.json";path.write_bytes(path.read_bytes()+b" ")
 with pytest.raises(CloseoutError):verify(repo_root=Path.cwd(),subject_directory=out,sdlc_decision=decision)

def test_closeout_retains_non_effects_schema_and_exact_subject_digests(tmp_path):
 issues,decision=inputs(tmp_path);out=tmp_path/"out";build(repo_root=Path.cwd(),issue_directory=issues,sdlc_decision=decision,observed_at="x",output_directory=out)
 receipt=json.loads((out/"increment10g-final-closeout.json").read_bytes());manifest=json.loads((out/"increment10-subject-manifest.json").read_bytes())
 assert receipt["schema"]["version"]==33 and all(v is False for v in receipt["non_effects"].values())
 for name,digest in manifest["subjects"].items():assert digest_bytes((out/name).read_bytes())==digest

def test_receipt_and_manifest_cannot_be_forged_together(tmp_path):
 issues,decision=inputs(tmp_path);out=tmp_path/"out";build(repo_root=Path.cwd(),issue_directory=issues,sdlc_decision=decision,observed_at="x",output_directory=out)
 receipt_path=out/"increment10g-final-closeout.json";receipt=json.loads(receipt_path.read_bytes());receipt["schema"]["version"]=999;receipt["residual_blockers"]=[];receipt_path.write_bytes(canonical_json_bytes(receipt))
 manifest_path=out/"increment10-subject-manifest.json";manifest=json.loads(manifest_path.read_bytes());manifest["subjects"][receipt_path.name]=digest_bytes(receipt_path.read_bytes());manifest_path.write_bytes(canonical_json_bytes(manifest))
 with pytest.raises(CloseoutError,match="complete closeout reconstruction differs"):verify(repo_root=Path.cwd(),subject_directory=out,sdlc_decision=decision)

def test_forged_non_main_failed_decision_cannot_be_rebound(tmp_path):
 issues,decision=inputs(tmp_path);out=tmp_path/"out";build(repo_root=Path.cwd(),issue_directory=issues,sdlc_decision=decision,observed_at="x",output_directory=out)
 value=json.loads(decision.read_bytes());value["result"]="FAIL";value["context"]["event_name"]="pull_request";value["context"]["ref"]="refs/pull/548/merge";decision.write_bytes(canonical_json_bytes(value))
 receipt_path=out/"increment10g-final-closeout.json";receipt=json.loads(receipt_path.read_bytes());receipt["source"]["sdlc_decision_digest"]=digest_bytes(decision.read_bytes());receipt_path.write_bytes(canonical_json_bytes(receipt))
 manifest_path=out/"increment10-subject-manifest.json";manifest=json.loads(manifest_path.read_bytes());manifest["subjects"][receipt_path.name]=digest_bytes(receipt_path.read_bytes());manifest_path.write_bytes(canonical_json_bytes(manifest))
 with pytest.raises(CloseoutError,match="exact checked-out main PASS"):verify(repo_root=Path.cwd(),subject_directory=out,sdlc_decision=decision)
