from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.sdlc.contracts import (
    ContractError,
    load_contract,
    validate_contract_data,
)
from scripts.sdlc.validate_contract import main as validate_main


REPO_ROOT = Path(__file__).parents[2]


def test_accepted_contract_loads_and_references_exact_source_files() -> None:
    contract = load_contract(REPO_ROOT)

    assert contract.contract_version == "sdlc-v2.2"
    assert contract.data["status"] == "accepted"
    assert contract.source_path == REPO_ROOT / ".sdlc" / "gates.toml"
    assert contract.data["acceptance_record"] == (
        "docs/specs/sdlc/2026-07-22-sdlc-v2-owner-acceptance.md"
    )
    assert contract.unknown_path_risk == "R3_EXTERNAL_SERVICE_SECURITY"


def test_every_gate_lane_resolves_and_all_machine_timeouts_are_sub_minute() -> None:
    contract = load_contract(REPO_ROOT)
    lanes = contract.data["lanes"]

    for gate in contract.data["gate"].values():
        assert gate["lane"] in lanes
        assert 0 < gate["hard_timeout_seconds"] < 60
    assert lanes["decision"]["always_reports"] is True
    assert lanes["core"]["hard_timeout_seconds"] == 55
    assert lanes["service"]["hard_timeout_seconds"] == 55
    assert lanes["merge_group"]["hard_timeout_seconds"] == 55


def test_unresolved_lane_is_rejected_instead_of_using_a_generic_default() -> None:
    contract = load_contract(REPO_ROOT)
    data = deepcopy(contract.data)
    data["gate"]["merge-exact"]["lane"] = "merge-group"

    with pytest.raises(ContractError, match="does not resolve"):
        validate_contract_data(data)


def test_proposed_contract_cannot_drive_accepted_implementation() -> None:
    contract = load_contract(REPO_ROOT)
    data = deepcopy(contract.data)
    data["status"] = "proposed"

    with pytest.raises(ContractError, match="not accepted"):
        validate_contract_data(data)


def test_owner_values_match_review_and_selector_policy() -> None:
    contract = load_contract(REPO_ROOT)
    owner = contract.data["owner_decisions"]

    assert owner == {
        "accepted_at": "2026-07-22",
        "review_net_executable_lines_trigger": 400,
        "review_changed_files_trigger": 12,
        "selector_shadow_calendar_days": 30,
        "selector_shadow_minimum_changes": 500,
        "selector_known_failure_miss_limit": 0,
        "selector_mutation_recall_minimum": 0.995,
        "prewarmed_runner_evaluation_permitted_after_measured_slo_failure": True,
        "critical_main_failure_pauses_merges": True,
        "pr_evidence_retention_days": 30,
        "main_evidence_retention_days": 180,
        "release_evidence_retention_years": 7,
    }


def test_contract_validation_cli_emits_a_small_typed_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert validate_main(("--repo-root", str(REPO_ROOT))) == 0
    output = capsys.readouterr().out

    assert '"status":"PASS"' in output
    assert '"contract_version":"sdlc-v2.2"' in output
    assert "R4_RELEASE_OPERATIONAL" in output
