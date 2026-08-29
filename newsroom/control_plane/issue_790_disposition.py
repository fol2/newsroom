"""Exact, approval-bound operation for issue #790's one unresolved leaf."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkstemp

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import cycle as cycle_module
from newsroom.control_plane import graphiti as graphiti_module
from newsroom.control_plane import graphiti_events as graphiti_events_module
from newsroom.control_plane import graphiti_requests as graphiti_requests_module
from newsroom.control_plane import issue_790_canary as issue_790_canary_module
from newsroom.control_plane import issue_790_contract as issue_790_contract_module
from newsroom.control_plane import issue_790_step16_activation as step16_activation_module
from newsroom.control_plane import model_usage as model_usage_module
from newsroom.control_plane.graphiti_events import GraphitiProcessResult
from newsroom.control_plane.graphiti_requests import (
    GraphitiLeafClass,
    load_checked_graphiti_call_shape_policy,
)
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_contract import (
    ISSUE_790_APPROVED_PLAN_DIGEST,
    issue_790_approved_plan_contract,
    issue_790_approved_plan_contracts,
)
from newsroom.control_plane.model_usage import (
    ModelUsageAdmissionError,
    ModelUsageIntegrityError,
    ModelUsageService,
)
from newsroom.graphiti_adapter import cli_client as cli_client_module
from newsroom.graphiti_adapter import cli_process as cli_process_module
from newsroom.graphiti_adapter import cursor_transport as cursor_transport_module
from newsroom.graphiti_adapter import evaluation_packet as evaluation_packet_module
from newsroom.graphiti_adapter import real as real_graphiti_module
from newsroom.graphiti_adapter.combined_temporal_projection import (
    PROJECTION_POLICY_DIGEST,
    PROJECTION_POLICY_VERSION,
)
from newsroom.graphiti_adapter.combined_temporal_validation import (
    VALIDATOR_CONTRACT_VERSION,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EXTRACTION_TIMEOUT_MS,
    GRAPHITI_MAX_CLEANUP_TIMEOUT_MS,
)
from newsroom.graphiti_adapter.cli_process import validated_timeout_diagnostics
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

ISSUE_790_PLAN_SCHEMA = "newsroom.issue-790.conservative-disposition-plan.v1"
ISSUE_790_ITERATIVE_PLAN_SCHEMA = "newsroom.issue-790.iterative-canary-plan.v2"
ISSUE_790_RECEIPT_SCHEMA = (
    "newsroom.issue-790.conservative-disposition-receipt.v1"
)
ISSUE_790_ITERATIVE_RECEIPT_SCHEMA = (
    "newsroom.issue-790.iterative-disposition-receipt.v2"
)
ISSUE_790_OPERATIONAL_EVIDENCE_SCHEMA = (
    "newsroom.issue-790.operational-preconditions.v1"
)
ISSUE_790_CANARY_RECEIPT_SCHEMA = "newsroom.issue-790.bounded-canary-receipt.v1"
ISSUE_790_ITERATIVE_CANARY_RECEIPT_SCHEMA = (
    "newsroom.issue-790.iterative-bounded-canary-receipt.v2"
)
ISSUE_790_CAUSAL_REPORT_SCHEMA = "newsroom.issue-790.causal-report.v1"
ISSUE_790_NON_TIMEOUT_CAUSAL_REPORT_SCHEMA = (
    "newsroom.issue-790.non-timeout-causal-report.v1"
)
ISSUE_790_REVIEWED_FIX_SCHEMA = "newsroom.issue-790.reviewed-non-timeout-fix.v1"
_ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS = frozenset(
    {"REVIEWED_NON_TIMEOUT_FIX", "COMPATIBILITY_FLOOR_ARCHITECTURE"}
)
_STEP16_SEQUENCE_IDENTITY_FIELDS = frozenset(
    {
        "projection_policy_version",
        "projection_policy_digest",
        "temporal_policy_version",
        "validator_contract_version",
        "pre_dispatch_operational_requirements_digest",
    }
)
_STEP16_ACTIVATION_FIELDS = frozenset(
    {
        "reviewed_correction_revision",
        "reviewed_correction_tree",
        "pre_dispatch_operational_requirements",
        "owner_activation",
    }
)
_STEP16_OWNER_CAPS = {
    "catalogue_query_cap": 1,
    "fresh_event_cap": 1,
    "provider_dispatch_cap": 1,
    "retry_cap": 0,
    "fallback_cap": 0,
    "backlog_drain_cap": 0,
    "bulk_requeue_cap": 0,
    "publication_cap": 0,
}
_PENDING_PLAN_ONLY_KEYS = ("plan_status", "executable", "live_canary_authorised")
_PENDING_SEQUENCE_ONLY_KEYS = ("hold_comment",)
_CANDIDATE_PLAN_STATUS = "CHECKED_CANDIDATE"
_OWNER_APPROVAL_REFERENCE = re.compile(
    r"https://github\.com/fol2/newsroom/issues/790#issuecomment-[1-9][0-9]*"
)
ISSUE_790_STEP16_PENDING_PLAN_PATH = Path(
    "docs/operations/2026-08-28-issue-790-success-sequence-step-16.pending-owner-review.json"
)
ISSUE_790_STEP16_PRE_DISPATCH_PATH = Path(
    "docs/operations/2026-08-28-issue-790-step-16-pre-dispatch-operational-requirements.json"
)
ISSUE_790_STEP16_CHECKED_APPROVED_BY = "checked:issue-790-step16-sealer"
ISSUE_790_STEP16_CHECKED_APPROVED_AT = "2026-08-28T21:00:00.000000Z"
ISSUE_790_ITERATIVE_PREFLIGHT_SCHEMA = (
    "newsroom.issue-790.iterative-fresh-event-preflight.v2"
)
_FALLBACK_MODE = "DISABLED_BEFORE_PROVIDER_DISPATCH"
_ISSUE_790_ACCEPTED_CI_CHECK_NAMES = frozenset(
    {
        "focus-gates",
        "test",
        # Fallback only: never the preferred wait for live canary wall time.
        # Prefer workflow_dispatch Focus Gates on the exact tip SHA.
        "full-deterministic-health",
    }
)
_ISSUE_790_CI_CHECK_PREFERENCE = {
    "focus-gates": 0,
    "test": 1,
    "full-deterministic-health": 2,
}
_AUTHORITY_SCHEMA = (
    "newsroom.model-usage.conservative-disposition-authority.v2"
)
_SCOPE = "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION"
_RELEASE_KIND = "AUTHORISED_OPERATOR_RESET"
_WORKER_LABEL = "com.jamesto.newsroom-graphiti-worker"
_NON_EFFECTS = (
    "NO_PUBLICATION",
    "NO_PUBLIC_DISPATCH",
    "NO_BACKLOG_DRAIN",
    "NO_BULK_REQUEUE",
    "NO_PRODUCTION_OPERATIONAL_ADMISSION",
    "NO_WIDER_ACTIVATION",
    "NO_PROVIDER_SUBSTITUTION",
    "NO_MODEL_SUBSTITUTION",
    "NO_TOKEN_LIMIT_REMOVAL",
    "NO_UNRELATED_SPEND_DISPOSITION",
)
_RETRY_FORBIDDEN_EVENTS: tuple[dict[str, object], ...] = (
    {
        "attempt_count": 1,
        "available_at": "2026-08-26T12:25:29.807056Z",
        "event_id": (
            "sha256:bacb9104c81dd86ca3f62a39f6c386cd4d84ab470e9675e31acf8e2feb50443e"
        ),
        "last_failure_code": "PRODUCER_INTERNAL_ERROR",
        "ledger_seq": 1932,
        "provider_dispatched": True,
        "state": "RETRY_HELD",
    },
    {
        "attempt_count": 1,
        "available_at": "2026-08-26T13:52:15.763233Z",
        "event_id": (
            "sha256:de7bb58fde4829f4778936e7c5ebd1dd583a63f8658fb6af2fcb4b6fc873b0d5"
        ),
        "last_failure_code": "PRODUCER_INTERNAL_ERROR",
        "ledger_seq": 1972,
        "provider_dispatched": False,
        "state": "RETRY_HELD",
    },
)
_RUNNING_CODE_MODULES: tuple[tuple[str, str], ...] = (
    (
        "newsroom.control_plane.issue_790_disposition",
        "newsroom/control_plane/issue_790_disposition.py",
    ),
    ("newsroom.control_plane.issue_790_canary", "newsroom/control_plane/issue_790_canary.py"),
    ("newsroom.control_plane.issue_790_contract", "newsroom/control_plane/issue_790_contract.py"),
    (
        "newsroom.control_plane.issue_790_step16_activation",
        "newsroom/control_plane/issue_790_step16_activation.py",
    ),
    ("newsroom.control_plane.model_usage", "newsroom/control_plane/model_usage.py"),
    ("newsroom.control_plane.graphiti_events", "newsroom/control_plane/graphiti_events.py"),
    ("newsroom.control_plane.graphiti", "newsroom/control_plane/graphiti.py"),
    (
        "newsroom.control_plane.graphiti_requests",
        "newsroom/control_plane/graphiti_requests.py",
    ),
    ("newsroom.control_plane.cycle", "newsroom/control_plane/cycle.py"),
    (
        "newsroom.graphiti_adapter.evaluation_packet",
        "newsroom/graphiti_adapter/evaluation_packet.py",
    ),
    (
        "newsroom.graphiti_adapter.cli_client",
        "newsroom/graphiti_adapter/cli_client.py",
    ),
    (
        "newsroom.graphiti_adapter.cli_process",
        "newsroom/graphiti_adapter/cli_process.py",
    ),
    (
        "newsroom.graphiti_adapter.cursor_transport",
        "newsroom/graphiti_adapter/cursor_transport.py",
    ),
    (
        "newsroom.graphiti_adapter.real",
        "newsroom/graphiti_adapter/real.py",
    ),
)
_RUNNING_CODE_PATHS: dict[str, str | None] = {
    "newsroom.control_plane.issue_790_disposition": __file__,
    "newsroom.control_plane.issue_790_canary": issue_790_canary_module.__file__,
    "newsroom.control_plane.issue_790_contract": issue_790_contract_module.__file__,
    "newsroom.control_plane.issue_790_step16_activation": (
        step16_activation_module.__file__
    ),
    "newsroom.control_plane.model_usage": model_usage_module.__file__,
    "newsroom.control_plane.graphiti_events": graphiti_events_module.__file__,
    "newsroom.control_plane.graphiti": graphiti_module.__file__,
    "newsroom.control_plane.graphiti_requests": graphiti_requests_module.__file__,
    "newsroom.control_plane.cycle": cycle_module.__file__,
    "newsroom.graphiti_adapter.evaluation_packet": evaluation_packet_module.__file__,
    "newsroom.graphiti_adapter.cli_client": cli_client_module.__file__,
    "newsroom.graphiti_adapter.cli_process": cli_process_module.__file__,
    "newsroom.graphiti_adapter.cursor_transport": cursor_transport_module.__file__,
    "newsroom.graphiti_adapter.real": real_graphiti_module.__file__,
}


class Issue790DispositionError(RuntimeError):
    """The exact #790 plan, retained target or operation failed closed."""


def _record(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise Issue790DispositionError(f"{field} must be an object")
    return dict(value)


def _text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 512
    ):
        raise Issue790DispositionError(f"plan {field} is invalid")
    return value


