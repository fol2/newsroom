from __future__ import annotations

from copy import deepcopy

import pytest

from newsroom.editorial.policy import (
    PolicyValidationError,
    load_shadow_policy,
    validate_policy,
)


def test_checked_in_shadow_policy_is_closed_and_has_required_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWSROOM_EDITORIAL_POLICY", "/tmp/attacker-policy.json")
    monkeypatch.setenv("NEWSROOM_EDITORIAL_STATE_ROOT", "/tmp/public")

    policy = load_shadow_policy()

    assert policy.policy_id == "editorial-shadow-v1"
    assert policy.target_allowlist == ("shadow-recording",)
    assert policy.outcome_precedence == ("REJECT", "HOLD_FOR_REVIEW", "AUTO_PUBLISH")
    assert policy.status_outcomes["MISSING"] == "HOLD_FOR_REVIEW"
    assert {gate.gate_id for gate in policy.gates} == {
        "claim_evidence",
        "rights",
        "sensitive_risk",
        "jurisdiction",
        "article_contract",
    }
    assert policy.limits.max_input_bytes == 16 * 1024 * 1024
    assert policy.limits.max_package_bytes == 16 * 1024 * 1024
    assert policy.limits.max_database_bytes == 512 * 1024 * 1024
    assert policy.limits.min_free_bytes == 256 * 1024 * 1024
    assert policy.limits.wal_autocheckpoint_pages > 0
    assert policy.state_root.root_id == "account-state"
    assert policy.specification_trace


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("gates"),
        lambda value: value.pop("reason_order"),
        lambda value: value.pop("target_allowlist"),
        lambda value: value.pop("outcome_precedence"),
        lambda value: value.pop("status_outcomes"),
        lambda value: value.pop("trusted_input_roots"),
        lambda value: value.pop("state_root"),
        lambda value: value.pop("limits"),
        lambda value: value.pop("component_versions"),
        lambda value: value.pop("specification_trace"),
        lambda value: value.update({"unreviewed_override": True}),
    ],
)
def test_policy_rejects_missing_or_unknown_authority_fields(mutate) -> None:  # type: ignore[no-untyped-def]
    value = deepcopy(load_shadow_policy().raw)
    mutate(value)
    with pytest.raises(PolicyValidationError):
        validate_policy(value)


def test_policy_rejects_widened_roots_limits_and_incomplete_reason_order() -> None:
    value = deepcopy(load_shadow_policy().raw)
    value["trusted_input_roots"][0]["relative_path"] = "../outside"
    with pytest.raises(PolicyValidationError, match="relative"):
        validate_policy(value)

    value = deepcopy(load_shadow_policy().raw)
    value["limits"]["max_package_bytes"] = 0
    with pytest.raises(PolicyValidationError):
        validate_policy(value)

    value = deepcopy(load_shadow_policy().raw)
    value["reason_order"].remove("MISSING_RIGHTS")
    with pytest.raises(PolicyValidationError, match="reason"):
        validate_policy(value)


def test_policy_rejects_duplicate_gate_root_reason_and_trace_ids() -> None:
    for field, duplicate in (
        ("gates", lambda value: deepcopy(value["gates"][0])),
        ("trusted_input_roots", lambda value: deepcopy(value["trusted_input_roots"][0])),
        ("reason_order", lambda value: value["reason_order"][0]),
        ("specification_trace", lambda value: deepcopy(value["specification_trace"][0])),
    ):
        value = deepcopy(load_shadow_policy().raw)
        value[field].append(duplicate(value))
        with pytest.raises(PolicyValidationError, match="duplicate"):
            validate_policy(value)
