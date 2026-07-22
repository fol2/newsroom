from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from typing import Mapping, Sequence

from .classify_change import GitRouteError, resolve_commit, resolve_tree
from .contracts import ContractError, SdlcContract, load_contract


SCHEMA_VERSION = "newsroom.sdlc.evidence.v1"
_ROUTE_SCHEMA_VERSION = "newsroom.sdlc.route.v1"
_GATE_RUN_SCHEMA_VERSION = "newsroom.sdlc.gate-run.v1"
_JUNIT_SCHEMA_VERSION = "newsroom.sdlc.junit-summary.v1"
_REPOSITORY = "fol2/newsroom"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.*-]{1,128}")
_RESULT_REASON = re.compile(
    r"(?:PASS|FAIL|BUDGET_EXCEEDED|CLASSIFIER_ERROR|ENVIRONMENT_ERROR|"
    r"EVIDENCE_MISMATCH|UNAUTHORISED_EFFECT):[A-Za-z0-9_.*-]+:"
    r"[A-Za-z0-9_.*-]+(?::[A-Za-z0-9_=.*-]+)?"
)
_RESULTS = frozenset(
    {
        "PASS",
        "FAIL",
        "BUDGET_EXCEEDED",
        "CLASSIFIER_ERROR",
        "ENVIRONMENT_ERROR",
        "EVIDENCE_MISMATCH",
        "UNAUTHORISED_EFFECT",
    }
)
_RISK_TIERS = frozenset(
    {
        "R0_DOCUMENTATION",
        "R1_LOCAL_CODE",
        "R2_STATEFUL_CONTRACT",
        "R3_EXTERNAL_SERVICE_SECURITY",
        "R4_RELEASE_OPERATIONAL",
    }
)
_RUNNER_KINDS = frozenset(
    {"github-hosted", "ephemeral-prewarmed", "local", "other"}
)
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_GIT_BLOB_BYTES = 16 * 1024 * 1024
_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "evidence_identity",
        "gate_id",
        "gate_contract_version",
        "risk_classifier_version",
        "repository",
        "base_sha",
        "head_sha",
        "base_tree_sha",
        "tree_sha",
        "risk_tier",
        "risk_reasons",
        "runner_kind",
        "queue_ms",
        "bootstrap_ms",
        "execution_ms",
        "finalize_ms",
        "cache_key",
        "cache_hit",
        "python_version",
        "uv_version",
        "lockfile_digest",
        "toolchain_digest",
        "service_compatibility_digest",
        "selected_test_manifest_digest",
        "gate_inputs_digest",
        "selected_tests",
        "sentinel_tests",
        "random_sample_seed",
        "random_sample_tests",
        "test_count",
        "failure_count",
        "error_count",
        "skip_count",
        "required_skip_count",
        "first_failure_fingerprint",
        "result",
        "result_reason",
        "created_at",
    }
)
_ROUTE_KEYS = frozenset(
    {
        "schema_version",
        "contract_version",
        "base_sha",
        "head_sha",
        "base_tree_sha",
        "head_tree_sha",
        "risk_tier",
        "reasons",
        "core_required",
        "service_required",
        "clustering_required",
        "owner_authority_required",
        "core_tests",
        "service_tests",
        "sentinels",
        "selected_test_manifest_digest",
    }
)
_GATE_RUN_KEYS = frozenset(
    {
        "schema_version",
        "gate_id",
        "phase",
        "result",
        "result_reason",
        "returncode",
        "execution_ms",
        "stdout",
        "stderr",
        "stdout_truncated",
        "stderr_truncated",
    }
)
_JUNIT_KEYS = frozenset(
    {
        "schema_version",
        "outcome",
        "reports",
        "test_ids_digest",
        "test_count",
        "failure_count",
        "error_count",
        "skip_count",
        "required_skip_count",
        "duration_ms",
        "first_failure_fingerprint",
    }
)


class EvidenceError(ValueError):
    """Raised when gate inputs cannot produce exact accepted evidence."""


