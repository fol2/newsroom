import sqlite3
import pytest
from newsroom.authority.increment10_canary_migrations import install
from newsroom.increment10.controller import *
from newsroom.increment10.deployment import prove_readiness
from newsroom.increment10.epoch import *

def setup(tmp_path):
 receipt=prove_readiness(tmp_path/"service",production_digest="sha256:"+"1"*64,public_surface_digest="sha256:"+"2"*64)
 epoch=create_epoch(receipt,opens_at=10,closes_at=100)
 c=sqlite3.connect(":memory:",isolation_level=None);install(c)
 return epoch,FixtureController(epoch,TransportStore(c))

def test_epoch_binds_plan_scope_deployment_and_exact_cohort(tmp_path):
 epoch,_=setup(tmp_path); assert epoch.denominator==3 and len(epoch.cohort)==3
 assert epoch.external_requests_max==epoch.gross_budget_gbp_minor==0 and not epoch.execution_authorised

def test_complete_path_qualification_is_non_decision_bearing_and_nonmutating(tmp_path):
 epoch,controller=setup(tmp_path); d="sha256:"+"3"*64
 result=controller.qualify(production_digest=d,publication_digest=d); validate_receipt(result)
 assert result.denominator==3 and len(result.checkpoint_digests)==3 and not result.decision_bearing
 with pytest.raises(ControllerError):controller.execute()

def test_checkpoint_budget_scope_and_chronology_fail_closed(tmp_path):
 epoch,_=setup(tmp_path)
 with pytest.raises(EpochError):checkpoint(epoch,candidate_version_id="other",sequence=1,state="x",watermark=1)
 with pytest.raises(EpochError):checkpoint(epoch,candidate_version_id=epoch.cohort[0],sequence=2,state="x",watermark=1)
 with pytest.raises(EpochError):checkpoint(epoch,candidate_version_id=epoch.cohort[0],sequence=1,state="x",watermark=1,usage_requests=1)

def test_epoch_material_change_changes_identity_and_old_history_remains(tmp_path):
 receipt=prove_readiness(tmp_path/"service",production_digest="sha256:"+"1"*64,public_surface_digest="sha256:"+"2"*64)
 a=create_epoch(receipt,opens_at=10,closes_at=100); b=create_epoch(receipt,opens_at=11,closes_at=100)
 assert a.digest!=b.digest and a.cohort==b.cohort

def test_all_outcomes_are_closed_vocabulary():
 assert {x.value for x in Outcome}=={"COMPLETE","PARTIAL","REJECTED","UNAVAILABLE","TIMED_OUT","AMBIGUOUS","EARLY_STOPPED","BLOCKED","INCONCLUSIVE"}
