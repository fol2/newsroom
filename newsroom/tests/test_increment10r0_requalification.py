from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

import newsroom.increment10.requalification as module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment10 import (
    EXPECTED_REQUALIFICATION_DIGEST,
    INCREMENT_10_REQUALIFICATION,
    INCREMENT_10_REQUALIFICATION_DIGEST,
    REQUALIFICATION_PATH,
    RequalificationError,
    RequalificationOutcome,
    load_requalification,
)
from newsroom.increment10.requalification import (
    EXPECTED_REQUIREMENTS,
    EXPECTED_RESIDUAL_GATES,
    EXPECTED_ZERO_TOLERANCE,
)


def _changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
):
    raw = canonical_json_bytes(document)
    path = tmp_path / "changed.json"
    path.write_bytes(raw)
    monkeypatch.setattr(module, "EXPECTED_REQUALIFICATION_DIGEST", digest_bytes(raw))
    return load_requalification(path)


def test_packet_is_exact_canonical_and_content_addressed() -> None:
    packet = INCREMENT_10_REQUALIFICATION
    assert REQUALIFICATION_PATH.read_bytes() == canonical_json_bytes(
        json.loads(REQUALIFICATION_PATH.read_bytes())
    )
    assert packet.packet_digest == EXPECTED_REQUALIFICATION_DIGEST
    assert packet.packet_digest == INCREMENT_10_REQUALIFICATION_DIGEST
    assert packet.packet_digest == digest_bytes(REQUALIFICATION_PATH.read_bytes())
    assert packet.issue_number == 526
    assert packet.parent_issue_number == 150


def test_exact_upstream_blocked_authority_is_preserved() -> None:
    upstream = INCREMENT_10_REQUALIFICATION.upstream
    assert upstream == {
        "closeout_digest": "sha256:a9eb84e3513b6a71c0d3301024c943aa75e8f112cec22c774ee4197bdd5e566b",
        "commit": "bd9ce46262a9286080e0dc5d648e33f94a9c6178",
        "exact_main_run": 31927978494,
        "increment10_eligible": False,
        "manifest_digest": "sha256:86760c07b31cbb75fb9c7a59ba39f3e5b5c502cff6a33e6f7d01ee0dc5260964",
        "retained_disposition": "BLOCKED_ACTIVE_COVERAGE",
        "tree": "1b3f69d305539432937ce5fdd8242bea83a1d659",
    }
    observed_tree = subprocess.check_output(
        ("/usr/bin/git", "rev-parse", f"{upstream['commit']}^{{tree}}"), text=True
    ).strip()
    assert observed_tree == upstream["tree"]


def test_all_twenty_residual_gates_are_truthful_classified_and_mapped() -> None:
    gates = INCREMENT_10_REQUALIFICATION.residual_gates
    assert tuple(item.gate_id for item in gates) == EXPECTED_RESIDUAL_GATES
    assert len(gates) == 20
    assert all(item.retained_status == "MISSING" for item in gates)
    assert all(item.downstream_owner.startswith("#") for item in gates)
    assert all(item.prospective_evidence_path for item in gates)
    assert {item.classification for item in gates} == {
        "BUDGET",
        "CREDENTIAL_EGRESS",
        "OPERATIONAL_ADMISSION",
        "OWNER_DECISION",
        "RIGHTS_LICENCE",
        "TECHNICAL_READINESS",
    }


def test_every_zero_tolerance_item_has_prospective_evidence_and_zero_threshold() -> (
    None
):
    paths = INCREMENT_10_REQUALIFICATION.zero_tolerance_paths
    assert tuple(item.finding_id for item in paths) == EXPECTED_ZERO_TOLERANCE
    assert all(item.retained_status == "NOT_EVALUATED" for item in paths)
    assert all(item.required_observed_count == 0 for item in paths)
    assert all(item.prospective_evidence_path for item in paths)


def test_minimum_evidence_intake_authority_is_explicit_and_fixture_scoped() -> None:
    requirements = INCREMENT_10_REQUALIFICATION.requirements
    assert tuple(item.requirement_id for item in requirements) == EXPECTED_REQUIREMENTS
    assert all(
        item.authority == "EXPLICIT_OWNER_AUTHORISED_FOR_LOCAL_FIXTURE_CANARY_ONLY"
        for item in requirements
    )
    assert requirements[-1].name == "DISCOVERY_NOT_EVIDENCE"
    assert all(item.text for item in requirements)


