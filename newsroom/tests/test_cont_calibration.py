from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.control_plane.cont_calibration import (
    assess_cont_calibration,
    stage_cont_calibration_policy,
)
from newsroom.control_plane.model_usage import (
    InvocationEfficiencyPolicy,
    ModelUsageAdmissionError,
    ModelUsageIntegrityError,
    ModelUsageService,
    WorkloadClass,
)
from newsroom.control_plane.writer import (
    CONT_CONTEXT_MANIFEST_SCHEMA_VERSION,
    CONT_DISABLED_CAPABILITIES,
    CONT_PRIMARY_COMMAND_FLAGS,
    CONT_PRIMARY_CONFIG_IDENTITY,
    CONT_PRIMARY_MODEL,
    CONT_PRIMARY_PROVIDER,
    CONT_PRIMARY_REASONING,
    CONT_PRIMARY_ROUTE,
    GROK_COMMAND_SEMANTIC_VERSION,
)

REVISION = "a" * 40


def _leaf(
    candidate_id: str,
    *,
    prompt_bytes: int,
    context_tokens: int,
    accepted: bool = True,
    tool_count: int = 0,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "workload_class": "CONT_WRITER_PRIMARY",
        "provider": CONT_PRIMARY_PROVIDER,
        "route": CONT_PRIMARY_ROUTE,
        "model": CONT_PRIMARY_MODEL,
        "reasoning": CONT_PRIMARY_REASONING,
        "prompt_bytes": prompt_bytes,
        "context_tokens": context_tokens,
        "output_tokens": 400,
        "total_tokens": context_tokens + 400,
        "actual_provider_dispatch": True,
        "work_outcome": "ACCEPTED" if accepted else "REJECT",
        "invocation_outcome": "ACCEPTED_OUTPUT" if accepted else "REJECTED_OUTPUT",
        "context_manifest": {
            "schema_version": CONT_CONTEXT_MANIFEST_SCHEMA_VERSION,
            "command_semantic_version": GROK_COMMAND_SEMANTIC_VERSION,
            "command_flags": list(CONT_PRIMARY_COMMAND_FLAGS),
            "disabled_capabilities": list(CONT_DISABLED_CAPABILITIES),
            "implementation_revision": REVISION,
            "implementation_worktree_clean": True,
            "one_turn": True,
            "exact_input": True,
            "skills_enabled": False,
            "tools_enabled": False,
            "mcp_enabled": False,
            "prior_message_count": 0,
            "skill_count": 0,
            "tool_count": tool_count,
            "mcp_server_count": 0,
            "mcp_tool_count": 0,
        },
    }


def _passing_leaves() -> list[dict[str, object]]:
    return [
        _leaf("short", prompt_bytes=1_000, context_tokens=3_000),
        _leaf("medium", prompt_bytes=2_000, context_tokens=4_000),
        _leaf("long", prompt_bytes=3_000, context_tokens=5_000),
    ]


def test_productive_low_context_packet_mints_exact_primary_policy() -> None:
    packet = assess_cont_calibration(
        _passing_leaves(),
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1",
        implementation_revision=REVISION,
        unpublished_payload_candidate_ids=("short", "medium", "long"),
    )

    assert packet.passed is True
    assert packet.failure_reasons == ()
    assert packet.metrics["accepted_unpublished_payload_count"] == 3
    assert packet.metrics["p50_context_tokens"] == 4_000
    assert packet.metrics["maximum_context_tokens"] == 5_000
    policy = packet.mint_primary_policy()
    assert policy.qualified is True
    assert policy.provider == CONT_PRIMARY_PROVIDER
    assert policy.route == CONT_PRIMARY_ROUTE
    assert policy.model == CONT_PRIMARY_MODEL
    assert policy.reasoning == CONT_PRIMARY_REASONING
    assert policy.max_prompt_bytes == 3_000
    assert policy.max_context_tokens == 15_000
    assert policy.max_total_tokens >= policy.max_context_tokens + policy.max_output_tokens
    assert policy.allowed_config_identities == (CONT_PRIMARY_CONFIG_IDENTITY,)
    assert policy.implementation_revision == REVISION
    assert policy.command_flags == CONT_PRIMARY_COMMAND_FLAGS
    assert policy.evidence_digest == packet.calibration_evidence_digest


