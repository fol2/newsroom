"""Machine-checkable, immutable Increment 10 local-fixture canary scope."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment10.plan import INCREMENT_10_PLAN

class ScopeError(ValueError): pass

def _freeze(v: object) -> object:
    if isinstance(v, Mapping): return MappingProxyType({str(k):_freeze(x) for k,x in v.items()})
    if isinstance(v, (tuple,list)): return tuple(_freeze(x) for x in v)
    return v

def _plain(v: object) -> object:
    if isinstance(v, Mapping): return {str(k):_plain(x) for k,x in v.items()}
    if isinstance(v, (tuple,list)): return [_plain(x) for x in v]
    return v

@dataclass(frozen=True, slots=True)
class CanaryScope:
    plan_digest: str
    scope: Mapping[str,object]
    rights_sensitive: Mapping[str,object]
    review: Mapping[str,object]
    credentials_egress: Mapping[str,object]
    budgets: Mapping[str,object]
    retention: Mapping[str,object]
    containment: Mapping[str,object]
    operational_profile: Mapping[str,object]
    digest: str

    def admits_candidate(self, candidate_version_id: str) -> bool:
        return candidate_version_id in self.scope["candidate_version_ids"]

    def stop_reason(self, findings: set[str]) -> str | None:
        aliases={"PRODUCTION_MUTATION":"PUBLIC_OR_PRODUCTION_EFFECT","PUBLIC_EFFECT":"PUBLIC_OR_PRODUCTION_EFFECT","RIGHTS_BREACH":"RIGHTS_OR_CREDENTIAL","CREDENTIAL_EXPOSURE":"RIGHTS_OR_CREDENTIAL","PROHIBITED_EGRESS":"PROHIBITED_EGRESS","AMBIGUOUS_EFFECT":"AMBIGUOUS_EFFECT","BUDGET_EXHAUSTION":"BUDGET","IMPOSSIBLE_COVERAGE":"IMPOSSIBLE_COVERAGE"}
        normalised={aliases.get(item,item) for item in findings}
        return next((item for item in self.containment["stop_precedence"] if item in normalised),None)

    def permits_material_change(self, replacement_plan_digest: str | None) -> bool:
        return bool(replacement_plan_digest and replacement_plan_digest != self.plan_digest and replacement_plan_digest.startswith("sha256:"))

    @property
    def permits_runtime(self) -> bool: return False


def load_frozen_scope() -> CanaryScope:
    decisions={item["decision_id"]:item["selection"] for item in INCREMENT_10_PLAN.owner_decisions}
    bindings=((1,"scope"),(3,"rights_sensitive"),(4,"review"),(5,"credentials_egress"),(6,"budgets"),(7,"retention"),(8,"containment"),(9,"operational_profile"))
    values=[]
    for index,name in bindings:
        raw=decisions[f"I10-OD-{index:03d}"]
        if set(raw)!={name}: raise ScopeError(f"owner binding for {name} differs")
        values.append(_freeze(raw[name]))
    snapshot={name:value for (_,name),value in zip(bindings,values)}
    digest=digest_bytes(canonical_json_bytes(_plain(snapshot)))
    result=CanaryScope(INCREMENT_10_PLAN.plan_digest,*values,digest)  # type: ignore[arg-type]
    _validate(result)
    return result


def _validate(value: CanaryScope) -> None:
    s=value.scope
    if len(s["candidate_version_ids"]) != s["denominator"] or (s["exposure_min"],s["exposure_max"]) != (3,3): raise ScopeError("cohort denominator differs")
    if s["destination"] != "local://increment10/evidence-intake-fixture-v1" or s["inclusion_rule"] != "EXACT_LIST_ONLY": raise ScopeError("destination or inclusion differs")
    if value.rights_sensitive["personal_data"] != "SYNTHETIC_ONLY" or value.rights_sensitive["live_source_bytes_allowed"] is not False: raise ScopeError("rights boundary differs")
    if value.review["live_evidence_access"] is not False or value.review["human_minutes"] != 0: raise ScopeError("review boundary differs")
    net=value.credentials_egress
    if net["credential_classes"] or net["secret_locations"] or net["allowed_hosts"] or not net["loopback_only"] or net["dns_allowed"] or net["tls_external_allowed"]: raise ScopeError("credentials or egress boundary differs")
    budget=value.budgets
    zero=("external_requests_max","provider_requests_max","model_input_tokens_max","model_output_tokens_max","embedding_units_max","reviewer_minutes_max","gross_gbp_minor_units_max")
    if any(budget[k] != 0 for k in zero) or budget["storage_bytes_max"] != 10*1024*1024: raise ScopeError("budget boundary differs")
    if not value.retention["no_resurrection"] or value.containment["kill_seconds_max"] > 1 or value.containment["contain_seconds_max"] > 5: raise ScopeError("retention or containment differs")
    if not value.operational_profile["production_nonmutation"] or not value.operational_profile["publication_nonreachability"]: raise ScopeError("Operational Profile differs")

FROZEN_SCOPE=load_frozen_scope()
