from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.sdlc.contracts import ContractError, load_contract, validate_contract_data
from scripts.sdlc.focus_gate import (
    FocusGateError,
    load_focus_contract,
    validate_focus_contract_data,
)


REPO_ROOT = Path(__file__).parents[2]


def test_accepted_legacy_and_focus_contracts_load_together() -> None:
    contract = load_contract(REPO_ROOT)
    focus = load_focus_contract(REPO_ROOT)

    assert contract.contract_version == "sdlc-v2.6"
    assert contract.data["status"] == "accepted"
    assert contract.data["specification"] == (
        "docs/specs/sdlc/ai-native-focus-gated-sdlc.md"
    )
    assert contract.data["acceptance_record"] == (
        "docs/specs/sdlc/ai-native-focus-gated-sdlc.md"
    )
    assert contract.data["issue"] == 799
    assert focus["contract_version"] == "focus-gates-v1"
    assert focus["issue"] == 799


def test_ordinary_pr_defaults_are_focused_not_universal() -> None:
    contract = load_contract(REPO_ROOT)
    assert contract.data["global"]["full_suite_is_default"] is False
    assert contract.data["test_strategy"]["full_suite_blocking_default"] is False
    assert contract.data["test_strategy"]["selector_initial_mode"] == "focus_enforced"
    assert contract.data["focus"]["ordinary_job_count"] == 1
    assert contract.data["focus"]["documentation_dependency_bootstraps"] == 0
    assert contract.data["focus"]["executable_dependency_bootstraps"] == 1


def test_full_health_and_service_contracts_remain_available() -> None:
    contract = load_contract(REPO_ROOT)
    lanes = contract.data["lanes"]
    assert lanes["core"]["shard_count"] == 18
    assert lanes["core"]["required"] is True
    assert lanes["service"]["actual_service_required"] is True
    assert lanes["service"]["fake_or_noop_satisfies"] is False
    assert contract.data["risk"]["R4_RELEASE_OPERATIONAL"][
        "owner_authority_required"
    ] is True


@pytest.mark.parametrize("version", ("sdlc-v2.5", "sdlc-v2.7"))
def test_unaccepted_legacy_contract_version_still_fails_closed(version: str) -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    data["contract_version"] = version
    with pytest.raises(ContractError, match="contract version"):
        validate_contract_data(data)


def test_measured_hard_budgets_remain_fail_closed() -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    data["gate"]["core-deterministic"]["hard_timeout_seconds"] = 331
    with pytest.raises(ContractError, match="below 331"):
        validate_contract_data(data)

    data = deepcopy(load_contract(REPO_ROOT).data)
    data["lanes"]["service"]["hard_timeout_seconds"] = 221
    with pytest.raises(ContractError):
        validate_contract_data(data)


def test_focus_contract_rejects_cost_or_safety_drift() -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    validate_focus_contract_data(data)

    data["focus"]["ordinary_job_count"] = 2
    with pytest.raises(FocusGateError, match="accepted policy"):
        validate_focus_contract_data(data)

    data = deepcopy(load_contract(REPO_ROOT).data)
    data["focus"]["provider_calls_implicit"] = True
    with pytest.raises(FocusGateError, match="accepted policy"):
        validate_focus_contract_data(data)


def test_focus_contract_references_real_machine_files() -> None:
    focus = load_focus_contract(REPO_ROOT)
    for field in (
        "route_schema",
        "ordinary_pr_workflow",
        "full_health_workflow",
        "research_workflow",
    ):
        assert (REPO_ROOT / focus[field]).is_file()
