from __future__ import annotations

from newsroom.control_plane.cont_calibration import assess_cont_calibration
from newsroom.control_plane.model_usage import ModelUsageAdmissionError
from newsroom.control_plane.writer import (
    CONT_PRIMARY_CONFIG_IDENTITY,
    CONT_PRIMARY_MODEL,
    CONT_PRIMARY_PROVIDER,
    CONT_PRIMARY_REASONING,
    CONT_PRIMARY_ROUTE,
)


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
    assert policy.allowed_config_identities == (CONT_PRIMARY_CONFIG_IDENTITY,)
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
    )

    assert packet.passed is False
    assert "PRODUCTIVITY_BELOW_GATE" in packet.failure_reasons
    try:
        packet.mint_primary_policy()
    except ModelUsageAdmissionError:
        pass
    else:
        raise AssertionError("failed calibration minted a policy")


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
    )

    assert packet.metrics["accepted_unpublished_payload_count"] == 3
    assert packet.passed is False
    assert "P50_CONTEXT_EXCEEDED" in packet.failure_reasons
    assert "MAXIMUM_CONTEXT_EXCEEDED" in packet.failure_reasons
    assert "AMBIENT_CAPABILITY_IN_MANIFEST" in packet.failure_reasons
