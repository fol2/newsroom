from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import newsroom.increment9.plan as plan_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9 import (
    INCREMENT_9_SHADOW_PLAN,
    INCREMENT_9_SHADOW_PLAN_DIGEST,
    SHADOW_PLAN_PATH,
    Increment9PlanError,
    OwnerApprovalRequired,
    load_increment9_shadow_plan,
    require_owner_approved_plan,
)


def _load_changed_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
) -> None:
    changed = canonical_json_bytes(document)
    path = tmp_path / "changed-plan.json"
    path.write_bytes(changed)
    monkeypatch.setattr(plan_module, "EXPECTED_SHADOW_PLAN_DIGEST", digest_bytes(changed))
    load_increment9_shadow_plan(path)


def test_plan_is_exact_canonical_content_addressed_base() -> None:
    plan = INCREMENT_9_SHADOW_PLAN
    assert plan.plan_digest == INCREMENT_9_SHADOW_PLAN_DIGEST
    assert plan.plan_digest == digest_bytes(SHADOW_PLAN_PATH.read_bytes())
    assert plan.issue_number == 488
    assert plan.parent_issue_number == 149
    assert plan.programme_issue_number == 141
    assert plan.planning_base == {
        "commit": "834250f8b0e7b5ce34e0cb54236d463429bd766e",
        "tree": "06b99d383f514db2fda95afe83f99c0e5b489ef5",
        "schema_version": 32,
        "schema_fingerprint": (
            "sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676"
        ),
        "migration_history_digest": (
            "sha256:5a48fd76cd11f266e19a4b48174d0c009f320a8d00d3eeb281a558fc2d561910"
        ),
        "increment8_exact_main_run": 31871581163,
        "increment8_operational_admission": "FIXTURE_OPERATIONAL_ADMITTED",
        "increment9_disposition": "ELIGIBLE_FOR_SEPARATE_PLAN",
    }


def test_repository_component_blobs_exist_at_exact_planning_base() -> None:
    base = str(INCREMENT_9_SHADOW_PLAN.planning_base["commit"])
    components = INCREMENT_9_SHADOW_PLAN.repository_baseline["component_blobs"]
    for component in components:
        observed = subprocess.check_output(
            ("/usr/bin/git", "rev-parse", f"{base}:{component['path']}"),
            text=True,
        ).strip()
        assert observed == component["git_blob"]


def test_unresolved_live_decisions_are_explicit_and_fail_closed() -> None:
    plan = INCREMENT_9_SHADOW_PLAN
    assert plan.owner_approved is False
    assert plan.unresolved_owner_decision_ids == tuple(
        f"OD-{number:03d}" for number in range(1, 15)
    )
    assert all(item.selection is None for item in plan.owner_decisions)
    assert all(item.evidence_refs == () for item in plan.owner_decisions)
    with pytest.raises(OwnerApprovalRequired, match="OD-001.*OD-014"):
        require_owner_approved_plan(plan)


def test_no_runtime_or_public_effect_is_authorised() -> None:
    plan = INCREMENT_9_SHADOW_PLAN
    assert plan.approval["contract_implementation_authorised"] is False
    assert plan.approval["live_shadow_authorised"] is False
    assert plan.approval["comparator_fault_execution_authorised"] is False
    assert plan.approval["evidence_intake_authorised"] is False
    assert plan.approval["publication_authorised"] is False
    assert plan.approval["canary_authorised"] is False
    assert plan.approval["production_activation_authorised"] is False
    assert plan.non_effect_authority["public_effect_authorised"] is False
    assert (
        plan.non_effect_authority["production_authority_mutation_authorised"]
        is False
    )
    assert set(plan.non_effect_authority["prohibited_until_exact_later_gate"]) >= {
        "LIVE_SOURCE_REQUEST",
        "PROVIDER_OR_MODEL_EXECUTION",
        "CREDENTIAL_USE",
        "EXTERNAL_EGRESS",
        "EXTERNAL_SPEND",
        "SHADOW_DEPLOYMENT",
        "DECISION_BEARING_SHADOW_RUN",
        "EVIDENCE_INTAKE",
        "PUBLICATION",
        "CANARY",
        "PRODUCTION_MUTATION",
    }


def test_dependency_graph_and_file_ownership_are_exact() -> None:
    plan = INCREMENT_9_SHADOW_PLAN
    assert tuple(item.issue_number for item in plan.allocations) == tuple(
        range(488, 499)
    )
    assert plan.waves == (
        (488,),
        (489, 491, 494, 496),
        (490, 492),
        (493,),
        (495,),
        (497,),
        (498,),
    )
    allocations = {item.issue_number: item for item in plan.allocations}
    assert allocations[493].dependencies == (488, 489, 490, 491, 492)
    assert allocations[495].dependencies == (490, 491, 492, 493, 494)
    assert allocations[497].dependencies == (493, 495, 496)
    assert allocations[498].dependencies == tuple(range(488, 498))
    paths = [path for item in plan.allocations for path in item.file_ownership]
    assert len(paths) == len(set(paths))


