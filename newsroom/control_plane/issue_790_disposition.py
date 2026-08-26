"""Exact, approval-bound operation for issue #790's one unresolved leaf."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.model_usage import (
    ModelUsageAdmissionError,
    ModelUsageIntegrityError,
    ModelUsageService,
)

ISSUE_790_PLAN_SCHEMA = "newsroom.issue-790.conservative-disposition-plan.v1"
ISSUE_790_RECEIPT_SCHEMA = (
    "newsroom.issue-790.conservative-disposition-receipt.v1"
)
ISSUE_790_APPROVED_PLAN_DIGEST = (
    "sha256:e9d06bf838b4895021ddc92c4981068721ccc2b01562846046fbdb99b9816163"
)
_AUTHORITY_SCHEMA = (
    "newsroom.model-usage.conservative-disposition-authority.v1"
)
_SCOPE = "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION"
_RELEASE_KIND = "AUTHORISED_OPERATOR_RESET"
_NON_EFFECTS = (
    "NO_PUBLICATION",
    "NO_PUBLIC_DISPATCH",
    "NO_BACKLOG_DRAIN",
    "NO_BULK_REQUEUE",
    "NO_PRODUCTION_OPERATIONAL_ADMISSION",
    "NO_WIDER_ACTIVATION",
    "NO_PROVIDER_SUBSTITUTION",
    "NO_UNRELATED_SPEND_DISPOSITION",
)


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


def validate_issue_790_plan(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the complete, content-addressed and deliberately narrow plan."""

    plan = dict(value)
    expected_keys = {
        "schema_version",
        "canonical_digest",
        "issue",
        "approval",
        "target",
        "release",
        "retry_forbidden_ledger_ids",
        "canary",
        "non_effects",
    }
    if set(plan) != expected_keys:
        raise Issue790DispositionError("issue #790 plan fields differ")
    if plan.get("schema_version") != ISSUE_790_PLAN_SCHEMA or plan.get("issue") != 790:
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
    if set(target) != {
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
    }:
        raise Issue790DispositionError("issue #790 target fields differ")
    for field in (
        "invocation_id",
        "terminal_digest",
        "allocation_digest",
        "policy_digest",
    ):
        if not _text(target, field).startswith("sha256:"):
            raise Issue790DispositionError(f"issue #790 {field} differs")
    if (
        target.get("route") != "GRAPHITI_CHAT_PRIMARY"
        or target.get("provider") != "cursor-agent-cli"
        or target.get("workload_class") != "GRAPHITI_CHAT_PRIMARY"
        or target.get("terminal_usage_status") != "UNREPORTED"
        or target.get("terminal_failure_class") != "MISSING_PROVIDER_TELEMETRY"
        or target.get("route_open_reason") != "SYSTEMIC_TRANSPORT"
        or target.get("conservative_total_source")
        != "QUALIFIED_POLICY_MAX_TOTAL_TOKENS"
    ):
        raise Issue790DispositionError("issue #790 target contract differs")
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
    if plan.get("retry_forbidden_ledger_ids") != [1932, 1972]:
        raise Issue790DispositionError("issue #790 retry exclusions differ")
    if canary != {
        "fresh_provider_backed_attempt_count": 1,
        "persistent_worker_state_before_canary": "UNLOADED",
        "requires_exact_main_deployment": True,
    }:
        raise Issue790DispositionError("issue #790 canary boundary differs")
    if plan.get("non_effects") != list(_NON_EFFECTS):
        raise Issue790DispositionError("issue #790 non-effects differ")
    return plan


def load_issue_790_plan(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Issue790DispositionError("issue #790 plan is not readable JSON") from exc
    if not isinstance(value, dict):
        raise Issue790DispositionError("issue #790 plan must be an object")
    plan = validate_issue_790_plan(value)
    if plan["canonical_digest"] != ISSUE_790_APPROVED_PLAN_DIGEST:
        raise Issue790DispositionError("issue #790 approved plan identity differs")
    return plan


def _sqlite_backup(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise Issue790DispositionError("source unpublished store is absent")
    if destination.exists():
        raise Issue790DispositionError("backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(
        f"{source.absolute().as_uri()}?mode=ro",
        uri=True,
    )
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]) != "ok":
            raise Issue790DispositionError("SQLite backup integrity check failed")
    finally:
        destination_connection.close()
        source_connection.close()
    destination.chmod(0o600)
    return "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest()


