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
    CONT_CONTEXT_MANIFEST_SCHEMA_VERSION,
    CONT_DISABLED_CAPABILITIES,
    CONT_FALLBACK_COMMAND_FLAGS,
    CONT_FALLBACK_CONFIG_IDENTITY,
    CONT_FALLBACK_MODEL,
    CONT_FALLBACK_PROVIDER,
    CONT_FALLBACK_REASONING,
    CONT_FALLBACK_ROUTE,
    CONT_PRIMARY_COMMAND_FLAGS,
    CONT_PRIMARY_CONFIG_IDENTITY,
    CONT_PRIMARY_MODEL,
    CONT_PRIMARY_PROVIDER,
    CONT_PRIMARY_REASONING,
    CONT_PRIMARY_ROUTE,
    CONT_WRITER_CONTEXT_IDENTITY,
    CONT_WRITER_OUTPUT_SCHEMA_DIGEST,
    CONT_WRITER_PROMPT_CONTRACT_VERSION,
    CURSOR_COMMAND_SEMANTIC_VERSION,
    GROK_COMMAND_SEMANTIC_VERSION,
)

CONT_INCIDENT_CONTEXT_BASELINE = 37_479
CONT_CALIBRATION_MAX_CANDIDATES = 5
CONT_CALIBRATION_MIN_ACCEPTED = 3
CONT_CALIBRATION_P50_CONTEXT_MAX = 10_000
CONT_CALIBRATION_MAX_CONTEXT = 15_000
CONT_CALIBRATION_MIN_REDUCTION_PERCENT = 70
CONT_POLICY_HEADROOM_FRACTION = 0.20
CONT_POLICY_MIN_HEADROOM_TOKENS = 1_000
CONT_CALIBRATION_BOOTSTRAP_MAX_OUTPUT_TOKENS = 4_096


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
    implementation_revision: str
    candidate_ids: tuple[str, ...]
    accepted_candidate_ids: tuple[str, ...]
    passed: bool
    failure_reasons: tuple[str, ...]
    metrics: dict[str, object]
    calibration_evidence_digest: str

    def _evidence_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.cont-hermetic-calibration.v1",
            "version": self.version,
            "implementation_revision": self.implementation_revision,
            "candidate_ids": list(self.candidate_ids),
            "accepted_candidate_ids": list(self.accepted_candidate_ids),
            "passed": self.passed,
            "failure_reasons": list(self.failure_reasons),
            "metrics": self.metrics,
        }

    def as_record(self) -> dict[str, object]:
        return {
            **self._evidence_value(),
            "calibration_evidence_digest": self.calibration_evidence_digest,
            "public_effects": self.metrics.get("public_effect_count"),
        }

    def mint_primary_policy(self) -> InvocationEfficiencyPolicy:
        if not self.passed:
            raise ModelUsageAdmissionError(
                "failed calibration cannot mint an invocation policy"
            )
        if digest_canonical(self._evidence_value()) != self.calibration_evidence_digest:
            raise ModelUsageAdmissionError("calibration packet digest is invalid")
        maximum_prompt_bytes = _integer(self.metrics, "maximum_prompt_bytes")
        maximum_output_tokens = _integer(self.metrics, "maximum_output_tokens")
        maximum_total_tokens = _integer(self.metrics, "maximum_total_tokens")
        if (
            maximum_prompt_bytes is None
            or maximum_output_tokens is None
            or maximum_total_tokens is None
        ):
            raise ModelUsageAdmissionError(
                "calibration packet token metrics are invalid"
            )
        output_headroom = max(
            CONT_POLICY_MIN_HEADROOM_TOKENS,
            ceil(maximum_output_tokens * CONT_POLICY_HEADROOM_FRACTION),
        )
        total_headroom = max(
            CONT_POLICY_MIN_HEADROOM_TOKENS,
            ceil(maximum_total_tokens * CONT_POLICY_HEADROOM_FRACTION),
        )
        policy_output = maximum_output_tokens + output_headroom
        policy_total = max(
            maximum_total_tokens + total_headroom,
            CONT_CALIBRATION_MAX_CONTEXT + policy_output,
        )
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
            command_semantic_version=GROK_COMMAND_SEMANTIC_VERSION,
            command_flags=CONT_PRIMARY_COMMAND_FLAGS,
            context_manifest_schema_version=CONT_CONTEXT_MANIFEST_SCHEMA_VERSION,
            disabled_capabilities=CONT_DISABLED_CAPABILITIES,
            implementation_revision=self.implementation_revision,
            calibration_only=False,
            allowed_candidate_ids=(),
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
    implementation_revision: str,
    public_effect_count: int = 0,
    unpublished_payload_candidate_ids: Sequence[str] = (),
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
    dispatched_rows: list[Mapping[str, object]] = []
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
        dispatched = [row for row in rows if row.get("actual_provider_dispatch") is True]
        dispatched_fallbacks = [
            row for row in fallbacks if row.get("actual_provider_dispatch") is True
        ]
        fallback_attempts += len(dispatched_fallbacks)
        primary_rows.extend(
            row for row in primaries if row.get("actual_provider_dispatch") is True
        )
        dispatched_rows.extend(dispatched)
        accepted_rows = [
            row
            for row in dispatched
            if row.get("work_outcome") == "ACCEPTED"
            and row.get("invocation_outcome") == "ACCEPTED_OUTPUT"
        ]
        candidate_totals = [
            value
            for row in dispatched
            if (value := _integer(row, "total_tokens")) is not None
        ]
        if accepted_rows:
            accepted.append(candidate_id)
            if len(candidate_totals) == len(dispatched):
                accepted_token_totals.append(sum(candidate_totals))
            if any(
                row.get("workload_class")
                == WorkloadClass.CONT_WRITER_PRIMARY.value
                for row in accepted_rows
            ):
                primary_accepts += 1
            elif dispatched_fallbacks:
                fallback_recoveries += 1

    contexts = [
        value
        for row in dispatched_rows
        if (value := _integer(row, "context_tokens")) is not None
    ]
    prompt_sizes = [
        value
        for row in primary_rows
        if (value := _integer(row, "prompt_bytes")) is not None
    ]
    evidence_package_sizes = [
        value
        for row in primary_rows
        if isinstance(row.get("context_manifest"), dict)
        and (
            value := _integer(
                row["context_manifest"],  # type: ignore[arg-type]
                "evidence_package_bytes",
            )
        )
        is not None
    ]
    output_tokens = [
        value
        for row in dispatched_rows
        if (value := _integer(row, "output_tokens")) is not None
    ]
    total_tokens = [
        value
        for row in dispatched_rows
        if (value := _integer(row, "total_tokens")) is not None
    ]
    primary_output_tokens = [
        value
        for row in primary_rows
        if (value := _integer(row, "output_tokens")) is not None
    ]
    primary_total_tokens = [
        value
        for row in primary_rows
        if (value := _integer(row, "total_tokens")) is not None
    ]
    complete_total_telemetry = len(total_tokens) == len(dispatched_rows)
    complete_output_telemetry = len(output_tokens) == len(dispatched_rows)
    reported_usage = all(
        row.get("usage_status") == "REPORTED" for row in dispatched_rows
    )
    policy_clean = all(row.get("policy_breach") is None for row in dispatched_rows)
    no_result_tokens = (
        sum(
            _integer(row, "total_tokens") or 0
            for row in dispatched_rows
            if row.get("invocation_outcome") != "ACCEPTED_OUTPUT"
            or row.get("work_outcome") != "ACCEPTED"
        )
        if complete_total_telemetry
        else None
    )
    p50_context = _median_int(contexts)
    reduction = (
        None
        if p50_context is None
        else {
            "numerator": CONT_INCIDENT_CONTEXT_BASELINE - p50_context,
            "denominator": CONT_INCIDENT_CONTEXT_BASELINE,
        }
    )

    def manifest_controls_match(row: Mapping[str, object]) -> bool:
        workload = row.get("workload_class")
        if workload == WorkloadClass.CONT_WRITER_PRIMARY.value:
            command_version = GROK_COMMAND_SEMANTIC_VERSION
            command_flags = CONT_PRIMARY_COMMAND_FLAGS
            config_identity = CONT_PRIMARY_CONFIG_IDENTITY
        elif workload == WorkloadClass.CONT_WRITER_FALLBACK.value:
            command_version = CURSOR_COMMAND_SEMANTIC_VERSION
            command_flags = CONT_FALLBACK_COMMAND_FLAGS
            config_identity = CONT_FALLBACK_CONFIG_IDENTITY
        else:
            return False
        manifest = row.get("context_manifest")
        return (
            isinstance(manifest, dict)
            and all(
                manifest.get(field) == 0
                for field in (
                    "prior_message_count",
                    "skill_count",
                    "tool_count",
                    "mcp_server_count",
                    "mcp_tool_count",
                )
            )
            and manifest.get("one_turn") is True
            and manifest.get("exact_input") is True
            and manifest.get("skills_enabled") is False
            and manifest.get("tools_enabled") is False
            and manifest.get("mcp_enabled") is False
            and manifest.get("implementation_revision") == implementation_revision
            and manifest.get("implementation_worktree_clean") is True
            and manifest.get("schema_version")
            == CONT_CONTEXT_MANIFEST_SCHEMA_VERSION
            and manifest.get("command_semantic_version") == command_version
            and tuple(manifest.get("command_flags", ())) == command_flags
            and manifest.get("config_identity") == config_identity
            and tuple(manifest.get("disabled_capabilities", ()))
            == CONT_DISABLED_CAPABILITIES
        )

    manifest_controls_pass = all(
        manifest_controls_match(row) for row in dispatched_rows
    )

    def route_pins_match(row: Mapping[str, object]) -> bool:
        if row.get("workload_class") == WorkloadClass.CONT_WRITER_PRIMARY.value:
            expected = (
                CONT_PRIMARY_PROVIDER,
                CONT_PRIMARY_ROUTE,
                CONT_PRIMARY_MODEL,
                CONT_PRIMARY_REASONING,
            )
        elif row.get("workload_class") == WorkloadClass.CONT_WRITER_FALLBACK.value:
            expected = (
                CONT_FALLBACK_PROVIDER,
                CONT_FALLBACK_ROUTE,
                CONT_FALLBACK_MODEL,
                CONT_FALLBACK_REASONING,
            )
        else:
            return False
        return (
            row.get("provider"),
            row.get("route"),
            row.get("model"),
            row.get("reasoning"),
        ) == expected

    exact_route_pins = all(route_pins_match(row) for row in dispatched_rows)
    primary_once = all(
        len(
            [
                row
                for row in by_candidate.get(candidate_id, [])
                if row.get("workload_class")
                == WorkloadClass.CONT_WRITER_PRIMARY.value
                and row.get("actual_provider_dispatch") is True
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
        (
            len(evidence_package_sizes) == len(primary_rows)
            and len(set(evidence_package_sizes)) >= 3,
            "EVIDENCE_SIZE_RANGE_MISSING",
        ),
        (len(accepted) >= CONT_CALIBRATION_MIN_ACCEPTED, "PRODUCTIVITY_BELOW_GATE"),
        (
            set(accepted).issubset(set(unpublished_payload_candidate_ids)),
            "ACCEPTED_UNPUBLISHED_PAYLOAD_MISSING",
        ),
        (len(contexts) == len(dispatched_rows), "CONTEXT_TELEMETRY_MISSING"),
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
        (reported_usage, "USAGE_STATUS_NOT_REPORTED"),
        (policy_clean, "POLICY_BREACH_DETECTED"),
        (complete_output_telemetry, "OUTPUT_TELEMETRY_MISSING"),
        (complete_total_telemetry, "TOTAL_TELEMETRY_MISSING"),
    )
    failures.extend(reason for passed, reason in checks if not passed)
    metrics: dict[str, object] = {
        "admitted_candidate_count": len(candidates),
        "accepted_unpublished_payload_count": len(accepted),
        "p50_context_tokens": p50_context,
        "context_reduction_from_incident_baseline": reduction,
        "maximum_context_tokens": max(contexts) if contexts else None,
        "maximum_prompt_bytes": max(prompt_sizes) if prompt_sizes else 0,
        "prompt_size_bands": (
            None
            if not prompt_sizes
            else {
                "short_bytes": min(prompt_sizes),
                "medium_bytes": _median_int(prompt_sizes),
                "long_bytes": max(prompt_sizes),
            }
        ),
        "evidence_package_size_bands": (
            None
            if not evidence_package_sizes
            or len(evidence_package_sizes) != len(primary_rows)
            else {
                "short_bytes": min(evidence_package_sizes),
                "medium_bytes": _median_int(evidence_package_sizes),
                "long_bytes": max(evidence_package_sizes),
            }
        ),
        "maximum_output_tokens": (
            max(primary_output_tokens)
            if len(primary_output_tokens) == len(primary_rows)
            and primary_output_tokens
            else None
        ),
        "maximum_total_tokens": (
            max(primary_total_tokens)
            if len(primary_total_tokens) == len(primary_rows)
            and primary_total_tokens
            else None
        ),
        "maximum_leaf_output_tokens": (
            max(output_tokens) if complete_output_telemetry else None
        ),
        "maximum_leaf_total_tokens": (
            max(total_tokens) if complete_total_telemetry else None
        ),
        "accepted_payload_token_totals": accepted_token_totals,
        "total_tokens_for_accepted_payloads": (
            sum(accepted_token_totals)
            if len(accepted_token_totals) == len(accepted)
            else None
        ),
        "median_tokens_per_accepted_payload": (
            _median_int(accepted_token_totals)
            if len(accepted_token_totals) == len(accepted)
            else None
        ),
        "tokens_on_hold_reject_or_no_result": (
            None if no_result_tokens is None else max(no_result_tokens, 0)
        ),
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
        "public_effect_proof": "UNPUBLISHED_PAYLOAD_SCHEMA_AND_RETAINED_ROWS",
        "implementation_revision": implementation_revision,
        "policy_headroom_fraction_percent": 20,
        "policy_minimum_headroom_tokens": CONT_POLICY_MIN_HEADROOM_TOKENS,
    }
    evidence = {
        "schema_version": "newsroom.cont-hermetic-calibration.v1",
        "version": version,
        "implementation_revision": implementation_revision,
        "candidate_ids": list(candidates),
        "accepted_candidate_ids": accepted,
        "passed": not failures,
        "failure_reasons": failures,
        "metrics": metrics,
    }
    return ContCalibrationPacket(
        version=version,
        implementation_revision=implementation_revision,
        candidate_ids=candidates,
        accepted_candidate_ids=tuple(accepted),
        passed=not failures,
        failure_reasons=tuple(failures),
        metrics=metrics,
        calibration_evidence_digest=digest_canonical(evidence),
    )


def stage_cont_calibration_policy(
    *,
    candidate_ids: Sequence[str],
    version: str,
    implementation_revision: str,
    max_prompt_bytes: int,
) -> InvocationEfficiencyPolicy:
    """Create an exact-head, candidate-scoped EVALUATION bootstrap policy."""

    candidates = tuple(candidate_ids)
    if (
        not candidates
        or len(candidates) > CONT_CALIBRATION_MAX_CANDIDATES
        or len(set(candidates)) != len(candidates)
    ):
        raise ModelUsageAdmissionError(
            "calibration bootstrap requires one to five unique candidates"
        )
    if max_prompt_bytes <= 0:
        raise ModelUsageAdmissionError(
            "calibration bootstrap prompt bound must be positive"
        )
    evidence = {
        "schema_version": "newsroom.cont-hermetic-calibration-bootstrap.v1",
        "version": version,
        "implementation_revision": implementation_revision,
        "candidate_ids": list(candidates),
        "max_prompt_bytes": max_prompt_bytes,
        "max_context_tokens": CONT_CALIBRATION_MAX_CONTEXT,
        "max_output_tokens": CONT_CALIBRATION_BOOTSTRAP_MAX_OUTPUT_TOKENS,
        "command_semantic_version": GROK_COMMAND_SEMANTIC_VERSION,
        "command_flags": list(CONT_PRIMARY_COMMAND_FLAGS),
        "context_manifest_schema_version": CONT_CONTEXT_MANIFEST_SCHEMA_VERSION,
        "disabled_capabilities": list(CONT_DISABLED_CAPABILITIES),
    }
    maximum_total = (
        CONT_CALIBRATION_MAX_CONTEXT
        + CONT_CALIBRATION_BOOTSTRAP_MAX_OUTPUT_TOKENS
    )
    return InvocationEfficiencyPolicy.create(
        policy_id="cont-hermetic-grok-calibration-bootstrap",
        version=version,
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
        command_semantic_version=GROK_COMMAND_SEMANTIC_VERSION,
        command_flags=CONT_PRIMARY_COMMAND_FLAGS,
        context_manifest_schema_version=CONT_CONTEXT_MANIFEST_SCHEMA_VERSION,
        disabled_capabilities=CONT_DISABLED_CAPABILITIES,
        implementation_revision=implementation_revision,
        calibration_only=True,
        allowed_candidate_ids=candidates,
        max_prompt_bytes=max_prompt_bytes,
        max_context_tokens=CONT_CALIBRATION_MAX_CONTEXT,
        max_output_tokens=CONT_CALIBRATION_BOOTSTRAP_MAX_OUTPUT_TOKENS,
        max_total_tokens=maximum_total,
        prompt_contract_version=CONT_WRITER_PROMPT_CONTRACT_VERSION,
        output_schema_digest=CONT_WRITER_OUTPUT_SCHEMA_DIGEST,
        allowed_context_identities=(CONT_WRITER_CONTEXT_IDENTITY,),
        allowed_config_identities=(CONT_PRIMARY_CONFIG_IDENTITY,),
        hard_estimate_ceiling_tokens=maximum_total,
        evidence_digest=digest_canonical(evidence),
        qualified=True,
    )


__all__ = [
    "ContCalibrationPacket",
    "assess_cont_calibration",
    "stage_cont_calibration_policy",
]
