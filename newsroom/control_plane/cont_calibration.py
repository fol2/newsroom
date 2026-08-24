"""Productive hermetic CONT route calibration and policy minting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from statistics import median

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.model_usage import (
    InvocationEfficiencyPolicy,
    ModelUsageAdmissionError,
    WorkloadClass,
)
from newsroom.control_plane.writer import (
    CONT_PRIMARY_CONFIG_IDENTITY,
    CONT_PRIMARY_MODEL,
    CONT_PRIMARY_PROVIDER,
    CONT_PRIMARY_REASONING,
    CONT_PRIMARY_ROUTE,
    CONT_WRITER_CONTEXT_IDENTITY,
    CONT_WRITER_OUTPUT_SCHEMA_DIGEST,
    CONT_WRITER_PROMPT_CONTRACT_VERSION,
)

CONT_INCIDENT_CONTEXT_BASELINE = 37_479
CONT_CALIBRATION_MAX_CANDIDATES = 5
CONT_CALIBRATION_MIN_ACCEPTED = 3
CONT_CALIBRATION_P50_CONTEXT_MAX = 10_000
CONT_CALIBRATION_MAX_CONTEXT = 15_000
CONT_CALIBRATION_MIN_REDUCTION_PERCENT = 70
CONT_POLICY_HEADROOM_FRACTION = 0.20
CONT_POLICY_MIN_HEADROOM_TOKENS = 1_000


def _integer(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ratio(numerator: int, denominator: int) -> dict[str, int] | None:
    return (
        None
        if denominator <= 0
        else {"numerator": numerator, "denominator": denominator}
    )


def _median_int(values: Sequence[int]) -> int | None:
    return None if not values else ceil(median(values))


@dataclass(frozen=True, slots=True)
class ContCalibrationPacket:
    version: str
    candidate_ids: tuple[str, ...]
    accepted_candidate_ids: tuple[str, ...]
    passed: bool
    failure_reasons: tuple[str, ...]
    metrics: dict[str, object]
    calibration_evidence_digest: str

    def as_record(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.cont-hermetic-calibration.v1",
            "version": self.version,
            "candidate_ids": list(self.candidate_ids),
            "accepted_candidate_ids": list(self.accepted_candidate_ids),
            "passed": self.passed,
            "failure_reasons": list(self.failure_reasons),
            "metrics": self.metrics,
            "calibration_evidence_digest": self.calibration_evidence_digest,
            "public_effects": 0,
        }

    def mint_primary_policy(self) -> InvocationEfficiencyPolicy:
        if not self.passed:
            raise ModelUsageAdmissionError(
                "failed calibration cannot mint an invocation policy"
            )
        maximum_prompt_bytes = int(self.metrics["maximum_prompt_bytes"])
        maximum_output_tokens = int(self.metrics["maximum_output_tokens"])
        maximum_total_tokens = int(self.metrics["maximum_total_tokens"])
        output_headroom = max(
            CONT_POLICY_MIN_HEADROOM_TOKENS,
            ceil(maximum_output_tokens * CONT_POLICY_HEADROOM_FRACTION),
        )
        total_headroom = max(
            CONT_POLICY_MIN_HEADROOM_TOKENS,
            ceil(maximum_total_tokens * CONT_POLICY_HEADROOM_FRACTION),
        )
        policy_output = maximum_output_tokens + output_headroom
        policy_total = max(maximum_total_tokens + total_headroom, policy_output)
        return InvocationEfficiencyPolicy.create(
            policy_id="cont-hermetic-grok-primary",
            version=self.version,
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
            max_prompt_bytes=maximum_prompt_bytes,
            max_context_tokens=CONT_CALIBRATION_MAX_CONTEXT,
            max_output_tokens=policy_output,
            max_total_tokens=policy_total,
            prompt_contract_version=CONT_WRITER_PROMPT_CONTRACT_VERSION,
            output_schema_digest=CONT_WRITER_OUTPUT_SCHEMA_DIGEST,
            allowed_context_identities=(CONT_WRITER_CONTEXT_IDENTITY,),
            allowed_config_identities=(CONT_PRIMARY_CONFIG_IDENTITY,),
            hard_estimate_ceiling_tokens=policy_total,
            evidence_digest=self.calibration_evidence_digest,
            qualified=True,
        )


def assess_cont_calibration(
    leaves: Sequence[Mapping[str, object]],
    *,
    candidate_ids: Sequence[str],
    version: str,
    public_effect_count: int = 0,
) -> ContCalibrationPacket:
    """Assess an exact-head, unpublished calibration without rerunning a baseline."""

    candidates = tuple(candidate_ids)
    selected = [row for row in leaves if row.get("candidate_id") in candidates]
    by_candidate: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in selected:
        by_candidate[str(row["candidate_id"])].append(row)

    accepted: list[str] = []
    accepted_token_totals: list[int] = []
    primary_accepts = 0
    fallback_attempts = 0
    fallback_recoveries = 0
    primary_rows: list[Mapping[str, object]] = []
    actual_rows: list[Mapping[str, object]] = []
    for candidate_id in candidates:
        rows = by_candidate.get(candidate_id, [])
        primaries = [
            row
            for row in rows
            if row.get("workload_class") == WorkloadClass.CONT_WRITER_PRIMARY.value
        ]
        fallbacks = [
            row
            for row in rows
            if row.get("workload_class") == WorkloadClass.CONT_WRITER_FALLBACK.value
        ]
        primary_rows.extend(primaries)
        fallback_attempts += len(fallbacks)
        dispatched = [row for row in rows if row.get("actual_provider_dispatch") is True]
        actual_rows.extend(dispatched)
        accepted_rows = [
            row
            for row in rows
            if row.get("work_outcome") == "ACCEPTED"
            and row.get("invocation_outcome") == "ACCEPTED_OUTPUT"
        ]
        if accepted_rows:
            accepted.append(candidate_id)
            accepted_token_totals.append(
                sum(
                    value
                    for row in rows
                    if (value := _integer(row, "total_tokens")) is not None
                )
            )
            if any(
                row.get("workload_class")
                == WorkloadClass.CONT_WRITER_PRIMARY.value
                for row in accepted_rows
            ):
                primary_accepts += 1
            elif fallbacks:
                fallback_recoveries += 1

    contexts = [
        value
        for row in actual_rows
        if (value := _integer(row, "context_tokens")) is not None
    ]
    prompt_sizes = [
        value
        for row in primary_rows
        if (value := _integer(row, "prompt_bytes")) is not None
    ]
    output_tokens = [
        value
        for row in actual_rows
        if (value := _integer(row, "output_tokens")) is not None
    ]
    total_tokens = [
        value
        for row in actual_rows
        if (value := _integer(row, "total_tokens")) is not None
    ]
    no_result_tokens = sum(total_tokens) - sum(accepted_token_totals)
    p50_context = _median_int(contexts)
    reduction = (
        None
        if p50_context is None
        else {
            "numerator": CONT_INCIDENT_CONTEXT_BASELINE - p50_context,
            "denominator": CONT_INCIDENT_CONTEXT_BASELINE,
        }
    )

    manifest_controls_pass = all(
        isinstance(row.get("context_manifest"), dict)
        and all(
            row["context_manifest"].get(field) == 0  # type: ignore[union-attr]
            for field in (
                "prior_message_count",
                "skill_count",
                "tool_count",
                "mcp_server_count",
                "mcp_tool_count",
            )
        )
        for row in actual_rows
    )
    exact_route_pins = all(
        row.get("provider") == CONT_PRIMARY_PROVIDER
        and row.get("route") == CONT_PRIMARY_ROUTE
        and row.get("model") == CONT_PRIMARY_MODEL
        and row.get("reasoning") == CONT_PRIMARY_REASONING
        for row in primary_rows
    )
    primary_once = all(
        len(
            [
                row
                for row in by_candidate.get(candidate_id, [])
                if row.get("workload_class")
                == WorkloadClass.CONT_WRITER_PRIMARY.value
            ]
        )
        == 1
        for candidate_id in candidates
    )

    failures: list[str] = []
    checks = (
        (0 < len(candidates) <= CONT_CALIBRATION_MAX_CANDIDATES, "CANDIDATE_BOUND"),
        (len(set(candidates)) == len(candidates), "CANDIDATE_ID_DUPLICATE"),
        (set(by_candidate) == set(candidates), "CALIBRATION_CANDIDATE_MISSING"),
        (len(set(prompt_sizes)) >= 3, "EVIDENCE_SIZE_RANGE_MISSING"),
        (len(accepted) >= CONT_CALIBRATION_MIN_ACCEPTED, "PRODUCTIVITY_BELOW_GATE"),
        (len(contexts) == len(actual_rows), "CONTEXT_TELEMETRY_MISSING"),
        (
            p50_context is not None
            and p50_context <= CONT_CALIBRATION_P50_CONTEXT_MAX,
            "P50_CONTEXT_EXCEEDED",
        ),
        (
            p50_context is not None
            and (CONT_INCIDENT_CONTEXT_BASELINE - p50_context) * 100
            >= CONT_INCIDENT_CONTEXT_BASELINE
            * CONT_CALIBRATION_MIN_REDUCTION_PERCENT,
            "CONTEXT_REDUCTION_BELOW_GATE",
        ),
        (
            bool(contexts) and max(contexts) <= CONT_CALIBRATION_MAX_CONTEXT,
            "MAXIMUM_CONTEXT_EXCEEDED",
        ),
        (primary_once, "PRIMARY_CALL_COUNT_NOT_ONE"),
        (manifest_controls_pass, "AMBIENT_CAPABILITY_IN_MANIFEST"),
        (exact_route_pins, "ROUTE_PIN_DRIFT"),
        (public_effect_count == 0, "PUBLIC_EFFECT_DETECTED"),
        (bool(output_tokens), "OUTPUT_TELEMETRY_MISSING"),
        (bool(total_tokens), "TOTAL_TELEMETRY_MISSING"),
    )
    failures.extend(reason for passed, reason in checks if not passed)
    metrics: dict[str, object] = {
        "admitted_candidate_count": len(candidates),
        "accepted_unpublished_payload_count": len(accepted),
        "p50_context_tokens": p50_context,
        "context_reduction_from_incident_baseline": reduction,
        "maximum_context_tokens": max(contexts) if contexts else None,
        "maximum_prompt_bytes": max(prompt_sizes) if prompt_sizes else 0,
        "maximum_output_tokens": max(output_tokens) if output_tokens else 0,
        "maximum_total_tokens": max(total_tokens) if total_tokens else 0,
        "total_tokens_per_accepted_payload": accepted_token_totals,
        "median_tokens_per_accepted_payload": _median_int(accepted_token_totals),
        "tokens_on_hold_reject_or_no_result": max(no_result_tokens, 0),
        "primary_acceptance_rate": _ratio(primary_accepts, len(primary_rows)),
        "fallback_recovery_rate": _ratio(fallback_recoveries, fallback_attempts),
        "fallback_no_result_rate": _ratio(
            fallback_attempts - fallback_recoveries, fallback_attempts
        ),
        "context_to_newsroom_input_ratio": _ratio(
            sum(contexts), sum(prompt_sizes)
        ),
        "context_to_newsroom_input_ratio_units": "context_tokens_per_prompt_byte",
        "primary_model_calls_per_attempt": 1 if primary_once else None,
        "public_effect_count": public_effect_count,
    }
    evidence = {
        "schema_version": "newsroom.cont-hermetic-calibration.v1",
        "version": version,
        "candidate_ids": list(candidates),
        "accepted_candidate_ids": accepted,
        "passed": not failures,
        "failure_reasons": failures,
        "metrics": metrics,
    }
    return ContCalibrationPacket(
        version=version,
        candidate_ids=candidates,
        accepted_candidate_ids=tuple(accepted),
        passed=not failures,
        failure_reasons=tuple(failures),
        metrics=metrics,
        calibration_evidence_digest=digest_canonical(evidence),
    )


__all__ = [
    "ContCalibrationPacket",
    "assess_cont_calibration",
]
