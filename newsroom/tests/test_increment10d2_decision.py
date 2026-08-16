import json
from dataclasses import replace
import pytest
from newsroom.increment10.decision import *

def inventory():
 return {"schema_version":"newsroom.increment10.sealed-inventory.v1","epoch_digest":"sha256:"+"1"*64,"denominator":3,"results":[{"candidate_version_id":f"candidate-version:increment10-fixture-{i:03d}"} for i in range(1,4)],"terminal_outcome":"COMPLETE","incidents":[],"sealed_at":100}

def test_review_universe_assignments_and_complete_metrics():
 r=decide(inventory());assert len(r.eligible_cases)==3 and len(r.review_records)==6
 assert all(label==3 and denominator==3 for _,label,denominator in r.metrics)
 assert r.adjudication_status=="NOT_REQUIRED_NO_DISAGREEMENT"

def test_all_zero_tolerance_and_reconciliation_records_are_explicit():
 r=decide(inventory());assert len(r.zero_tolerance)==12 and all(v==0 for _,v in r.zero_tolerance)
 assert dict(r.reconciliation)["Acknowledgement"]=="COMPLETE"
 assert dict(r.reconciliation)["Feedback"]=="NO_PUBLICATION_ELIGIBILITY"

def test_truthful_blocked_disposition_retains_all_active_coverage_gates():
 r=decide(inventory());assert r.disposition is Disposition.BLOCKED_ACTIVE_COVERAGE
 assert len(r.residual_blockers)==20 and not r.increment11_eligible
 assert not r.publication_authorised and not r.production_activation_authorised

def test_missing_case_partial_or_optimistic_report_fails_closed():
 value=inventory();value["results"].pop()
 with pytest.raises(DecisionError):decide(value)
 value=inventory();value["terminal_outcome"]="PARTIAL"
 with pytest.raises(DecisionError):decide(value)
 with pytest.raises(DecisionError):validate(replace(decide(inventory()),increment11_eligible=True))

def test_decision_is_canonical_and_replay_deterministic():
 a=decide(inventory());b=decide(inventory());assert a.canonical_bytes()==b.canonical_bytes() and a.digest==b.digest
 assert json.loads(a.canonical_bytes())["disposition"]=="BLOCKED_ACTIVE_COVERAGE"