def test_narrow_scope_and_operational_admission_do_not_claim_external_coverage() -> (
    None
):
    packet = INCREMENT_10_REQUALIFICATION
    scope = packet.proposed_canary_scope
    assert scope["purpose"] == "NARROWER_LOCAL_QUALIFICATION_RUN"
    assert scope["destination"] == "local://increment10/evidence-intake-fixture-v1"
    assert scope["public_effect"] is False
    assert len(scope["candidate_version_ids"]) == 3
    assert set(scope["excluded"]) >= {
        "EXTERNAL_EVIDENCE_ACQUISITION",
        "LIVE_SOURCE_BYTES",
        "PROVIDER_OR_MODEL_EXECUTION",
        "PUBLICATION",
        "PRODUCTION_AUTHORITY",
    }
    assert packet.operational_admission["retained_verdict"] == (
        "FIXTURE_OPERATIONAL_ADMITTED"
    )
    assert packet.operational_admission["compatibility"] == (
        "COMPATIBLE_WITH_LOCAL_FIXTURE_CANARY_PLANNING_ONLY"
    )


def test_requalification_authorises_only_later_planning_after_signed_close() -> None:
    packet = INCREMENT_10_REQUALIFICATION
    assert packet.outcome is RequalificationOutcome.ELIGIBLE_FOR_INCREMENT10_PLAN
    assert packet.permits_increment10_plan is True
    assert packet.decision["runtime_authorised"] is False
    assert packet.approval["implementation_after_10r0_authorised"] is False
    assert packet.approval["live_effect_authorised"] is False
    assert packet.outcome_vocabulary == (
        "REMAIN_BLOCKED",
        "RETURN_TO_BOUNDED_SHADOW",
        "ELIGIBLE_FOR_INCREMENT10_PLAN",
    )


def test_closed_world_budgets_credentials_egress_and_non_effects_are_exact() -> None:
    packet = INCREMENT_10_REQUALIFICATION
    budget = packet.prerequisite_bindings["budget"]
    assert budget["external_requests"] == 0
    assert budget["gross_gbp_minor_units"] == 0
    assert budget["model_tokens"] == 0
    assert budget["non_loopback_bytes"] == 0
    assert budget["provider_requests"] == 0
    assert budget["reviewer_minutes"] == 0
    assert packet.prerequisite_bindings["credentials"] == {
        "allowed_classes": (),
        "secret_locations": (),
    }
    assert packet.prerequisite_bindings["egress"] == {
        "allowed_hosts": (),
        "loopback_only": True,
        "redirects": 0,
    }
    assert all(value in (False, 0) for value in packet.non_effects.values())


def test_loaded_nested_authority_is_immutable() -> None:
    packet = INCREMENT_10_REQUALIFICATION
    assert isinstance(packet.upstream, Mapping)
    with pytest.raises(TypeError):
        packet.upstream["commit"] = "0" * 40  # type: ignore[index]
    with pytest.raises(TypeError):
        packet.prerequisite_bindings["budget"]["external_requests"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("upstream_eligible", "upstream reviewed bytes differ"),
        ("upstream_digests", "upstream reviewed bytes differ"),
        ("drop_gate", "residual_gate_inventory reviewed bytes differ"),
        ("pass_gate", "residual_gate_inventory reviewed bytes differ"),
        ("gate_owner", "residual_gate_inventory reviewed bytes differ"),
        ("gate_classification", "residual_gate_inventory reviewed bytes differ"),
        ("drop_zero", "zero_tolerance_remediation reviewed bytes differ"),
        ("weaken_zero", "zero_tolerance_remediation reviewed bytes differ"),
        ("live_rights", "proposed_canary_scope reviewed bytes differ"),
        ("decision_scope", "proposed_canary_scope reviewed bytes differ"),
        ("intake_version", "proposed_canary_scope reviewed bytes differ"),
        ("authorise_runtime", "decision reviewed bytes differ"),
        ("authorise_effect", "non_effects reviewed bytes differ"),
        ("allow_egress", "prerequisite_bindings reviewed bytes differ"),
        ("spend", "prerequisite_bindings reviewed bytes differ"),
        ("live_reviewer", "prerequisite_bindings reviewed bytes differ"),
        ("live_fixture_rights", "prerequisite_bindings reviewed bytes differ"),
        ("weaken_containment", "prerequisite_bindings reviewed bytes differ"),
        ("weaken_retention", "prerequisite_bindings reviewed bytes differ"),
        (
            "weaken_requirement",
            "evidence_intake_requirements reviewed bytes differ",
        ),
        (
            "rewrite_requirement",
            "evidence_intake_requirements reviewed bytes differ",
        ),
        ("change_admission", "operational_admission reviewed bytes differ"),
    ),
)
def test_material_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    document = json.loads(REQUALIFICATION_PATH.read_bytes())
    payload = document["payload"]
    if mutation == "upstream_eligible":
        payload["upstream"]["increment10_eligible"] = True
    elif mutation == "upstream_digests":
        payload["upstream"]["closeout_digest"] = "sha256:" + "0" * 64
        payload["upstream"]["manifest_digest"] = "sha256:" + "1" * 64
    elif mutation == "drop_gate":
        payload["residual_gate_inventory"].pop()
    elif mutation == "pass_gate":
        payload["residual_gate_inventory"][0]["retained_status"] = "PASS"
    elif mutation == "gate_owner":
        payload["residual_gate_inventory"][0]["downstream_owner"] = ""
    elif mutation == "gate_classification":
        payload["residual_gate_inventory"][0]["classification"] = "BUDGET"
    elif mutation == "drop_zero":
        payload["zero_tolerance_remediation"].pop()
    elif mutation == "weaken_zero":
        payload["zero_tolerance_remediation"][0]["required_observed_count"] = 1
    elif mutation == "live_rights":
        payload["proposed_canary_scope"]["excluded"].remove("LIVE_SOURCE_BYTES")
    elif mutation == "decision_scope":
        payload["proposed_canary_scope"]["decision_bearing_for"] = ["PUBLICATION"]
    elif mutation == "intake_version":
        payload["proposed_canary_scope"]["intake_version"] = "unreviewed-v2"
    elif mutation == "authorise_runtime":
        payload["decision"]["runtime_authorised"] = True
    elif mutation == "authorise_effect":
        payload["non_effects"]["evidence_intake"] = True
    elif mutation == "allow_egress":
        payload["prerequisite_bindings"]["egress"]["allowed_hosts"] = ["example.test"]
    elif mutation == "spend":
        payload["prerequisite_bindings"]["budget"]["gross_gbp_minor_units"] = 1
    elif mutation == "live_reviewer":
        payload["prerequisite_bindings"]["reviewers"]["live_reviewer_access"] = True
    elif mutation == "live_fixture_rights":
        payload["prerequisite_bindings"]["rights"]["live_source_bytes_allowed"] = True
    elif mutation == "weaken_containment":
        payload["prerequisite_bindings"]["containment"][
            "teardown_residual_count_max"
        ] = 1
    elif mutation == "weaken_retention":
        payload["prerequisite_bindings"]["retention"]["purge_hours_max"] = 2
    elif mutation == "weaken_requirement":
        payload["evidence_intake_requirements"][0]["authority"] = "DRAFT"
    elif mutation == "rewrite_requirement":
        payload["evidence_intake_requirements"][7]["name"] = "ALLOW_EXTERNAL_EFFECT"
        payload["evidence_intake_requirements"][7]["text"] = (
            "External effects are allowed."
        )
    elif mutation == "change_admission":
        payload["operational_admission"]["retained_verdict"] = "NOT_ADMITTED"
    with pytest.raises(RequalificationError, match=message):
        _changed(tmp_path, monkeypatch, document)