def test_low_context_without_three_accepted_payloads_does_not_pass() -> None:
    leaves = _passing_leaves()
    leaves[1] = _leaf(
        "medium", prompt_bytes=2_000, context_tokens=4_000, accepted=False
    )

    packet = assess_cont_calibration(
        leaves,
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1",
        implementation_revision=REVISION,
        unpublished_payload_candidate_ids=("short", "medium", "long"),
    )

    assert packet.passed is False
    assert "PRODUCTIVITY_BELOW_GATE" in packet.failure_reasons
    with pytest.raises(ModelUsageAdmissionError):
        packet.mint_primary_policy()


def test_accepted_prose_cannot_waive_context_or_manifest_gates() -> None:
    leaves = [
        _leaf("short", prompt_bytes=1_000, context_tokens=16_000),
        _leaf(
            "medium",
            prompt_bytes=2_000,
            context_tokens=16_000,
            tool_count=1,
        ),
        _leaf("long", prompt_bytes=3_000, context_tokens=16_000),
    ]

    packet = assess_cont_calibration(
        leaves,
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1",
        implementation_revision=REVISION,
        unpublished_payload_candidate_ids=("short", "medium", "long"),
    )

    assert packet.metrics["accepted_unpublished_payload_count"] == 3
    assert packet.passed is False
    assert "P50_CONTEXT_EXCEEDED" in packet.failure_reasons
    assert "MAXIMUM_CONTEXT_EXCEEDED" in packet.failure_reasons
    assert "AMBIENT_CAPABILITY_IN_MANIFEST" in packet.failure_reasons


def test_missing_usage_is_not_inferred_as_zero() -> None:
    leaves = _passing_leaves()
    leaves[1].pop("total_tokens")
    leaves[2].pop("output_tokens")

    packet = assess_cont_calibration(
        leaves,
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1",
        implementation_revision=REVISION,
        unpublished_payload_candidate_ids=("short", "medium", "long"),
    )

    assert packet.passed is False
    assert "TOTAL_TELEMETRY_MISSING" in packet.failure_reasons
    assert "OUTPUT_TELEMETRY_MISSING" in packet.failure_reasons
    assert packet.metrics["tokens_on_hold_reject_or_no_result"] is None
    assert packet.metrics["maximum_total_tokens"] is None
    assert packet.metrics["total_tokens_for_accepted_payloads"] is None
    assert packet.metrics["median_tokens_per_accepted_payload"] is None


def test_bootstrap_policy_is_exact_head_and_candidate_scoped() -> None:
    policy = stage_cont_calibration_policy(
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1+aaaaaaaaaaaa",
        implementation_revision=REVISION,
        max_prompt_bytes=8_000,
    )

    assert policy.qualified is True
    assert policy.calibration_only is True
    assert policy.allowed_candidate_ids == ("short", "medium", "long")
    assert policy.implementation_revision == REVISION
    assert policy.max_context_tokens == 15_000


def test_bootstrap_policy_resolves_only_for_bound_candidate_and_revision(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "usage.sqlite3"))
    policy = stage_cont_calibration_policy(
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1+aaaaaaaaaaaa",
        implementation_revision=REVISION,
        max_prompt_bytes=8_000,
    )
    service.register_policy(policy)

    selected = service.qualified_policy(
        workload_class=WorkloadClass.CONT_WRITER_PRIMARY,
        provider=CONT_PRIMARY_PROVIDER,
        route=CONT_PRIMARY_ROUTE,
        model=CONT_PRIMARY_MODEL,
        reasoning=CONT_PRIMARY_REASONING,
        candidate_id="short",
        implementation_revision=REVISION,
        config_identity=CONT_PRIMARY_CONFIG_IDENTITY,
    )
    assert selected.canonical_digest == policy.canonical_digest

    with pytest.raises(ModelUsageAdmissionError):
        service.qualified_policy(
            workload_class=WorkloadClass.CONT_WRITER_PRIMARY,
            provider=CONT_PRIMARY_PROVIDER,
            route=CONT_PRIMARY_ROUTE,
            model=CONT_PRIMARY_MODEL,
            reasoning=CONT_PRIMARY_REASONING,
            candidate_id="outside",
            implementation_revision=REVISION,
            config_identity=CONT_PRIMARY_CONFIG_IDENTITY,
        )


