from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.sdlc.contracts import ContractError, load_contract, validate_contract_data
from scripts.sdlc.validate_contract import main as validate_main
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
    assert contract.data["focus"]["ordinary_evidence_job_count"] == 1
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

    data["focus"]["ordinary_evidence_job_count"] = 2
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


def test_retained_legacy_contract_sentinels_remain_fail_closed() -> None:
    contract = load_contract(REPO_ROOT)

    assert contract.classifier_version == "sdlc-risk-v1"
    assert contract.source_path == REPO_ROOT / ".sdlc" / "gates.toml"
    assert contract.unknown_path_risk == "R3_EXTERNAL_SERVICE_SECURITY"

    global_config = contract.data["global"]
    assert global_config["required_decision_always_reports"] is True
    assert global_config["rerun_can_overwrite_required_result"] is False

    core = contract.data["lanes"]["core"]
    assert core["shard_count"] == 18
    assert core["workers_per_shard"] == 2
    assert core["max_worker_restart"] == 0
    assert core["reducer_single_canonical_receipt"] is True
    assert core["hard_timeout_seconds"] == 330


@pytest.mark.parametrize(
    ("section", "field", "value"),
    (
        ("global", "gate_command_timeout_seconds", 219),
        ("global", "gate_command_timeout_seconds", 221),
        ("global", "lane_execution_timeout_seconds", 219),
        ("global", "lane_execution_timeout_seconds", 221),
        ("global", "finalization_timeout_seconds", 19),
        ("global", "finalization_timeout_seconds", 21),
        ("gate.core-deterministic", "hard_timeout_seconds", 329),
        ("gate.core-deterministic", "hard_timeout_seconds", 331),
        ("lanes.core", "per_shard_hard_timeout_seconds", 329),
        ("lanes.core", "per_shard_hard_timeout_seconds", 331),
        ("lanes.core", "hard_timeout_seconds", 329),
        ("lanes.core", "hard_timeout_seconds", 331),
        ("lanes.core", "per_shard_warning_seconds", 299),
        ("lanes.core", "per_shard_warning_seconds", 301),
        ("lanes.core", "critical_path_warning_seconds", 299),
        ("lanes.core", "critical_path_warning_seconds", 301),
        ("test_strategy", "individual_testcase_hard_timeout_seconds", 89),
        ("test_strategy", "individual_testcase_hard_timeout_seconds", 91),
        ("test_strategy", "individual_testcase_warning_seconds", 74),
        ("test_strategy", "individual_testcase_warning_seconds", 76),
        ("lanes.service", "hard_timeout_seconds", 219),
        ("lanes.service", "hard_timeout_seconds", 221),
        ("lanes.merge_group", "hard_timeout_seconds", 219),
        ("lanes.merge_group", "hard_timeout_seconds", 221),
        ("lanes.science", "per_shard_hard_timeout_seconds", 219),
        ("lanes.science", "per_shard_hard_timeout_seconds", 221),
        ("test_sizes.science", "shard_hard_timeout_seconds", 219),
        ("test_sizes.science", "shard_hard_timeout_seconds", 221),
        ("lanes.decision", "hard_timeout_seconds", 19),
        ("lanes.decision", "hard_timeout_seconds", 21),
    ),
)
def test_retained_timing_boundaries_are_caller_invariant(
    section: str,
    field: str,
    value: int,
) -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    table = data
    for part in section.split("."):
        table = table[part]
    table[field] = value

    with pytest.raises(ContractError):
        validate_contract_data(data)


@pytest.mark.parametrize("worker_count", (1, 3, 4))
def test_unaccepted_legacy_worker_counts_fail_closed(worker_count: int) -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    data["lanes"]["core"]["workers_per_shard"] = worker_count

    with pytest.raises(ContractError, match="accepted topology"):
        validate_contract_data(data)


@pytest.mark.parametrize("shard_count", (8, 10, 12, 16))
def test_unaccepted_legacy_shard_counts_fail_closed(shard_count: int) -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    data["lanes"]["core"]["shard_count"] = shard_count

    with pytest.raises(ContractError, match="accepted topology"):
        validate_contract_data(data)


def test_owner_multiplier_lane_resolution_and_risk_order_remain_fail_closed() -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    data["owner_decisions"]["hard_budget_multiplier"] = 3
    with pytest.raises(ContractError, match="multiplier must be two"):
        validate_contract_data(data)

    data = deepcopy(load_contract(REPO_ROOT).data)
    data["gate"]["merge-exact"]["lane"] = "merge-group"
    with pytest.raises(ContractError, match="does not resolve"):
        validate_contract_data(data)

    data = deepcopy(load_contract(REPO_ROOT).data)
    data["risk"]["R2_STATEFUL_CONTRACT"]["rank"] = 1
    with pytest.raises(ContractError, match="risk ranks"):
        validate_contract_data(data)

    data = deepcopy(load_contract(REPO_ROOT).data)
    data["owner_decisions"]["selector_mutation_recall_minimum"] = 1.1
    data["test_strategy"]["selector_mutation_recall_minimum"] = 1.1
    with pytest.raises(ContractError, match=r"\(0, 1\]"):
        validate_contract_data(data)


def test_unaccepted_status_and_classifier_remain_fail_closed() -> None:
    data = deepcopy(load_contract(REPO_ROOT).data)
    data["status"] = "proposed"
    with pytest.raises(ContractError, match="not accepted"):
        validate_contract_data(data)

    data = deepcopy(load_contract(REPO_ROOT).data)
    data["classification"]["version"] = "future-unreviewed"
    with pytest.raises(ContractError, match="classifier version"):
        validate_contract_data(data)


def test_contract_path_cannot_escape_repository_or_use_symlink(
    tmp_path: Path,
) -> None:
    with pytest.raises(ContractError, match="escapes the repository"):
        load_contract(REPO_ROOT, "../outside.toml")

    link = tmp_path / "gates.toml"
    link.symlink_to(REPO_ROOT / ".sdlc" / "gates.toml")
    with pytest.raises(ContractError, match="symlinked"):
        load_contract(tmp_path, "gates.toml")


def test_owner_values_retain_safety_and_focus_decisions() -> None:
    owner = load_contract(REPO_ROOT).data["owner_decisions"]

    assert owner["accepted_at"] == "2026-07-22"
    assert owner["budget_amended_at"] == "2026-08-02"
    assert owner["focus_gate_accepted_at"] == "2026-08-27"
    assert owner["hard_budget_multiplier"] == 2
    assert owner["selector_known_failure_miss_limit"] == 0
    assert owner["selector_mutation_recall_minimum"] == 0.995
    assert owner["critical_main_failure_pauses_merges"] is True
    assert owner["release_evidence_retention_years"] == 7


def test_contract_control_still_covers_classifier_and_focus_sources() -> None:
    patterns = load_contract(REPO_ROOT).path_groups["contract_control"]

    assert "scripts/sdlc/**" in patterns
    assert "newsroom/tests/test_sdlc_*.py" in patterns
    assert "newsroom/tests/test_focus_gate.py" in patterns


def test_contract_validation_cli_emits_small_typed_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert validate_main(("--repo-root", str(REPO_ROOT))) == 0
    output = capsys.readouterr().out

    assert '"status":"PASS"' in output
    assert '"contract_version":"sdlc-v2.6"' in output
    assert "R4_RELEASE_OPERATIONAL" in output