def test_unknown_duplicate_noncanonical_and_raw_byte_changes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = json.loads(REQUALIFICATION_PATH.read_bytes())
    document["payload"]["unknown"] = True
    with pytest.raises(RequalificationError, match="payload fields differ"):
        _changed(tmp_path, monkeypatch, document)

    duplicate = REQUALIFICATION_PATH.read_text().replace(
        '"issue_number":526', '"issue_number":526,"issue_number":526', 1
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicate)
    monkeypatch.setattr(
        module, "EXPECTED_REQUALIFICATION_DIGEST", digest_bytes(duplicate.encode())
    )
    with pytest.raises(RequalificationError, match="duplicated"):
        load_requalification(duplicate_path)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(json.loads(REQUALIFICATION_PATH.read_bytes())))
    monkeypatch.setattr(
        module,
        "EXPECTED_REQUALIFICATION_DIGEST",
        digest_bytes(noncanonical.read_bytes()),
    )
    with pytest.raises(RequalificationError, match="exact canonical JSON"):
        load_requalification(noncanonical)

    changed = tmp_path / "changed.json"
    changed.write_bytes(
        REQUALIFICATION_PATH.read_bytes().replace(b"EINT-FX-010", b"EINT-FX-999")
    )
    monkeypatch.setattr(
        module, "EXPECTED_REQUALIFICATION_DIGEST", EXPECTED_REQUALIFICATION_DIGEST
    )
    with pytest.raises(RequalificationError, match="bytes differ"):
        load_requalification(changed)


@pytest.mark.parametrize("unsafe_value", (1.5, 9_007_199_254_740_992))
def test_values_outside_the_canonical_domain_fail_with_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_value: object,
) -> None:
    path = tmp_path / "unsafe.json"
    path.write_text(
        json.dumps(
            {
                "payload": unsafe_value,
                "schema_version": "newsroom.increment10.requalification.v1",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    monkeypatch.setattr(
        module, "EXPECTED_REQUALIFICATION_DIGEST", digest_bytes(path.read_bytes())
    )
    with pytest.raises(RequalificationError, match="outside the canonical domain"):
        load_requalification(path)


def test_deeply_nested_json_normalises_recursion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "deep.json"
    path.write_bytes(b"[" * 2_000 + b"0" + b"]" * 2_000)
    monkeypatch.setattr(
        module, "EXPECTED_REQUALIFICATION_DIGEST", digest_bytes(path.read_bytes())
    )
    with pytest.raises(RequalificationError):
        load_requalification(path)