def test_new_head_bootstrap_supersedes_old_final_and_later_final_tightening(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "usage.sqlite3"))
    old_packet = assess_cont_calibration(
        _passing_leaves(),
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v1+aaaaaaaaaaaa",
        implementation_revision=REVISION,
        unpublished_payload_candidate_ids=("short", "medium", "long"),
    )
    old_final = old_packet.mint_primary_policy()
    service.register_policy(old_final)
    new_revision = "b" * 40
    bootstrap = stage_cont_calibration_policy(
        candidate_ids=("new-short", "new-medium", "new-long"),
        version="issue-730-v2+bbbbbbbbbbbb",
        implementation_revision=new_revision,
        max_prompt_bytes=8_000,
    )
    service.register_policy(bootstrap)

    selected_bootstrap = service.qualified_policy(
        workload_class=WorkloadClass.CONT_WRITER_PRIMARY,
        provider=CONT_PRIMARY_PROVIDER,
        route=CONT_PRIMARY_ROUTE,
        model=CONT_PRIMARY_MODEL,
        reasoning=CONT_PRIMARY_REASONING,
        candidate_id="new-short",
        implementation_revision=new_revision,
        config_identity=CONT_PRIMARY_CONFIG_IDENTITY,
    )
    assert selected_bootstrap.canonical_digest == bootstrap.canonical_digest

    newer_packet = assess_cont_calibration(
        [
            {
                **row,
                "context_manifest": {
                    **row["context_manifest"],  # type: ignore[dict-item]
                    "implementation_revision": new_revision,
                },
            }
            for row in _passing_leaves()
        ],
        candidate_ids=("short", "medium", "long"),
        version="issue-730-v2+bbbbbbbbbbbb",
        implementation_revision=new_revision,
        unpublished_payload_candidate_ids=("short", "medium", "long"),
    )
    newer_final = newer_packet.mint_primary_policy()
    service.register_policy(newer_final)
    tightened_values = newer_final.as_record()
    tightened_values.pop("schema_version")
    tightened_values["workload_class"] = WorkloadClass.CONT_WRITER_PRIMARY
    for field in (
        "command_flags",
        "disabled_capabilities",
        "allowed_candidate_ids",
        "allowed_context_identities",
        "allowed_config_identities",
    ):
        tightened_values[field] = tuple(tightened_values[field])  # type: ignore[arg-type]
    tightened_values.update(
        version="issue-730-v3+bbbbbbbbbbbb",
        max_prompt_bytes=newer_final.max_prompt_bytes - 1,
        evidence_digest="sha256:" + "c" * 64,
    )
    tightened = InvocationEfficiencyPolicy.create(**tightened_values)
    service.register_policy(tightened)
    selected_final = service.qualified_policy(
        workload_class=WorkloadClass.CONT_WRITER_PRIMARY,
        provider=CONT_PRIMARY_PROVIDER,
        route=CONT_PRIMARY_ROUTE,
        model=CONT_PRIMARY_MODEL,
        reasoning=CONT_PRIMARY_REASONING,
        candidate_id="short",
        implementation_revision=new_revision,
        config_identity=CONT_PRIMARY_CONFIG_IDENTITY,
    )
    assert selected_final.canonical_digest == tightened.canonical_digest


def test_hermetic_policy_cannot_omit_command_manifest_binding() -> None:
    with pytest.raises(ModelUsageIntegrityError):
        InvocationEfficiencyPolicy.create(
            policy_id="invalid-hermetic-policy",
            version="v1",
            workload_class=WorkloadClass.CONT_WRITER_PRIMARY,
            provider=CONT_PRIMARY_PROVIDER,
            route=CONT_PRIMARY_ROUTE,
            model=CONT_PRIMARY_MODEL,
            reasoning=CONT_PRIMARY_REASONING,
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            max_prompt_bytes=8_000,
            max_context_tokens=15_000,
            max_output_tokens=4_000,
            max_total_tokens=19_000,
            prompt_contract_version="prompt-v1",
            output_schema_digest="sha256:" + "d" * 64,
            allowed_context_identities=("context-v1",),
            allowed_config_identities=(CONT_PRIMARY_CONFIG_IDENTITY,),
            hard_estimate_ceiling_tokens=19_000,
            evidence_digest="sha256:" + "e" * 64,
            qualified=True,
        )
