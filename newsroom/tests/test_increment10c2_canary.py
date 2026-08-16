import importlib.util,sqlite3,sys
from dataclasses import replace
from pathlib import Path
import pytest
from newsroom.authority.increment10_canary_migrations import install
from newsroom.increment10.epoch import CanaryEpoch
from newsroom.increment10.transport_store import TransportStore
spec=importlib.util.spec_from_file_location("canary","scripts/increment10_canary.py");m=importlib.util.module_from_spec(spec);sys.modules["canary"]=m;spec.loader.exec_module(m) # type: ignore[union-attr]

def epoch():return CanaryEpoch("epoch",m.PLAN_DIGEST,"scope",m.DEPLOYMENT_DIGEST,m.COHORT,3,1786875300,1786875600,0,0,False)
def canonical_epoch(e):return replace(e,epoch_id="epoch:"+"x")
def store():c=sqlite3.connect(":memory:",isolation_level=None);install(c);return TransportStore(c)

def test_complete_prospective_inventory_is_sealed_without_cherry_picking(monkeypatch):
 e=epoch(); monkeypatch.setattr(type(e),"digest",property(lambda self:m.EPOCH_DIGEST))
 result=m.execute(store(),e,production_digest="sha256:"+"a"*64,publication_digest="sha256:"+"b"*64,sealed_at=e.opens_at+10)
 assert result.denominator==3 and tuple(x.candidate_version_id for x in result.results)==m.COHORT
 assert result.terminal_outcome=="COMPLETE" and result.digest.startswith("sha256:")

def test_every_case_retains_transport_evidence_and_zero_external_budget(monkeypatch):
 e=epoch();monkeypatch.setattr(type(e),"digest",property(lambda self:m.EPOCH_DIGEST));r=m.execute(store(),e,production_digest="p",publication_digest="q",sealed_at=e.opens_at+10)
 assert all(x.transport_receipts and x.evidence_package_digest.startswith("sha256:") for x in r.results)
 assert sum(x.external_requests for x in r.results)==sum(x.cost_gbp_minor for x in r.results)==0
 assert all(x.outcome=="ACCEPTED" for x in r.results)

def test_authority_drift_window_and_mutation_fail_closed(monkeypatch):
 e=epoch();monkeypatch.setattr(type(e),"digest",property(lambda self:m.EPOCH_DIGEST))
 with pytest.raises(m.CanaryExecutionError):m.execute(store(),replace(e,plan_digest="changed"),production_digest="p",publication_digest="q",sealed_at=e.opens_at+1)
 with pytest.raises(m.CanaryExecutionError):m.execute(store(),e,production_digest="p",publication_digest="q",sealed_at=e.closes_at)
 good=m.execute(store(),e,production_digest="p",publication_digest="q",sealed_at=e.opens_at+1)
 with pytest.raises(m.CanaryExecutionError):m.validate(replace(good,production_after="changed"))

def test_no_publication_eligibility_is_inferred():
 digest,ack=m._fixture_intake(m.COHORT[0],1);assert digest.startswith("sha256:") and ack.startswith("fixture-ack-")
 assert "publication_eligible" not in m.CaseResult.__annotations__
