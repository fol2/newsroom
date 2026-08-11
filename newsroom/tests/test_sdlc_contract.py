from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import scripts.sdlc.workflow_lane as lane_module
from scripts.sdlc.contracts import (
    ContractError,
    load_contract,
    validate_contract_data,
)
from scripts.sdlc.validate_contract import main as validate_main

REPO_ROOT = Path(__file__).parents[2]


def test_accepted_contract_loads_and_references_exact_source_files() -> None:
    contract = load_contract(REPO_ROOT)

    assert contract.contract_version == "sdlc-v2.5"
    assert contract.classifier_version == "sdlc-risk-v1"
    assert contract.data["status"] == "accepted"
    assert contract.source_path == REPO_ROOT / ".sdlc" / "gates.toml"
    assert contract.data["acceptance_record"] == (
        "docs/specs/sdlc/2026-08-10-sdlc-v2.5-core-sharding-amendment.md"
    )
    assert contract.unknown_path_risk == "R3_EXTERNAL_SERVICE_SECURITY"


def test_every_gate_lane_resolves_and_all_hard_timeouts_are_below_four_minutes() -> (
    None
):
    contract = load_contract(REPO_ROOT)
    lanes = contract.data["lanes"]

    for gate in contract.data["gate"].values():
        assert gate["lane"] in lanes
        assert 0 < gate["hard_timeout_seconds"] < 240
    assert contract.data["global"] == {
        "gate_command_timeout_seconds": 220,
        "lane_execution_timeout_seconds": 220,
        "finalization_timeout_seconds": 20,
        "pr_feedback_p50_target_seconds": 30,
        "pr_feedback_p95_target_seconds": 60,
        "runner_queue_p95_target_seconds": 5,
        "warm_bootstrap_p95_target_seconds": 10,
        "cold_bootstrap_migration_p95_target_seconds": 30,
        "obsolete_head_cancellation_target_seconds": 5,
        "unknown_path_risk": "R3_EXTERNAL_SERVICE_SECURITY",
        "classifier_error_risk": "R3_EXTERNAL_SERVICE_SECURITY",
        "full_suite_is_default": True,
        "required_decision_always_reports": True,
        "rerun_can_overwrite_required_result": False,
    }
    assert {
        name: value["hard_timeout_seconds"]
        for name, value in contract.data["gate"].items()
    } == {
        "route": 20,
        "source-integrity": 60,
        "core-deterministic": 220,
        "service-neo4j": 220,
        "merge-exact": 220,
        "science-shard": 220,
        "evidence-finalize": 20,
    }
    assert lanes["decision"] == {"always_reports": True, "hard_timeout_seconds": 20}
    assert lanes["core"]["hard_timeout_seconds"] == 220
    assert lanes["core"] == {
        "bootstrap_once": True,
        "shard_count": 6,
        "partition": "sha256_node_id_balanced",
        "workers_per_shard": 2,
        "distribution": "worksteal",
        "max_worker_restart": 0,
        "per_shard_hard_timeout_seconds": 220,
        "reducer_single_canonical_receipt": True,
        "run_full_suite_when_p95_below_seconds": 35,
        "hard_timeout_seconds": 220,
        "required": True,
    }
    assert lanes["service"]["hard_timeout_seconds"] == 220
    assert lanes["merge_group"]["hard_timeout_seconds"] == 220
    assert lanes["science"]["per_shard_hard_timeout_seconds"] == 220
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/evidence.yml").read_text(encoding="utf-8")
    )
    workflow_shards = workflow["jobs"]["core_shard"]["strategy"]["matrix"]["shard"]
    assert workflow_shards == list(range(lanes["core"]["shard_count"]))
    assert lanes["core"]["shard_count"] == lane_module._CORE_SHARD_COUNT


@pytest.mark.parametrize("worker_count", (1, 3, 4))
def test_unaccepted_core_worker_counts_fail_closed(worker_count: int) -> None:
    contract = load_contract(REPO_ROOT)
    data = deepcopy(contract.data)
    data["lanes"]["core"]["workers_per_shard"] = worker_count

    with pytest.raises(ContractError, match="accepted topology"):
        validate_contract_data(data)


