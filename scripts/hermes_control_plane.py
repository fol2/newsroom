#!/usr/bin/env python3
"""Hermes Control Plane private editorial-beta CLI. No public dispatch."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.cycle import (
    CycleReport,
    assert_no_owner_emergency_stop,
    owner_emergency_stop_fence,
    run_cycle,
)
from newsroom.control_plane.cycle_governor import (
    CycleNotEligible,
    CycleOutcomeInput,
    CycleTerminalResult,
    DurableCycleGovernor,
    EvaluationCyclePolicy,
    WriterRouteHealthProof,
)
from newsroom.control_plane.cont_calibration import (
    assess_cont_calibration,
    stage_cont_calibration_policy,
)
from newsroom.control_plane.graphiti_events import GraphitiEventQueue
from newsroom.control_plane.intake import IntakeReport, run_intake
from newsroom.control_plane.model_usage import (
    InvocationAllocation,
    InvocationTerminal,
    ModelUsageAdmissionError,
    ModelUsageService,
    UsageComponents,
    UsageStatus,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    CANONICAL_UNPUBLISHED_STORE,
    ensure_control_plane_state_root,
)
from newsroom.control_plane.store import list_payloads
from newsroom.control_plane.veto import VetoError
from newsroom.control_plane.writer import (
    WriterDispatchError,
    cont_writer_implementation_identity,
    default_writer,
    probe_grok_writer_route,
    read_grok_command_semantic_version,
)

DEFAULT_PROVING = str(CANONICAL_PROVING_STORE)
DEFAULT_UNPUBLISHED = str(CANONICAL_UNPUBLISHED_STORE)
CONT_HEALTH_PROBE_PROVIDER = "grok-build-cli"
CONT_HEALTH_PROBE_ROUTE = "CONT_HEALTH_PROBE"
CONT_HEALTH_PROBE_MODEL = "grok-4.6"
CONT_HEALTH_PROBE_REASONING = "none"
CONT_HEALTH_PROBE_PROMPT_CONTRACT = "newsroom.cont-health-probe.models.v1"
CONT_HEALTH_PROBE_CONTEXT_IDENTITY = "cont-route-health-probe-v1"


class _CycleArgs(Protocol):
    proving: str
    unpublished: str
    max_writes: int


def _cycle(
    args: _CycleArgs,
    *,
    cycle_id: str,
    writer_dispatch_permitted: bool,
    writer_dispatch_fence: Callable[[], None],
) -> CycleReport:
    model_usage = ModelUsageService(args.unpublished)
    model_usage.recover_unresolved(observed_at=datetime.now(tz=UTC))
    return run_cycle(
        proving_store=args.proving,
        unpublished_store=args.unpublished,
        writer=default_writer(),
        max_writes=args.max_writes,
        graphiti=None,
        max_graphiti=0,
        max_writer_provider_dispatches=5 if writer_dispatch_permitted else 0,
        max_writer_fallback_dispatches=1 if writer_dispatch_permitted else 0,
        cycle_id=cycle_id,
        writer_dispatch_fence=writer_dispatch_fence,
        model_usage=model_usage,
    )


def _resolve_cooldown(*, cooldown: int | None, interval: int | None) -> int:
    if cooldown is not None and interval is not None and cooldown != interval:
        raise ValueError("--cooldown and compatibility --interval values conflict")
    value = cooldown if cooldown is not None else interval
    if value is None:
        value = 300
    if value < 300:
        raise ValueError("EVALUATION post-cycle cooldown must be at least 300 seconds")
    return value


def _validate_max_writes(max_writes: int) -> None:
    if not 1 <= max_writes <= 5:
        raise ValueError("--max-writes must be between 1 and 5 inclusive")


def _evaluation_policy(cooldown_seconds: int) -> EvaluationCyclePolicy:
    return EvaluationCyclePolicy(
        normal_cooldown_seconds=cooldown_seconds,
        unproductive_cooldown_seconds=max(900, cooldown_seconds),
    )


def _probe_cont_writer_route() -> WriterRouteHealthProof:
    proof = probe_grok_writer_route()
    return WriterRouteHealthProof(
        executable_ok=proof.executable_ok,
        authentication_ok=proof.authentication_ok,
        configuration_ok=proof.configuration_ok,
        provider_available=proof.provider_available,
        provider_dispatched=proof.provider_dispatched,
        provider_receipt_reference=proof.provider_receipt_reference,
    )


def _metered_cont_writer_route_probe(
    path: str, proving_store: str
) -> Callable[[], WriterRouteHealthProof]:
    def probe() -> WriterRouteHealthProof:
        assert_no_owner_emergency_stop(proving_store)
        service = ModelUsageService(path)
        service.recover_unresolved(observed_at=datetime.now(tz=UTC))
        admitted_at = datetime.now(tz=UTC)
        cycle_id = str(uuid.uuid4())
        envelope = WorkEnvelope.create(
            cycle_id=cycle_id,
            workload_class=WorkloadClass.CONT_ROUTE_HEALTH_PROBE,
            admitted_at=admitted_at,
            admission_decision_id=None,
            candidate_id=None,
            hypothesis_digest=None,
            evidence_package_digest=None,
            ingest_id=None,
            graphiti_attempt_id=None,
        )
        service.open_envelope(envelope)
        policy = service.qualified_policy(
            workload_class=WorkloadClass.CONT_ROUTE_HEALTH_PROBE,
            provider=CONT_HEALTH_PROBE_PROVIDER,
            route=CONT_HEALTH_PROBE_ROUTE,
            model=CONT_HEALTH_PROBE_MODEL,
            reasoning=CONT_HEALTH_PROBE_REASONING,
        )
        request = canonical_json_bytes({"command": ["grok", "models"]})
        request_digest = digest_bytes(request)
        allocation = InvocationAllocation.create(
            envelope_id=envelope.envelope_id,
            cycle_id=cycle_id,
            leaf_ordinal=1,
            workload_class=WorkloadClass.CONT_ROUTE_HEALTH_PROBE,
            invocation_policy_digest=policy.canonical_digest,
            provider=CONT_HEALTH_PROBE_PROVIDER,
            route=CONT_HEALTH_PROBE_ROUTE,
            model=CONT_HEALTH_PROBE_MODEL,
            reasoning=CONT_HEALTH_PROBE_REASONING,
            prompt_contract_version=CONT_HEALTH_PROBE_PROMPT_CONTRACT,
            prompt_bytes=len(request),
            prompt_digest=request_digest,
            request_digest=request_digest,
            output_schema_digest=digest_canonical({"schema": "writer-route-health"}),
            max_output_tokens=policy.max_output_tokens,
            context_manifest_digest=digest_canonical(
                {"context_identity": CONT_HEALTH_PROBE_CONTEXT_IDENTITY}
            ),
            context_identity=CONT_HEALTH_PROBE_CONTEXT_IDENTITY,
            config_identity="cont-health-probe-command-v1",
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            allocated_at=admitted_at,
            recovery_deadline_at=admitted_at + timedelta(minutes=1),
            parent_invocation_id=None,
        )
        service.allocate(allocation, owner_emergency_stop=False)
        dispatch_started_at: datetime | None = None
        try:
            with owner_emergency_stop_fence(proving_store):
                dispatch_started_at = datetime.now(tz=UTC)
                service.observe_transport(
                    invocation_id=allocation.invocation_id,
                    observed_at=dispatch_started_at,
                    state="DISPATCH_STARTED",
                    evidence_digest=request_digest,
                )
                proof = _probe_cont_writer_route()
        except VetoError:
            failed_at = datetime.now(tz=UTC)
            service.complete(
                InvocationTerminal.create(
                    invocation_id=allocation.invocation_id,
                    outcome="VETOED_BEFORE_PROVIDER_DISPATCH",
                    failure_class="OWNER_EMERGENCY_STOP",
                    usage_status=UsageStatus.REPORTED,
                    components=UsageComponents(
                        total_tokens=0, provenance="CLI_DERIVED"
                    ),
                    dispatch_at=None,
                    completed_at=failed_at,
                    observed_at=failed_at,
                    subscription_cli_chat_not_cash_debited=True,
                    pre_dispatch_zero_proved=True,
                )
            )
            service.record_work_outcome(
                envelope_id=envelope.envelope_id,
                outcome="FAILED",
                outcome_record_id=allocation.invocation_id,
                payload_digest=None,
                terminal_at=failed_at,
            )
            raise
        except (OSError, RuntimeError, ValueError):
            if dispatch_started_at is None:
                raise
            failed_at = datetime.now(tz=UTC)
            service.complete(
                InvocationTerminal.create(
                    invocation_id=allocation.invocation_id,
                    outcome="PROBE_EXCEPTION",
                    failure_class="PROBE_EXCEPTION_AFTER_POSSIBLE_DISPATCH",
                    usage_status=UsageStatus.AMBIGUOUS,
                    components=UsageComponents(provenance="UNAVAILABLE"),
                    dispatch_at=dispatch_started_at,
                    completed_at=failed_at,
                    observed_at=failed_at,
                    subscription_cli_chat_not_cash_debited=True,
                )
            )
            service.record_work_outcome(
                envelope_id=envelope.envelope_id,
                outcome="FAILED",
                outcome_record_id=allocation.invocation_id,
                payload_digest=None,
                terminal_at=failed_at,
            )
            raise
        terminal_at = datetime.now(tz=UTC)
        telemetry = asdict(proof)
        provider_attempt_id = (
            proof.provider_receipt_reference
            or f"{allocation.invocation_id}:pre-dispatch"
        )
        service.link_provider_attempt(
            invocation_id=allocation.invocation_id,
            provider_attempt_id=provider_attempt_id,
            linked_at=terminal_at,
        )
        provider_dispatched = proof.provider_dispatched
        service.complete(
            InvocationTerminal.create(
                invocation_id=allocation.invocation_id,
                outcome=("COMPLETE" if proof.provider_available else "FAILED"),
                failure_class=(None if proof.provider_available else "PROBE_FAILED"),
                usage_status=(
                    UsageStatus.ESTIMATED
                    if provider_dispatched
                    and policy.hard_estimate_ceiling_tokens is not None
                    else UsageStatus.UNREPORTED
                    if provider_dispatched
                    else UsageStatus.REPORTED
                ),
                components=(
                    UsageComponents(
                        total_tokens=policy.hard_estimate_ceiling_tokens,
                        provenance="BOUNDED_ESTIMATE",
                    )
                    if provider_dispatched
                    and policy.hard_estimate_ceiling_tokens is not None
                    else UsageComponents(provenance="UNAVAILABLE")
                    if provider_dispatched
                    else UsageComponents(total_tokens=0, provenance="CLI_DERIVED")
                ),
                dispatch_at=(dispatch_started_at if provider_dispatched else None),
                completed_at=terminal_at,
                observed_at=terminal_at,
                provider_telemetry_digest=digest_canonical(telemetry),
                raw_telemetry_pointer=(
                    "sqlite-private://model_provider_telemetry/"
                    f"{allocation.invocation_id}"
                ),
                pre_dispatch_zero_proved=not provider_dispatched,
                subscription_cli_chat_not_cash_debited=True,
                estimate_policy_digest=(
                    policy.canonical_digest
                    if provider_dispatched
                    and policy.hard_estimate_ceiling_tokens is not None
                    else None
                ),
                estimate_calculation=(
                    "qualified_policy.hard_estimate_ceiling_tokens="
                    f"{policy.hard_estimate_ceiling_tokens}"
                    if provider_dispatched
                    and policy.hard_estimate_ceiling_tokens is not None
                    else None
                ),
            ),
            provider_telemetry=telemetry,
        )
        service.record_work_outcome(
            envelope_id=envelope.envelope_id,
            outcome=("ACCEPTED" if proof.provider_available else "REJECT"),
            outcome_record_id=provider_attempt_id,
            payload_digest=None,
            terminal_at=terminal_at,
        )
        return proof

    return probe


def _report_body(report: CycleReport) -> dict[str, object]:
    return {
        "cycle_id": report.cycle_id,
        "proving_run_id": report.proving_run_id,
        "minted": report.minted,
        "duplicate": report.duplicate,
        "sources": report.sources,
        "candidates": report.candidates,
        "candidates_considered": report.candidates_considered,
        "admission_counts": {
            "WRITE_READY": report.write_ready,
            "HOLD": report.admission_hold,
            "REJECT": report.admission_reject,
        },
        "admission_reason_counts": dict(report.admission_reason_counts),
        "selected_write_ready": report.selected_write_ready,
        "candidate_attempts": report.candidate_attempts,
        "provider_dispatches": report.provider_dispatches,
        "primary_dispatches": report.primary_dispatches,
        "fallback_dispatches": report.fallback_dispatches,
        "draft_outcomes": {
            "ACCEPTED": report.draft_accepted,
            "HOLD": report.draft_hold,
            "REJECT": report.draft_reject,
        },
        "draft_reason_counts": dict(report.draft_reason_counts),
        "accepted_payload_count": report.accepted_payload_count,
        "writer_circuit_open": report.writer_circuit_open,
        "writer_circuit_open_reason": report.writer_circuit_open_reason,
        "no_useful_output_circuit_open": report.no_useful_output_circuit_open,
        "no_useful_output_circuit_open_reason": (
            report.no_useful_output_circuit_open_reason
        ),
        "candidate_budget_exhausted": report.candidate_budget_exhausted,
        "provider_budget_exhausted": report.provider_budget_exhausted,
        "fallback_budget_exhausted": report.fallback_budget_exhausted,
        "write_budget_exhausted": report.write_budget_exhausted,
        "writer_id": report.writer_id,
        "graphiti": report.graphiti,
        "ledger_digest": report.ledger_digest,
        "public_dispatch": False,
        "auto_publish": False,
    }


class GovernedUnitFailure(RuntimeError):
    def __init__(self, failure_class: str, terminal: CycleTerminalResult) -> None:
        super().__init__(f"governed cycle failed: {failure_class}")
        self.failure_class = failure_class
        self.terminal = terminal


def _governed_unit(
    args: _CycleArgs,
    *,
    cooldown_seconds: int,
) -> tuple[IntakeReport, CycleReport, CycleTerminalResult]:
    _validate_max_writes(args.max_writes)
    policy = _evaluation_policy(cooldown_seconds)
    governor = DurableCycleGovernor(args.unpublished, policy=policy)
    lease = governor.claim(owner_id=f"hermes-cycle:{uuid.uuid4()}")

    def writer_dispatch_fence() -> None:
        governor.renew(lease)

    try:
        intake = run_intake(proving_store=args.proving)
        governor.renew(lease)
        report = _cycle(
            args,
            cycle_id=lease.cycle_id,
            writer_dispatch_permitted=lease.writer_dispatch_permitted,
            writer_dispatch_fence=writer_dispatch_fence,
        )
        terminal = governor.complete(
            lease,
            CycleOutcomeInput(
                write_ready=report.write_ready,
                admission_hold=report.admission_hold,
                admission_reject=report.admission_reject,
                provider_dispatches=report.provider_dispatches,
                accepted_payload_count=report.accepted_payload_count,
                systemic_provider_failure_reason=(
                    report.writer_circuit_open_reason
                    if report.writer_circuit_open
                    else ""
                ),
            ),
        )
    except Exception as exc:
        try:
            terminal = governor.fail_ambiguous(
                lease,
                failure_reason=f"GOVERNED_UNIT_EXCEPTION:{type(exc).__name__}",
            )
        except Exception as terminal_error:
            exc.add_note(
                "durable ambiguous-cycle terminalisation also failed: "
                f"{type(terminal_error).__name__}"
            )
            raise
        raise GovernedUnitFailure(type(exc).__name__, terminal) from exc
    return intake, report, terminal


def _wait_monotonic(seconds: float) -> None:
    if seconds <= 0:
        return
    started = time.monotonic()
    remaining = seconds
    while remaining > 0:
        time.sleep(remaining)
        remaining = seconds - (time.monotonic() - started)


def _reported_wait(seconds: float) -> float | None:
    return seconds if math.isfinite(seconds) else None


def _reporting_boundaries(
    *, cooldown_seconds: int, usage_window_seconds: int
) -> dict[str, object]:
    return {
        "post_cycle_cooldown_seconds": cooldown_seconds,
        "writer_no_result_backoff_is_route_specific": True,
        "fixed_utc_token_reporting_bucket_seconds": usage_window_seconds,
        "token_usage_reporting_command": "usage",
        "human_emergency_stop_is_separate": True,
        "daily_article_quota": None,
    }


def _usage_instant(value: str | None, *, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("usage range timestamps must include a UTC offset")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Private unpublished editorial beta (no AUTO_PUBLISH).",
        epilog=(
            "Post-cycle cooldown and writer no-result backoff are durable. "
            "The usage command reports fixed UTC token buckets separately; "
            "Human Emergency Stop is a separate authority."
        ),
    )
    parser.add_argument(
        "command",
        choices=(
            "cycle",
            "status",
            "serve",
            "intake",
            "usage",
            "writer-health-probe",
            "writer-calibration",
        ),
    )
    parser.add_argument("--proving", default=DEFAULT_PROVING)
    parser.add_argument("--unpublished", default=DEFAULT_UNPUBLISHED)
    parser.add_argument(
        "--cooldown",
        type=int,
        help="post-cycle cooldown in seconds (EVALUATION minimum: 300)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="compatibility alias for --cooldown; conflicting values are refused",
    )
    parser.add_argument(
        "--max-writes",
        type=int,
        default=5,
        help="per-cycle accepted unpublished payload ceiling; not a time or token quota",
    )
    parser.add_argument(
        "--usage-window",
        type=int,
        default=300,
        help="fixed UTC reporting bucket for token usage; not a cooldown",
    )
    parser.add_argument(
        "--usage-start",
        help="inclusive ISO-8601 start for deterministic usage export",
    )
    parser.add_argument(
        "--usage-end",
        help="exclusive ISO-8601 end for deterministic usage export",
    )
    parser.add_argument(
        "--usage-format",
        choices=("json", "csv", "envelope-csv", "leaf-csv"),
        default="json",
        help="deterministic shared model-usage export format",
    )
    parser.add_argument(
        "--calibration-candidates",
        help="comma-separated retained WRITE_READY candidate identities (maximum five)",
    )
    parser.add_argument(
        "--calibration-version",
        default="issue-730-v1",
        help="version bound into the calibration packet and minted route policy",
    )
    parser.add_argument(
        "--register-policy",
        action="store_true",
        help="register the policy only when every productive calibration gate passes",
    )
    parser.add_argument(
        "--stage-calibration-policy",
        action="store_true",
        help=(
            "register a candidate-scoped exact-head EVALUATION bootstrap policy "
            "before productive calibration"
        ),
    )
    parser.add_argument(
        "--calibration-max-prompt-bytes",
        type=int,
        default=131_072,
        help="hard exact-input byte bound for the candidate-scoped bootstrap policy",
    )
    args = parser.parse_args(argv)
    try:
        cooldown_seconds = _resolve_cooldown(
            cooldown=args.cooldown,
            interval=args.interval,
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        _validate_max_writes(args.max_writes)
    except ValueError as exc:
        parser.error(str(exc))
    ensure_control_plane_state_root()
    if args.command == "writer-calibration":
        if not args.calibration_candidates:
            parser.error("writer-calibration requires --calibration-candidates")
        candidate_ids = tuple(
            value.strip()
            for value in args.calibration_candidates.split(",")
            if value.strip()
        )
        now = datetime.now(tz=UTC)
        try:
            start = _usage_instant(
                args.usage_start,
                default=now - timedelta(days=1),
            )
            end = _usage_instant(
                args.usage_end,
                default=now + timedelta(microseconds=1),
            )
        except ValueError as exc:
            parser.error(str(exc))
        usage = ModelUsageService(args.unpublished)
        revision, worktree_clean = cont_writer_implementation_identity()
        if not worktree_clean:
            parser.error(
                "writer-calibration requires a clean versioned exact-head worktree"
            )
        exact_version = f"{args.calibration_version}+{revision[:12]}"
        if args.stage_calibration_policy:
            if args.register_policy:
                parser.error(
                    "--stage-calibration-policy and --register-policy are separate steps"
                )
            try:
                staged_policy = stage_cont_calibration_policy(
                    candidate_ids=candidate_ids,
                    version=exact_version,
                    implementation_revision=revision,
                    max_prompt_bytes=args.calibration_max_prompt_bytes,
                    command_semantic_version=read_grok_command_semantic_version(),
                )
            except (ModelUsageAdmissionError, ValueError, WriterDispatchError) as exc:
                parser.error(str(exc))
            usage.register_policy(staged_policy)
            sys.stdout.write(
                json.dumps(
                    {
                        "stage": "CALIBRATION_POLICY_REGISTERED",
                        "implementation_revision": revision,
                        "policy": staged_policy.as_record(),
                        "public_effects": 0,
                        "public_effect_proof": (
                            "POLICY_REGISTRATION_HAS_NO_PUBLIC_DISPATCH_PATH"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            return 0
        query = usage.query(start=start, end=end)
        payloads = [
            payload
            for payload in list_payloads(args.unpublished, limit=10_000)
            if payload.story_candidate_id in candidate_ids
        ]
        public_effect_count = sum(
            1
            for payload in payloads
            if payload.publication_bundle
            or payload.auto_publish
            or payload.status != "UNPUBLISHED"
        )
        packet = assess_cont_calibration(
            query["leaves"],  # type: ignore[arg-type]
            candidate_ids=candidate_ids,
            version=exact_version,
            implementation_revision=revision,
            public_effect_count=public_effect_count,
            unpublished_payload_candidate_ids=tuple(
                payload.story_candidate_id for payload in payloads
            ),
        )
        body = packet.as_record()
        if packet.passed:
            policy = packet.mint_primary_policy()
            body["invocation_efficiency_policy"] = policy.as_record()
            if args.register_policy:
                usage.register_policy(policy)
                body["policy_registered"] = True
        elif args.register_policy:
            body["policy_registered"] = False
        sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        return 0 if packet.passed else 2
    if args.command == "usage":
        now = datetime.now(tz=UTC)
        try:
            start = _usage_instant(
                args.usage_start,
                default=now - timedelta(days=1),
            )
            end = _usage_instant(
                args.usage_end,
                default=now + timedelta(microseconds=1),
            )
        except ValueError as exc:
            parser.error(str(exc))
        usage = ModelUsageService(args.unpublished)
        if args.usage_format == "csv":
            sys.stdout.write(
                usage.export_bucket_csv(
                    start=start,
                    end=end,
                    bucket_seconds=args.usage_window,
                )
            )
        elif args.usage_format == "leaf-csv":
            sys.stdout.write(usage.export_csv(start=start, end=end))
        elif args.usage_format == "envelope-csv":
            sys.stdout.write(usage.export_envelope_csv(start=start, end=end))
        else:
            sys.stdout.write(
                json.dumps(
                    usage.report(
                        start=start,
                        end=end,
                        bucket_seconds=args.usage_window,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        return 0
    if args.command == "writer-health-probe":
        governor = DurableCycleGovernor(
            args.unpublished,
            policy=_evaluation_policy(cooldown_seconds),
            writer_route_health_probe=_metered_cont_writer_route_probe(
                args.unpublished, args.proving
            ),
        )
        health = governor.status()
        if health.writer_circuit_state != "OPEN":
            sys.stdout.write(
                json.dumps(
                    {
                        "event": "CONT_WRITER_HEALTH_PROBE_NOT_REQUIRED",
                        "writer_circuit_state": health.writer_circuit_state,
                        "provider_dispatched": False,
                    }
                )
                + "\n"
            )
            return 0
        try:
            release = governor.release_with_health_probe(
                bound_failure_reason=health.writer_circuit_open_reason,
            )
        except CycleNotEligible as exc:
            sys.stdout.write(
                json.dumps(
                    {
                        "event": "CONT_WRITER_HEALTH_PROBE_REFUSED",
                        "reason": exc.reason,
                        "remaining_seconds": _reported_wait(exc.remaining_seconds),
                        "next_probe_eligible_at": exc.next_cycle_eligible_at,
                    }
                )
                + "\n"
            )
            return 3
        except ValueError as exc:
            sys.stdout.write(
                json.dumps(
                    {
                        "event": "CONT_WRITER_HEALTH_PROBE_FAILED",
                        "failure_class": type(exc).__name__,
                        "writer_circuit_state": "OPEN",
                    }
                )
                + "\n"
            )
            return 2
        sys.stdout.write(
            json.dumps(
                {
                    "event": "CONT_WRITER_HEALTH_PROBE_PASSED",
                    "release": asdict(release),
                    "writer_circuit_state": "CLOSED",
                }
            )
            + "\n"
        )
        return 0
    if args.command == "status":
        payloads = list_payloads(args.unpublished)
        graphiti_events = GraphitiEventQueue(args.unpublished).health()
        cycle_governor = DurableCycleGovernor(
            args.unpublished,
            policy=_evaluation_policy(cooldown_seconds),
        ).status()
        body = {
            "count": len(payloads),
            "public_dispatch": False,
            "auto_publish": False,
            "graphiti_events": graphiti_events.as_dict(),
            "cycle_governor": asdict(cycle_governor),
            "reporting_boundaries": _reporting_boundaries(
                cooldown_seconds=cooldown_seconds,
                usage_window_seconds=args.usage_window,
            ),
            "payloads": [
                {
                    "story_candidate_id": item.story_candidate_id,
                    "title": item.title,
                    "evidence_package_digest": item.evidence_package_digest,
                    "source_lineage": list(item.source_lineage),
                    "generated_at": item.generated_at,
                    "status": item.status,
                    "writer_id": item.writer_id,
                    "publication_bundle": item.publication_bundle,
                }
                for item in payloads
            ],
        }
        sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        return 0
    if args.command == "intake":
        intake = run_intake(proving_store=args.proving)
        sys.stdout.write(
            json.dumps(
                {
                    "proving_run_id": intake.proving_run_id,
                    "authorised": intake.authorised,
                    "complete": intake.complete,
                    "ok": intake.ok,
                    "sources": intake.sources,
                    "health": intake.health,
                    "active": intake.active,
                    "degraded": intake.degraded,
                    "held": intake.held,
                    "blocked": intake.blocked,
                    "public_dispatch": False,
                    "auto_publish": False,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return 0 if intake.authorised else 2
    if args.command == "cycle":
        try:
            intake, report, terminal = _governed_unit(
                cast(_CycleArgs, args),
                cooldown_seconds=cooldown_seconds,
            )
        except CycleNotEligible as exc:
            sys.stdout.write(
                json.dumps(
                    {
                        "cycle_started": False,
                        "refusal_reason": exc.reason,
                        "remaining_seconds": _reported_wait(exc.remaining_seconds),
                        "next_cycle_eligible_at": exc.next_cycle_eligible_at,
                        "public_dispatch": False,
                        "auto_publish": False,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            return 3
        except GovernedUnitFailure as exc:
            sys.stdout.write(
                json.dumps(
                    {
                        "event": "GOVERNED_CYCLE_SYSTEMIC_FAILURE",
                        "failure_class": exc.failure_class,
                        "cycle_governor": asdict(exc.terminal),
                        "public_dispatch": False,
                        "auto_publish": False,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            return 2
        body = _report_body(report)
        body["intake"] = asdict(intake)
        body["cycle_governor"] = asdict(terminal)
        body["reporting_boundaries"] = _reporting_boundaries(
            cooldown_seconds=cooldown_seconds,
            usage_window_seconds=args.usage_window,
        )
        sys.stdout.write(json.dumps(body, ensure_ascii=False) + "\n")
        return 0
    while True:
        try:
            intake, report, terminal = _governed_unit(
                cast(_CycleArgs, args),
                cooldown_seconds=cooldown_seconds,
            )
            print(
                json.dumps(
                    {
                        "event": "GOVERNED_CYCLE_TERMINAL",
                        "intake": asdict(intake),
                        "cycle": _report_body(report),
                        "cycle_governor": asdict(terminal),
                        "reporting_boundaries": _reporting_boundaries(
                            cooldown_seconds=cooldown_seconds,
                            usage_window_seconds=args.usage_window,
                        ),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except GovernedUnitFailure as exc:
            print(
                json.dumps(
                    {
                        "event": "GOVERNED_CYCLE_SYSTEMIC_FAILURE",
                        "failure_class": exc.failure_class,
                        "cycle_governor": asdict(exc.terminal),
                        "public_dispatch": False,
                        "auto_publish": False,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            _wait_monotonic(1.0)
        except CycleNotEligible as exc:
            print(
                json.dumps(
                    {
                        "event": "GOVERNED_CYCLE_REFUSED",
                        "reason": exc.reason,
                        "remaining_seconds": _reported_wait(exc.remaining_seconds),
                        "next_cycle_eligible_at": exc.next_cycle_eligible_at,
                    }
                ),
                flush=True,
            )
            wait_seconds = exc.remaining_seconds
            if not math.isfinite(wait_seconds):
                wait_seconds = 60.0
            _wait_monotonic(wait_seconds)
        except (VetoError, ValueError, OSError, RuntimeError) as exc:
            print(f"cycle refused: {exc}", flush=True)
            _wait_monotonic(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