def test_prospective_stop_and_outcome_rules_are_frozen() -> None:
    plan = INCREMENT_9_SHADOW_PLAN
    assert plan.frozen_rules["prospective_only"] is True
    assert plan.frozen_rules["complete_denominators_required"] is True
    assert plan.frozen_rules["hindsight_selection_allowed"] is False
    assert plan.frozen_rules["post_result_threshold_change_allowed"] is False
    assert plan.frozen_rules["post_result_case_substitution_allowed"] is False
    assert plan.frozen_rules["material_change_closes_epoch"] is True
    assert plan.frozen_rules["unchanged_failed_run_retry_allowed"] is False
    assert all(
        value == 0
        for value in plan.frozen_rules["zero_tolerance_counts"].values()
    )
    assert plan.stop_and_recovery["later_phase_after_early_stop_allowed"] is False
    assert plan.outcome_vocabulary == (
        "FAILED",
        "INCONCLUSIVE",
        "CONTINUE_SHADOW",
        "COMPARATOR_ONLY",
        "BLOCKED_ACTIVE_COVERAGE",
        "SCOPED_OPERATIONAL_ELIGIBILITY",
    )
    assert plan.increment10_eligibility["automatic_transition_allowed"] is False


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("invent_approval", "unapproved owner decision was invented"),
        ("remove_decision", "owner decision inventory differs"),
        ("authorise_runtime", "live_shadow_authorised must remain false"),
        ("weaken_zero_tolerance", "zero-tolerance thresholds differ"),
        ("move_dependency", "allocation dependencies differ"),
        ("overlap_file", "file ownership overlaps"),
        ("automatic_increment10", "Increment 10 must not start automatically"),
    ),
)
def test_material_plan_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_error: str,
) -> None:
    document = json.loads(SHADOW_PLAN_PATH.read_bytes())
    payload = document["payload"]
    if mutation == "invent_approval":
        payload["owner_decisions"][0]["status"] = "APPROVED"
        payload["owner_decisions"][0]["selection"] = {"invented": True}
    elif mutation == "remove_decision":
        payload["owner_decisions"].pop()
    elif mutation == "authorise_runtime":
        payload["approval"]["live_shadow_authorised"] = True
    elif mutation == "weaken_zero_tolerance":
        payload["frozen_rules"]["zero_tolerance_counts"]["rights_breach"] = 1
    elif mutation == "move_dependency":
        payload["execution_graph"]["allocations"][1]["dependencies"] = [498]
    elif mutation == "overlap_file":
        payload["execution_graph"]["allocations"][1]["file_ownership"][0] = (
            payload["execution_graph"]["allocations"][0]["file_ownership"][0]
        )
    elif mutation == "automatic_increment10":
        payload["increment10_eligibility"]["automatic_transition_allowed"] = True
    with pytest.raises(Increment9PlanError, match=expected_error):
        _load_changed_document(tmp_path, monkeypatch, document)


def test_unknown_duplicate_noncanonical_and_raw_byte_tamper_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = json.loads(SHADOW_PLAN_PATH.read_bytes())
    document["payload"]["unknown"] = True
    with pytest.raises(Increment9PlanError, match="payload fields differ"):
        _load_changed_document(tmp_path, monkeypatch, document)

    nested = json.loads(SHADOW_PLAN_PATH.read_bytes())
    nested["payload"]["approval"]["unknown"] = True
    with pytest.raises(Increment9PlanError, match="approval fields differ"):
        _load_changed_document(tmp_path, monkeypatch, nested)

    nested = json.loads(SHADOW_PLAN_PATH.read_bytes())
    nested["payload"]["non_effect_authority"]["unknown"] = True
    with pytest.raises(
        Increment9PlanError, match="non_effect_authority fields differ"
    ):
        _load_changed_document(tmp_path, monkeypatch, nested)

    duplicate = SHADOW_PLAN_PATH.read_text().replace(
        '"schema_version":"newsroom.increment9.shadow-plan.v1"',
        '"schema_version":"newsroom.increment9.shadow-plan.v1",'
        '"schema_version":"newsroom.increment9.shadow-plan.v1"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicate)
    monkeypatch.setattr(
        plan_module,
        "EXPECTED_SHADOW_PLAN_DIGEST",
        digest_bytes(duplicate.encode()),
    )
    with pytest.raises(Increment9PlanError, match="duplicate object name"):
        load_increment9_shadow_plan(duplicate_path)

    noncanonical_path = tmp_path / "noncanonical.json"
    noncanonical_path.write_text(json.dumps(json.loads(SHADOW_PLAN_PATH.read_bytes())))
    monkeypatch.setattr(
        plan_module,
        "EXPECTED_SHADOW_PLAN_DIGEST",
        digest_bytes(noncanonical_path.read_bytes()),
    )
    with pytest.raises(Increment9PlanError, match="exact canonical JSON"):
        load_increment9_shadow_plan(noncanonical_path)

    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_bytes(SHADOW_PLAN_PATH.read_bytes().replace(b"OD-014", b"OD-999"))
    monkeypatch.setattr(
        plan_module,
        "EXPECTED_SHADOW_PLAN_DIGEST",
        INCREMENT_9_SHADOW_PLAN_DIGEST,
    )
    with pytest.raises(Increment9PlanError, match="bytes differ"):
        load_increment9_shadow_plan(tampered_path)


def test_plan_contains_no_secret_value_shapes() -> None:
    raw = SHADOW_PLAN_PATH.read_text().lower()
    prohibited = (
        "api_key=",
        "api-key=",
        "authorization: bearer",
        "-----begin private key-----",
        "ghp_",
        "sk-proj-",
    )
    assert all(token not in raw for token in prohibited)