def canonical_json_bytes(value: object) -> bytes:
    """Canonical JSON for the accepted no-float evidence identity domain."""

    def validate(item: object) -> None:
        if item is None or isinstance(item, (bool, int, str)):
            return
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise EvidenceError("canonical_key_type")
            for child in item.values():
                validate(child)
            return
        raise EvidenceError("canonical_value_type")

    validate(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except UnicodeError as exc:
        raise EvidenceError("canonical_unicode") from exc


def sha256_identity(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{name}_mapping")
    return value


def _text(value: object, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise EvidenceError(f"{name}_text")
    return value


def _string(value: object, name: str, *, maximum: int = 512) -> str:
    text = _text(value, name, maximum=maximum)
    if not text:
        raise EvidenceError(f"{name}_string")
    if any(ord(character) < 32 for character in text):
        raise EvidenceError(f"{name}_control")
    return text


def _optional_string(
    value: object, name: str, *, maximum: int = 512
) -> str | None:
    if value is None:
        return None
    return _string(value, name, maximum=maximum)


def _sha(value: object, name: str) -> str:
    text = _string(value, name, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise EvidenceError(f"{name}_sha256")
    return text


def _optional_sha(value: object, name: str) -> str | None:
    return None if value is None else _sha(value, name)


def _git_sha(value: object, name: str) -> str:
    text = _string(value, name, maximum=40)
    if _GIT_SHA.fullmatch(text) is None:
        raise EvidenceError(f"{name}_git_sha")
    return text


def _nonnegative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError(f"{name}_nonnegative")
    if value > 9_223_372_036_854_775_807:
        raise EvidenceError(f"{name}_range")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceError(f"{name}_boolean")
    return value


def _string_list(
    value: object,
    name: str,
    *,
    maximum_items: int,
    maximum_length: int,
    sorted_required: bool = False,
    nonempty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise EvidenceError(f"{name}_array")
    result = [_string(item, name, maximum=maximum_length) for item in value]
    if nonempty and not result:
        raise EvidenceError(f"{name}_empty")
    if len(set(result)) != len(result):
        raise EvidenceError(f"{name}_duplicate")
    if sorted_required and result != sorted(result):
        raise EvidenceError(f"{name}_order")
    return result


def _created_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
    text = _string(value, "created_at", maximum=64)
    if not text.endswith("Z"):
        raise EvidenceError("created_at_utc")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise EvidenceError("created_at_format") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EvidenceError("created_at_utc")
    return text


def _git_bytes(
    repo_root: Path,
    arguments: Sequence[str],
    *,
    maximum: int,
) -> bytes:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repo_root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("git_environment") from exc
    if completed.returncode != 0:
        raise EvidenceError("git_evidence_input")
    if len(completed.stdout) > maximum:
        raise EvidenceError("git_blob_size")
    return completed.stdout


def git_blob_digest(repo_root: str | Path, commit_sha: str, path: str) -> str:
    root = Path(repo_root).resolve()
    _git_sha(commit_sha, "commit_sha")
    if path != "uv.lock":
        raise EvidenceError("unsupported_git_blob")
    size_bytes = _git_bytes(
        root,
        ("cat-file", "-s", f"{commit_sha}:{path}"),
        maximum=64,
    )
    try:
        size = int(size_bytes.decode("ascii").strip())
    except (UnicodeError, ValueError) as exc:
        raise EvidenceError("git_blob_size") from exc
    if size <= 0 or size > _MAX_GIT_BLOB_BYTES:
        raise EvidenceError("git_blob_size")
    payload = _git_bytes(
        root,
        ("cat-file", "blob", f"{commit_sha}:{path}"),
        maximum=_MAX_GIT_BLOB_BYTES,
    )
    if len(payload) != size:
        raise EvidenceError("git_blob_size_mismatch")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_route(
    contract: SdlcContract,
    route_value: object,
) -> dict[str, object]:
    route = dict(_mapping(route_value, "route"))
    if set(route) != _ROUTE_KEYS:
        raise EvidenceError("route_shape")
    if route.get("schema_version") != _ROUTE_SCHEMA_VERSION:
        raise EvidenceError("route_schema")
    if route.get("contract_version") != contract.contract_version:
        raise EvidenceError("route_contract_version")
    for field in ("base_sha", "head_sha", "base_tree_sha", "head_tree_sha"):
        route[field] = _git_sha(route.get(field), f"route_{field}")
    risk_tier = _string(route.get("risk_tier"), "route_risk", maximum=64)
    if risk_tier not in contract.risk_rank:
        raise EvidenceError("route_risk")
    route["reasons"] = _string_list(
        route.get("reasons"),
        "route_reasons",
        maximum_items=4096,
        maximum_length=512,
        sorted_required=True,
        nonempty=True,
    )
    for field in (
        "core_required",
        "service_required",
        "clustering_required",
        "owner_authority_required",
    ):
        route[field] = _boolean(route.get(field), f"route_{field}")
    if route["core_required"] is not True:
        raise EvidenceError("route_core_required")
    expected_service = contract.service_required(risk_tier)
    if route["service_required"] is not expected_service:
        raise EvidenceError("route_service_required")
    expected_owner = contract.owner_authority_required(risk_tier)
    if route["owner_authority_required"] is not expected_owner:
        raise EvidenceError("route_owner_authority")
    route["core_tests"] = _string_list(
        route.get("core_tests"),
        "route_core_tests",
        maximum_items=100000,
        maximum_length=1024,
        sorted_required=True,
        nonempty=True,
    )
    route["service_tests"] = _string_list(
        route.get("service_tests"),
        "route_service_tests",
        maximum_items=100000,
        maximum_length=1024,
        sorted_required=True,
    )
    if expected_service != bool(route["service_tests"]):
        raise EvidenceError("route_service_tests")
    route["sentinels"] = _string_list(
        route.get("sentinels"),
        "route_sentinels",
        maximum_items=10000,
        maximum_length=1024,
        nonempty=True,
    )
    selected_digest = _sha(
        route.get("selected_test_manifest_digest"),
        "route_selected_manifest",
    )
    expected_digest = sha256_identity(
        {
            "core_tests": route["core_tests"],
            "service_tests": route["service_tests"],
            "sentinels": route["sentinels"],
        }
    )
    if selected_digest != expected_digest:
        raise EvidenceError("route_selected_manifest_mismatch")
    route["selected_test_manifest_digest"] = selected_digest
    return route


def _validate_gate_run(gate_id: str, value: object) -> dict[str, object]:
    run = dict(_mapping(value, "gate_run"))
    if set(run) != _GATE_RUN_KEYS:
        raise EvidenceError("gate_run_shape")
    if run.get("schema_version") != _GATE_RUN_SCHEMA_VERSION:
        raise EvidenceError("gate_run_schema")
    if run.get("gate_id") != gate_id:
        raise EvidenceError("gate_run_id")
    run["phase"] = _string(run.get("phase"), "gate_run_phase", maximum=128)
    result = _string(run.get("result"), "gate_run_result", maximum=64)
    if result not in _RESULTS:
        raise EvidenceError("gate_run_result")
    reason = _string(run.get("result_reason"), "gate_run_reason", maximum=512)
    if _RESULT_REASON.fullmatch(reason) is None or not reason.startswith(result + ":"):
        raise EvidenceError("gate_run_reason")
    returncode = run.get("returncode")
    if returncode is not None and (
        isinstance(returncode, bool) or not isinstance(returncode, int)
    ):
        raise EvidenceError("gate_run_returncode")
    if result == "PASS" and returncode != 0:
        raise EvidenceError("gate_run_pass_returncode")
    if result == "FAIL" and (returncode is None or returncode == 0):
        raise EvidenceError("gate_run_fail_returncode")
    run["execution_ms"] = _nonnegative(run.get("execution_ms"), "execution_ms")
    _text(run.get("stdout"), "gate_run_stdout", maximum=1_048_576)
    _text(run.get("stderr"), "gate_run_stderr", maximum=1_048_576)
    _boolean(run.get("stdout_truncated"), "stdout_truncated")
    _boolean(run.get("stderr_truncated"), "stderr_truncated")
    return run


def _validate_junit(value: object | None) -> dict[str, object] | None:
    if value is None:
        return None
    summary = dict(_mapping(value, "junit"))
    if set(summary) != _JUNIT_KEYS or summary.get("schema_version") != _JUNIT_SCHEMA_VERSION:
        raise EvidenceError("junit_shape")
    outcome = _string(summary.get("outcome"), "junit_outcome", maximum=16)
    if outcome not in {"PASS", "FAIL"}:
        raise EvidenceError("junit_outcome")
    reports = summary.get("reports")
    if not isinstance(reports, list) or not reports or len(reports) > 32:
        raise EvidenceError("junit_reports")
    normalized_reports: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in reports:
        report = _mapping(item, "junit_report")
        if set(report) != {"path", "digest"}:
            raise EvidenceError("junit_report_shape")
        path = _string(report.get("path"), "junit_report_path", maximum=1024)
        digest = _sha(report.get("digest"), "junit_report_digest")
        if path in seen_paths:
            raise EvidenceError("junit_report_duplicate")
        seen_paths.add(path)
        normalized_reports.append({"path": path, "digest": digest})
    if normalized_reports != sorted(normalized_reports, key=lambda item: item["path"]):
        raise EvidenceError("junit_report_order")
    summary["reports"] = normalized_reports
    summary["test_ids_digest"] = _sha(
        summary.get("test_ids_digest"),
        "junit_test_ids_digest",
    )
    for field in (
        "test_count",
        "failure_count",
        "error_count",
        "skip_count",
        "required_skip_count",
        "duration_ms",
    ):
        summary[field] = _nonnegative(summary.get(field), f"junit_{field}")
    if summary["required_skip_count"] > summary["skip_count"]:
        raise EvidenceError("junit_required_skip_count")
    terminal_count = (
        summary["failure_count"] + summary["error_count"] + summary["skip_count"]
    )
    if terminal_count > summary["test_count"]:
        raise EvidenceError("junit_counts")
    fingerprint = _optional_sha(
        summary.get("first_failure_fingerprint"),
        "junit_first_failure",
    )
    summary["first_failure_fingerprint"] = fingerprint
    expected_outcome = (
        "FAIL"
        if summary["failure_count"]
        or summary["error_count"]
        or summary["required_skip_count"]
        else "PASS"
    )
    if outcome != expected_outcome:
        raise EvidenceError("junit_outcome_counts")
    if outcome == "PASS" and fingerprint is not None:
        raise EvidenceError("junit_pass_fingerprint")
    if outcome == "FAIL" and fingerprint is None:
        raise EvidenceError("junit_fail_fingerprint")
    return summary


def _selected_tests(gate_id: str, route: Mapping[str, object]) -> list[str]:
    if gate_id == "service-neo4j":
        return list(route["service_tests"])
    if gate_id in {"core-deterministic", "merge-exact"}:
        return list(route["core_tests"])
    return []


def _identity_inputs(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "repository_tree_sha": record["tree_sha"],
        "base_tree_sha": record["base_tree_sha"],
        "gate_contract_version": record["gate_contract_version"],
        "risk_classifier_version": record["risk_classifier_version"],
        "lockfile_digest": record["lockfile_digest"],
        "toolchain_digest": record["toolchain_digest"],
        "service_compatibility_digest": record["service_compatibility_digest"],
        "selected_test_manifest_digest": record["selected_test_manifest_digest"],
        "gate_inputs_digest": record["gate_inputs_digest"],
    }


def validate_evidence_record(record_value: object) -> dict[str, object]:
    record = dict(_mapping(record_value, "evidence"))
    if set(record) != _EVIDENCE_KEYS:
        raise EvidenceError("evidence_shape")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceError("evidence_schema")
    if record.get("repository") != _REPOSITORY:
        raise EvidenceError("evidence_repository")
    record["evidence_identity"] = _sha(
        record.get("evidence_identity"), "evidence_identity"
    )
    gate_id = _string(record.get("gate_id"), "gate_id", maximum=128)
    if _SAFE_ID.fullmatch(gate_id) is None:
        raise EvidenceError("gate_id")
    for field in ("base_sha", "head_sha", "base_tree_sha", "tree_sha"):
        record[field] = _git_sha(record.get(field), field)
    record["gate_contract_version"] = _string(
        record.get("gate_contract_version"), "gate_contract_version", maximum=128
    )
    record["risk_classifier_version"] = _string(
        record.get("risk_classifier_version"),
        "risk_classifier_version",
        maximum=128,
    )
    risk_tier = _string(record.get("risk_tier"), "risk_tier", maximum=64)
    if risk_tier not in _RISK_TIERS:
        raise EvidenceError("risk_tier")
    record["risk_reasons"] = _string_list(
        record.get("risk_reasons"),
        "risk_reasons",
        maximum_items=4096,
        maximum_length=512,
        sorted_required=True,
        nonempty=True,
    )
    runner_kind = _string(record.get("runner_kind"), "runner_kind", maximum=64)
    if runner_kind not in _RUNNER_KINDS:
        raise EvidenceError("runner_kind")
    for field in (
        "queue_ms",
        "bootstrap_ms",
        "execution_ms",
        "finalize_ms",
        "test_count",
        "failure_count",
        "error_count",
        "skip_count",
        "required_skip_count",
    ):
        record[field] = _nonnegative(record.get(field), field)
    if record["required_skip_count"] > record["skip_count"]:
        raise EvidenceError("required_skip_count")
    if (
        record["failure_count"]
        + record["error_count"]
        + record["skip_count"]
        > record["test_count"]
    ):
        raise EvidenceError("test_counts")
    cache_key = _optional_string(record.get("cache_key"), "cache_key")
    cache_hit = _boolean(record.get("cache_hit"), "cache_hit")
    if cache_hit and cache_key is None:
        raise EvidenceError("cache_hit_without_key")
    record["python_version"] = _string(
        record.get("python_version"), "python_version", maximum=128
    )
    record["uv_version"] = _string(
        record.get("uv_version"), "uv_version", maximum=128
    )
    for field in (
        "lockfile_digest",
        "toolchain_digest",
        "selected_test_manifest_digest",
        "gate_inputs_digest",
    ):
        record[field] = _sha(record.get(field), field)
    record["service_compatibility_digest"] = _optional_sha(
        record.get("service_compatibility_digest"),
        "service_compatibility_digest",
    )
    record["selected_tests"] = _string_list(
        record.get("selected_tests"),
        "selected_tests",
        maximum_items=100000,
        maximum_length=1024,
    )
    record["sentinel_tests"] = _string_list(
        record.get("sentinel_tests"),
        "sentinel_tests",
        maximum_items=10000,
        maximum_length=1024,
        nonempty=True,
    )
    record["random_sample_seed"] = _optional_string(
        record.get("random_sample_seed"),
        "random_sample_seed",
        maximum=256,
    )
    record["random_sample_tests"] = _string_list(
        record.get("random_sample_tests"),
        "random_sample_tests",
        maximum_items=100000,
        maximum_length=1024,
    )
    record["first_failure_fingerprint"] = _optional_sha(
        record.get("first_failure_fingerprint"),
        "first_failure_fingerprint",
    )
    result = _string(record.get("result"), "result", maximum=64)
    if result not in _RESULTS:
        raise EvidenceError("result")
    reason = _string(record.get("result_reason"), "result_reason", maximum=512)
    if _RESULT_REASON.fullmatch(reason) is None or not reason.startswith(result + ":"):
        raise EvidenceError("result_reason")
    record["created_at"] = _created_at(
        _string(record.get("created_at"), "created_at", maximum=64)
    )
    if result == "PASS" and (
        record["failure_count"]
        or record["error_count"]
        or record["required_skip_count"]
        or record["first_failure_fingerprint"] is not None
    ):
        raise EvidenceError("pass_invariant")
    expected_identity = sha256_identity(_identity_inputs(record))
    if record["evidence_identity"] != expected_identity:
        raise EvidenceError("evidence_identity_mismatch")
    return record


def build_gate_evidence(
    *,
    repo_root: str | Path,
    contract: SdlcContract,
    route: object,
    gate_run: object,
    junit_summary: object | None,
    runner_kind: str,
    queue_ms: int,
    bootstrap_ms: int,
    finalize_ms: int,
    cache_key: str | None,
    cache_hit: bool,
    uv_version: str,
    command_spec_digest: str,
    service_compatibility_digest: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    if contract.repo_root != root:
        raise EvidenceError("contract_repository")
    normalized_route = _validate_route(contract, route)
    current_head = resolve_commit(root, "HEAD")
    if current_head != normalized_route["head_sha"]:
        raise EvidenceError("head_mismatch")
    if resolve_tree(root, current_head) != normalized_route["head_tree_sha"]:
        raise EvidenceError("head_tree_mismatch")
    if (
        resolve_tree(root, str(normalized_route["base_sha"]))
        != normalized_route["base_tree_sha"]
    ):
        raise EvidenceError("base_tree_mismatch")

    gate_id = _string(
        _mapping(gate_run, "gate_run").get("gate_id"),
        "gate_id",
        maximum=128,
    )
    if _SAFE_ID.fullmatch(gate_id) is None:
        raise EvidenceError("gate_id")
    accepted_gate_ids = {
        str(value["id"]) for value in contract.data["gate"].values()
    }
    if gate_id not in accepted_gate_ids:
        raise EvidenceError("gate_not_accepted")
    normalized_run = _validate_gate_run(gate_id, gate_run)
    junit = _validate_junit(junit_summary)
    selected_tests = _selected_tests(gate_id, normalized_route)
    if normalized_run["result"] == "PASS" and selected_tests and junit is None:
        raise EvidenceError("junit_required")
    if not selected_tests and junit is not None:
        raise EvidenceError("junit_unexpected")

    if (
        normalized_run["result"] == "PASS"
        and junit is not None
        and junit["outcome"] == "FAIL"
    ):
        result = "FAIL"
        result_reason = f"FAIL:{gate_id}:junit"
    else:
        result = str(normalized_run["result"])
        result_reason = str(normalized_run["result_reason"])

    if junit is None:
        counts = {
            "test_count": 0,
            "failure_count": 0,
            "error_count": 0,
            "skip_count": 0,
            "required_skip_count": 0,
            "first_failure_fingerprint": None,
        }
    else:
        counts = {
            field: junit[field]
            for field in (
                "test_count",
                "failure_count",
                "error_count",
                "skip_count",
                "required_skip_count",
                "first_failure_fingerprint",
            )
        }

    service_digest = _optional_sha(
        service_compatibility_digest,
        "service_compatibility_digest",
    )
    if gate_id == "service-neo4j" and service_digest is None:
        raise EvidenceError("service_compatibility_required")
    if gate_id != "service-neo4j" and service_digest is not None:
        raise EvidenceError("service_compatibility_unexpected")

    actual_python = platform.python_version()
    normalized_uv = _string(uv_version, "uv_version", maximum=128)
    normalized_runner = _string(runner_kind, "runner_kind", maximum=64)
    if normalized_runner not in _RUNNER_KINDS:
        raise EvidenceError("runner_kind")
    lockfile_digest = git_blob_digest(root, current_head, "uv.lock")
    toolchain_digest = sha256_identity(
        {
            "python_implementation": platform.python_implementation(),
            "python_version": actual_python,
            "runner_arch": platform.machine(),
            "runner_os": platform.system().lower(),
            "uv_version": normalized_uv,
        }
    )
    command_digest = _sha(command_spec_digest, "command_spec_digest")
    route_digest = sha256_identity(normalized_route)
    gate_inputs_digest = sha256_identity(
        {
            "command_spec_digest": command_digest,
            "gate_id": gate_id,
            "head_tree_sha": normalized_route["head_tree_sha"],
            "phase": normalized_run["phase"],
            "route_digest": route_digest,
            "selected_test_manifest_digest": normalized_route[
                "selected_test_manifest_digest"
            ],
        }
    )

    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_identity": "",
        "gate_id": gate_id,
        "gate_contract_version": contract.contract_version,
        "risk_classifier_version": contract.classifier_version,
        "repository": _REPOSITORY,
        "base_sha": normalized_route["base_sha"],
        "head_sha": normalized_route["head_sha"],
        "base_tree_sha": normalized_route["base_tree_sha"],
        "tree_sha": normalized_route["head_tree_sha"],
        "risk_tier": normalized_route["risk_tier"],
        "risk_reasons": normalized_route["reasons"],
        "runner_kind": normalized_runner,
        "queue_ms": _nonnegative(queue_ms, "queue_ms"),
        "bootstrap_ms": _nonnegative(bootstrap_ms, "bootstrap_ms"),
        "execution_ms": normalized_run["execution_ms"],
        "finalize_ms": _nonnegative(finalize_ms, "finalize_ms"),
        "cache_key": _optional_string(cache_key, "cache_key"),
        "cache_hit": _boolean(cache_hit, "cache_hit"),
        "python_version": actual_python,
        "uv_version": normalized_uv,
        "lockfile_digest": lockfile_digest,
        "toolchain_digest": toolchain_digest,
        "service_compatibility_digest": service_digest,
        "selected_test_manifest_digest": normalized_route[
            "selected_test_manifest_digest"
        ],
        "gate_inputs_digest": gate_inputs_digest,
        "selected_tests": selected_tests,
        "sentinel_tests": normalized_route["sentinels"],
        "random_sample_seed": None,
        "random_sample_tests": [],
        **counts,
        "result": result,
        "result_reason": result_reason,
        "created_at": _created_at(created_at),
    }
    record["evidence_identity"] = sha256_identity(_identity_inputs(record))
    return validate_evidence_record(record)


def _safe_json_path(root: Path, relative: str, *, output: bool) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in relative
    ):
        raise EvidenceError("json_path")
    path = root / candidate
    current = root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise EvidenceError("json_symlink")
    if not path.resolve().is_relative_to(root):
        raise EvidenceError("json_path")
    if path.suffix != ".json":
        raise EvidenceError("json_extension")
    if output and not path.parent.is_dir():
        raise EvidenceError("output_parent")
    return path


def _load_json(root: Path, relative: str) -> object:
    path = _safe_json_path(root, relative, output=False)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise EvidenceError("json_input") from exc
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= _MAX_JSON_BYTES:
        raise EvidenceError("json_input")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvidenceError("json_input") from exc
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode) or not 0 < current.st_size <= _MAX_JSON_BYTES:
            raise EvidenceError("json_input")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_JSON_BYTES + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > _MAX_JSON_BYTES:
        raise EvidenceError("json_input")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("json_input") from exc


def _write_json(root: Path, relative: str, value: object) -> None:
    path = _safe_json_path(root, relative, output=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise EvidenceError("output_exists") from exc
    except OSError as exc:
        raise EvidenceError("output_open") from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit exact Newsroom SDLC gate evidence")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--route", required=True)
    parser.add_argument("--gate-run", required=True)
    parser.add_argument("--junit-summary")
    parser.add_argument("--runner-kind", required=True)
    parser.add_argument("--queue-ms", type=int, required=True)
    parser.add_argument("--bootstrap-ms", type=int, required=True)
    parser.add_argument("--finalize-ms", type=int, required=True)
    parser.add_argument("--cache-key")
    parser.add_argument("--cache-hit", action="store_true")
    parser.add_argument("--uv-version", required=True)
    parser.add_argument("--command-spec-digest", required=True)
    parser.add_argument("--service-compatibility-digest")
    parser.add_argument("--created-at")
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repo_root).resolve()
    try:
        contract = load_contract(root)
        record = build_gate_evidence(
            repo_root=root,
            contract=contract,
            route=_load_json(root, arguments.route),
            gate_run=_load_json(root, arguments.gate_run),
            junit_summary=(
                _load_json(root, arguments.junit_summary)
                if arguments.junit_summary
                else None
            ),
            runner_kind=arguments.runner_kind,
            queue_ms=arguments.queue_ms,
            bootstrap_ms=arguments.bootstrap_ms,
            finalize_ms=arguments.finalize_ms,
            cache_key=arguments.cache_key,
            cache_hit=arguments.cache_hit,
            uv_version=arguments.uv_version,
            command_spec_digest=arguments.command_spec_digest,
            service_compatibility_digest=arguments.service_compatibility_digest,
            created_at=arguments.created_at,
        )
        if arguments.output:
            _write_json(root, arguments.output, record)
        else:
            sys.stdout.buffer.write(canonical_json_bytes(record) + b"\n")
    except EvidenceError as exc:
        print(f"EVIDENCE_MISMATCH:gate:{str(exc)}", file=sys.stderr)
        return 2
    except (ContractError, GitRouteError, OSError, UnicodeError) as exc:
        print(
            f"EVIDENCE_MISMATCH:gate:{type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