def test_four_minute_ceiling_and_owner_multiplier_are_fail_closed() -> None:
    contract = load_contract(REPO_ROOT)

    oversized = deepcopy(contract.data)
    oversized["gate"]["core-deterministic"]["hard_timeout_seconds"] = 240
    with pytest.raises(ContractError, match="below 240"):
        validate_contract_data(oversized)

    wrong_owner_multiplier = deepcopy(contract.data)
    wrong_owner_multiplier["owner_decisions"]["hard_budget_multiplier"] = 3
    with pytest.raises(ContractError, match="multiplier must be two"):
        validate_contract_data(wrong_owner_multiplier)


def test_unresolved_lane_is_rejected_instead_of_using_a_generic_default() -> None:
    contract = load_contract(REPO_ROOT)
    data = deepcopy(contract.data)
    data["gate"]["merge-exact"]["lane"] = "merge-group"

    with pytest.raises(ContractError, match="does not resolve"):
        validate_contract_data(data)


def test_duplicate_risk_rank_and_out_of_range_mutation_recall_are_rejected() -> None:
    contract = load_contract(REPO_ROOT)
    duplicate = deepcopy(contract.data)
    duplicate["risk"]["R2_STATEFUL_CONTRACT"]["rank"] = 1
    with pytest.raises(ContractError, match="risk ranks"):
        validate_contract_data(duplicate)

    invalid_probability = deepcopy(contract.data)
    invalid_probability["owner_decisions"]["selector_mutation_recall_minimum"] = 1.1
    invalid_probability["test_strategy"]["selector_mutation_recall_minimum"] = 1.1
    with pytest.raises(ContractError, match=r"\(0, 1\]"):
        validate_contract_data(invalid_probability)


def test_proposed_or_unknown_classifier_contract_cannot_drive_implementation() -> None:
    contract = load_contract(REPO_ROOT)
    proposed = deepcopy(contract.data)
    proposed["status"] = "proposed"
    with pytest.raises(ContractError, match="not accepted"):
        validate_contract_data(proposed)

    unknown_classifier = deepcopy(contract.data)
    unknown_classifier["classification"]["version"] = "future-unreviewed"
    with pytest.raises(ContractError, match="classifier version"):
        validate_contract_data(unknown_classifier)


def test_contract_path_cannot_escape_repository() -> None:
    with pytest.raises(ContractError, match="escapes the repository"):
        load_contract(REPO_ROOT, "../outside.toml")


def test_contract_path_cannot_be_a_symlink(tmp_path: Path) -> None:
    link = tmp_path / "gates.toml"
    link.symlink_to(REPO_ROOT / ".sdlc" / "gates.toml")

    with pytest.raises(ContractError, match="symlinked"):
        load_contract(tmp_path, "gates.toml")


def test_owner_values_match_review_and_selector_policy() -> None:
    contract = load_contract(REPO_ROOT)
    owner = contract.data["owner_decisions"]

    assert owner == {
        "accepted_at": "2026-07-22",
        "budget_amended_at": "2026-08-02",
        "predecessor_contract_version": "sdlc-v2.3",
        "hard_budget_multiplier": 2,
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


def test_contract_control_includes_classifier_source_and_tests() -> None:
    contract = load_contract(REPO_ROOT)
    patterns = contract.path_groups["contract_control"]

    assert "scripts/sdlc/**" in patterns
    assert "newsroom/tests/test_sdlc_*.py" in patterns


def test_contract_validation_cli_emits_a_small_typed_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert validate_main(("--repo-root", str(REPO_ROOT))) == 0
    output = capsys.readouterr().out

    assert '"status":"PASS"' in output
    assert '"contract_version":"sdlc-v2.5"' in output
    assert "R4_RELEASE_OPERATIONAL" in output
