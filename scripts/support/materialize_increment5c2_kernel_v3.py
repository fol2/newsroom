"""Complete the coherent hardening pass for the Increment 5C2 branch kernel."""
from __future__ import annotations

from scripts.support import materialize_increment5c2_kernel_v2 as wrapper

builder = wrapper.builder
_ORIGINAL_PATCH = builder.patch


def _replace_once(text: str, old: str, new: str, *, field: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{field} anchor drifted")
    return text.replace(old, new, 1)


def patch(root):
    _ORIGINAL_PATCH(root)

    module = root / builder.PRODUCT_FILES[0]
    text = module.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        "hydration, collision decision, fusion, Candidate mutation, external service\n",
        "hydration, collision decision, Candidate mutation or external service\n",
        field="kernel self-description boundary",
    )
    text = _replace_once(
        text,
        '''        if not all(\n            isinstance(component, BranchComponentIdentity)\n            for component in self.component_identities\n        ):\n            raise NamedToolContractError("branch component identities must be typed")\n        names = tuple(component.name for component in self.component_identities)\n''',
        '''        if not all(\n            isinstance(component, BranchComponentIdentity)\n            for component in self.component_identities\n        ):\n            raise NamedToolContractError("branch component identities must be typed")\n        if len(self.component_identities) > 16:\n            raise NamedToolContractError(\n                "branch attribution may retain at most 16 component identities"\n            )\n        names = tuple(component.name for component in self.component_identities)\n''',
        field="component identity hard cap",
    )
    text = _replace_once(
        text,
        '''        if not isinstance(self.branch_receipt_bytes, bytes) or not self.branch_receipt_bytes:\n            raise NamedToolContractError(\n                "branch result must retain non-empty canonical receipt bytes"\n            )\n        if len(self.branch_receipt_bytes) != self.attribution.branch_receipt_bytes:\n''',
        '''        if not isinstance(self.branch_receipt_bytes, bytes) or not self.branch_receipt_bytes:\n            raise NamedToolContractError(\n                "branch result must retain non-empty canonical receipt bytes"\n            )\n        if len(self.branch_receipt_bytes) > NAMED_TOOL_RESPONSE_LIMIT_BYTES:\n            raise NamedToolContractError(\n                "branch receipt exceeds the global response bound"\n            )\n        if len(self.branch_receipt_bytes) != self.attribution.branch_receipt_bytes:\n''',
        field="absolute branch receipt byte cap",
    )
    text = _replace_once(
        text,
        '''        if len(self.canonical_bytes) > self.response_limit_bytes:\n            raise NamedToolContractError(\n                "named-tool execution receipt exceeds the response bound"\n            )\n''',
        "",
        field="separate audit receipt from response payload bound",
    )
    module.write_text(text, encoding="utf-8")

    tests = root / builder.PRODUCT_FILES[1]
    text = tests.read_text(encoding="utf-8")
    old = '''def test_typed_stale_local_gate_maps_to_stale_without_branch_call(tmp_path: Path) -> None:\n    request = fulltext_request()\n    grant = replace(grant_for(request), generation_id="other-generation")\n    # Rebuild the content-addressed grant after changing generation.\n    grant = NamedToolAuthorizationGrant.create(\n        grant_id=grant.grant_id,\n        actor_id=grant.actor_id,\n        authenticated_principal_digest=grant.authenticated_principal_digest,\n        tool_id=grant.tool_id,\n        purposes=grant.purposes,\n        scope=grant.scope,\n        valid_from=grant.valid_from,\n        valid_to=grant.valid_to,\n        policy_id=grant.policy_id,\n        policy_digest=grant.policy_digest,\n        contract_digest=grant.contract_digest,\n        profile_id=grant.profile_id,\n        generation_id="other-generation",\n    )\n'''
    new = '''def test_typed_stale_local_gate_maps_to_stale_without_branch_call(tmp_path: Path) -> None:\n    request = fulltext_request()\n    base_grant = grant_for(request)\n    grant = NamedToolAuthorizationGrant.create(\n        grant_id=base_grant.grant_id,\n        actor_id=base_grant.actor_id,\n        authenticated_principal_digest=base_grant.authenticated_principal_digest,\n        tool_id=base_grant.tool_id,\n        purposes=base_grant.purposes,\n        scope=base_grant.scope,\n        valid_from=base_grant.valid_from,\n        valid_to=base_grant.valid_to,\n        policy_id=base_grant.policy_id,\n        policy_digest=base_grant.policy_digest,\n        contract_digest=base_grant.contract_digest,\n        profile_id=base_grant.profile_id,\n        generation_id="other-generation",\n    )\n'''
    text = _replace_once(
        text,
        old,
        new,
        field="content-addressed stale grant fixture",
    )
    tests.write_text(text.rstrip() + "\n", encoding="utf-8")


builder.patch = patch


if __name__ == "__main__":
    builder.main()
