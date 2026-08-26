"""Exact, approval-bound operation for issue #790's one unresolved leaf."""

from __future__ import annotations

import hashlib
import importlib
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
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkstemp

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti_events import GraphitiProcessResult
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_contract import (
    ISSUE_790_APPROVED_PLAN_DIGEST,
)
from newsroom.control_plane.model_usage import (
    ModelUsageAdmissionError,
    ModelUsageIntegrityError,
    ModelUsageService,
)

ISSUE_790_PLAN_SCHEMA = "newsroom.issue-790.conservative-disposition-plan.v1"
ISSUE_790_RECEIPT_SCHEMA = (
    "newsroom.issue-790.conservative-disposition-receipt.v1"
)
ISSUE_790_OPERATIONAL_EVIDENCE_SCHEMA = (
    "newsroom.issue-790.operational-preconditions.v1"
)
ISSUE_790_CANARY_RECEIPT_SCHEMA = "newsroom.issue-790.bounded-canary-receipt.v1"
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
    ("newsroom.control_plane.model_usage", "newsroom/control_plane/model_usage.py"),
    ("newsroom.control_plane.graphiti_events", "newsroom/control_plane/graphiti_events.py"),
    ("newsroom.control_plane.cycle", "newsroom/control_plane/cycle.py"),
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
        "retry_forbidden_events",
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
    if plan.get("retry_forbidden_events") != list(_RETRY_FORBIDDEN_EVENTS):
        raise Issue790DispositionError("issue #790 retry exclusions differ")
    if canary != {
        "authority_consumption": "APPEND_ONLY_SINGLE_USE_BEFORE_PROVIDER_IO",
        "event_binding": "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT",
        "fresh_provider_backed_attempt_count": 1,
        "persistent_worker_state_before_canary": "UNLOADED",
        "requires_exact_main_deployment": True,
    }:
        raise Issue790DispositionError("issue #790 canary boundary differs")
    if plan.get("non_effects") != list(_NON_EFFECTS):
        raise Issue790DispositionError("issue #790 non-effects differ")
    return plan


def load_issue_790_plan(path: Path) -> dict[str, object]:
    path = _canonical_existing_file(path, field="issue #790 plan")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Issue790DispositionError("issue #790 plan is not readable JSON") from exc
    if not isinstance(value, dict):
        raise Issue790DispositionError("issue #790 plan must be an object")
    return _require_approved_plan(value)


def _require_approved_plan(value: Mapping[str, object]) -> dict[str, object]:
    plan = validate_issue_790_plan(value)
    if plan["canonical_digest"] != ISSUE_790_APPROVED_PLAN_DIGEST:
        raise Issue790DispositionError("issue #790 approved plan identity differs")
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
    disposition_digest: str,
) -> list[dict[str, object]]:
    retained = list(repository.retry_exclusions())
    expected_events = plan.get("retry_forbidden_events")
    if (
        not isinstance(expected_events, list)
        or len(retained) != len(expected_events) == 2
        or any(
            record.get("approved_plan_digest") != plan.get("canonical_digest")
            or record.get("disposition_digest") != disposition_digest
            or record.get("reason") != "ISSUE_790_RETRY_FORBIDDEN"
            or record.get("event_snapshot") != expected
            for record, expected in zip(retained, expected_events, strict=True)
        )
    ):
        raise Issue790DispositionError(
            "issue #790 durable retry exclusions differ"
        )
    return retained


