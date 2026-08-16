import pytest
from newsroom.increment10.review import *

def universe(): return seal_universe(epoch_id="e1",cohort_digest="sha256:"+"1"*64,case_ids=("c1","c2","c3"),sealed_at=10,execution_complete=True)
def people(): return (Reviewer("m","MECHANISM_REVIEWER"),Reviewer("a","RESULT_AUDITOR"),Reviewer("j","FIXTURE_ADJUDICATOR"))

def test_unsealed_or_substituted_universe_is_rejected():
    with pytest.raises(ReviewContractError): seal_universe(epoch_id="e",cohort_digest="d",case_ids=("c1","c2","c3"),sealed_at=1,execution_complete=False)
    with pytest.raises(ReviewContractError): seal_universe(epoch_id="e",cohort_digest="d",case_ids=("c1","c1","c3"),sealed_at=1,execution_complete=True)

def test_deterministic_blinded_independent_assignments():
    result=assign(universe(),people())
    assert len(result)==3 and all(x.expected_outcome_hidden for x in result)
    assert all(x.mechanism_reviewer!=x.result_auditor for x in result)

def test_conflict_same_reviewer_and_chronology_fail_closed():
    with pytest.raises(ReviewContractError): assign(universe(),(Reviewer("x","MECHANISM_REVIEWER"),Reviewer("x","RESULT_AUDITOR")))
    a=assign(universe(),people())[0]
    with pytest.raises(ReviewContractError): record_review(universe(),a,reviewer_id="m",role="MECHANISM_REVIEWER",label=Label.PASS,structured_reasons=("ok",),confidence_basis="fixture",completed_at=9)

def test_review_pair_and_adjudication_are_complete():
    u=universe(); a=assign(u,people())[0]
    r1=record_review(u,a,reviewer_id="m",role="MECHANISM_REVIEWER",label=Label.PASS,structured_reasons=("contract",),confidence_basis="replay",completed_at=11)
    r2=record_review(u,a,reviewer_id="a",role="RESULT_AUDITOR",label=Label.FAIL,structured_reasons=("result",),confidence_basis="sealed bytes",completed_at=12)
    result=adjudicate(u,adjudicator=people()[2],records=(r1,r2),label=Label.UNREVIEWABLE,reason="disagreement")
    assert result.case_id=="c1" and len(result.input_digests)==2

def test_metrics_use_complete_denominators_and_closed_inventory():
    validate_metric_inventory({name:(3,3) for name in METRICS})
    with pytest.raises(ReviewContractError): validate_metric_inventory({name:(1,2) for name in METRICS})
    with pytest.raises(ReviewContractError): validate_metric_inventory({"quality":(3,3)})

def test_zero_tolerance_precedes_material_and_ordinary_incidents():
    assert incident_severity({"PUBLIC_EFFECT","RESIDUAL_RISK"}) is IncidentSeverity.ZERO_TOLERANCE
    assert incident_severity({"RESIDUAL_RISK"}) is IncidentSeverity.MATERIAL
    assert incident_severity({"RETRY"}) is IncidentSeverity.ORDINARY
    assert "ELIGIBLE_FOR_ACTIVATION_PLANNING" in DECISIONS