def _instant(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise Issue790DispositionError(f"plan {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Issue790DispositionError(f"plan {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise Issue790DispositionError(f"plan {field} lacks a timezone")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise Issue790DispositionError("operation timestamp lacks a timezone")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _issue_790_fixed_constraints_digest(policy: object) -> str:
    primary_routes = tuple(
        route
        for route in policy.qualified_routes  # type: ignore[attr-defined]
        if route.leaf_class is GraphitiLeafClass.PRIMARY
    )
    if len(primary_routes) != 1:
        raise Issue790DispositionError("issue #790 primary route differs")
    primary = primary_routes[0]
    fixed_flags = tuple(
        flag
        for flag in primary.command_flags
        if not flag.startswith("CONTROLLER_TIMEOUT_MS=")
    )
    return digest_canonical(
        {
            "schema_version": "newsroom.issue-790.fixed-constraints.v1",
            "fallback_mode": _FALLBACK_MODE,
            "provider": primary.provider,
            "route": primary.route,
            "model": primary.model,
            "reasoning": primary.reasoning,
            "command_flags_except_controller_timeout": list(fixed_flags),
            "disabled_capabilities": list(primary.disabled_capabilities),
            "max_prompt_bytes": primary.max_prompt_bytes,
            "max_context_tokens": primary.max_context_tokens,
            "max_output_tokens": primary.max_output_tokens,
            "max_total_tokens": primary.max_total_tokens,
        }
    )


def _validated_timeout_causal_report(value: object) -> dict[str, object]:
    report = _record(value, field="predecessor causal report")
    supplied_digest = report.get("report_digest")
    without_digest = dict(report)
    without_digest.pop("report_digest", None)
    if supplied_digest != digest_canonical(without_digest):
        raise Issue790DispositionError("issue #790 causal report digest differs")
    if set(report) != {
        "schema_version",
        "classification",
        "causal_constraint",
        "local_cause",
        "provider_cause",
        "diagnostic_reference",
        "diagnostic",
        "report_digest",
    }:
        raise Issue790DispositionError("issue #790 causal report fields differ")
    try:
        diagnostic = validated_timeout_diagnostics([report.get("diagnostic")])[0]
    except ValueError as exc:
        raise Issue790DispositionError(
            "issue #790 causal timeout diagnostic differs"
        ) from exc
    if (
        report.get("schema_version") != ISSUE_790_CAUSAL_REPORT_SCHEMA
        or report.get("classification") != "CONTROLLER_TIMEOUT"
        or report.get("causal_constraint") != "CONTROLLER_TIMEOUT_MS"
        or report.get("local_cause") != diagnostic.get("cause")
        or report.get("provider_cause") != diagnostic.get("provider_cause")
        or diagnostic.get("boundary") != "CONTROLLER_DEADLINE"
        or diagnostic.get("phase") != "PRIMARY_TRANSPORT"
        or diagnostic.get("cause") != "CONFIGURED_TIMEOUT_EXPIRED"
        or diagnostic.get("provider_cause") != "UNOBSERVED"
        or diagnostic.get("process") != "CLI_CHILD"
        or int(diagnostic["elapsed_ms"])
        < int(diagnostic["configured_timeout_ms"])
    ):
        raise Issue790DispositionError("issue #790 causal report differs")
    _text(report, "diagnostic_reference")
    return report


def _validated_non_timeout_causal_report(value: object) -> dict[str, object]:
    report = _record(value, field="predecessor causal report")
    supplied_digest = report.get("report_digest")
    unsigned = dict(report)
    unsigned.pop("report_digest", None)
    if supplied_digest != digest_canonical(unsigned):
        raise Issue790DispositionError("issue #790 causal report digest differs")
    if set(report) != {
        "schema_version", "classification", "causal_constraint",
        "predecessor_outcome_digest", "event_id", "boundary",
        "configured_controller_timeout_ms", "configured_extraction_timeout_ms",
        "cleanup_reserve_ms", "deadline_at", "elapsed_ms", "last_progress",
        "termination", "provider_cause", "local_cause",
        "diagnostic_reference", "report_digest",
    }:
        raise Issue790DispositionError("issue #790 non-timeout causal fields differ")
    timings = tuple(
        report.get(field)
        for field in (
            "configured_controller_timeout_ms",
            "configured_extraction_timeout_ms",
            "cleanup_reserve_ms",
            "elapsed_ms",
        )
    )
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in timings
    ):
        raise Issue790DispositionError("issue #790 non-timeout timing differs")
    controller_timeout, extraction_timeout, cleanup_reserve, _elapsed = timings
    if report.get("deadline_at") is not None:
        _instant(report.get("deadline_at"), field="non-timeout deadline_at")
    for field in (
        "predecessor_outcome_digest", "event_id", "boundary", "last_progress",
        "termination", "provider_cause", "local_cause", "diagnostic_reference",
    ):
        _text(report, field)
    if (
        report.get("schema_version") != ISSUE_790_NON_TIMEOUT_CAUSAL_REPORT_SCHEMA
        or report.get("classification") != "NON_TIMEOUT_FAILURE"
        or report.get("causal_constraint")
        not in {
            "REVIEWED_CODE_OR_CONFIGURATION_FIX",
            "COMPATIBILITY_FLOOR_ARCHITECTURE",
        }
        or report.get("boundary") == "CONTROLLER_DEADLINE"
        or report.get("local_cause") == "CONFIGURED_TIMEOUT_EXPIRED"
        or controller_timeout != extraction_timeout - cleanup_reserve
    ):
        raise Issue790DispositionError("issue #790 non-timeout causal report differs")
    if report.get("causal_constraint") == "COMPATIBILITY_FLOOR_ARCHITECTURE" and (
        report.get("boundary") != "GOVERNANCE"
        or report.get("local_cause") != "OWNER_COMPATIBILITY_FLOOR_AMENDMENT"
        or report.get("termination") != "SUCCESSOR_WITHDRAWN_BEFORE_CONSUMPTION"
    ):
        raise Issue790DispositionError("issue #790 non-timeout causal report differs")
    return report


def _validated_causal_report(value: object) -> dict[str, object]:
    report = _record(value, field="predecessor causal report")
    if report.get("schema_version") == ISSUE_790_CAUSAL_REPORT_SCHEMA:
        return _validated_timeout_causal_report(report)
    if report.get("schema_version") == ISSUE_790_NON_TIMEOUT_CAUSAL_REPORT_SCHEMA:
        return _validated_non_timeout_causal_report(report)
    raise Issue790DispositionError("issue #790 causal report schema differs")


def _validated_reviewed_fix(value: object) -> dict[str, object]:
    fix = _record(value, field="reviewed non-timeout fix")
    supplied_digest = fix.get("record_digest")
    unsigned = dict(fix)
    unsigned.pop("record_digest", None)
    if supplied_digest != digest_canonical(unsigned) or set(fix) != {
        "schema_version", "predecessor_outcome_digest", "causal_report_digest",
        "fix_kind", "pull_request_url", "reviewed_fix_revision",
        "review_receipt_digest", "provider_free_qualification_digest",
        "record_digest",
    }:
        raise Issue790DispositionError("issue #790 reviewed fix fields differ")
    if (
        fix.get("schema_version") != ISSUE_790_REVIEWED_FIX_SCHEMA
        or fix.get("fix_kind") not in {"CODE", "CONFIGURATION", "CODE_AND_CONFIGURATION"}
        or re.fullmatch(
            r"https://github\.com/fol2/newsroom/pull/[1-9][0-9]*",
            _text(fix, "pull_request_url"),
        ) is None
        or re.fullmatch(r"[0-9a-f]{40}", _text(fix, "reviewed_fix_revision")) is None
        or any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", _text(fix, field)) is None
            for field in (
                "predecessor_outcome_digest", "causal_report_digest",
                "review_receipt_digest", "provider_free_qualification_digest",
            )
        )
    ):
        raise Issue790DispositionError("issue #790 reviewed fix differs")
    return fix


def validate_issue_790_plan(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the complete, content-addressed and deliberately narrow plan."""

    plan = dict(value)
    schema_version = plan.get("schema_version")
    iterative = schema_version == ISSUE_790_ITERATIVE_PLAN_SCHEMA
    expected_keys = {
        "schema_version",
        "canonical_digest",
        "issue",
        "approval",
        "target",
        "release",
        "retry_forbidden_events",
        "canary",
        "non_effects",
    }
    if iterative:
        expected_keys.add("sequence")
    if set(plan) != expected_keys:
        raise Issue790DispositionError("issue #790 plan fields differ")
    if schema_version not in {
        ISSUE_790_PLAN_SCHEMA,
        ISSUE_790_ITERATIVE_PLAN_SCHEMA,
    } or plan.get("issue") != 790:
        raise Issue790DispositionError("issue #790 plan identity differs")
    supplied_digest = _text(plan, "canonical_digest")
    calculated_digest = digest_canonical(
        {key: item for key, item in plan.items() if key != "canonical_digest"}
    )
    if supplied_digest != calculated_digest:
        raise Issue790DispositionError("issue #790 plan digest differs")

    approval = _record(plan.get("approval"), field="approval")
    target = _record(plan.get("target"), field="target")
    release = _record(plan.get("release"), field="release")
    canary = _record(plan.get("canary"), field="canary")
    if set(approval) != {"approved_by", "approval_reference", "approved_at", "scope"}:
        raise Issue790DispositionError("issue #790 approval fields differ")
    if _text(approval, "scope") != _SCOPE:
        raise Issue790DispositionError("issue #790 approval scope differs")
    _text(approval, "approved_by")
    _text(approval, "approval_reference")
    _instant(approval.get("approved_at"), field="approved_at")
    target_fields = {
        "invocation_id",
        "terminal_digest",
        "allocation_digest",
        "policy_digest",
        "route",
        "provider",
        "workload_class",
        "terminal_usage_status",
        "terminal_failure_class",
        "route_open_reason",
        "conservative_total_source",
        "expected_conservative_total_tokens",
    }
    if iterative:
        target_fields.add("terminal_outcome")
    if set(target) != target_fields:
        raise Issue790DispositionError("issue #790 target fields differ")
    for field in (
        "invocation_id",
        "terminal_digest",
        "allocation_digest",
        "policy_digest",
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", _text(target, field)) is None:
            raise Issue790DispositionError(f"issue #790 {field} differs")
    if (
        target.get("route") != "GRAPHITI_CHAT_PRIMARY"
        or target.get("provider") != "cursor-agent-cli"
        or target.get("workload_class") != "GRAPHITI_CHAT_PRIMARY"
        or target.get("terminal_usage_status") != "UNREPORTED"
        or target.get("terminal_failure_class") != "MISSING_PROVIDER_TELEMETRY"
        or target.get("route_open_reason")
        not in {"SYSTEMIC_TRANSPORT", "TIMEOUT"}
        or target.get("conservative_total_source")
        != "QUALIFIED_POLICY_MAX_TOTAL_TOKENS"
    ):
        raise Issue790DispositionError("issue #790 target contract differs")
    if iterative and target.get("terminal_outcome") not in {"FAILED", "TIMEOUT"}:
        raise Issue790DispositionError("issue #790 target outcome differs")
    expected_total = target.get("expected_conservative_total_tokens")
    if (
        isinstance(expected_total, bool)
        or not isinstance(expected_total, int)
        or expected_total <= 0
    ):
        raise Issue790DispositionError("issue #790 conservative total is invalid")
    if release != {
        "kind": _RELEASE_KIND,
        "evidence": "CONSERVATIVE_DISPOSITION_DIGEST",
    }:
        raise Issue790DispositionError("issue #790 release contract differs")
    if plan.get("retry_forbidden_events") != list(_RETRY_FORBIDDEN_EVENTS):
        raise Issue790DispositionError("issue #790 retry exclusions differ")
    expected_canary = {
        "authority_consumption": "APPEND_ONLY_SINGLE_USE_BEFORE_PROVIDER_IO",
        "event_binding": "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT",
        "fresh_provider_backed_attempt_count": 1,
        "persistent_worker_state_before_canary": "UNLOADED",
        "requires_exact_main_deployment": True,
    }
    if iterative:
        expected_canary["fallback_mode"] = _FALLBACK_MODE
    if canary != expected_canary:
        raise Issue790DispositionError("issue #790 canary boundary differs")
    if iterative:
        sequence = _record(plan.get("sequence"), field="sequence")
        constraint_change = sequence.get("constraint_change")
        expected_sequence_fields = {
            "sequence_ordinal",
            "stop_condition",
            "constraint_change",
            "controller_timeout_ms",
            "extraction_timeout_ms",
            "cleanup_reserve_ms",
            "timeout_increment_ms",
            "call_shape_policy_digest",
            "call_shape_policy_version",
            "fixed_constraints_digest",
            "root_plan_digest",
            "predecessor",
            "predecessor_causal_report",
        }
        if constraint_change in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS:
            expected_sequence_fields.add("reviewed_fix")
        if sequence.get("sequence_ordinal") == 16:
            expected_sequence_fields.update(_STEP16_SEQUENCE_IDENTITY_FIELDS)
            expected_sequence_fields.update(_STEP16_ACTIVATION_FIELDS)
        if set(sequence) != expected_sequence_fields:
            raise Issue790DispositionError("issue #790 sequence fields differ")
        predecessor = _record(sequence.get("predecessor"), field="predecessor")
        if set(predecessor) != {
            "plan_digest",
            "consumption_digest",
            "outcome_digest",
            "event_id",
            "ledger_seq",
        }:
            raise Issue790DispositionError("issue #790 predecessor fields differ")
        for field in (
            "call_shape_policy_digest",
            "fixed_constraints_digest",
            "root_plan_digest",
            "plan_digest",
            "consumption_digest",
            "outcome_digest",
            "event_id",
        ):
            source = (
                sequence
                if field
                in {
                    "call_shape_policy_digest",
                    "fixed_constraints_digest",
                    "root_plan_digest",
                }
                else predecessor
            )
            if re.fullmatch(r"sha256:[0-9a-f]{64}", _text(source, field)) is None:
                raise Issue790DispositionError(
                    f"issue #790 sequence {field} differs"
                )
        ordinal = sequence.get("sequence_ordinal")
        ledger_seq = predecessor.get("ledger_seq")
        timings = tuple(
            sequence.get(field)
            for field in (
                "controller_timeout_ms",
                "extraction_timeout_ms",
                "cleanup_reserve_ms",
                "timeout_increment_ms",
            )
        )
        if (
            isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal <= 0
            or isinstance(ledger_seq, bool)
            or not isinstance(ledger_seq, int)
            or ledger_seq <= 0
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item <= 0
                for item in timings
            )
        ):
            raise Issue790DispositionError("issue #790 sequence bounds differ")
        controller_timeout, extraction_timeout, cleanup_reserve, timeout_increment = (
            timings
        )
        if (
            controller_timeout != extraction_timeout - cleanup_reserve
            or timeout_increment != 10_000
            or sequence.get("stop_condition")
            != "FIRST_TRUTHFUL_PROVIDER_BACKED_SUCCESS"
        ):
            raise Issue790DispositionError("issue #790 sequence contract differs")
        if constraint_change not in {
            "INITIAL_QUALIFIED_BASELINE",
            "CONTROLLER_TIMEOUT_INCREMENT",
            "REVIEWED_NON_TIMEOUT_FIX",
            "COMPATIBILITY_FLOOR_ARCHITECTURE",
        }:
            raise Issue790DispositionError(
                "issue #790 sequence constraint change differs"
            )
        _text(sequence, "call_shape_policy_version")
        if sequence.get("sequence_ordinal") == 16:
            if (
                sequence.get("projection_policy_version") != PROJECTION_POLICY_VERSION
                or sequence.get("projection_policy_digest") != PROJECTION_POLICY_DIGEST
                or sequence.get("temporal_policy_version") != TEMPORAL_POLICY_VERSION
                or sequence.get("validator_contract_version")
                != VALIDATOR_CONTRACT_VERSION
                or re.fullmatch(
                    r"sha256:[0-9a-f]{64}",
                    _text(
                        sequence,
                        "pre_dispatch_operational_requirements_digest",
                    ),
                )
                is None
            ):
                raise Issue790DispositionError(
                    "issue #790 step 16 identity fields differ"
                )
            if predecessor.get("plan_digest") != (
                issue_790_contract_module.ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST
            ):
                raise Issue790DispositionError(
                    "issue #790 predecessor identity differs"
                )
            _reject_checked_live_approval(approval)
            pre_dispatch = _record(
                sequence.get("pre_dispatch_operational_requirements"),
                field="pre-dispatch operational requirements",
            )
            pre_unsigned = {
                key: item
                for key, item in pre_dispatch.items()
                if key != "requirements_digest"
            }
            revision = _text(sequence, "reviewed_correction_revision")
            tree = _text(sequence, "reviewed_correction_tree")
            if (
                re.fullmatch(r"[0-9a-f]{40}", revision) is None
                or re.fullmatch(r"[0-9a-f]{40}", tree) is None
                or pre_dispatch.get("requirements_digest")
                != digest_canonical(pre_unsigned)
                or sequence.get("pre_dispatch_operational_requirements_digest")
                != pre_dispatch.get("requirements_digest")
                or pre_dispatch.get("exact_main_commit") != revision
                or pre_dispatch.get("exact_main_tree") != tree
            ):
                raise Issue790DispositionError(
                    "issue #790 reviewed correction identity differs"
                )
            owner_activation = (
                step16_activation_module.validate_step16_owner_activation_binding(
                    _record(
                        sequence.get("owner_activation"),
                        field="owner activation",
                    )
                )
            )
            if (
                owner_activation["checked_candidate_digest"]
                != issue_790_contract_module.ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST
                or owner_activation["caps"] != _STEP16_OWNER_CAPS
                or pre_dispatch.get("public_effects") != "DISABLED"
                or pre_dispatch.get("event_binding")
                != "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT"
            ):
                raise Issue790DispositionError(
                    "issue #790 owner activation binding differs"
                )
        causal_report = _validated_causal_report(
            sequence.get("predecessor_causal_report")
        )
        if constraint_change in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS:
            reviewed_fix = _validated_reviewed_fix(sequence.get("reviewed_fix"))
            if (
                causal_report.get("schema_version")
                != ISSUE_790_NON_TIMEOUT_CAUSAL_REPORT_SCHEMA
                or reviewed_fix.get("predecessor_outcome_digest")
                != predecessor.get("outcome_digest")
                or reviewed_fix.get("causal_report_digest")
                != causal_report.get("report_digest")
                or causal_report.get("predecessor_outcome_digest")
                != predecessor.get("outcome_digest")
                or causal_report.get("event_id") != predecessor.get("event_id")
            ):
                raise Issue790DispositionError(
                    "issue #790 reviewed fix predecessor binding differs"
                )
        elif causal_report.get("schema_version") != ISSUE_790_CAUSAL_REPORT_SCHEMA:
            raise Issue790DispositionError(
                "issue #790 timeout transition causal report differs"
            )
    if plan.get("non_effects") != list(_NON_EFFECTS):
        raise Issue790DispositionError("issue #790 non-effects differ")
    return plan


def load_issue_790_plan(
    path: Path,
    *,
    store: Path | None = None,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    path = _canonical_existing_file(path, field="issue #790 plan")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Issue790DispositionError("issue #790 plan is not readable JSON") from exc
    if not isinstance(value, dict):
        raise Issue790DispositionError("issue #790 plan must be an object")
    return _require_approved_plan(value, store=store, github_api=github_api)


def _require_iterative_call_shape(plan: Mapping[str, object]) -> None:
    raw_sequence = plan.get("sequence")
    if raw_sequence is None:
        return
    sequence = _record(raw_sequence, field="sequence")
    target = _record(plan.get("target"), field="target")
    try:
        policy = load_checked_graphiti_call_shape_policy()
    except (OSError, TypeError, ValueError) as exc:
        raise Issue790DispositionError(
            "issue #790 checked call-shape policy is unavailable"
        ) from exc
    primary_routes = tuple(
        route
        for route in policy.qualified_routes
        if route.leaf_class is GraphitiLeafClass.PRIMARY
    )
    expected_timeout_flag = (
        f"CONTROLLER_TIMEOUT_MS={sequence['controller_timeout_ms']}"
    )
    if (
        policy.canonical_digest != sequence.get("call_shape_policy_digest")
        or policy.version != sequence.get("call_shape_policy_version")
        or len(primary_routes) != 1
        or _issue_790_fixed_constraints_digest(policy)
        != sequence.get("fixed_constraints_digest")
        or _record(plan.get("canary"), field="canary").get("fallback_mode")
        != _FALLBACK_MODE
    ):
        raise Issue790DispositionError("issue #790 call-shape policy differs")
    primary = primary_routes[0]
    if primary.model == "composer>=2.5":
        model_ok = (
            "sdk=cursor-sdk>=1.0.29" in primary.command_flags
            and "composer_floor>=2.5" in primary.command_flags
        )
    elif primary.model == "composer-2.5":
        model_ok = True
    else:
        model_ok = False
    if (
        primary.provider != target.get("provider")
        or primary.route != target.get("route")
        or not model_ok
        or primary.max_total_tokens
        != target.get("expected_conservative_total_tokens")
        or expected_timeout_flag not in primary.command_flags
        or GRAPHITI_EXTRACTION_TIMEOUT_MS != sequence.get("extraction_timeout_ms")
        or GRAPHITI_MAX_CLEANUP_TIMEOUT_MS != sequence.get("cleanup_reserve_ms")
    ):
        raise Issue790DispositionError("issue #790 call-shape policy differs")


def _reject_checked_live_approval(approval: Mapping[str, object]) -> None:
    approved_by = approval.get("approved_by")
    reference = approval.get("approval_reference")
    if (
        isinstance(approved_by, str) and approved_by.startswith("checked:")
    ) or (isinstance(reference, str) and reference.startswith("checked:")):
        raise Issue790DispositionError(
            "issue #790 checked approval is not live authority"
        )


def _require_owner_approval_tuple(value: Mapping[str, object]) -> dict[str, str]:
    approval = dict(value)
    _reject_checked_live_approval(approval)
    if set(approval) != {
        "approved_by",
        "approval_reference",
        "approved_at",
        "scope",
        "reviewed_correction_revision",
        "reviewed_correction_tree",
    }:
        raise Issue790DispositionError("issue #790 owner approval fields differ")
    if (
        approval.get("approved_by") != issue_790_contract_module.ISSUE_790_APPROVED_BY
        or _OWNER_APPROVAL_REFERENCE.fullmatch(
            _text(approval, "approval_reference")
        )
        is None
        or approval.get("scope") != _SCOPE
        or re.fullmatch(
            r"[0-9a-f]{40}", _text(approval, "reviewed_correction_revision")
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{40}", _text(approval, "reviewed_correction_tree")
        )
        is None
    ):
        raise Issue790DispositionError("issue #790 owner approval differs")
    _instant(approval.get("approved_at"), field="approved_at")
    return {
        "approved_by": str(approval["approved_by"]),
        "approval_reference": str(approval["approval_reference"]),
        "approved_at": str(approval["approved_at"]),
        "scope": str(approval["scope"]),
        "reviewed_correction_revision": str(
            approval["reviewed_correction_revision"]
        ),
        "reviewed_correction_tree": str(approval["reviewed_correction_tree"]),
    }


def _require_step16_code_identity(
    plan: Mapping[str, object],
    *,
    evidence: Mapping[str, object],
) -> None:
    sequence = plan.get("sequence")
    if not isinstance(sequence, dict) or sequence.get("sequence_ordinal") != 16:
        return
    sequence = _record(sequence, field="sequence")
    pre = _record(
        sequence.get("pre_dispatch_operational_requirements"),
        field="pre-dispatch operational requirements",
    )
    binding = _record(sequence.get("owner_activation"), field="owner activation")
    revision = sequence.get("reviewed_correction_revision")
    tree = sequence.get("reviewed_correction_tree")
    if (
        revision != evidence.get("revision")
        or tree != evidence.get("tree")
        or evidence.get("github_main_revision") != revision
        or pre.get("exact_main_commit") != revision
        or pre.get("exact_main_tree") != tree
    ):
        raise Issue790DispositionError(
            "issue #790 reviewed correction identity differs"
        )
    ci_test = evidence.get("ci_test")
    run_url = binding.get("focus_gate_run_url")
    run_id = binding.get("focus_gate_run_id")
    url = ci_test.get("url") if isinstance(ci_test, dict) else None
    expected_run = f"https://github.com/fol2/newsroom/actions/runs/{run_id}"
    if (
        not isinstance(ci_test, dict)
        or not isinstance(run_url, str)
        or run_url != expected_run
        or not isinstance(url, str)
        or (url != expected_run and not url.startswith(f"{expected_run}/"))
        or ci_test.get("name") != "focus-gates"
        or ci_test.get("status") != "completed"
        or ci_test.get("conclusion") != "success"
        or ci_test.get("head_sha") != revision
    ):
        raise Issue790DispositionError("issue #790 focus gate evidence differs")


def _circuit_state(store: Path) -> dict[str, object] | None:
    try:
        connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
        try:
            circuit = connection.execute(
                "SELECT state,opened_at,available_at,failure_code "
                "FROM unpublished_graphiti_event_circuit WHERE singleton=1"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if circuit is None:
        return None
    return {
        "state": str(circuit[0]),
        "opened_at": None if circuit[1] is None else str(circuit[1]),
        "available_at": None if circuit[2] is None else str(circuit[2]),
        "failure_code": None if circuit[3] is None else str(circuit[3]),
    }


def _require_step16_event_circuit(
    circuit_state: Mapping[str, object] | None,
    *,
    observed_at: datetime,
    policy: object,
) -> str:
    if policy != step16_activation_module.ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY:
        raise Issue790DispositionError("issue #790 event circuit policy differs")
    if circuit_state is None:
        raise Issue790DispositionError(
            "issue #790 pre-dispatch circuit is not observed"
        )
    state = circuit_state.get("state")
    if state == "CLOSED":
        if (
            circuit_state.get("opened_at") is not None
            or circuit_state.get("available_at") is not None
            or circuit_state.get("failure_code") is not None
        ):
            raise Issue790DispositionError("issue #790 event circuit is malformed")
        return "CLOSED"
    if state == "OPEN":
        available_raw = circuit_state.get("available_at")
        opened_raw = circuit_state.get("opened_at")
        failure = circuit_state.get("failure_code")
        if (
            not isinstance(available_raw, str)
            or not isinstance(opened_raw, str)
            or not isinstance(failure, str)
            or not failure
            or failure != failure.strip()
        ):
            raise Issue790DispositionError("issue #790 event circuit is malformed")
        try:
            available_at = _instant(available_raw, field="circuit available_at")
            opened_at = _instant(opened_raw, field="circuit opened_at")
        except Issue790DispositionError as exc:
            raise Issue790DispositionError(
                "issue #790 event circuit is malformed"
            ) from exc
        if opened_at > available_at:
            raise Issue790DispositionError("issue #790 event circuit is malformed")
        if available_at > observed_at:
            raise Issue790DispositionError("issue #790 event circuit is future-open")
        return "EXPIRED_OPEN"
    raise Issue790DispositionError("issue #790 event circuit is unknown")


def _release_step16_expired_open_circuit(
    *,
    store: Path,
    plan: Mapping[str, object],
    circuit_state: Mapping[str, object],
    observed_at: datetime,
    event_id: str,
    ledger_seq: int,
    repository: Issue790CanaryRepository,
) -> dict[str, object]:
    policy = _record(
        _record(plan.get("sequence"), field="sequence").get("owner_activation"),
        field="owner activation",
    ).get("event_circuit_policy")
    eligibility = _require_step16_event_circuit(
        circuit_state,
        observed_at=observed_at,
        policy=policy,
    )
    if eligibility != "EXPIRED_OPEN":
        raise Issue790DispositionError("issue #790 event circuit release differs")
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        record = step16_activation_module.load_step16_activation_record(
            connection,
            plan_digest=str(plan["canonical_digest"]),
        )
    finally:
        connection.close()
    try:
        return repository.release_step16_expired_open_circuit(
            plan_digest=str(plan["canonical_digest"]),
            activation_digest=str(record["activation_digest"]),
            event_id=event_id,
            ledger_seq=ledger_seq,
            prior_state=circuit_state,
            observed_at=observed_at,
            policy=str(policy),
        )
    except Issue790CanaryIntegrityError as exc:
        raise Issue790DispositionError(str(exc)) from exc


def _require_step16_runtime_semantics(
    plan: Mapping[str, object],
    *,
    evidence: Mapping[str, object],
    route_state: Mapping[str, object],
    circuit_state: Mapping[str, object] | None,
    observed_at: datetime,
    canary_event: Mapping[str, object] | None = None,
    fresh_event: bool = True,
) -> None:
    sequence = plan.get("sequence")
    if not isinstance(sequence, dict) or sequence.get("sequence_ordinal") != 16:
        return
    sequence = _record(sequence, field="sequence")
    pre = _record(
        sequence.get("pre_dispatch_operational_requirements"),
        field="pre-dispatch operational requirements",
    )
    binding = _record(sequence.get("owner_activation"), field="owner activation")
    worker = evidence.get("worker")
    if not isinstance(worker, dict):
        raise Issue790DispositionError("issue #790 worker evidence differs")
    _require_worker_unloaded(worker)
    target = _record(plan.get("target"), field="target")
    canary = _record(plan.get("canary"), field="canary")
    permitted = pre.get("route_open_reason_permitted")
    if (
        pre.get("persistent_worker_state_before_provider_io") != "UNLOADED"
        or pre.get("fallback_mode") != _FALLBACK_MODE
        or canary.get("fallback_mode") != _FALLBACK_MODE
        or pre.get("public_effects") != "DISABLED"
        or canary.get("event_binding") != "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT"
        or pre.get("event_binding") != "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT"
        or binding.get("caps") != _STEP16_OWNER_CAPS
        or (
            pre.get("stores_required_healthy") is True
            and evidence.get("store_quick_check") != "ok"
        )
        or not isinstance(permitted, list)
        or target.get("route") != pre.get("route")
    ):
        raise Issue790DispositionError(
            "issue #790 pre-dispatch runtime semantics differ"
        )
    route_status = route_state.get("state")
    if route_status == "OPEN":
        if route_state.get("reason") not in permitted:
            raise Issue790DispositionError(
                "issue #790 pre-dispatch route state differs"
            )
    elif route_status != "CLOSED":
        raise Issue790DispositionError("issue #790 pre-dispatch route state differs")
    if not fresh_event:
        return
    _require_step16_event_circuit(
        circuit_state,
        observed_at=observed_at,
        policy=binding.get("event_circuit_policy"),
    )
    if canary_event is None:
        return
    try:
        event_available = _instant(
            canary_event.get("available_at"),
            field="event available_at",
        )
    except Issue790DispositionError as exc:
        raise Issue790DispositionError(
            "issue #790 pre-dispatch event is not untouched"
        ) from exc
    ledger_seq = canary_event.get("ledger_seq")
    event_id = canary_event.get("event_id")
    if (
        pre.get("untouched_attempt_zero_events_only") != 1
        or pre.get("fresh_provider_backed_attempt_count") != 1
        or canary_event.get("state") != "QUEUED"
        or canary_event.get("attempt_count") != 0
        or canary_event.get("provider_dispatched") is not False
        or canary_event.get("claim_owner") is not None
        or canary_event.get("claim_expires_at") is not None
        or canary_event.get("terminal_at") is not None
        or not isinstance(event_id, str)
        or not event_id.startswith("sha256:")
        or isinstance(ledger_seq, bool)
        or not isinstance(ledger_seq, int)
        or ledger_seq <= 0
        or ledger_seq in {1932, 1972}
        or event_available > observed_at
    ):
        raise Issue790DispositionError(
            "issue #790 pre-dispatch event is not untouched"
        )


def _default_github_api(resource: str) -> dict[str, object]:
    gh = shutil.which("gh")
    if gh is None:
        raise Issue790DispositionError("issue #790 GitHub evidence is unavailable")
    raw = _run_checked(
        (gh, "api", "-H", "Accept: application/vnd.github+json", resource)
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Issue790DispositionError(
            "issue #790 GitHub evidence is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise Issue790DispositionError("issue #790 GitHub evidence is unavailable")
    return value


def _step16_live_contract(
    plan: Mapping[str, object],
    *,
    store: Path | None,
    github_api: step16_activation_module.GitHubApi | None,
) -> issue_790_contract_module.Issue790ApprovedPlanContract:
    if store is None:
        raise Issue790DispositionError(
            "issue #790 step 16 activation store is absent"
        )
    store = _canonical_existing_file(store, field="issue #790 activation store")
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        record = step16_activation_module.load_step16_activation_record(
            connection,
            plan_digest=str(plan["canonical_digest"]),
        )
    finally:
        connection.close()
    authenticated = step16_activation_module.fetch_authenticated_step16_owner_comment(
        comment_id=int(record["comment_id"]),
        github_api=github_api,
        default_github_api=_default_github_api,
        require_bound_evidence=False,
    )
    record = step16_activation_module.validate_step16_activation_receipt(
        record,
        authenticated=authenticated,
        plan=plan,
    )
    return step16_activation_module.activation_record_to_contract(record)


def _require_approved_plan(
    value: Mapping[str, object],
    *,
    store: Path | None = None,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    approval_value = value.get("approval")
    if isinstance(approval_value, dict):
        _reject_checked_live_approval(approval_value)
    plan = validate_issue_790_plan(value)
    sequence = plan.get("sequence")
    step16 = isinstance(sequence, dict) and sequence.get("sequence_ordinal") == 16
    if step16:
        contract = _step16_live_contract(plan, store=store, github_api=github_api)
    else:
        try:
            contract = issue_790_approved_plan_contract(
                str(plan["canonical_digest"])
            )
        except KeyError as exc:
            raise Issue790DispositionError(
                "issue #790 approved plan identity differs"
            ) from exc
    approval = _record(plan.get("approval"), field="approval")
    target = _record(plan.get("target"), field="target")
    if (
        plan.get("schema_version") != contract.schema_version
        or target.get("invocation_id") != contract.invocation_id
        or target.get("terminal_digest") != contract.terminal_digest
        or target.get("allocation_digest") != contract.allocation_digest
        or target.get("terminal_outcome", "FAILED") != contract.terminal_outcome
        or target.get("route_open_reason") != contract.route_open_reason
        or approval.get("approved_by") != contract.approved_by
        or approval.get("approval_reference") != contract.approval_reference
        or approval.get("approved_at") != contract.approved_at
        or approval.get("scope") != contract.scope
    ):
        raise Issue790DispositionError("issue #790 approved plan contract differs")
    if contract.sequence_ordinal > 0:
        sequence = _record(plan.get("sequence"), field="sequence")
        predecessor = _record(sequence.get("predecessor"), field="predecessor")
        causal_report = _validated_causal_report(
            sequence.get("predecessor_causal_report")
        )
        diagnostic = (
            _record(causal_report.get("diagnostic"), field="diagnostic")
            if causal_report.get("schema_version") == ISSUE_790_CAUSAL_REPORT_SCHEMA
            else causal_report
        )
        reviewed_fix = (
            _validated_reviewed_fix(sequence.get("reviewed_fix"))
            if sequence.get("constraint_change")
            in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS
            else None
        )
        if (
            sequence.get("sequence_ordinal") != contract.sequence_ordinal
            or sequence.get("controller_timeout_ms")
            != contract.controller_timeout_ms
            or sequence.get("extraction_timeout_ms")
            != contract.extraction_timeout_ms
            or sequence.get("cleanup_reserve_ms") != contract.cleanup_reserve_ms
            or sequence.get("fixed_constraints_digest")
            != contract.fixed_constraints_digest
            or sequence.get("root_plan_digest") != contract.root_plan_digest
            or predecessor.get("plan_digest")
            != contract.predecessor_plan_digest
            or causal_report.get("report_digest")
            != contract.predecessor_causal_report_digest
            or sequence.get("constraint_change") != contract.constraint_change
            or (
                None if reviewed_fix is None else reviewed_fix.get("record_digest")
            )
            != contract.reviewed_fix_digest
            or sequence.get("projection_policy_digest")
            != contract.projection_policy_digest
            or sequence.get("projection_policy_version")
            != contract.projection_policy_version
            or sequence.get("temporal_policy_version")
            != contract.temporal_policy_version
            or sequence.get("validator_contract_version")
            != contract.validator_contract_version
            or sequence.get("pre_dispatch_operational_requirements_digest")
            != contract.pre_dispatch_operational_requirements_digest
        ):
            raise Issue790DispositionError(
                "issue #790 approved sequence contract differs"
            )
        if contract.sequence_ordinal == 1:
            if (
                sequence.get("constraint_change")
                != "INITIAL_QUALIFIED_BASELINE"
                or diagnostic.get("configured_timeout_ms") != 80_000
                or contract.predecessor_plan_digest
                != ISSUE_790_APPROVED_PLAN_DIGEST
            ):
                raise Issue790DispositionError(
                    "issue #790 initial sequence contract differs"
                )
        else:
            try:
                previous_contract = issue_790_approved_plan_contract(
                    str(contract.predecessor_plan_digest)
                )
            except KeyError as exc:
                raise Issue790DispositionError(
                    "issue #790 previous sequence contract differs"
                ) from exc
            ordinal_step = contract.sequence_ordinal - previous_contract.sequence_ordinal
            if (
                ordinal_step < 1
                or (
                    ordinal_step > 1
                    and sequence.get("constraint_change")
                    != "COMPATIBILITY_FLOOR_ARCHITECTURE"
                )
                or previous_contract.root_plan_digest != contract.root_plan_digest
                or (
                    sequence.get("constraint_change")
                    not in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS
                    and previous_contract.fixed_constraints_digest
                    != contract.fixed_constraints_digest
                )
                or previous_contract.cleanup_reserve_ms
                != contract.cleanup_reserve_ms
            ):
                raise Issue790DispositionError(
                    "issue #790 monotonic sequence contract differs"
                )
            if sequence.get("constraint_change") == "CONTROLLER_TIMEOUT_INCREMENT":
                if (
                    causal_report.get("schema_version")
                    != ISSUE_790_CAUSAL_REPORT_SCHEMA
                    or diagnostic.get("configured_timeout_ms")
                    != previous_contract.controller_timeout_ms
                    or contract.controller_timeout_ms
                    != previous_contract.controller_timeout_ms + 10_000
                    or contract.extraction_timeout_ms
                    != previous_contract.extraction_timeout_ms + 10_000
                ):
                    raise Issue790DispositionError(
                        "issue #790 timeout increment contract differs"
                    )
            elif sequence.get("constraint_change") in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS:
                if (
                    reviewed_fix is None
                    or causal_report.get("schema_version")
                    != ISSUE_790_NON_TIMEOUT_CAUSAL_REPORT_SCHEMA
                    or diagnostic.get("configured_controller_timeout_ms")
                    != previous_contract.controller_timeout_ms
                    or diagnostic.get("configured_extraction_timeout_ms")
                    != previous_contract.extraction_timeout_ms
                    or diagnostic.get("cleanup_reserve_ms")
                    != previous_contract.cleanup_reserve_ms
                    or contract.controller_timeout_ms
                    != previous_contract.controller_timeout_ms
                    or contract.extraction_timeout_ms
                    != previous_contract.extraction_timeout_ms
                ):
                    raise Issue790DispositionError(
                        "issue #790 reviewed fix contract differs"
                    )
                if (
                    sequence.get("constraint_change")
                    == "COMPATIBILITY_FLOOR_ARCHITECTURE"
                    and causal_report.get("causal_constraint")
                    != "COMPATIBILITY_FLOOR_ARCHITECTURE"
                ):
                    raise Issue790DispositionError(
                        "issue #790 compatibility-floor contract differs"
                    )
            else:
                raise Issue790DispositionError(
                    "issue #790 successor transition differs"
                )
    if step16 or contract.plan_digest == issue_790_approved_plan_contracts()[-1].plan_digest:
        _require_iterative_call_shape(plan)
    return plan


def _canonical_existing_file(path: Path, *, field: str) -> Path:
    absolute = path.expanduser().absolute()
    try:
        metadata = absolute.lstat()
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise Issue790DispositionError(f"{field} is absent") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise Issue790DispositionError(f"{field} must be a regular non-symlink file")
    if resolved != absolute:
        raise Issue790DispositionError(f"{field} path is not canonical")
    return absolute


def _canonical_new_file(path: Path, *, field: str) -> Path:
    absolute = path.expanduser().absolute()
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise Issue790DispositionError(f"{field} parent is absent") from exc
    if parent != absolute.parent or not parent.is_dir():
        raise Issue790DispositionError(f"{field} parent path is not canonical")
    if os.path.lexists(absolute):
        raise Issue790DispositionError(f"{field} already exists")
    return absolute


def assert_issue_790_paths_disjoint(*paths: Path) -> None:
    """Reject path aliases before any issue #790 operation or evidence write."""

    normalised = [path.expanduser().absolute() for path in paths]
    if len(set(normalised)) != len(normalised):
        raise Issue790DispositionError("issue #790 operation paths alias")
    existing = [path for path in normalised if os.path.lexists(path)]
    for index, left in enumerate(existing):
        for right in existing[index + 1 :]:
            try:
                aliases = os.path.samefile(left, right)
            except OSError as exc:
                raise Issue790DispositionError(
                    "issue #790 operation path identity is unavailable"
                ) from exc
            if aliases:
                raise Issue790DispositionError("issue #790 operation paths alias")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_file_no_replace(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise Issue790DispositionError("evidence destination already exists") from exc
    _fsync_directory(destination.parent)


def _unlink_temporary(temporary: Path) -> None:
    if temporary.exists():
        temporary.unlink()
        _fsync_directory(temporary.parent)


def _run_checked(
    argv: tuple[str, ...],
    *,
    cwd: Path | None = None,
) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise Issue790DispositionError(
            f"operational evidence command timed out: {argv[0]}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Issue790DispositionError(
            f"operational evidence command failed: {detail or argv[0]}"
        )
    return completed.stdout.strip()


def _worker_state() -> dict[str, object]:
    launchctl = Path("/bin/launchctl")
    pgrep = Path("/usr/bin/pgrep")
    if not launchctl.is_file() or not pgrep.is_file():
        raise Issue790DispositionError("worker-state tools are unavailable")
    try:
        service = subprocess.run(
            (
                str(launchctl),
                "print",
                f"gui/{os.getuid()}/{_WORKER_LABEL}",
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15,
        )
        processes = subprocess.run(
            (str(pgrep), "-f", "scripts/hermes_graphiti_worker.py"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise Issue790DispositionError("worker-state probe timed out") from exc
    if processes.returncode not in {0, 1}:
        raise Issue790DispositionError("worker process-state probe failed")
    process_ids = tuple(
        int(value)
        for value in processes.stdout.splitlines()
        if value.strip().isdigit()
    )
    return {
        "label": _WORKER_LABEL,
        "launchctl_loaded": service.returncode == 0,
        "process_ids": list(process_ids),
    }


def _require_worker_unloaded(state: Mapping[str, object]) -> None:
    if state != {
        "label": _WORKER_LABEL,
        "launchctl_loaded": False,
        "process_ids": [],
    }:
        raise Issue790DispositionError(
            "persistent Graphiti worker is not proved unloaded"
        )


def _retry_event_snapshots(store: Path) -> list[dict[str, object]]:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,available_at,"
            "last_failure_code,provider_dispatched "
            "FROM unpublished_graphiti_revision_events "
            "WHERE ledger_seq IN (1932,1972) ORDER BY ledger_seq"
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "attempt_count": int(row[3]),
            "available_at": str(row[4]),
            "event_id": str(row[0]),
            "last_failure_code": str(row[5]),
            "ledger_seq": int(row[1]),
            "provider_dispatched": bool(row[6]),
            "state": str(row[2]),
        }
        for row in rows
    ]


def _require_retry_events_unchanged(
    store: Path,
    plan: Mapping[str, object],
) -> list[dict[str, object]]:
    expected = plan.get("retry_forbidden_events")
    retained = _retry_event_snapshots(store)
    if retained != expected:
        raise Issue790DispositionError(
            "issue #790 retry-forbidden event state differs"
        )
    return retained


def _require_retry_exclusions(
    repository: Issue790CanaryRepository,
    *,
    plan: Mapping[str, object],
) -> list[dict[str, object]]:
    retained = list(repository.retry_exclusions())
    expected_events = plan.get("retry_forbidden_events")
    if (
        not isinstance(expected_events, list)
        or len(retained) != len(expected_events) == 2
        or any(
            record.get("reason") != "ISSUE_790_RETRY_FORBIDDEN"
            or record.get("event_snapshot") != expected
            for record, expected in zip(retained, expected_events, strict=True)
        )
    ):
        raise Issue790DispositionError(
            "issue #790 durable retry exclusions differ"
        )
    bindings = {
        (
            str(record.get("approved_plan_digest")),
            str(record.get("disposition_digest")),
        )
        for record in retained
    }
    if len(bindings) != 1:
        raise Issue790DispositionError("issue #790 retry exclusion binding differs")
    approved_plan_digest, disposition_digest = next(iter(bindings))
    raw_sequence = plan.get("sequence")
    expected_plan_digest = str(plan["canonical_digest"])
    expected_disposition_digest = disposition_digest
    if raw_sequence is not None:
        sequence = _record(raw_sequence, field="sequence")
        expected_plan_digest = str(sequence.get("root_plan_digest"))
        root_consumption = repository.existing_consumption(
            approved_plan_digest=expected_plan_digest
        )
        if root_consumption is None:
            raise Issue790DispositionError(
                "issue #790 root canary consumption is absent"
            )
        expected_disposition_digest = str(
            root_consumption.get("disposition_digest")
        )
    if (
        approved_plan_digest != expected_plan_digest
        or disposition_digest != expected_disposition_digest
    ):
        raise Issue790DispositionError(
            "issue #790 retry exclusions do not bind the immutable root"
        )
    try:
        exclusion_contract = issue_790_approved_plan_contract(
            approved_plan_digest
        )
    except KeyError as exc:
        raise Issue790DispositionError(
            "issue #790 retry exclusion plan differs"
        ) from exc
    binding = repository.disposition_invocation(
        approved_plan_digest=approved_plan_digest,
        disposition_digest=disposition_digest,
    )
    if binding != exclusion_contract.invocation_id:
        raise Issue790DispositionError("issue #790 retry exclusion authority differs")
    return retained


def _require_sequence_predecessor(
    repository: Issue790CanaryRepository,
    *,
    plan: Mapping[str, object],
) -> dict[str, object] | None:
    raw_sequence = plan.get("sequence")
    if raw_sequence is None:
        return None
    sequence = _record(raw_sequence, field="sequence")
    predecessor = _record(sequence.get("predecessor"), field="predecessor")
    causal_report = _validated_causal_report(
        sequence.get("predecessor_causal_report")
    )
    diagnostic = (
        _record(causal_report.get("diagnostic"), field="diagnostic")
        if causal_report.get("schema_version") == ISSUE_790_CAUSAL_REPORT_SCHEMA
        else causal_report
    )
    transition = str(sequence.get("constraint_change"))
    reviewed_fix = (
        _validated_reviewed_fix(sequence.get("reviewed_fix"))
        if transition in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS
        else None
    )
    plan_digest = str(predecessor["plan_digest"])
    try:
        issue_790_approved_plan_contract(plan_digest)
    except KeyError as exc:
        raise Issue790DispositionError(
            "issue #790 predecessor plan differs"
        ) from exc
    consumption = repository.existing_consumption(
        approved_plan_digest=plan_digest
    )
    if (
        consumption is None
        or consumption.get("consumption_digest")
        != predecessor.get("consumption_digest")
        or consumption.get("approved_plan_digest") != plan_digest
        or consumption.get("event_id") != predecessor.get("event_id")
        or consumption.get("ledger_seq") != predecessor.get("ledger_seq")
    ):
        raise Issue790DispositionError("issue #790 predecessor consumption differs")
    outcome = repository.existing_outcome(
        consumption_digest=str(consumption["consumption_digest"])
    )
    if (
        outcome is None
        or outcome.get("outcome_digest") != predecessor.get("outcome_digest")
        or outcome.get("approved_plan_digest") != plan_digest
        or outcome.get("event_id") != predecessor.get("event_id")
        or outcome.get("ledger_seq") != predecessor.get("ledger_seq")
        or outcome.get("retry_authorised") is not False
    ):
        raise Issue790DispositionError("issue #790 predecessor outcome differs")
    if outcome.get("result_class") == "TRUTHFUL_PROVIDER_SUCCESS":
        raise Issue790DispositionError(
            "issue #790 predecessor already reached truthful success"
        )
    process_result = outcome.get("process_result")
    if (
        outcome.get("state_before_seal") == "TERMINAL"
        and outcome.get("attempt_count") == 1
        and outcome.get("provider_dispatched") is True
        and isinstance(process_result, dict)
        and process_result.get("state") == "TERMINAL"
    ):
        raise Issue790DispositionError(
            "issue #790 predecessor retained a terminal success boundary"
        )
    ordinal = int(sequence["sequence_ordinal"])
    if ordinal == 1:
        if (
            outcome.get("schema_version")
            != "newsroom.issue-790.canary-outcome.v2"
            or (
                process_result is not None
                and (
                    not isinstance(process_result, dict)
                    or process_result.get("state") == "TERMINAL"
                )
            )
        ):
            raise Issue790DispositionError(
                "issue #790 initial predecessor result differs"
            )
    elif transition == "CONTROLLER_TIMEOUT_INCREMENT":
        if (
            outcome.get("schema_version")
            != "newsroom.issue-790.canary-outcome.v3"
            or outcome.get("result_class") != "CONTROLLER_TIMEOUT_NON_SUCCESS"
            or outcome.get("causal_report") != causal_report
        ):
            raise Issue790DispositionError(
                "issue #790 predecessor lacks causal timeout evidence"
            )
    elif transition in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS:
        if (
            reviewed_fix is None
            or outcome.get("schema_version")
            != "newsroom.issue-790.canary-outcome.v3"
            or outcome.get("result_class") != "UNCLASSIFIED_NON_SUCCESS"
            or outcome.get("causal_report") is not None
            or causal_report.get("predecessor_outcome_digest")
            != outcome.get("outcome_digest")
            or causal_report.get("event_id") != outcome.get("event_id")
            or reviewed_fix.get("predecessor_outcome_digest")
            != outcome.get("outcome_digest")
        ):
            raise Issue790DispositionError(
                "issue #790 predecessor lacks reviewed non-timeout evidence"
            )
        if (
            transition == "COMPATIBILITY_FLOOR_ARCHITECTURE"
            and causal_report.get("causal_constraint")
            != "COMPATIBILITY_FLOOR_ARCHITECTURE"
        ):
            raise Issue790DispositionError(
                "issue #790 predecessor lacks compatibility-floor evidence"
            )
    else:
        raise Issue790DispositionError(
            "issue #790 predecessor transition differs"
        )

    if transition not in _ISSUE_790_REVIEWED_SUCCESSOR_TRANSITIONS:
        target = _record(plan.get("target"), field="target")
        try:
            terminal = repository.invocation_terminal(
                invocation_id=str(target["invocation_id"])
            )
        except Issue790CanaryIntegrityError as exc:
            raise Issue790DispositionError(str(exc)) from exc
        if terminal is None:
            raise Issue790DispositionError("issue #790 causal terminal is absent")
        if (
            terminal.get("terminal_digest") != target.get("terminal_digest")
            or terminal.get("outcome") != "TIMEOUT"
            or terminal.get("usage_status") != "UNREPORTED"
            or terminal.get("failure_class") != "MISSING_PROVIDER_TELEMETRY"
        ):
            raise Issue790DispositionError("issue #790 causal terminal differs")
        dispatched_at = _instant(terminal.get("dispatch_at"), field="dispatch_at")
        completed_at = _instant(terminal.get("completed_at"), field="completed_at")
        configured_timeout_ms = diagnostic.get("configured_timeout_ms")
        if not isinstance(configured_timeout_ms, int) or isinstance(
            configured_timeout_ms, bool
        ):
            raise Issue790DispositionError("issue #790 causal timeout differs")
        deadline_at = _instant(
            diagnostic.get("deadline_at"),
            field="causal timeout deadline_at",
        )
        process_started_at = deadline_at - timedelta(
            milliseconds=configured_timeout_ms
        )
        elapsed_ms = int(diagnostic["elapsed_ms"])
        clock_tolerance = timedelta(seconds=5)
        if (
            diagnostic.get("last_progress")
            not in {
                "DISPATCH_STARTED",  # retained by the approved initial record
                "NO_OUTPUT_OBSERVED",
                "OUTPUT_OBSERVED",
            }
            or diagnostic.get("provider_cause") != "UNOBSERVED"
            or process_started_at < dispatched_at - clock_tolerance
            or process_started_at > dispatched_at + clock_tolerance
            or deadline_at > completed_at + clock_tolerance
            or elapsed_ms
            > round(
                (
                    completed_at - process_started_at + clock_tolerance
                ).total_seconds()
                * 1_000
            )
        ):
            raise Issue790DispositionError(
                "issue #790 causal timing evidence differs"
            )
    return {
        "consumption": consumption,
        "outcome": outcome,
        "causal_report": causal_report,
        "reviewed_fix": reviewed_fix,
    }


def _running_code_evidence(
    *,
    root: Path,
    git: str,
    revision: str,
) -> list[dict[str, object]]:
    """Bind the executing modules to blobs in the reviewed repository tree."""

    retained: list[dict[str, object]] = []
    for module_name, relative_path in _RUNNING_CODE_MODULES:
        raw_path = _RUNNING_CODE_PATHS.get(module_name)
        if not isinstance(raw_path, str):
            raise Issue790DispositionError("operation module path is absent")
        actual = Path(raw_path).resolve(strict=True)
        expected = (root / relative_path).resolve(strict=True)
        if actual != expected:
            raise Issue790DispositionError(
                "executing operation code is outside exact main"
            )
        expected_blob = _run_checked(
            (git, "rev-parse", f"{revision}:{relative_path}"),
            cwd=root,
        )
        actual_blob = _run_checked(
            (git, "hash-object", "--no-filters", str(actual)),
            cwd=root,
        )
        if (
            expected_blob != actual_blob
            or re.fullmatch(r"[0-9a-f]{40}", expected_blob) is None
        ):
            raise Issue790DispositionError(
                "executing operation code differs from exact main"
            )
        retained.append(
            {
                "module": module_name,
                "repository_path": relative_path,
                "git_blob": expected_blob,
                "sha256": "sha256:" + hashlib.sha256(actual.read_bytes()).hexdigest(),
            }
        )
    return retained


def collect_issue_790_operational_evidence(
    *,
    repository_root: Path,
    store: Path,
    observed_at: datetime,
) -> dict[str, object]:
    """Collect exact-main, CI, worker, store and retry-exclusion evidence.

    Exact-head CI prefers Focus Gates on the deployed tip SHA. Dispatch
    Focus Gates on tip after merge rather than waiting for Full Health.
    """

    root = repository_root.expanduser().absolute()
    try:
        root_is_canonical = root.resolve(strict=True) == root and root.is_dir()
    except OSError as exc:
        raise Issue790DispositionError("repository root is absent") from exc
    if not root_is_canonical:
        raise Issue790DispositionError("repository root path is not canonical")
    store = _canonical_existing_file(store, field="source unpublished store")
    git = shutil.which("git")
    gh = shutil.which("gh")
    if git is None or gh is None:
        raise Issue790DispositionError("git or GitHub evidence tool is unavailable")
    branch = _run_checked((git, "symbolic-ref", "--short", "HEAD"), cwd=root)
    revision = _run_checked((git, "rev-parse", "HEAD^{commit}"), cwd=root)
    tree = _run_checked((git, "rev-parse", "HEAD^{tree}"), cwd=root)
    local_main = _run_checked(
        (git, "rev-parse", "refs/heads/main^{commit}"),
        cwd=root,
    )
    origin_main = _run_checked(
        (git, "rev-parse", "refs/remotes/origin/main^{commit}"),
        cwd=root,
    )
    status = _run_checked(
        (git, "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=root,
    )
    if (
        branch != "main"
        or status
        or revision != local_main
        or revision != origin_main
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or re.fullmatch(r"[0-9a-f]{40}", tree) is None
    ):
        raise Issue790DispositionError(
            "operation repository is not clean exact current main"
        )
    raw_main = _run_checked(
        (
            gh,
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            "repos/fol2/newsroom/git/ref/heads/main",
        ),
        cwd=root,
    )
    try:
        main_value = json.loads(raw_main)
    except json.JSONDecodeError as exc:
        raise Issue790DispositionError("live GitHub main evidence is malformed") from exc
    main_object = main_value.get("object") if isinstance(main_value, dict) else None
    github_main = main_object.get("sha") if isinstance(main_object, dict) else None
    if github_main != revision:
        raise Issue790DispositionError("operation revision is not live GitHub main")
    running_code = _running_code_evidence(
        root=root,
        git=git,
        revision=revision,
    )
    raw_checks = _run_checked(
        (
            gh,
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"repos/fol2/newsroom/commits/{revision}/check-runs",
        ),
        cwd=root,
    )
    try:
        checks_value = json.loads(raw_checks)
    except json.JSONDecodeError as exc:
        raise Issue790DispositionError("exact-main CI evidence is malformed") from exc
    if not isinstance(checks_value, dict) or not isinstance(
        checks_value.get("check_runs"), list
    ):
        raise Issue790DispositionError("exact-main CI evidence is malformed")
    successful_tests = [
        item
        for item in checks_value["check_runs"]
        if isinstance(item, dict)
        and item.get("name") in _ISSUE_790_ACCEPTED_CI_CHECK_NAMES
        and item.get("status") == "completed"
        and item.get("conclusion") == "success"
        and item.get("head_sha") == revision
        and isinstance(item.get("html_url"), str)
    ]
    if not successful_tests:
        raise Issue790DispositionError("exact-main CI test is not successful")
    successful_test = min(
        successful_tests,
        key=lambda item: (
            _ISSUE_790_CI_CHECK_PREFERENCE[str(item.get("name"))],
            -int(item.get("id", 0)),
        ),
    )
    connection = sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if quick_check is None or str(quick_check[0]) != "ok":
        raise Issue790DispositionError("live store integrity check failed")
    worker = _worker_state()
    _require_worker_unloaded(worker)
    retry_events = _retry_event_snapshots(store)
    if retry_events != list(_RETRY_FORBIDDEN_EVENTS):
        raise Issue790DispositionError(
            "issue #790 retry-forbidden event state differs"
        )
    evidence_without_digest: dict[str, object] = {
        "schema_version": ISSUE_790_OPERATIONAL_EVIDENCE_SCHEMA,
        "repository_root": str(root),
        "branch": branch,
        "revision": revision,
        "tree": tree,
        "local_main_revision": local_main,
        "origin_main_revision": origin_main,
        "github_main_revision": github_main,
        "worktree_clean": True,
        "running_code": running_code,
        "ci_test": {
            "name": successful_test["name"],
            "status": "completed",
            "conclusion": "success",
            "head_sha": revision,
            "url": successful_test["html_url"],
        },
        "worker": worker,
        "retry_forbidden_events": retry_events,
        "store": str(store),
        "store_quick_check": "ok",
        "observed_at": _utc_text(observed_at),
    }
    return {
        **evidence_without_digest,
        "evidence_digest": digest_canonical(evidence_without_digest),
    }


def _validate_operational_evidence(
    evidence: Mapping[str, object],
    *,
    store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
) -> dict[str, object]:
    retained = dict(evidence)
    digest = retained.pop("evidence_digest", None)
    if (
        retained.get("schema_version")
        != ISSUE_790_OPERATIONAL_EVIDENCE_SCHEMA
        or digest != digest_canonical(retained)
        or retained.get("branch") != "main"
        or retained.get("worktree_clean") is not True
        or retained.get("revision") != retained.get("local_main_revision")
        or retained.get("revision") != retained.get("origin_main_revision")
        or retained.get("revision") != retained.get("github_main_revision")
        or retained.get("store") != str(store.absolute())
        or retained.get("store_quick_check") != "ok"
        or retained.get("retry_forbidden_events")
        != plan.get("retry_forbidden_events")
    ):
        raise Issue790DispositionError("issue #790 operational evidence differs")
    revision = retained.get("revision")
    tree = retained.get("tree")
    ci_test = retained.get("ci_test")
    running_code = retained.get("running_code")
    expected_code_paths = [item[1] for item in _RUNNING_CODE_MODULES]
    if (
        not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or not isinstance(tree, str)
        or re.fullmatch(r"[0-9a-f]{40}", tree) is None
        or not isinstance(ci_test, dict)
        or ci_test.get("name") not in _ISSUE_790_ACCEPTED_CI_CHECK_NAMES
        or ci_test.get("status") != "completed"
        or ci_test.get("conclusion") != "success"
        or ci_test.get("head_sha") != revision
        or not isinstance(ci_test.get("url"), str)
        or not str(ci_test["url"]).startswith(
            "https://github.com/fol2/newsroom/actions/runs/"
        )
        or not isinstance(running_code, list)
        or [
            item.get("repository_path")
            for item in running_code
            if isinstance(item, dict)
        ]
        != expected_code_paths
        or any(
            not isinstance(item, dict)
            or item.get("module") != module_name
            or item.get("repository_path") != relative_path
            or not isinstance(item.get("git_blob"), str)
            or re.fullmatch(r"[0-9a-f]{40}", str(item["git_blob"])) is None
            or not isinstance(item.get("sha256"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(item["sha256"])) is None
            for item, (module_name, relative_path) in zip(
                running_code,
                _RUNNING_CODE_MODULES,
                strict=True,
            )
        )
    ):
        raise Issue790DispositionError("issue #790 exact-main evidence differs")
    worker = retained.get("worker")
    if not isinstance(worker, dict):
        raise Issue790DispositionError("issue #790 worker evidence differs")
    _require_worker_unloaded(worker)
    if _instant(retained.get("observed_at"), field="observed_at") > observed_at:
        raise Issue790DispositionError("operational evidence follows operation")
    bound = {**retained, "evidence_digest": digest}
    _require_step16_code_identity(plan, evidence=bound)
    return bound


def _sqlite_backup(source: Path, destination: Path) -> str:
    source = _canonical_existing_file(source, field="source unpublished store")
    destination = _canonical_new_file(destination, field="backup destination")
    assert_issue_790_paths_disjoint(source, destination)
    descriptor, temporary_text = mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_text)
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    try:
        os.fchmod(descriptor, 0o600)
        identity = os.fstat(descriptor)
        os.close(descriptor)
        descriptor = -1
        source_connection = sqlite3.connect(
            f"{source.absolute().as_uri()}?mode=ro",
            uri=True,
        )
        destination_connection = sqlite3.connect(temporary)
        retained_identity = temporary.lstat()
        if (
            stat.S_ISLNK(retained_identity.st_mode)
            or retained_identity.st_dev != identity.st_dev
            or retained_identity.st_ino != identity.st_ino
        ):
            raise Issue790DispositionError("backup temporary identity changed")
        source_connection.backup(destination_connection)
        destination_connection.commit()
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]) != "ok":
            raise Issue790DispositionError("SQLite backup integrity check failed")
        destination_connection.close()
        destination_connection = None
        source_connection.close()
        source_connection = None
        retained_identity = temporary.lstat()
        if (
            stat.S_ISLNK(retained_identity.st_mode)
            or retained_identity.st_dev != identity.st_dev
            or retained_identity.st_ino != identity.st_ino
        ):
            raise Issue790DispositionError("backup temporary identity changed")
        descriptor = os.open(
            temporary,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = -1
        _publish_file_no_replace(temporary, destination)
        return "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest()
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if descriptor >= 0:
            os.close(descriptor)
        _unlink_temporary(temporary)


def _authority_digest(plan: Mapping[str, object]) -> str:
    approval = _record(plan["approval"], field="approval")
    target = _record(plan["target"], field="target")
    return digest_canonical(
        {
            "schema_version": _AUTHORITY_SCHEMA,
            "approved_plan_digest": plan["canonical_digest"],
            "approved_by": approval["approved_by"],
            "approval_reference": approval["approval_reference"],
            "approved_at": approval["approved_at"],
            "invocation_id": target["invocation_id"],
            "terminal_digest": target["terminal_digest"],
            "allocation_digest": target["allocation_digest"],
            "scope": approval["scope"],
        }
    )


def _existing_target_disposition(
    store: Path,
    target: Mapping[str, object],
) -> dict[str, object] | None:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT disposition_digest,record_json "
            "FROM model_usage_conservative_dispositions "
            "WHERE invocation_id=?",
            (target["invocation_id"],),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    disposition = json.loads(str(row[1]))
    if (
        str(row[0]) != disposition.get("disposition_digest")
        or disposition.get("terminal_digest") != target.get("terminal_digest")
        or disposition.get("allocation_digest") != target.get("allocation_digest")
        or disposition.get("exact_usage_remains_unknown") is not True
        or disposition.get("unknown_spend_released") is not False
    ):
        raise Issue790DispositionError(
            "issue #790 retained disposition authority differs"
        )
    components = disposition.get("components")
    if not isinstance(components, dict) or components.get("total_tokens") != target.get(
        "expected_conservative_total_tokens"
    ):
        raise Issue790DispositionError(
            "issue #790 retained conservative total differs"
        )
    return disposition


def _assert_exact_target(store: Path, plan: Mapping[str, object]) -> None:
    target = _record(plan["target"], field="target")
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT a.canonical_digest,a.policy_digest,a.route,a.provider,"
            "a.workload_class,t.terminal_digest,t.usage_status,t.failure_class,"
            "json_extract(p.record_json,'$.max_total_tokens'),"
            "json_extract(p.record_json,'$.qualified') "
            "FROM model_invocation_allocations a "
            "JOIN model_invocation_terminals t USING(invocation_id) "
            "JOIN model_invocation_policies p "
            "ON p.canonical_digest=a.policy_digest WHERE a.invocation_id=?",
            (target["invocation_id"],),
        ).fetchone()
        expected = (
            target["allocation_digest"],
            target["policy_digest"],
            target["route"],
            target["provider"],
            target["workload_class"],
            target["terminal_digest"],
            target["terminal_usage_status"],
            target["terminal_failure_class"],
            target["expected_conservative_total_tokens"],
            1,
        )
        if row is None or tuple(row) != expected:
            raise Issue790DispositionError("retained issue #790 target differs")
        if connection.execute(
            "SELECT COUNT(*) FROM model_transport_observations "
            "WHERE invocation_id=? AND state='DISPATCH_STARTED'",
            (target["invocation_id"],),
        ).fetchone()[0] != 1:
            raise Issue790DispositionError("issue #790 dispatch evidence differs")
        reconciliation_count = connection.execute(
            "SELECT COUNT(*) FROM model_usage_reconciliations "
            "WHERE invocation_id=?",
            (target["invocation_id"],),
        ).fetchone()[0]
        telemetry_count = connection.execute(
            "SELECT COUNT(*) FROM model_provider_telemetry WHERE invocation_id=?",
            (target["invocation_id"],),
        ).fetchone()[0]
        if reconciliation_count != 0 or telemetry_count != 0:
            raise Issue790DispositionError(
                "issue #790 exact provider telemetry already exists"
            )
    finally:
        connection.close()


def _execute_issue_790_plan(
    *,
    store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    mode: str,
    backup_path: Path,
    backup_digest: str,
    source_store: Path | None = None,
    repository_root: Path | None = None,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    """Apply the same exact transition to a dry-run copy or the live store."""

    retained_plan = _require_approved_plan(
        plan,
        store=source_store if source_store is not None else store,
        github_api=github_api,
    )
    approval = _record(retained_plan["approval"], field="approval")
    target = _record(retained_plan["target"], field="target")
    if mode not in {"dry-run", "apply"}:
        raise Issue790DispositionError("issue #790 operation mode is invalid")
    if observed_at < _instant(approval["approved_at"], field="approved_at"):
        raise Issue790DispositionError("issue #790 operation precedes approval")
    retained_operational_evidence: dict[str, object] | None = None
    retry_events_before: list[dict[str, object]] | None = None
    if mode == "apply":
        if repository_root is None:
            raise Issue790DispositionError(
                "issue #790 live operation repository is absent"
            )
        operational_evidence = collect_issue_790_operational_evidence(
            repository_root=repository_root,
            store=store,
            observed_at=observed_at,
        )
        retained_operational_evidence = _validate_operational_evidence(
            operational_evidence,
            store=store,
            plan=retained_plan,
            observed_at=observed_at,
        )
        _require_worker_unloaded(_worker_state())
        retry_events_before = _require_retry_events_unchanged(
            store,
            retained_plan,
        )
        retained_backup = _canonical_existing_file(
            backup_path,
            field="pre-operation snapshot",
        )
        assert_issue_790_paths_disjoint(store, retained_backup)
        if (
            "sha256:" + hashlib.sha256(retained_backup.read_bytes()).hexdigest()
            != backup_digest
            or _sqlite_quick_check(
                retained_backup,
                field="pre-operation snapshot",
            )
            != "ok"
        ):
            raise Issue790DispositionError(
                "issue #790 pre-operation snapshot evidence differs"
            )

    _assert_exact_target(store, retained_plan)
    service = ModelUsageService(str(store))
    canary_repository = Issue790CanaryRepository(str(store))
    predecessor = _require_sequence_predecessor(
        canary_repository,
        plan=retained_plan,
    )
    authority_digest = _authority_digest(retained_plan)
    try:
        initial_route_state = service.route_state(str(target["route"]))
        if initial_route_state.get("state") == "OPEN":
            # Root apply binds the original open reason. Successor steps may
            # release whatever OPEN reason the prior bounded canary left.
            if (
                predecessor is None
                and initial_route_state.get("reason") != target["route_open_reason"]
            ):
                raise Issue790DispositionError(
                    "issue #790 current route failure differs"
                )
        elif initial_route_state.get("state") == "CLOSED":
            connection = sqlite3.connect(
                f"{store.absolute().as_uri()}?mode=ro", uri=True
            )
            try:
                existing_disposition = connection.execute(
                    "SELECT 1 FROM model_usage_conservative_dispositions "
                    "WHERE invocation_id=?",
                    (target["invocation_id"],),
                ).fetchone()
            finally:
                connection.close()
            if existing_disposition is None:
                raise Issue790DispositionError(
                    "issue #790 route closed without its disposition"
                )
        else:
            raise Issue790DispositionError("issue #790 route state is invalid")
        sequence = retained_plan.get("sequence")
        if (
            retained_operational_evidence is not None
            and isinstance(sequence, dict)
            and sequence.get("sequence_ordinal") == 16
        ):
            _require_step16_runtime_semantics(
                retained_plan,
                evidence=retained_operational_evidence,
                route_state=initial_route_state,
                circuit_state=_circuit_state(store),
                observed_at=observed_at,
            )
        disposition = (
            _existing_target_disposition(store, target)
            if predecessor is not None
            else None
        )
        if disposition is None:
            disposition = service.disposition_unreported_subscription_usage(
                invocation_id=str(target["invocation_id"]),
                expected_terminal_digest=str(target["terminal_digest"]),
                expected_allocation_digest=str(target["allocation_digest"]),
                approved_by=str(approval["approved_by"]),
                approval_reference=str(approval["approval_reference"]),
                approved_at=_instant(approval["approved_at"], field="approved_at"),
                approved_plan_digest=str(retained_plan["canonical_digest"]),
                authority_digest=authority_digest,
                observed_at=observed_at,
            )
        components = _record(disposition.get("components"), field="components")
        if components.get("total_tokens") != target[
            "expected_conservative_total_tokens"
        ]:
            raise Issue790DispositionError(
                "issue #790 retained conservative total differs"
            )
        if not canary_repository.retry_exclusions():
            if predecessor is not None:
                raise Issue790DispositionError(
                    "issue #790 predecessor retry exclusions are absent"
                )
            canary_repository.retain_retry_exclusions(
                approved_plan_digest=str(retained_plan["canonical_digest"]),
                disposition_digest=str(disposition["disposition_digest"]),
                events=tuple(
                    _record(item, field="retry-forbidden event")
                    for item in retained_plan["retry_forbidden_events"]  # type: ignore[union-attr]
                ),
                excluded_at=observed_at,
            )
        retry_exclusions = _require_retry_exclusions(
            canary_repository,
            plan=retained_plan,
        )
        route_state_before_release = service.route_state(str(target["route"]))
        expected_closed_reason = (
            f"{_RELEASE_KIND}:{disposition['disposition_digest']}"
        )
        if route_state_before_release.get("state") == "OPEN":
            bound_failure_reason = (
                str(route_state_before_release["reason"])
                if predecessor is not None
                else str(target["route_open_reason"])
            )
            if (
                predecessor is None
                and route_state_before_release.get("reason") != bound_failure_reason
            ):
                raise Issue790DispositionError(
                    "issue #790 current route failure differs"
                )
            service.release_route_circuit(
                route=str(target["route"]),
                release_kind=_RELEASE_KIND,
                bound_failure_reason=bound_failure_reason,
                evidence_digest=str(disposition["disposition_digest"]),
                recorded_at=observed_at,
            )
        elif (
            route_state_before_release.get("state") != "CLOSED"
            or route_state_before_release.get("reason") != expected_closed_reason
        ):
            raise Issue790DispositionError(
                "issue #790 route is neither releasable nor an exact replay"
            )
        route_state_after_release = service.route_state(str(target["route"]))
        if (
            route_state_after_release.get("state") != "CLOSED"
            or route_state_after_release.get("reason") != expected_closed_reason
        ):
            raise Issue790DispositionError("issue #790 route release did not retain")
        if mode == "apply":
            _require_worker_unloaded(_worker_state())
            retry_events_after = _require_retry_events_unchanged(
                store,
                retained_plan,
            )
        else:
            retry_events_after = None
    except (
        Issue790CanaryIntegrityError,
        ModelUsageIntegrityError,
        ModelUsageAdmissionError,
    ) as exc:
        raise Issue790DispositionError(str(exc)) from exc

    operation_source = store if source_store is None else source_store
    receipt_without_digest: dict[str, object] = {
        "schema_version": (
            ISSUE_790_RECEIPT_SCHEMA
            if predecessor is None
            else ISSUE_790_ITERATIVE_RECEIPT_SCHEMA
        ),
        "mode": mode,
        "plan_digest": retained_plan["canonical_digest"],
        "source_store": str(operation_source.absolute()),
        "operation_store": str(store.absolute()),
        "source_mutated": mode == "apply",
        "pre_operation_snapshot_path": str(backup_path.absolute()),
        "pre_operation_snapshot_digest": backup_digest,
        "pre_operation_snapshot_retained": mode == "apply",
        "observed_at": _utc_text(observed_at),
        "authority_digest": authority_digest,
        "disposition_digest": disposition["disposition_digest"],
        "invocation_id": target["invocation_id"],
        "conservative_total_tokens": target[
            "expected_conservative_total_tokens"
        ],
        "exact_usage_remains_unknown": True,
        "provider_dispatch_preserved": True,
        "unknown_spend_released": False,
        "operational_evidence": retained_operational_evidence,
        "retry_forbidden_events_before": retry_events_before,
        "retry_forbidden_events_after": retry_events_after,
        "retry_exclusions": list(retry_exclusions),
        "route_state_before_release": route_state_before_release,
        "route_state_after_release": route_state_after_release,
        "retry_performed": False,
        "canary_performed": False,
        "publication_performed": False,
        "public_dispatch_performed": False,
        "non_effects": list(_NON_EFFECTS),
    }
    if predecessor is not None:
        receipt_without_digest["predecessor"] = predecessor
    receipt_digest = digest_canonical(receipt_without_digest)
    return {**receipt_without_digest, "receipt_digest": receipt_digest}


def dry_run_issue_790_plan(
    *,
    source_store: Path,
    scratch_store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    assert_issue_790_paths_disjoint(source_store, scratch_store)
    retained_plan = _require_approved_plan(
        plan,
        store=source_store,
        github_api=github_api,
    )
    backup_digest = _sqlite_backup(source_store, scratch_store)
    receipt = _execute_issue_790_plan(
        store=scratch_store,
        plan=retained_plan,
        observed_at=observed_at,
        mode="dry-run",
        backup_path=scratch_store,
        backup_digest=backup_digest,
        source_store=source_store,
        github_api=github_api,
    )
    return receipt


def apply_issue_790_plan(
    *,
    store: Path,
    backup_path: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    repository_root: Path,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    assert_issue_790_paths_disjoint(store, backup_path)
    retained_plan = _require_approved_plan(
        plan,
        store=store,
        github_api=github_api,
    )
    pre_backup_evidence = collect_issue_790_operational_evidence(
        repository_root=repository_root,
        store=store,
        observed_at=observed_at,
    )
    backup_digest = _sqlite_backup(store, backup_path)
    receipt = _execute_issue_790_plan(
        store=store,
        plan=retained_plan,
        observed_at=observed_at,
        mode="apply",
        backup_path=backup_path,
        backup_digest=backup_digest,
        repository_root=repository_root,
        github_api=github_api,
    )
    retained_evidence = _record(
        receipt["operational_evidence"],
        field="operational evidence",
    )
    if retained_evidence.get("evidence_digest") != pre_backup_evidence.get(
        "evidence_digest"
    ):
        raise Issue790DispositionError(
            "issue #790 operational evidence changed across backup"
        )
    return receipt


def _sqlite_quick_check(path: Path, *, field: str) -> str:
    path = _canonical_existing_file(path, field=field)
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if result is None or str(result[0]) != "ok":
        raise Issue790DispositionError(f"{field} integrity check failed")
    return "ok"


def _event_snapshot(
    store: Path,
    *,
    event_id: str,
    ledger_seq: int,
) -> dict[str, object]:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT event_id,ledger_seq,source_id,item_key,revision_digest,state,"
            "attempt_count,available_at,claim_owner,claim_expires_at,"
            "last_failure_code,provider_dispatched,terminal_at,proposal_count,"
            "unit_count,manifest_digest FROM unpublished_graphiti_revision_events "
            "WHERE event_id=? AND ledger_seq=?",
            (event_id, ledger_seq),
        ).fetchone()
        state_rows = connection.execute(
            "SELECT state,COUNT(*) FROM unpublished_graphiti_revision_events "
            "GROUP BY state ORDER BY state"
        ).fetchall()
        try:
            circuit = connection.execute(
                "SELECT state,opened_at,available_at,failure_code "
                "FROM unpublished_graphiti_event_circuit WHERE singleton=1"
            ).fetchone()
        except sqlite3.Error:
            circuit = None
    finally:
        connection.close()
    if row is None:
        raise Issue790DispositionError("bounded canary event identity is absent")
    return {
        "event": {
            "event_id": str(row[0]),
            "ledger_seq": int(row[1]),
            "source_id": str(row[2]),
            "item_key": str(row[3]),
            "revision_digest": str(row[4]),
            "state": str(row[5]),
            "attempt_count": int(row[6]),
            "available_at": str(row[7]),
            "claim_owner": None if row[8] is None else str(row[8]),
            "claim_expires_at": None if row[9] is None else str(row[9]),
            "last_failure_code": None if row[10] is None else str(row[10]),
            "provider_dispatched": bool(row[11]),
            "terminal_at": None if row[12] is None else str(row[12]),
            "proposal_count": None if row[13] is None else int(row[13]),
            "unit_count": int(row[14]),
            "manifest_digest": str(row[15]),
        },
        "state_counts": {str(item[0]): int(item[1]) for item in state_rows},
        "circuit": (
            None
            if circuit is None
            else {
                "state": str(circuit[0]),
                "opened_at": None if circuit[1] is None else str(circuit[1]),
                "available_at": None if circuit[2] is None else str(circuit[2]),
                "failure_code": None if circuit[3] is None else str(circuit[3]),
            }
        ),
    }


def _issue_790_canary_usage_evidence(
    store: Path,
    *,
    event_id: str,
) -> dict[str, object]:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT a.invocation_id,a.record_json,t.record_json "
            "FROM model_work_envelopes e "
            "JOIN model_invocation_allocations a USING(envelope_id) "
            "LEFT JOIN model_invocation_terminals t USING(invocation_id) "
            "WHERE e.cycle_id=? ORDER BY a.allocated_at,a.leaf_ordinal",
            (event_id,),
        ).fetchall()
        dispatch_rows = connection.execute(
            "SELECT x.invocation_id,x.record_json FROM model_transport_observations x "
            "JOIN model_invocation_allocations a USING(invocation_id) "
            "JOIN model_work_envelopes e USING(envelope_id) "
            "WHERE e.cycle_id=? AND x.state='DISPATCH_STARTED' "
            "ORDER BY x.observed_at",
            (event_id,),
        ).fetchall()
        telemetry_rows = connection.execute(
            "SELECT p.invocation_id,p.record_json FROM model_provider_telemetry p "
            "JOIN model_invocation_allocations a USING(invocation_id) "
            "JOIN model_work_envelopes e USING(envelope_id) "
            "WHERE e.cycle_id=? ORDER BY p.rowid",
            (event_id,),
        ).fetchall()
        reconciliation_rows = connection.execute(
            "SELECT r.invocation_id,r.record_json FROM model_usage_reconciliations r "
            "JOIN model_invocation_allocations a USING(invocation_id) "
            "JOIN model_work_envelopes e USING(envelope_id) "
            "WHERE e.cycle_id=? ORDER BY r.rowid",
            (event_id,),
        ).fetchall()
    finally:
        connection.close()

    def retained_json(raw: object, *, field: str) -> dict[str, object]:
        try:
            value = json.loads(str(raw))
        except json.JSONDecodeError as exc:
            raise Issue790DispositionError(f"{field} evidence is malformed") from exc
        if not isinstance(value, dict):
            raise Issue790DispositionError(f"{field} evidence is malformed")
        return value

    dispatch_ids = {str(row[0]) for row in dispatch_rows}
    leaves: list[dict[str, object]] = []
    provider_backed_terminal_count = 0
    truthful_nonzero_usage_count = 0
    unresolved_terminal_count = 0
    unterminated_leaf_count = 0
    primary_chat_leaf_count = 0
    qualified_primary_identity_count = 0
    truthful_primary_usage_count = 0
    fallback_chat_leaf_count = 0
    for invocation_id, allocation_json, terminal_json in rows:
        allocation = retained_json(allocation_json, field="canary allocation")
        terminal = (
            None
            if terminal_json is None
            else retained_json(terminal_json, field="canary terminal")
        )
        provider_backed = str(invocation_id) in dispatch_ids
        if provider_backed and terminal is not None:
            provider_backed_terminal_count += 1
        if terminal is None:
            unterminated_leaf_count += 1
        components = None if terminal is None else terminal.get("components")
        total_tokens = (
            components.get("total_tokens") if isinstance(components, dict) else None
        )
        usage_status = None if terminal is None else terminal.get("usage_status")
        workload_class = allocation.get("workload_class")
        primary_chat = workload_class == "GRAPHITI_CHAT_PRIMARY"
        qualified_primary_identity = bool(
            primary_chat
            and allocation.get("provider") == "cursor-agent-cli"
            and allocation.get("route") == "GRAPHITI_CHAT_PRIMARY"
            and (
                allocation.get("model") == "composer-2.5"
                or cursor_transport_module.composer_model_meets_floor(
                    str(allocation.get("model") or "")
                )
            )
        )
        if primary_chat:
            primary_chat_leaf_count += 1
        if qualified_primary_identity:
            qualified_primary_identity_count += 1
        if workload_class == "GRAPHITI_CHAT_FALLBACK":
            fallback_chat_leaf_count += 1
        if (
            provider_backed
            and usage_status in {"REPORTED", "ESTIMATED"}
            and isinstance(total_tokens, int)
            and not isinstance(total_tokens, bool)
            and total_tokens > 0
        ):
            truthful_nonzero_usage_count += 1
            if qualified_primary_identity:
                truthful_primary_usage_count += 1
        if usage_status in {"UNREPORTED", "AMBIGUOUS", "INVALID"}:
            unresolved_terminal_count += 1
        leaves.append(
            {
                "invocation_id": str(invocation_id),
                "allocation": allocation,
                "terminal": terminal,
                "committed_provider_dispatch": provider_backed,
            }
        )
    return {
        "leaves": leaves,
        "committed_dispatch_observations": [
            retained_json(row[1], field="canary dispatch") for row in dispatch_rows
        ],
        "provider_telemetry": [
            retained_json(row[1], field="canary telemetry") for row in telemetry_rows
        ],
        "reconciliations": [
            retained_json(row[1], field="canary reconciliation")
            for row in reconciliation_rows
        ],
        "leaf_count": len(leaves),
        "provider_backed_terminal_count": provider_backed_terminal_count,
        "truthful_nonzero_usage_count": truthful_nonzero_usage_count,
        "primary_chat_leaf_count": primary_chat_leaf_count,
        "qualified_primary_identity_count": qualified_primary_identity_count,
        "truthful_primary_usage_count": truthful_primary_usage_count,
        "fallback_chat_leaf_count": fallback_chat_leaf_count,
        "unresolved_terminal_count": unresolved_terminal_count,
        "unterminated_leaf_count": unterminated_leaf_count,
    }


def _require_issue_790_canary_route(
    *,
    route_state: Mapping[str, object],
    expected_closed_reason: str,
    recovery_usage: Mapping[str, object] | None,
) -> None:
    """Require a fresh release or the exact consumed event's retained open route."""

    if (
        route_state.get("state") == "CLOSED"
        and route_state.get("reason") == expected_closed_reason
    ):
        return
    if recovery_usage is None or route_state.get("state") != "OPEN":
        raise Issue790DispositionError(
            "bounded canary route release authority differs"
        )
    invocation_id = route_state.get("invocation_id")
    leaves = recovery_usage.get("leaves")
    if not isinstance(invocation_id, str) or not isinstance(leaves, list):
        raise Issue790DispositionError(
            "interrupted bounded canary route differs"
        )
    matching = [
        leaf
        for leaf in leaves
        if isinstance(leaf, dict)
        and leaf.get("invocation_id") == invocation_id
        and isinstance(leaf.get("terminal"), dict)
        and leaf["terminal"].get("usage_status")
        in {"UNREPORTED", "AMBIGUOUS", "INVALID"}
    ]
    if len(matching) != 1:
        raise Issue790DispositionError(
            "interrupted bounded canary route differs"
        )


def _issue_790_controller_timeout_report(
    store: Path,
    *,
    event_id: str,
    configured_timeout_ms: int,
) -> dict[str, object] | None:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT r.receipt_digest,r.receipt_json "
            "FROM unpublished_graphiti_attempt_receipts r "
            "JOIN model_work_envelopes e "
            "ON json_extract(e.record_json,'$.ingest_id')=r.ingest_id "
            "WHERE e.cycle_id=? ORDER BY r.attempt_number,r.rowid",
            (event_id,),
        ).fetchall()
    finally:
        connection.close()
    candidates: dict[
        tuple[str, str], tuple[dict[str, object], str]
    ] = {}
    for row in rows:
        try:
            receipt = json.loads(str(row[1]))
        except json.JSONDecodeError as exc:
            raise Issue790DispositionError(
                "bounded canary attempt receipt is malformed"
            ) from exc
        if not isinstance(receipt, dict):
            raise Issue790DispositionError(
                "bounded canary attempt receipt is malformed"
            )
        receipt_digest = str(row[0])
        unsigned_receipt = dict(receipt)
        supplied_receipt_digest = unsigned_receipt.pop("receipt_digest", None)
        if (
            supplied_receipt_digest != receipt_digest
            or digest_canonical(unsigned_receipt) != receipt_digest
        ):
            raise Issue790DispositionError(
                "bounded canary attempt receipt digest differs"
            )
        raw_diagnostics: list[object] = []
        attempt_diagnostics = receipt.get("timeout_diagnostics")
        if isinstance(attempt_diagnostics, list):
            raw_diagnostics.extend(attempt_diagnostics)
        invocations = receipt.get("chat_invocations")
        if isinstance(invocations, list):
            raw_diagnostics.extend(
                invocation.get("transport_diagnostic")
                for invocation in invocations
                if isinstance(invocation, dict)
                and invocation.get("provider") == "cursor-agent-cli"
                and invocation.get("transport_diagnostic") is not None
            )
        if not raw_diagnostics:
            continue
        try:
            diagnostics = validated_timeout_diagnostics(raw_diagnostics)
        except ValueError as exc:
            raise Issue790DispositionError(
                "bounded canary timeout diagnostics differ"
            ) from exc
        for diagnostic in diagnostics:
            if (
                diagnostic.get("boundary") == "CONTROLLER_DEADLINE"
                and diagnostic.get("phase") == "PRIMARY_TRANSPORT"
                and diagnostic.get("cause") == "CONFIGURED_TIMEOUT_EXPIRED"
                and diagnostic.get("configured_timeout_ms")
                == configured_timeout_ms
            ):
                key = (digest_canonical(diagnostic), receipt_digest)
                candidates[key] = (diagnostic, receipt_digest)
    if len(candidates) != 1:
        return None
    diagnostic, receipt_digest = next(iter(candidates.values()))
    report_without_digest: dict[str, object] = {
        "schema_version": ISSUE_790_CAUSAL_REPORT_SCHEMA,
        "classification": "CONTROLLER_TIMEOUT",
        "causal_constraint": "CONTROLLER_TIMEOUT_MS",
        "local_cause": diagnostic["cause"],
        "provider_cause": diagnostic["provider_cause"],
        "diagnostic_reference": (
            "retained:unpublished_graphiti_attempt_receipts:" + receipt_digest
        ),
        "diagnostic": diagnostic,
    }
    return {
        **report_without_digest,
        "report_digest": digest_canonical(report_without_digest),
    }


def _issue_790_iterative_result(
    *,
    store: Path,
    plan: Mapping[str, object],
    event_id: str,
    process_result: Mapping[str, object] | None,
    exception_present: bool,
) -> dict[str, object]:
    """Classify foreground and zero-I/O recovery from the same durable facts."""

    raw_sequence = plan.get("sequence")
    if raw_sequence is None:
        return {}
    usage = _issue_790_canary_usage_evidence(store, event_id=event_id)
    truthful_success = bool(
        not exception_present
        and process_result is not None
        and process_result.get("state") == "TERMINAL"
        and process_result.get("attempt_count") == 1
        and usage["primary_chat_leaf_count"] >= 1
        and usage["qualified_primary_identity_count"]
        == usage["primary_chat_leaf_count"]
        and usage["truthful_primary_usage_count"]
        == usage["primary_chat_leaf_count"]
        and usage["fallback_chat_leaf_count"] == 0
        and usage["unresolved_terminal_count"] == 0
        and usage["unterminated_leaf_count"] == 0
    )
    if truthful_success:
        return {
            "result_class": "TRUTHFUL_PROVIDER_SUCCESS",
            "causal_report": None,
        }
    sequence = _record(raw_sequence, field="sequence")
    causal_report = _issue_790_controller_timeout_report(
        store,
        event_id=event_id,
        configured_timeout_ms=int(sequence["controller_timeout_ms"]),
    )
    return {
        "result_class": (
            "CONTROLLER_TIMEOUT_NON_SUCCESS"
            if causal_report is not None
            else "UNCLASSIFIED_NON_SUCCESS"
        ),
        "causal_report": causal_report,
    }


def _consume_issue_790_event(
    *,
    proving_store: Path,
    unpublished_store: Path,
    owner_id: str,
    event_id: str,
    canary_consumption_digest: str,
    model_usage: ModelUsageService,
) -> GraphitiProcessResult | None:
    from newsroom.control_plane.cycle import consume_next_graphiti_event
    from newsroom.control_plane.graphiti import EvaluationGraphitiRunner

    return consume_next_graphiti_event(
        proving_store=str(proving_store),
        unpublished_store=str(unpublished_store),
        graphiti=EvaluationGraphitiRunner(fallback_permitted=False),
        owner_id=owner_id,
        model_usage=model_usage,
        event_id=event_id,
        require_fresh=True,
        recover_model_usage=False,
        canary_consumption_digest=canary_consumption_digest,
    )


def _qualify_issue_790_event(
    *,
    proving_store: Path,
    unpublished_store: Path,
    event_id: str,
    ledger_seq: int,
    observed_at: datetime,
    plan: Mapping[str, object],
) -> dict[str, object]:
    from newsroom.control_plane.cycle import qualify_fresh_graphiti_event

    evidence = qualify_fresh_graphiti_event(
        proving_store=str(proving_store),
        unpublished_store=str(unpublished_store),
        event_id=event_id,
        ledger_seq=ledger_seq,
        clock=lambda: observed_at,
    )
    if plan.get("sequence") is None:
        return evidence
    retained = dict(evidence)
    retained.pop("evidence_digest", None)
    sequence = _record(plan.get("sequence"), field="sequence")
    retained.update(
        {
            "schema_version": ISSUE_790_ITERATIVE_PREFLIGHT_SCHEMA,
            "approved_plan_digest": plan["canonical_digest"],
            "fallback_mode": _FALLBACK_MODE,
            "fixed_constraints_digest": sequence["fixed_constraints_digest"],
        }
    )
    return {**retained, "evidence_digest": digest_canonical(retained)}


def run_issue_790_canary(
    *,
    store: Path,
    proving_store: Path,
    backup_path: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    repository_root: Path,
    event_id: str,
    ledger_seq: int,
    disposition_digest: str,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    """Consume and seal exactly one fresh event under the approved #790 authority."""

    retained_plan = _require_approved_plan(
        plan,
        store=store,
        github_api=github_api,
    )
    store = _canonical_existing_file(store, field="source unpublished store")
    proving_store = _canonical_existing_file(
        proving_store,
        field="source proving store",
    )
    backup_path = _canonical_new_file(backup_path, field="canary backup destination")
    assert_issue_790_paths_disjoint(store, proving_store, backup_path)
    if ledger_seq in {1932, 1972}:
        raise Issue790DispositionError("bounded canary targeted a retained failure")
    if not event_id.startswith("sha256:"):
        raise Issue790DispositionError("bounded canary event identity is invalid")
    _sqlite_quick_check(proving_store, field="source proving store")
    operational_evidence = collect_issue_790_operational_evidence(
        repository_root=repository_root,
        store=store,
        observed_at=observed_at,
    )
    _validate_operational_evidence(
        operational_evidence,
        store=store,
        plan=retained_plan,
        observed_at=observed_at,
    )
    _assert_exact_target(store, retained_plan)
    target = _record(retained_plan["target"], field="target")
    try:
        canary_repository = Issue790CanaryRepository.open_existing(str(store))
    except Issue790CanaryIntegrityError as exc:
        raise Issue790DispositionError(str(exc)) from exc
    predecessor = _require_sequence_predecessor(
        canary_repository,
        plan=retained_plan,
    )
    retry_exclusions = _require_retry_exclusions(
        canary_repository,
        plan=retained_plan,
    )
    event_before = _event_snapshot(
        store,
        event_id=event_id,
        ledger_seq=ledger_seq,
    )
    event_before_record = _record(event_before["event"], field="canary event")
    prior_consumption = canary_repository.existing_consumption(
        approved_plan_digest=str(retained_plan["canonical_digest"]),
    )
    resuming_zero_io_finalisation = prior_consumption is not None
    if prior_consumption is None:
        if (
            event_before_record.get("state") != "QUEUED"
            or event_before_record.get("attempt_count") != 0
        ):
            raise Issue790DispositionError("bounded canary event is not untouched")
        try:
            preflight_evidence = _qualify_issue_790_event(
                proving_store=proving_store,
                unpublished_store=store,
                event_id=event_id,
                ledger_seq=ledger_seq,
                observed_at=observed_at,
                plan=retained_plan,
            )
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
            raise Issue790DispositionError(
                f"bounded canary provider-free preflight failed: {type(exc).__name__}: {exc}"
            ) from exc
    else:
        if (
            prior_consumption.get("event_id") != event_id
            or prior_consumption.get("ledger_seq") != ledger_seq
            or prior_consumption.get("disposition_digest") != disposition_digest
        ):
            raise Issue790DispositionError(
                "interrupted bounded canary authority differs"
            )
        preflight_evidence = _record(
            prior_consumption.get("preflight_evidence"),
            field="bounded canary preflight",
        )
    retry_before = _require_retry_events_unchanged(store, retained_plan)
    worker_before = _worker_state()
    _require_worker_unloaded(worker_before)
    state_counts_before = _record(
        event_before["state_counts"],
        field="canary state counts",
    )
    dead_letters_before = int(state_counts_before.get("DEAD_LETTER", 0))
    backup_digest = _sqlite_backup(store, backup_path)
    operational_evidence_after_backup = collect_issue_790_operational_evidence(
        repository_root=repository_root,
        store=store,
        observed_at=observed_at,
    )
    if operational_evidence_after_backup.get(
        "evidence_digest"
    ) != operational_evidence.get("evidence_digest"):
        raise Issue790DispositionError(
            "bounded canary operational evidence changed across backup"
        )
    operational_evidence = operational_evidence_after_backup
    service = ModelUsageService(str(store))
    route_before = service.route_state(str(target["route"]))
    expected_route_reason = f"{_RELEASE_KIND}:{disposition_digest}"
    recovery_usage = (
        None
        if prior_consumption is None
        else _issue_790_canary_usage_evidence(store, event_id=event_id)
    )
    _require_issue_790_canary_route(
        route_state=route_before,
        expected_closed_reason=expected_route_reason,
        recovery_usage=recovery_usage,
    )
    recovering = prior_consumption is not None
    _require_step16_runtime_semantics(
        retained_plan,
        evidence=operational_evidence,
        route_state=route_before,
        circuit_state=(
            None
            if event_before.get("circuit") is None
            else _record(event_before.get("circuit"), field="canary circuit")
        ),
        observed_at=observed_at,
        canary_event=None if recovering else event_before_record,
        fresh_event=not recovering,
    )
    sequence = retained_plan.get("sequence")
    circuit_release = None
    circuit_before = (
        None
        if event_before.get("circuit") is None
        else _record(event_before.get("circuit"), field="canary circuit")
    )
    process_result: dict[str, object] | None = None
    exception: dict[str, object] | None = None
    completed_at = datetime.now(tz=UTC)
    try:
        if isinstance(sequence, dict) and sequence.get("sequence_ordinal") == 16:
            if recovering:
                attempt_count = event_before_record.get("attempt_count")
                if attempt_count not in {0, 1}:
                    raise Issue790DispositionError(
                        "interrupted bounded canary retained more than one attempt"
                    )
                if event_before_record.get("state") not in {
                    "QUEUED",
                    "CLAIMED",
                    "RUNNING",
                    "RETRY_HELD",
                    "RIGHTS_HELD",
                    "CONFIGURATION_HELD",
                    "DEAD_LETTER",
                    "TERMINAL",
                }:
                    raise Issue790DispositionError(
                        "interrupted bounded canary event state differs"
                    )
                circuit_release = canary_repository.existing_step16_circuit_release(
                    plan_digest=str(retained_plan["canonical_digest"]),
                    event_id=event_id,
                    ledger_seq=ledger_seq,
                )
            else:
                eligibility = _require_step16_event_circuit(
                    circuit_before,
                    observed_at=observed_at,
                    policy=_record(
                        sequence.get("owner_activation"),
                        field="owner activation",
                    ).get("event_circuit_policy"),
                )
                if eligibility == "EXPIRED_OPEN":
                    assert circuit_before is not None
                    circuit_release = _release_step16_expired_open_circuit(
                        store=store,
                        plan=retained_plan,
                        circuit_state=circuit_before,
                        observed_at=observed_at,
                        event_id=event_id,
                        ledger_seq=ledger_seq,
                        repository=canary_repository,
                    )
                else:
                    circuit_release = (
                        canary_repository.existing_step16_circuit_release(
                            plan_digest=str(retained_plan["canonical_digest"]),
                            event_id=event_id,
                            ledger_seq=ledger_seq,
                        )
                    )
                if circuit_release is not None:
                    unsigned_preflight = dict(preflight_evidence)
                    unsigned_preflight.pop("evidence_digest", None)
                    unsigned_preflight["circuit_release"] = circuit_release
                    preflight_evidence = {
                        **unsigned_preflight,
                        "evidence_digest": digest_canonical(unsigned_preflight),
                    }
        if prior_consumption is not None:
            consumption = prior_consumption
            owner_id = str(consumption["owner_id"])
            recovered_attempt_count = int(event_before_record["attempt_count"])
            process_result = (
                None
                if recovered_attempt_count == 0
                else {
                    "event_id": event_id,
                    "ledger_seq": ledger_seq,
                    "state": event_before_record["state"],
                    "attempt_count": recovered_attempt_count,
                }
            )
            completion_fields = _issue_790_iterative_result(
                store=store,
                plan=retained_plan,
                event_id=event_id,
                process_result=process_result,
                exception_present=False,
            )
            outcome = canary_repository.finalise_without_dispatch(
                consumption_digest=str(consumption["consumption_digest"]),
                event_id=event_id,
                ledger_seq=ledger_seq,
                owner_id=owner_id,
                completed_at=completed_at,
                **completion_fields,
            )
            retained_result = outcome.get("process_result")
            process_result = (
                None
                if retained_result is None
                else _record(retained_result, field="canary process result")
            )
        else:
            owner_id = f"issue-790-canary:{uuid.uuid4()}"
            consumption = canary_repository.consume(
                approved_plan_digest=str(retained_plan["canonical_digest"]),
                disposition_digest=disposition_digest,
                event_id=event_id,
                ledger_seq=ledger_seq,
                owner_id=owner_id,
                preflight_evidence=preflight_evidence,
                consumed_at=observed_at,
            )
            try:
                _require_worker_unloaded(_worker_state())
                result = _consume_issue_790_event(
                    proving_store=proving_store,
                    unpublished_store=store,
                    owner_id=owner_id,
                    event_id=event_id,
                    canary_consumption_digest=str(
                        consumption["consumption_digest"]
                    ),
                    model_usage=service,
                )
                if result is not None:
                    process_result = asdict(result)
            except Exception as exc:  # authority is consumed; seal and stop
                exception = {
                    "type": type(exc).__name__,
                    "detail_digest": digest_canonical(
                        {"type": type(exc).__name__, "detail": str(exc)}
                    ),
                }
            completed_at = datetime.now(tz=UTC)
            completion_fields = _issue_790_iterative_result(
                store=store,
                plan=retained_plan,
                event_id=event_id,
                process_result=process_result,
                exception_present=exception is not None,
            )
            outcome = canary_repository.complete(
                consumption_digest=str(consumption["consumption_digest"]),
                event_id=event_id,
                ledger_seq=ledger_seq,
                owner_id=owner_id,
                process_result=process_result,
                completed_at=completed_at,
                exception_code=(
                    None if exception is None else str(exception["type"])
                ),
                **completion_fields,
            )
    except Issue790CanaryIntegrityError as exc:
        raise Issue790DispositionError(str(exc)) from exc

    event_after = _event_snapshot(store, event_id=event_id, ledger_seq=ledger_seq)
    usage_evidence = _issue_790_canary_usage_evidence(store, event_id=event_id)
    retry_after = _retry_event_snapshots(store)
    worker_after = _worker_state()
    store_quick_check = _sqlite_quick_check(store, field="source unpublished store")
    route_after = service.route_state(str(target["route"]))
    if resuming_zero_io_finalisation and route_after != route_before:
        raise Issue790DispositionError(
            "interrupted bounded canary route changed during recovery"
        )
    if resuming_zero_io_finalisation:
        circuit_after = _circuit_state(store)
        if circuit_after != circuit_before:
            raise Issue790DispositionError(
                "interrupted bounded canary event circuit changed during recovery"
            )
    state_counts_after = _record(
        event_after["state_counts"],
        field="canary state counts",
    )
    dead_letters_after = int(state_counts_after.get("DEAD_LETTER", 0))
    retry_unchanged = retry_after == retry_before == retained_plan.get(
        "retry_forbidden_events"
    )
    worker_unloaded = worker_after == worker_before == {
        "label": _WORKER_LABEL,
        "launchctl_loaded": False,
        "process_ids": [],
    }
    event_after_record = _record(event_after["event"], field="canary event")
    canary_evidence_passed = bool(
        exception is None
        and process_result is not None
        and process_result.get("state") == "TERMINAL"
        and process_result.get("attempt_count") == 1
        and (
            predecessor is None
            or outcome.get("result_class") == "TRUTHFUL_PROVIDER_SUCCESS"
        )
        and event_after_record.get("state") == "TERMINAL"
        and usage_evidence["provider_backed_terminal_count"] >= 1
        and usage_evidence["truthful_nonzero_usage_count"] >= 1
        and usage_evidence["primary_chat_leaf_count"] >= 1
        and usage_evidence["qualified_primary_identity_count"]
        == usage_evidence["primary_chat_leaf_count"]
        and usage_evidence["truthful_primary_usage_count"]
        == usage_evidence["primary_chat_leaf_count"]
        and usage_evidence["fallback_chat_leaf_count"] == 0
        and usage_evidence["unresolved_terminal_count"] == 0
        and usage_evidence["unterminated_leaf_count"] == 0
        and route_after.get("state") == "CLOSED"
        and dead_letters_after == dead_letters_before
        and retry_unchanged
        and worker_unloaded
        and store_quick_check == "ok"
    )
    receipt_without_digest: dict[str, object] = {
        "schema_version": (
            ISSUE_790_CANARY_RECEIPT_SCHEMA
            if predecessor is None
            else ISSUE_790_ITERATIVE_CANARY_RECEIPT_SCHEMA
        ),
        "plan_digest": retained_plan["canonical_digest"],
        "operational_evidence": operational_evidence,
        "source_store": str(store),
        "proving_store": str(proving_store),
        "pre_operation_snapshot_path": str(backup_path),
        "pre_operation_snapshot_digest": backup_digest,
        "pre_operation_snapshot_retained": True,
        "observed_at": _utc_text(observed_at),
        "completed_at": _utc_text(completed_at),
        "disposition_digest": disposition_digest,
        "preflight_evidence": preflight_evidence,
        "consumption": consumption,
        "outcome": outcome,
        "process_result": process_result,
        "exception": exception,
        "event_before": event_before,
        "event_after": event_after,
        "usage_evidence": usage_evidence,
        "route_before": route_before,
        "route_after": route_after,
        "retry_forbidden_events_before": retry_before,
        "retry_forbidden_events_after": retry_after,
        "retry_exclusions": retry_exclusions,
        "retry_forbidden_events_unchanged": retry_unchanged,
        "worker_before": worker_before,
        "worker_after": worker_after,
        "worker_remained_unloaded": worker_unloaded,
        "dead_letter_count_before": dead_letters_before,
        "dead_letter_count_after": dead_letters_after,
        "store_quick_check": store_quick_check,
        "canary_evidence_passed": canary_evidence_passed,
        "resumed_zero_io_finalisation": resuming_zero_io_finalisation,
        "provider_dispatch_attempted_this_run": not resuming_zero_io_finalisation,
        "retry_authorised": False,
        "publication_performed": False,
        "public_dispatch_performed": False,
        "backlog_drain_performed": False,
        "persistent_worker_loaded": False,
        "non_effects": list(_NON_EFFECTS),
    }
    if isinstance(sequence, dict) and sequence.get("sequence_ordinal") == 16:
        looked_up = _optional_step16_circuit_release(circuit_release)
        consumption_release = _optional_step16_circuit_release(
            None
            if not isinstance(consumption, dict)
            else consumption.get("circuit_release")
        )
        outcome_release = _optional_step16_circuit_release(
            None if not isinstance(outcome, dict) else outcome.get("circuit_release")
        )
        bound = [
            item
            for item in (looked_up, consumption_release, outcome_release)
            if item is not None
        ]
        if bound and any(item != bound[0] for item in bound):
            raise Issue790DispositionError(
                "issue #790 event circuit release differs"
            )
        receipt_without_digest["circuit_release"] = None if not bound else bound[0]
    if predecessor is not None:
        receipt_without_digest["predecessor"] = predecessor
    return {
        **receipt_without_digest,
        "receipt_digest": digest_canonical(receipt_without_digest),
    }


def write_issue_790_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    path = _canonical_new_file(path, field="receipt destination")
    retained_receipt = dict(receipt)
    supplied_digest = retained_receipt.pop("receipt_digest", None)
    if supplied_digest != digest_canonical(retained_receipt):
        raise Issue790DispositionError("issue #790 receipt digest differs")
    payload = json.dumps(
        dict(receipt), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    descriptor, temporary_text = mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_text)
    try:
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _publish_file_no_replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _unlink_temporary(temporary)


def require_issue_790_path_outside_git(path: Path, *, field: str) -> Path:
    """Reject destinations inside a Git worktree."""

    absolute = path.expanduser().absolute()
    for parent in (absolute, *absolute.parents):
        if (parent / ".git").exists():
            raise Issue790DispositionError(f"{field} is inside a Git worktree")
    return absolute


def write_issue_790_canonical_json(
    path: Path,
    value: Mapping[str, object],
    *,
    field: str,
) -> dict[str, object]:
    """Write one canonical JSON object. Identical bytes are idempotent."""

    retained = dict(value)
    encoded = json.dumps(
        retained, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    destination = require_issue_790_path_outside_git(path, field=field)
    if os.path.lexists(destination):
        try:
            existing = destination.read_text(encoding="utf-8")
        except OSError as exc:
            raise Issue790DispositionError(f"{field} is not readable") from exc
        if existing != encoded:
            raise Issue790DispositionError(f"{field} differs")
        return json.loads(existing)
    written_path = _canonical_new_file(destination, field=field)
    descriptor, temporary_text = mkstemp(
        prefix=f".{written_path.name}.",
        dir=written_path.parent,
    )
    temporary = Path(temporary_text)
    try:
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _publish_file_no_replace(temporary, written_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _unlink_temporary(temporary)
    reread = written_path.read_text(encoding="utf-8")
    if reread != encoded:
        raise Issue790DispositionError(f"{field} read-back differs")
    return json.loads(reread)


def issue_790_step16_checked_approval(pending_digest: str) -> dict[str, str]:
    """Return the checked, non-live approval tuple bound to one pending digest."""

    if re.fullmatch(r"sha256:[0-9a-f]{64}", pending_digest) is None:
        raise Issue790DispositionError("issue #790 pending digest differs")
    return {
        "approved_by": ISSUE_790_STEP16_CHECKED_APPROVED_BY,
        "approval_reference": f"checked:{pending_digest}",
        "approved_at": ISSUE_790_STEP16_CHECKED_APPROVED_AT,
        "scope": _SCOPE,
    }


def _bind_step16_pending_family(
    pending: Mapping[str, object],
    *,
    pre_dispatch: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    pending_plan = dict(pending)
    supplied = pending_plan.get("canonical_digest")
    unsigned = {
        key: item for key, item in pending_plan.items() if key != "canonical_digest"
    }
    if supplied != digest_canonical(unsigned):
        raise Issue790DispositionError("issue #790 pending plan digest differs")
    if pending_plan.get("executable") is not False:
        raise Issue790DispositionError(
            "issue #790 pending plan must remain non-executable"
        )
    sequence = dict(_record(pending_plan.get("sequence"), field="sequence"))
    if sequence.get("sequence_ordinal") != 16:
        raise Issue790DispositionError("issue #790 pending plan ordinal differs")
    predecessor = _record(sequence.get("predecessor"), field="predecessor")
    if (
        predecessor.get("plan_digest")
        != issue_790_contract_module.ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST
    ):
        raise Issue790DispositionError("issue #790 predecessor identity differs")
    pre = dict(pre_dispatch)
    pre_unsigned = {
        key: item for key, item in pre.items() if key != "requirements_digest"
    }
    if pre.get("requirements_digest") != digest_canonical(pre_unsigned):
        raise Issue790DispositionError("issue #790 pre-dispatch digest differs")
    if sequence.get("pre_dispatch_operational_requirements_digest") != pre.get(
        "requirements_digest"
    ):
        raise Issue790DispositionError("issue #790 pre-dispatch identity differs")
    if (
        sequence.get("projection_policy_version") != PROJECTION_POLICY_VERSION
        or sequence.get("projection_policy_digest") != PROJECTION_POLICY_DIGEST
        or sequence.get("temporal_policy_version") != TEMPORAL_POLICY_VERSION
        or sequence.get("validator_contract_version") != VALIDATOR_CONTRACT_VERSION
    ):
        raise Issue790DispositionError("issue #790 projection identity differs")
    _validated_reviewed_fix(sequence.get("reviewed_fix"))
    _validated_non_timeout_causal_report(sequence.get("predecessor_causal_report"))
    return pending_plan, sequence, pre


def validate_issue_790_step16_candidate(
    value: Mapping[str, object],
) -> dict[str, object]:
    """Validate the Step 16 seal-proof candidate. This is not live authority."""

    candidate = dict(value)
    expected_keys = {
        "schema_version",
        "canonical_digest",
        "issue",
        "approval",
        "target",
        "release",
        "retry_forbidden_events",
        "canary",
        "non_effects",
        "sequence",
        "plan_status",
        "executable",
        "live_canary_authorised",
    }
    if set(candidate) != expected_keys:
        raise Issue790DispositionError("issue #790 candidate fields differ")
    if (
        candidate.get("schema_version")
        != issue_790_contract_module.ISSUE_790_STEP16_CANDIDATE_SCHEMA
        or candidate.get("issue") != 790
        or candidate.get("plan_status") != _CANDIDATE_PLAN_STATUS
        or candidate.get("executable") is not False
        or candidate.get("live_canary_authorised") is not False
    ):
        raise Issue790DispositionError("issue #790 candidate identity differs")
    supplied = _text(candidate, "canonical_digest")
    calculated = digest_canonical(
        {key: item for key, item in candidate.items() if key != "canonical_digest"}
    )
    if supplied != calculated:
        raise Issue790DispositionError("issue #790 candidate digest differs")
    approval = _record(candidate.get("approval"), field="approval")
    if (
        not str(approval.get("approved_by", "")).startswith("checked:")
        or not str(approval.get("approval_reference", "")).startswith("checked:")
    ):
        raise Issue790DispositionError("issue #790 candidate approval differs")
    if "NO_LIVE_CANARY_WITHOUT_OWNER_APPROVAL" not in list(
        candidate.get("non_effects") or ()
    ):
        raise Issue790DispositionError("issue #790 candidate non-effects differ")
    release = _record(candidate.get("release"), field="release")
    if release.get("kind") != "PENDING_OWNER_APPROVAL":
        raise Issue790DispositionError("issue #790 candidate release differs")
    sequence = _record(candidate.get("sequence"), field="sequence")
    target = _record(candidate.get("target"), field="target")
    reviewed_fix = _validated_reviewed_fix(sequence.get("reviewed_fix"))
    causal_report = _validated_non_timeout_causal_report(
        sequence.get("predecessor_causal_report")
    )
    predecessor = _record(sequence.get("predecessor"), field="predecessor")
    try:
        contract = issue_790_contract_module.issue_790_checked_candidate_contract(
            supplied
        )
    except KeyError as exc:
        raise Issue790DispositionError(
            "issue #790 candidate identity differs"
        ) from exc
    if (
        target.get("invocation_id") != contract.invocation_id
        or target.get("terminal_digest") != contract.terminal_digest
        or target.get("allocation_digest") != contract.allocation_digest
        or predecessor.get("plan_digest") != contract.predecessor_plan_digest
        or sequence.get("sequence_ordinal") != contract.sequence_ordinal
        or sequence.get("projection_policy_version")
        != contract.projection_policy_version
        or sequence.get("projection_policy_digest")
        != contract.projection_policy_digest
        or sequence.get("temporal_policy_version")
        != contract.temporal_policy_version
        or sequence.get("validator_contract_version")
        != contract.validator_contract_version
        or sequence.get("pre_dispatch_operational_requirements_digest")
        != contract.pre_dispatch_operational_requirements_digest
        or reviewed_fix.get("record_digest") != contract.reviewed_fix_digest
        or causal_report.get("report_digest")
        != contract.predecessor_causal_report_digest
        or approval.get("approved_by") != contract.checked_approved_by
        or approval.get("approval_reference") != contract.checked_approval_reference
    ):
        raise Issue790DispositionError("issue #790 candidate contract differs")
    return candidate


def seal_issue_790_step16_plan(
    pending: Mapping[str, object],
    approval: Mapping[str, object],
    *,
    pre_dispatch: Mapping[str, object],
) -> dict[str, object]:
    """Seal the pending family into a checked candidate. Not live authority."""

    pending_plan, sequence, _pre = _bind_step16_pending_family(
        pending, pre_dispatch=pre_dispatch
    )
    checked = dict(approval)
    if (
        checked.get("approved_by") != ISSUE_790_STEP16_CHECKED_APPROVED_BY
        or checked.get("approval_reference")
        != f"checked:{pending_plan['canonical_digest']}"
        or checked.get("approved_at") != ISSUE_790_STEP16_CHECKED_APPROVED_AT
        or checked.get("scope") != _SCOPE
    ):
        raise Issue790DispositionError("issue #790 checked approval differs")
    for key in _PENDING_SEQUENCE_ONLY_KEYS:
        sequence.pop(key, None)
    pending_plan["sequence"] = sequence
    pending_plan["schema_version"] = (
        issue_790_contract_module.ISSUE_790_STEP16_CANDIDATE_SCHEMA
    )
    pending_plan["plan_status"] = _CANDIDATE_PLAN_STATUS
    pending_plan["executable"] = False
    pending_plan["live_canary_authorised"] = False
    pending_plan["approval"] = checked
    pending_plan.pop("canonical_digest", None)
    pending_plan["canonical_digest"] = digest_canonical(
        {key: item for key, item in pending_plan.items() if key != "canonical_digest"}
    )
    return validate_issue_790_step16_candidate(pending_plan)


def _assemble_step16_owner_plan(
    candidate: Mapping[str, object],
    *,
    approval: Mapping[str, object],
    pre_dispatch: Mapping[str, object],
    revision: str,
    tree: str,
    owner_activation: Mapping[str, object],
) -> dict[str, object]:
    retained = validate_issue_790_step16_candidate(candidate)
    if retained["canonical_digest"] != (
        issue_790_contract_module.ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST
    ):
        raise Issue790DispositionError("issue #790 candidate identity differs")
    sequence = dict(_record(retained.get("sequence"), field="sequence"))
    pre = dict(pre_dispatch)
    pre_unsigned = {
        key: item for key, item in pre.items() if key != "requirements_digest"
    }
    if pre.get("requirements_digest") != digest_canonical(pre_unsigned):
        raise Issue790DispositionError("issue #790 pre-dispatch digest differs")
    if sequence.get("pre_dispatch_operational_requirements_digest") != pre.get(
        "requirements_digest"
    ):
        raise Issue790DispositionError("issue #790 pre-dispatch identity differs")
    template_digest = str(pre["requirements_digest"])
    binding = step16_activation_module.validate_step16_owner_activation_binding(
        owner_activation
    )
    if (
        binding["checked_candidate_digest"] != retained["canonical_digest"]
        or binding["pre_dispatch_template_digest"] != template_digest
    ):
        raise Issue790DispositionError("issue #790 owner activation binding differs")
    pre["exact_main_commit"] = revision
    pre["exact_main_tree"] = tree
    pre["requirements_digest"] = digest_canonical(
        {key: item for key, item in pre.items() if key != "requirements_digest"}
    )
    sequence["pre_dispatch_operational_requirements"] = pre
    sequence["pre_dispatch_operational_requirements_digest"] = pre[
        "requirements_digest"
    ]
    sequence["reviewed_correction_revision"] = revision
    sequence["reviewed_correction_tree"] = tree
    sequence["owner_activation"] = binding
    plan = {
        key: item
        for key, item in retained.items()
        if key not in _PENDING_PLAN_ONLY_KEYS
    }
    plan["schema_version"] = ISSUE_790_ITERATIVE_PLAN_SCHEMA
    plan["sequence"] = sequence
    plan["approval"] = {
        "approved_by": approval["approved_by"],
        "approval_reference": approval["approval_reference"],
        "approved_at": approval["approved_at"],
        "scope": approval["scope"],
    }
    plan["release"] = {
        "kind": _RELEASE_KIND,
        "evidence": "CONSERVATIVE_DISPOSITION_DIGEST",
    }
    plan["non_effects"] = list(_NON_EFFECTS)
    plan.pop("canonical_digest", None)
    plan["canonical_digest"] = digest_canonical(
        {key: item for key, item in plan.items() if key != "canonical_digest"}
    )
    return validate_issue_790_plan(plan)


def _step16_contract_from_plan(
    plan: Mapping[str, object],
) -> issue_790_contract_module.Issue790ApprovedPlanContract:
    sequence = _record(plan.get("sequence"), field="sequence")
    target = _record(plan.get("target"), field="target")
    approval = _record(plan.get("approval"), field="approval")
    predecessor = _record(sequence.get("predecessor"), field="predecessor")
    reviewed_fix = _validated_reviewed_fix(sequence.get("reviewed_fix"))
    causal = _validated_causal_report(sequence.get("predecessor_causal_report"))
    return issue_790_contract_module.Issue790ApprovedPlanContract(
        schema_version=ISSUE_790_ITERATIVE_PLAN_SCHEMA,
        plan_digest=str(plan["canonical_digest"]),
        invocation_id=str(target["invocation_id"]),
        terminal_digest=str(target["terminal_digest"]),
        allocation_digest=str(target["allocation_digest"]),
        approved_by=str(approval["approved_by"]),
        approval_reference=str(approval["approval_reference"]),
        approved_at=str(approval["approved_at"]),
        scope=str(approval["scope"]),
        terminal_outcome=str(target["terminal_outcome"]),
        route_open_reason=str(target["route_open_reason"]),
        root_plan_digest=str(sequence["root_plan_digest"]),
        predecessor_plan_digest=str(predecessor["plan_digest"]),
        sequence_ordinal=16,
        controller_timeout_ms=int(sequence["controller_timeout_ms"]),
        extraction_timeout_ms=int(sequence["extraction_timeout_ms"]),
        cleanup_reserve_ms=int(sequence["cleanup_reserve_ms"]),
        fixed_constraints_digest=str(sequence["fixed_constraints_digest"]),
        predecessor_causal_report_digest=str(causal["report_digest"]),
        constraint_change=str(sequence["constraint_change"]),
        reviewed_fix_digest=str(reviewed_fix["record_digest"]),
        projection_policy_version=str(sequence["projection_policy_version"]),
        projection_policy_digest=str(sequence["projection_policy_digest"]),
        temporal_policy_version=str(sequence["temporal_policy_version"]),
        validator_contract_version=str(sequence["validator_contract_version"]),
        pre_dispatch_operational_requirements_digest=str(
            sequence["pre_dispatch_operational_requirements_digest"]
        ),
    )


def finalise_issue_790_step16_plan(
    candidate: Mapping[str, object],
    owner_approval: Mapping[str, object],
    *,
    pre_dispatch: Mapping[str, object],
) -> dict[str, object]:
    """Bind a syntactic owner tuple. Still not live authority."""

    retained = validate_issue_790_step16_candidate(candidate)
    owner = _require_owner_approval_tuple(owner_approval)
    sequence = _record(retained.get("sequence"), field="sequence")
    binding = {
        "checked_candidate_digest": retained["canonical_digest"],
        "pre_dispatch_template_digest": sequence[
            "pre_dispatch_operational_requirements_digest"
        ],
        "final_correction_pr": 1,
        "reviewed_head_commit": owner["reviewed_correction_revision"],
        "reviewed_head_tree": owner["reviewed_correction_tree"],
        "focus_gate_run_url": "https://github.com/fol2/newsroom/actions/runs/1",
        "focus_gate_run_id": 1,
        "focus_gate_manifest_digest": "sha256:" + "00" * 32,
        "feature_complete_review_receipt": "sha256:" + "11" * 32,
        "event_circuit_policy": (
            step16_activation_module.ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY
        ),
        "caps": dict(_STEP16_OWNER_CAPS),
        "activation_policy_version": (
            issue_790_contract_module.ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION
        ),
    }
    return _assemble_step16_owner_plan(
        retained,
        approval=owner,
        pre_dispatch=pre_dispatch,
        revision=owner["reviewed_correction_revision"],
        tree=owner["reviewed_correction_tree"],
        owner_activation=binding,
    )


def activate_issue_790_step16_plan(
    candidate: Mapping[str, object],
    *,
    comment_id: int,
    pre_dispatch: Mapping[str, object],
    store: Path,
    github_api: step16_activation_module.GitHubApi | None = None,
    focus_gate_manifest: Mapping[str, object] | None = None,
    review_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Mint one activation receipt and one dynamically validated Step 16 plan."""

    retained = validate_issue_790_step16_candidate(candidate)
    authenticated = step16_activation_module.fetch_authenticated_step16_owner_comment(
        comment_id=comment_id,
        github_api=github_api,
        default_github_api=_default_github_api,
        focus_gate_manifest=focus_gate_manifest,
        review_receipt=review_receipt,
    )
    payload = authenticated["payload"]
    if not isinstance(payload, dict):
        raise Issue790DispositionError("issue #790 owner approval payload differs")
    step16_activation_module.require_step16_candidate_matches_payload(
        candidate=retained,
        payload=payload,
    )
    if payload.get("non_effects") != list(_NON_EFFECTS):
        raise Issue790DispositionError("issue #790 owner approval payload differs")
    sequence = _record(retained.get("sequence"), field="sequence")
    binding = step16_activation_module.step16_owner_activation_binding(
        payload,
        template_digest=str(sequence["pre_dispatch_operational_requirements_digest"]),
    )
    plan = _assemble_step16_owner_plan(
        retained,
        approval={
            "approved_by": authenticated["approved_by"],
            "approval_reference": authenticated["approval_reference"],
            "approved_at": authenticated["approved_at"],
            "scope": authenticated["scope"],
        },
        pre_dispatch=pre_dispatch,
        revision=str(payload["final_main_commit"]),
        tree=str(payload["final_main_tree"]),
        owner_activation=binding,
    )
    contract = _step16_contract_from_plan(plan)
    fetcher = github_api if github_api is not None else _default_github_api
    api_manifest, api_review = step16_activation_module.evidence_from_github_api(
        fetcher
    )
    manifest = (
        focus_gate_manifest if focus_gate_manifest is not None else api_manifest
    )
    review = review_receipt if review_receipt is not None else api_review
    receipt = step16_activation_module.mint_step16_activation_receipt(
        authenticated=authenticated,
        plan=plan,
        contract=contract,
        template_digest=str(sequence["pre_dispatch_operational_requirements_digest"]),
        effective_digest=str(
            _record(plan.get("sequence"), field="sequence")[
                "pre_dispatch_operational_requirements_digest"
            ]
        ),
        focus_gate_evidence=None if not isinstance(manifest, dict) else manifest,
        review_evidence=None if not isinstance(review, dict) else review,
    )
    repository = Issue790CanaryRepository(str(store))
    stored = repository.retain_step16_activation(receipt)
    return {"activation": stored, "plan": plan}


def _optional_step16_circuit_release(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        return step16_activation_module.validate_step16_circuit_release_receipt(
            _record(value, field="circuit release")
        )
    except Issue790DispositionError:
        raise
    except Exception as exc:
        raise Issue790DispositionError(
            "issue #790 event circuit release differs"
        ) from exc


def qualify_issue_790_step16_readiness(
    *,
    plan: Mapping[str, object],
    store: Path,
    evidence: Mapping[str, object],
    route_state: Mapping[str, object],
    circuit_state: Mapping[str, object] | None,
    canary_event: Mapping[str, object],
    observed_at: datetime,
    github_api: step16_activation_module.GitHubApi | None = None,
) -> dict[str, object]:
    """Provider-free readiness bound. Stops before credential, catalogue or provider I/O."""

    retained = _require_approved_plan(plan, store=store, github_api=github_api)
    _require_step16_code_identity(retained, evidence=evidence)
    _require_step16_runtime_semantics(
        retained,
        evidence=evidence,
        route_state=route_state,
        circuit_state=circuit_state,
        observed_at=observed_at,
        canary_event=canary_event,
        fresh_event=True,
    )
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        record = step16_activation_module.load_step16_activation_record(
            connection,
            plan_digest=str(retained["canonical_digest"]),
        )
    finally:
        connection.close()
    unsigned = {
        "schema_version": "newsroom.issue-790.step16-provider-free-readiness.v1",
        "status": step16_activation_module.ISSUE_790_STEP16_READINESS_STATUS,
        "plan_digest": retained["canonical_digest"],
        "checked_candidate_digest": record["checked_candidate_digest"],
        "activation_digest": record["activation_digest"],
        "provider_calls": 0,
        "catalogue_queries": 0,
        "credential_resolution": False,
        "canary_consumed": False,
        "public_effects": "DISABLED",
    }
    return {**unsigned, "readiness_digest": digest_canonical(unsigned)}


__all__ = [
    "ISSUE_790_PLAN_SCHEMA",
    "ISSUE_790_RECEIPT_SCHEMA",
    "ISSUE_790_ITERATIVE_RECEIPT_SCHEMA",
    "ISSUE_790_CANARY_RECEIPT_SCHEMA",
    "ISSUE_790_ITERATIVE_CANARY_RECEIPT_SCHEMA",
    "ISSUE_790_APPROVED_PLAN_DIGEST",
    "Issue790DispositionError",
    "activate_issue_790_step16_plan",
    "apply_issue_790_plan",
    "assert_issue_790_paths_disjoint",
    "dry_run_issue_790_plan",
    "finalise_issue_790_step16_plan",
    "load_issue_790_plan",
    "qualify_issue_790_step16_readiness",
    "run_issue_790_canary",
    "validate_issue_790_plan",
    "validate_issue_790_step16_candidate",
    "issue_790_step16_checked_approval",
    "require_issue_790_path_outside_git",
    "seal_issue_790_step16_plan",
    "write_issue_790_canonical_json",
    "write_issue_790_receipt",
]