def _running_code_evidence(
    *,
    root: Path,
    git: str,
    revision: str,
) -> list[dict[str, object]]:
    """Bind the executing modules to blobs in the reviewed repository tree."""

    retained: list[dict[str, object]] = []
    for module_name, relative_path in _RUNNING_CODE_MODULES:
        module = importlib.import_module(module_name)
        raw_path = getattr(module, "__file__", None)
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
    """Collect exact-main, CI, worker, store and retry-exclusion evidence."""

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
        and item.get("name") == "test"
        and item.get("status") == "completed"
        and item.get("conclusion") == "success"
        and item.get("head_sha") == revision
        and isinstance(item.get("html_url"), str)
    ]
    if not successful_tests:
        raise Issue790DispositionError("exact-main CI test is not successful")
    successful_test = max(
        successful_tests,
        key=lambda item: int(item.get("id", 0)),
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
            "name": "test",
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
        or ci_test.get("name") != "test"
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
    return {**retained, "evidence_digest": digest}


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
) -> dict[str, object]:
    """Apply the same exact transition to a dry-run copy or the live store."""

    retained_plan = _require_approved_plan(plan)
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
        retry_exclusions = canary_repository.retain_retry_exclusions(
            approved_plan_digest=str(retained_plan["canonical_digest"]),
            disposition_digest=str(disposition["disposition_digest"]),
            events=tuple(
                _record(item, field="retry-forbidden event")
                for item in retained_plan["retry_forbidden_events"]  # type: ignore[union-attr]
            ),
            excluded_at=observed_at,
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
    receipt_digest = digest_canonical(receipt_without_digest)
    return {**receipt_without_digest, "receipt_digest": receipt_digest}


def dry_run_issue_790_plan(
    *,
    source_store: Path,
    scratch_store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
) -> dict[str, object]:
    assert_issue_790_paths_disjoint(source_store, scratch_store)
    retained_plan = _require_approved_plan(plan)
    backup_digest = _sqlite_backup(source_store, scratch_store)
    receipt = _execute_issue_790_plan(
        store=scratch_store,
        plan=retained_plan,
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
    repository_root: Path,
) -> dict[str, object]:
    assert_issue_790_paths_disjoint(store, backup_path)
    retained_plan = _require_approved_plan(plan)
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
        circuit = connection.execute(
            "SELECT state,opened_at,available_at,failure_code "
            "FROM unpublished_graphiti_event_circuit WHERE singleton=1"
        ).fetchone()
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
        if (
            provider_backed
            and usage_status in {"REPORTED", "ESTIMATED"}
            and isinstance(total_tokens, int)
            and not isinstance(total_tokens, bool)
            and total_tokens > 0
        ):
            truthful_nonzero_usage_count += 1
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
        "unresolved_terminal_count": unresolved_terminal_count,
        "unterminated_leaf_count": unterminated_leaf_count,
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
        graphiti=EvaluationGraphitiRunner(),
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
) -> dict[str, object]:
    from newsroom.control_plane.cycle import qualify_fresh_graphiti_event

    return qualify_fresh_graphiti_event(
        proving_store=str(proving_store),
        unpublished_store=str(unpublished_store),
        event_id=event_id,
        ledger_seq=ledger_seq,
        clock=lambda: observed_at,
    )


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
) -> dict[str, object]:
    """Consume and seal exactly one fresh event under the approved #790 authority."""

    retained_plan = _require_approved_plan(plan)
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
    retry_exclusions = _require_retry_exclusions(
        canary_repository,
        plan=retained_plan,
        disposition_digest=disposition_digest,
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
            )
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
            raise Issue790DispositionError(
                f"bounded canary provider-free preflight failed: {type(exc).__name__}"
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
    if (
        route_before.get("state") != "CLOSED"
        or route_before.get("reason") != expected_route_reason
    ):
        raise Issue790DispositionError(
            "bounded canary route release authority differs"
        )
    process_result: dict[str, object] | None = None
    exception: dict[str, object] | None = None
    completed_at = datetime.now(tz=UTC)
    try:
        if prior_consumption is not None:
            consumption = prior_consumption
            owner_id = str(consumption["owner_id"])
            outcome = canary_repository.finalise_without_dispatch(
                consumption_digest=str(consumption["consumption_digest"]),
                event_id=event_id,
                ledger_seq=ledger_seq,
                owner_id=owner_id,
                completed_at=completed_at,
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
            )
    except Issue790CanaryIntegrityError as exc:
        raise Issue790DispositionError(str(exc)) from exc

    event_after = _event_snapshot(store, event_id=event_id, ledger_seq=ledger_seq)
    usage_evidence = _issue_790_canary_usage_evidence(store, event_id=event_id)
    retry_after = _retry_event_snapshots(store)
    worker_after = _worker_state()
    store_quick_check = _sqlite_quick_check(store, field="source unpublished store")
    route_after = service.route_state(str(target["route"]))
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
        and event_after_record.get("state") == "TERMINAL"
        and usage_evidence["provider_backed_terminal_count"] >= 1
        and usage_evidence["truthful_nonzero_usage_count"] >= 1
        and usage_evidence["unresolved_terminal_count"] == 0
        and usage_evidence["unterminated_leaf_count"] == 0
        and route_after.get("state") == "CLOSED"
        and dead_letters_after == dead_letters_before
        and retry_unchanged
        and worker_unloaded
        and store_quick_check == "ok"
    )
    receipt_without_digest: dict[str, object] = {
        "schema_version": ISSUE_790_CANARY_RECEIPT_SCHEMA,
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


__all__ = [
    "ISSUE_790_PLAN_SCHEMA",
    "ISSUE_790_RECEIPT_SCHEMA",
    "ISSUE_790_CANARY_RECEIPT_SCHEMA",
    "ISSUE_790_APPROVED_PLAN_DIGEST",
    "Issue790DispositionError",
    "apply_issue_790_plan",
    "assert_issue_790_paths_disjoint",
    "dry_run_issue_790_plan",
    "load_issue_790_plan",
    "run_issue_790_canary",
    "validate_issue_790_plan",
    "write_issue_790_receipt",
]
