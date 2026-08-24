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
from typing import Protocol, cast

from newsroom.control_plane.cycle import CycleReport, run_cycle
from newsroom.control_plane.cycle_governor import (
    CycleNotEligible,
    CycleOutcomeInput,
    CycleTerminalResult,
    DurableCycleGovernor,
    EvaluationCyclePolicy,
    WriterRouteHealthProof,
)
from newsroom.control_plane.graphiti_events import GraphitiEventQueue
from newsroom.control_plane.intake import IntakeReport, run_intake
from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    CANONICAL_UNPUBLISHED_STORE,
    ensure_control_plane_state_root,
)
from newsroom.control_plane.store import list_payloads
from newsroom.control_plane.usage import graphiti_usage_report
from newsroom.control_plane.veto import VetoError
from newsroom.control_plane.writer import default_writer, probe_grok_writer_route

DEFAULT_PROVING = str(CANONICAL_PROVING_STORE)
DEFAULT_UNPUBLISHED = str(CANONICAL_UNPUBLISHED_STORE)


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
    if args.command == "usage":
        sys.stdout.write(
            json.dumps(
                graphiti_usage_report(
                    args.unpublished,
                    window_seconds=args.usage_window,
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
            writer_route_health_probe=_probe_cont_writer_route,
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