def _authority_digest(plan: Mapping[str, object]) -> str:
    approval = _record(plan["approval"], field="approval")
    target = _record(plan["target"], field="target")
    return digest_canonical(
        {
            "schema_version": _AUTHORITY_SCHEMA,
            "approved_by": approval["approved_by"],
            "approval_reference": approval["approval_reference"],
            "approved_at": approval["approved_at"],
            "invocation_id": target["invocation_id"],
            "terminal_digest": target["terminal_digest"],
            "allocation_digest": target["allocation_digest"],
            "scope": approval["scope"],
        }
    )


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


def execute_issue_790_plan(
    *,
    store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    mode: str,
    backup_path: Path,
    backup_digest: str,
    source_store: Path | None = None,
) -> dict[str, object]:
    """Apply the same exact transition to a dry-run copy or the live store."""

    retained_plan = validate_issue_790_plan(plan)
    approval = _record(retained_plan["approval"], field="approval")
    target = _record(retained_plan["target"], field="target")
    if mode not in {"dry-run", "apply"}:
        raise Issue790DispositionError("issue #790 operation mode is invalid")
    if observed_at < _instant(approval["approved_at"], field="approved_at"):
        raise Issue790DispositionError("issue #790 operation precedes approval")

    _assert_exact_target(store, retained_plan)
    service = ModelUsageService(str(store))
    authority_digest = _authority_digest(retained_plan)
    try:
        initial_route_state = service.route_state(str(target["route"]))
        if initial_route_state.get("state") == "OPEN":
            if initial_route_state.get("reason") != target["route_open_reason"]:
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
        disposition = service.disposition_unreported_subscription_usage(
            invocation_id=str(target["invocation_id"]),
            expected_terminal_digest=str(target["terminal_digest"]),
            expected_allocation_digest=str(target["allocation_digest"]),
            approved_by=str(approval["approved_by"]),
            approval_reference=str(approval["approval_reference"]),
            approved_at=_instant(approval["approved_at"], field="approved_at"),
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
        route_state_before_release = service.route_state(str(target["route"]))
        expected_closed_reason = (
            f"{_RELEASE_KIND}:{disposition['disposition_digest']}"
        )
        if route_state_before_release.get("state") == "OPEN":
            if (
                route_state_before_release.get("reason")
                != target["route_open_reason"]
            ):
                raise Issue790DispositionError(
                    "issue #790 current route failure differs"
                )
            service.release_route_circuit(
                route=str(target["route"]),
                release_kind=_RELEASE_KIND,
                bound_failure_reason=str(target["route_open_reason"]),
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
    except (ModelUsageIntegrityError, ModelUsageAdmissionError) as exc:
        raise Issue790DispositionError(str(exc)) from exc

    operation_source = store if source_store is None else source_store
    receipt_without_digest: dict[str, object] = {
        "schema_version": ISSUE_790_RECEIPT_SCHEMA,
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
        "route_state_before_release": route_state_before_release,
        "route_state_after_release": route_state_after_release,
        "retry_performed": False,
        "canary_performed": False,
        "publication_performed": False,
        "public_dispatch_performed": False,
        "non_effects": list(_NON_EFFECTS),
    }
    receipt_digest = digest_canonical(receipt_without_digest)
    return {**receipt_without_digest, "receipt_digest": receipt_digest}


def dry_run_issue_790_plan(
    *,
    source_store: Path,
    scratch_store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
) -> dict[str, object]:
    backup_digest = _sqlite_backup(source_store, scratch_store)
    receipt = execute_issue_790_plan(
        store=scratch_store,
        plan=plan,
        observed_at=observed_at,
        mode="dry-run",
        backup_path=scratch_store,
        backup_digest=backup_digest,
        source_store=source_store,
    )
    return receipt


def apply_issue_790_plan(
    *,
    store: Path,
    backup_path: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
) -> dict[str, object]:
    backup_digest = _sqlite_backup(store, backup_path)
    return execute_issue_790_plan(
        store=store,
        plan=plan,
        observed_at=observed_at,
        mode="apply",
        backup_path=backup_path,
        backup_digest=backup_digest,
    )


def write_issue_790_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        dict(receipt), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


__all__ = [
    "ISSUE_790_PLAN_SCHEMA",
    "ISSUE_790_RECEIPT_SCHEMA",
    "ISSUE_790_APPROVED_PLAN_DIGEST",
    "Issue790DispositionError",
    "apply_issue_790_plan",
    "dry_run_issue_790_plan",
    "execute_issue_790_plan",
    "load_issue_790_plan",
    "validate_issue_790_plan",
    "write_issue_790_receipt",
]
