import json,subprocess
from pathlib import Path
import pytest
from newsroom.increment10.deployment import *
D="sha256:"+"1"*64

def test_actual_isolated_service_readiness_backup_and_nonmutation(tmp_path):
 root=tmp_path/"service"; r=prove_readiness(root,production_digest=D,public_surface_digest=D); assert_current(r)
 assert r.authority_schema==33 and not r.execution_gate_enabled
 assert r.production_digest_before==r.production_digest_after
 assert (root/"authority.backup.sqlite3").exists(); assert oct((root/"authority.sqlite3").stat().st_mode & 0o777)=="0o600"
 teardown(root); assert not root.exists()

def test_existing_root_stale_receipt_and_orphan_fail_closed(tmp_path):
 root=tmp_path/"existing"; root.mkdir()
 with pytest.raises(DeploymentError):prove_readiness(root,production_digest=D,public_surface_digest=D)
 root.rmdir(); r=prove_readiness(root,production_digest=D,public_surface_digest=D)
 from dataclasses import replace
 with pytest.raises(DeploymentError):assert_current(replace(r,execution_gate_enabled=True))
 (root/"orphan").write_text("x")
 with pytest.raises(DeploymentError,match="orphan"):teardown(root)

def test_cli_emits_readiness_not_execution(tmp_path):
 root=tmp_path/"cli"
 result=subprocess.run(["python3","scripts/increment10_canary_deployment.py","--root",str(root),"--production-digest",D,"--public-surface-digest",D],text=True,capture_output=True,check=True)
 value=json.loads(result.stdout); assert value["status"]=="READY_NO_EXECUTION" and value["receipt"]["execution_gate_enabled"] is False

def test_configuration_has_no_credentials_network_or_public_routes(tmp_path):
 r=prove_readiness(tmp_path/"x",production_digest=D,public_surface_digest=D)
 assert r.principal_capabilities==("LOCAL_FIXTURE_READ","ISOLATED_AUTHORITY_WRITE")
 assert r.network_policy=="DENY_ALL_NON_LOOPBACK" and r.endpoint.startswith("inprocess://")
 assert "PROHIBITED_ROUTES_UNREACHABLE" in r.readiness
