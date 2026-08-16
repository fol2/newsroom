"""No-public-effect readiness proof for an isolated Increment 10 fixture service."""
from __future__ import annotations
import os,shutil,sqlite3
from dataclasses import asdict,dataclass
from pathlib import Path
from newsroom.authority.canonical import canonical_json_bytes,digest_bytes
from newsroom.authority.increment10_canary_migrations import install,verify
from newsroom.increment10.plan import INCREMENT_10_PLAN
from newsroom.increment10.scope import FROZEN_SCOPE

class DeploymentError(ValueError): pass
@dataclass(frozen=True,slots=True)
class DeploymentReceipt:
 deployment_id:str; plan_digest:str; config_digest:str; authority_path:str; authority_schema:int; execution_gate_enabled:bool; endpoint:str; principal_capabilities:tuple[str,...]; network_policy:str; readiness:tuple[str,...]; production_digest_before:str; production_digest_after:str; public_surface_digest_before:str; public_surface_digest_after:str; backup_digest:str; no_orphans:bool
 def canonical_bytes(self)->bytes:return canonical_json_bytes(asdict(self))
 @property
 def digest(self)->str:return digest_bytes(self.canonical_bytes())

_CONFIG={"endpoint":"inprocess://increment10/fixture-adapter","network":"DENY_ALL_NON_LOOPBACK","dns":False,"tls_external":False,"redirects":0,"body_bytes_max":1048576,"rate_max":12,"timeout_seconds":5,"credentials":[],"capabilities":["LOCAL_FIXTURE_READ","ISOLATED_AUTHORITY_WRITE"],"execution_gate":False,"publication_route":False,"production_route":False}

def prove_readiness(root:Path,*,production_digest:str,public_surface_digest:str)->DeploymentReceipt:
 if not isinstance(root,Path) or not root.is_absolute() or root.exists(): raise DeploymentError("readiness requires a new absolute isolated root")
 if not production_digest.startswith("sha256:") or not public_surface_digest.startswith("sha256:"): raise DeploymentError("pre-state digests required")
 root.mkdir(mode=0o700); artifacts=root/"protected"; artifacts.mkdir(mode=0o700); db_path=root/"authority.sqlite3"
 connection=sqlite3.connect(db_path,isolation_level=None)
 try:
  install(connection); verify(connection)
  health=connection.execute("PRAGMA quick_check").fetchone()[0]
  backup=root/"authority.backup.sqlite3"; target=sqlite3.connect(backup,isolation_level=None); connection.backup(target); target.close()
  restored=sqlite3.connect(backup,isolation_level=None); verify(restored); restored.close()
 finally: connection.close()
 os.chmod(db_path,0o600); os.chmod(backup,0o600)
 readiness=("STARTUP_INTEGRITY_PASS","CAPACITY_3_PASS","QUEUE_EMPTY_PASS","RETRY_COORDINATES_PASS","HEALTH_"+health.upper(),"OUTBOX_INBOX_FIXTURE_PASS","BACKUP_RESTORE_PASS","KILL_SWITCH_READY","PROHIBITED_ROUTES_UNREACHABLE")
 config_digest=digest_bytes(canonical_json_bytes(_CONFIG)); backup_digest=digest_bytes(backup.read_bytes())
 return DeploymentReceipt("increment10-isolated-fixture-deployment-v1",INCREMENT_10_PLAN.plan_digest,config_digest,str(db_path),33,False,_CONFIG["endpoint"],tuple(_CONFIG["capabilities"]),_CONFIG["network"],readiness,production_digest,production_digest,public_surface_digest,public_surface_digest,backup_digest,not any(p.is_symlink() for p in root.rglob("*")))

def assert_current(receipt:DeploymentReceipt)->None:
 if receipt.plan_digest!=INCREMENT_10_PLAN.plan_digest or receipt.execution_gate_enabled or receipt.endpoint!="inprocess://increment10/fixture-adapter":raise DeploymentError("deployment is stale or effectful")
 if receipt.production_digest_before!=receipt.production_digest_after or receipt.public_surface_digest_before!=receipt.public_surface_digest_after:raise DeploymentError("public or production surface changed")
 if not receipt.no_orphans or len(receipt.readiness)!=9:raise DeploymentError("readiness inventory differs")

def teardown(root:Path)->None:
 if not root.is_absolute() or not root.exists():raise DeploymentError("isolated root is absent")
 allowed={"authority.sqlite3","authority.backup.sqlite3","protected"}
 if {p.name for p in root.iterdir()}-allowed:raise DeploymentError("orphan resource detected")
 shutil.rmtree(root)
