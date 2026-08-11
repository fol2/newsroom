from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .artifact_envelope import (
    ArtifactProvenanceError,
    _safe_machine_file,
    _unique_object,
    _validate_json_depth,
    artifact_name,
    context_from_environment,
    create_envelope,
    validate_envelope,
)
from .artifact_receipt import ArtifactReceiptError, _validate_command_run
from .classify_change import GitRouteError
from .command_spec import (
    CommandRun,
    CommandSpec,
    CommandSpecError,
    build_environment,
    executable_digest,
    parse_command_spec,
)
from .contracts import ContractError, SdlcContract, load_contract
from .emit_evidence import (
    EvidenceError,
    _validate_junit,
    _validate_route,
    build_gate_evidence,
    canonical_json_bytes,
    git_blob_digest,
    installed_uv_version,
    sha256_identity,
    verify_tracked_checkout,
)
from .junit_evidence import JUnitEvidenceError, JUnitSummary, summarize_junit
from .run_gate import (
    GateRunError,
    GateRunResult,
    LaneDeadline,
    run_configured_gate,
    start_lane_deadline,
)

SCHEMA_VERSION = "newsroom.sdlc.workflow-lane.v1"
_SERVICE_IMAGE = "neo4j:2026.06.0-community-trixie"
_SERVICE_SERVER = "2026.06.0"
_SERVICE_DRIVER = "6.2.0"
_MAX_JSON_BYTES = 8 * 1024 * 1024
_OPTIONAL_CORE_TEST_IDS = (
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_complete_generation_queries_and_promotes_exact_state",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[deleted-document]",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[missing-vector-index]",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-fulltext-analyzer]",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-vector-dimensions]",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_replacement_generation_recovers_from_authority_only",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_revocation_and_tombstone_remove_current_derivatives",
    "newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_wrong_watermark_generation_and_vector_dimension_fail_closed",
    "newsroom.tests.test_increment4e_neo4j_service::test_actual_service_increment4_admitted_state_projects_exactly_and_replays",
    "newsroom.tests.test_increment4e_neo4j_service::test_actual_service_increment4_graph_loss_requires_isolated_replacement",
    "newsroom.tests.test_increment4e_neo4j_service::test_actual_service_increment4_replacement_generation_is_only_serving_state",
    "newsroom.tests.test_increment4e_neo4j_service::test_actual_service_increment4_tombstone_purges_and_never_resurrects",
    "newsroom.tests.test_increment5b4_neo4j_service::test_increment5b4_fixed_port_excludes_future_observations",
    "newsroom.tests.test_increment5b4_neo4j_service::test_increment5b4_fixed_port_reads_only_exact_generation_and_allowed_state",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_increment_2_proof_admits_replays_and_restarts",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[fulltext]",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[relation]",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[vector]",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_dead_letter_blocks_complete_candidate_proof",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_governed_deletion_purges_derivative_and_never_requalifies",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_relation_revocation_changes_later_context_without_rewrite",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_replacement_generation_deduplicates_candidate_authority",
    "newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_required_gap_blocks_complete_candidate_proof",
    "newsroom.tests.test_integrated_c1_neo4j_service::test_actual_service_integrated_foundation_replay_recovery_and_tombstone",
    "newsroom.tests.test_projection_b2_increment5e2_neo4j_service::test_actual_service_increment5e2_target_and_report",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_public_round_trip_duplicate_and_generation_isolation",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_requires_explicit_authentication_configuration",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_wrong_projector_credential_fails_closed_without_secret",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_3e_projects_complete_lineage_and_recovers_graph_loss",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_3e_replacement_generation_becomes_only_active_lineage",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_active_generation_revalidates_after_incremental_delivery",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_active_read_resolves_only_authority_promoted_generation",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_promotion_rejects_graph_loss_after_validation",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
    "newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_executes_all_four_branches_and_hydrates_authority",
    "newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_admitted_relation_is_incomplete_not_no_match",
    "newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_fulltext_index_is_unavailable_not_no_match",
    "newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_vector_index_is_unavailable_not_no_match",
)
_SERVICE_CONFIGURATION = {
    "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED": "1",
    "NEWSROOM_NEO4J_DATABASE": "neo4j",
    "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED": "1",
    "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",
    "NEWSROOM_NEO4J_USER": "newsroom_projector",
    "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED": "1",
    "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
    "NEWSROOM_NEO4J_URI": "bolt://localhost:7687",
}
_CORE_TESTS = ("newsroom/tests",)
_CORE_WORKER_COUNT = 2
_CORE_SHARD_COUNT = 10
_CORE_DISTRIBUTION = "worksteal"
_CORE_FRAGMENT_SCHEMA = "newsroom.sdlc.core-shard-fragment.v1"
_CORE_SHARD_LIFECYCLE_SCHEMA = "newsroom.sdlc.core-shard-lifecycle.v1"
_SOURCE_FRAGMENT_SCHEMA = "newsroom.sdlc.source-fragment.v1"
_SOURCE_LIFECYCLE_SCHEMA = "newsroom.sdlc.source-fragment-lifecycle.v1"
_LIFECYCLE_RESULTS = frozenset(
    [
        "PASS",
        "FAIL",
        "BUDGET_EXCEEDED",
        "CLASSIFIER_ERROR",
        "ENVIRONMENT_ERROR",
        "EVIDENCE_MISMATCH",
        "UNAUTHORISED_EFFECT",
    ]
)
_FRAGMENT_PROVENANCE_KEYS = frozenset(
    {
        "contract_version",
        "contract_digest",
        "lockfile_digest",
        "python_version",
        "uv_version",
        "toolchain_digest",
    }
)
_CORE_FRAGMENT_KEYS = (
    frozenset(
        "schema_version run_id run_attempt job_id evaluated_sha evaluated_tree_sha "  # noqa: SIM905
        "route_digest shard_index shard_count file_inventory file_inventory_digest "
        "node_inventory node_inventory_digest selected_node_ids selected_node_ids_digest "
        "command_spec command_run shard_lifecycle junit_summary report_digest "
        "fragment_identity".split()
    )
    | _FRAGMENT_PROVENANCE_KEYS
)
_SOURCE_FRAGMENT_KEYS = (
    frozenset(
        "schema_version run_id run_attempt job_id evaluated_sha evaluated_tree_sha "  # noqa: SIM905
        "route_digest command_spec command_run source_lifecycle fragment_identity".split()
    )
    | _FRAGMENT_PROVENANCE_KEYS
)
_CACHE_KEY_ENV = "NEWSROOM_SDLC_CACHE_KEY"
_CACHE_HIT_ENV = "NEWSROOM_SDLC_CACHE_HIT"
_MAX_CACHE_KEY_CHARS = 512
_SERVICE_SHARD_COUNT = 2
_SERVICE_PYTEST_OPTIONS = (
    "-q",
    "--assert=plain",
    "-p",
    "no:cacheprovider",
)


class WorkflowLaneError(ValueError):
    """Raised when a workflow lane cannot produce exact evidence."""


@dataclass(frozen=True)
class LaneExecutionOutput:
    lane_id: str
    artifact_name: str
    gate_results: tuple[tuple[str, str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.sdlc.workflow-lane-execution.v1",
            "lane_id": self.lane_id,
            "artifact_name": self.artifact_name,
            "gate_results": [
                {"gate_id": gate, "phase": phase, "result": result}
                for gate, phase, result in self.gate_results
            ],
        }


@dataclass(frozen=True)
class LaneOutput:
    lane_id: str
    artifact_name: str
    envelope_identity: str
    gate_results: tuple[tuple[str, str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "lane_id": self.lane_id,
            "artifact_name": self.artifact_name,
            "envelope_identity": self.envelope_identity,
            "gate_results": [
                {"gate_id": gate, "phase": phase, "result": result}
                for gate, phase, result in self.gate_results
            ],
        }


def service_compatibility_digest() -> str:
    return sha256_identity(
        {
            "database": _SERVICE_CONFIGURATION["NEWSROOM_NEO4J_DATABASE"],
            "driver_version": _SERVICE_DRIVER,
            "edition": "community",
            "image": _SERVICE_IMAGE,
            "projector_username": _SERVICE_CONFIGURATION[
                "NEWSROOM_NEO4J_PROJECTOR_USERNAME"
            ],
            "server_version": _SERVICE_SERVER,
            "uri": _SERVICE_CONFIGURATION["NEWSROOM_NEO4J_URI"],
        }
    )


def _load_json(root: Path, value: str | Path) -> object:
    candidate = Path(value)
    absolute = candidate if candidate.is_absolute() else root / candidate
    absolute = absolute if absolute.is_absolute() else absolute.absolute()
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise WorkflowLaneError("input_path") from exc
    if not resolved.is_relative_to(root):
        raise WorkflowLaneError("input_path")
    try:
        payload = _safe_machine_file(
            absolute, maximum=_MAX_JSON_BYTES, code="input_file"
        )
        parsed = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(parsed)
    except (
        ArtifactProvenanceError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise WorkflowLaneError("input_json") from exc
    if payload != canonical_json_bytes(parsed) + b"\n":
        raise WorkflowLaneError("input_canonical")
    return parsed


def _private_write(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise WorkflowLaneError("output_exists")
    payload = canonical_json_bytes(value) + b"\n"
    descriptor = -1
    temporary: Path | None = None
    linked = False
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(raw_name)
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb", closefd=True)
        descriptor = -1
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
            linked = True
            directory = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except FileExistsError as exc:
            raise WorkflowLaneError("output_exists") from exc
        except OSError as exc:
            if linked:
                path.unlink(missing_ok=True)
            raise WorkflowLaneError("output_publish") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _prepare_artifact_root(repo_root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
    ):
        raise WorkflowLaneError("artifact_root")
    current = repo_root
    for part in candidate.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise WorkflowLaneError("artifact_root")
    parent = current.resolve()
    if not parent.is_relative_to(repo_root) or not parent.is_dir():
        raise WorkflowLaneError("artifact_root")
    target = current / candidate.name
    if target.exists() or target.is_symlink():
        raise WorkflowLaneError("artifact_root_exists")
    target.mkdir(mode=0o700)
    return target.resolve()


def _static_environment() -> dict[str, str]:
    values = {
        "CI": "true",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
    }
    for name in ("HOME", "RUNNER_TEMP", "TMPDIR", "UV_CACHE_DIR"):
        value = os.environ.get(name)
        if value:
            values[name] = value
    return values


def _portable_static_environment() -> dict[str, str]:
    values = _static_environment()
    for name in ("HOME", "RUNNER_TEMP", "TMPDIR", "UV_CACHE_DIR"):
        values.pop(name, None)
    return values


def _cache_evidence(
    environment: Mapping[str, str] | None = None,
) -> tuple[str | None, bool]:
    source = os.environ if environment is None else environment
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in source.items()
    ):
        raise WorkflowLaneError("cache_environment")
    raw_key = source.get(_CACHE_KEY_ENV, "")
    raw_hit = source.get(_CACHE_HIT_ENV, "false")
    if (
        len(raw_key) > _MAX_CACHE_KEY_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_key)
        or raw_hit not in {"true", "false"}
    ):
        raise WorkflowLaneError("cache_environment")
    key = raw_key or None
    hit = raw_hit == "true"
    if hit and key is None:
        raise WorkflowLaneError("cache_environment")
    return key, hit


def _uv_command(*arguments: str) -> list[str]:
    executable = shutil.which("uv")
    if executable is None:
        raise WorkflowLaneError("uv_executable")
    path = Path(executable)
    if not path.is_absolute():
        raise WorkflowLaneError("uv_executable")
    return [path.as_posix(), "run", "--no-sync", "python", *arguments]


def _spec(
    *,
    contract: SdlcContract,
    gate_id: str,
    phase: str,
    argv: Sequence[str],
    static_env: Mapping[str, str],
    pass_env: Sequence[str] = (),
) -> CommandSpec:
    resolved, digest = executable_digest(argv[0])
    value = {
        "schema_version": "newsroom.sdlc.command-spec.v1",
        "gate_id": gate_id,
        "phase": phase,
        "argv": [resolved, *argv[1:]],
        "cwd": ".",
        "static_env": dict(static_env),
        "pass_env": sorted(pass_env),
        "redact_env": sorted(pass_env),
        "executable_digest": digest,
        "output_limit_bytes": 1_048_576,
        "termination_grace_ms": 500,
    }
    return parse_command_spec(value, contract=contract)


def _service_environment() -> dict[str, str]:
    if any(
        os.environ.get(name) != value for name, value in _SERVICE_CONFIGURATION.items()
    ):
        raise WorkflowLaneError("service_configuration")
    return dict(_SERVICE_CONFIGURATION)


def _repository_service_tests(repo_root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(repo_root).as_posix()
            for path in (repo_root / "newsroom" / "tests").glob(
                "test_*_neo4j_service.py"
            )
            if path.is_file() and not path.is_symlink()
        )
    )


def _validate_test_topology(
    contract: SdlcContract,
    route: Mapping[str, object],
) -> None:
    expected_service = (
        _repository_service_tests(contract.repo_root)
        if route["service_required"] is True
        else ()
    )
    if (
        tuple(route["core_tests"]) != _CORE_TESTS
        or tuple(route["service_tests"]) != expected_service
        or tuple(route["sentinels"]) != tuple(contract.sentinels)
        or (route["service_required"] is True and not expected_service)
    ):
        raise WorkflowLaneError("test_topology")


def _expected_spec(
    *,
    root: Path,
    artifact_root: Path,
    contract: SdlcContract,
    route: Mapping[str, object],
    gate_id: str,
    phase: str,
) -> CommandSpec:
    key = (gate_id, phase)
    environment = (
        _portable_static_environment()
        if key
        in {
            ("source-integrity", "source"),
            ("core-deterministic", "tests"),
        }
        else _static_environment()
    )
    pass_env: Sequence[str] = ()
    if key == ("source-integrity", "source"):
        argv: list[str] = _uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "source-check",
            "--repo-root",
            ".",
            "--base-sha",
            str(route["base_sha"]),
            "--head-sha",
            str(route["head_sha"]),
        )
    elif key == ("core-deterministic", "tests"):
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        report = artifact_root / "gates" / gate_id / phase / "reports" / "pytest.xml"
        argv = _uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "core-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
        )
        if route["clustering_required"]:
            argv.append("--clustering")
    elif key == ("service-neo4j", "tests"):
        report = artifact_root / "gates" / gate_id / phase / "reports" / "pytest.xml"
        environment.update(_service_environment())
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        pass_env = (
            "NEWSROOM_NEO4J_PASSWORD",
            "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",
        )
        argv = _uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "service-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
            *[str(item) for item in route["service_tests"]],
        )
    else:
        raise WorkflowLaneError("gate_identity")
    return _spec(
        contract=contract,
        gate_id=gate_id,
        phase=phase,
        argv=argv,
        static_env=environment,
        pass_env=pass_env,
    )


def _execute(
    *,
    contract: SdlcContract,
    spec: CommandSpec,
    deadline: LaneDeadline,
) -> CommandRun:
    validated = parse_command_spec(spec.as_dict(), contract=contract)
    if validated != spec:
        raise WorkflowLaneError("command_spec")
    environment = build_environment(validated, os.environ)
    result = run_configured_gate(
        contract=contract,
        gate_id=validated.gate_id,
        phase=validated.phase,
        argv=validated.argv,
        deadline=deadline,
        cwd=contract.repo_root,
        env=environment,
        redact_values=tuple(
            environment[name] for name in validated.redact_env if environment[name]
        ),
        output_limit_bytes=validated.output_limit_bytes,
        termination_grace_seconds=validated.termination_grace_ms / 1000.0,
    )
    return CommandRun(validated.digest, result)


def _gate_directory(artifact_root: Path, gate_id: str, phase: str) -> Path:
    path = artifact_root / "gates" / gate_id / phase
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def _report_summary(
    *,
    repo_root: Path,
    artifact_root: Path,
    report: Path,
    optional_test_ids: Sequence[str],
) -> JUnitSummary | None:
    if not report.is_file():
        return None
    try:
        repository_relative = report.relative_to(repo_root).as_posix()
        artifact_relative = report.relative_to(artifact_root).as_posix()
    except ValueError as exc:
        raise WorkflowLaneError("report_path") from exc
    summary = summarize_junit(
        repo_root,
        (repository_relative,),
        optional_test_ids=optional_test_ids,
    )
    if (
        len(summary.report_digests) != 1
        or summary.report_digests[0][0] != repository_relative
    ):
        raise WorkflowLaneError("report_summary")
    return JUnitSummary(
        outcome=summary.outcome,
        report_digests=((artifact_relative, summary.report_digests[0][1]),),
        test_ids_digest=summary.test_ids_digest,
        test_count=summary.test_count,
        failure_count=summary.failure_count,
        error_count=summary.error_count,
        skip_count=summary.skip_count,
        required_skip_count=summary.required_skip_count,
        duration_ms=summary.duration_ms,
        first_failure_fingerprint=summary.first_failure_fingerprint,
    )


def _discard_incomplete_shard_reports(
    *,
    report: Path,
    shard_count: int,
) -> None:
    if (
        isinstance(shard_count, bool)
        or not isinstance(shard_count, int)
        or shard_count <= 0
    ):
        raise WorkflowLaneError("shard_report_count")
    expected = frozenset(
        report.with_name(f"{report.stem}-shard-{index:02d}{report.suffix}")
        for index in range(shard_count)
    )
    candidates = tuple(
        sorted(report.parent.glob(f"{report.stem}-shard-*{report.suffix}"))
    )
    if any(path not in expected for path in candidates):
        raise WorkflowLaneError("shard_report_identity")
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            raise WorkflowLaneError("shard_report_cleanup")
        try:
            path.unlink()
        except OSError as exc:
            raise WorkflowLaneError("shard_report_cleanup") from exc


def _evidence(
    *,
    repo_root: Path,
    contract: SdlcContract,
    route: object,
    command_run: Mapping[str, object],
    summary: JUnitSummary | None,
    runner_kind: str,
    service_digest: str | None,
) -> dict[str, object]:
    gate_run = command_run.get("gate_run")
    command_digest = command_run.get("command_spec_digest")
    if not isinstance(gate_run, dict) or not isinstance(command_digest, str):
        raise WorkflowLaneError("command_run")
    cache_key, cache_hit = _cache_evidence()
    return build_gate_evidence(
        repo_root=repo_root,
        contract=contract,
        route=route,
        gate_run=gate_run,
        junit_summary=None if summary is None else summary.as_dict(),
        runner_kind=runner_kind,
        queue_ms=0,
        bootstrap_ms=0,
        finalize_ms=0,
        cache_key=cache_key,
        cache_hit=cache_hit,
        uv_version=installed_uv_version(),
        command_spec_digest=command_digest,
        service_compatibility_digest=service_digest,
    )


def _run_core(
    *,
    root: Path,
    artifact_root: Path,
    contract: SdlcContract,
    route: Mapping[str, object],
) -> tuple[tuple[str, str, CommandRun, JUnitSummary | None, Path], ...]:
    source_dir = _gate_directory(artifact_root, "source-integrity", "source")
    test_dir = _gate_directory(artifact_root, "core-deterministic", "tests")
    reports = test_dir / "reports"
    reports.mkdir(mode=0o700)
    deadline = start_lane_deadline(contract, "source-integrity")
    source_spec = _expected_spec(
        root=root,
        artifact_root=artifact_root,
        contract=contract,
        route=route,
        gate_id="source-integrity",
        phase="source",
    )
    test_spec = _expected_spec(
        root=root,
        artifact_root=artifact_root,
        contract=contract,
        route=route,
        gate_id="core-deterministic",
        phase="tests",
    )
    # Both gates are independent reads over the exact checked-out tree. Running
    # them concurrently preserves the single immutable lane deadline while
    # preventing the short source-integrity gate from consuming part of the
    # deterministic-suite command budget. Each gate still receives the same
    # deadline object and produces its own command/evidence record.
    with ThreadPoolExecutor(max_workers=2) as executor:
        source_future = executor.submit(
            _execute,
            contract=contract,
            spec=source_spec,
            deadline=deadline,
        )
        test_future = executor.submit(
            _execute,
            contract=contract,
            spec=test_spec,
            deadline=deadline,
        )
        source_run = source_future.result()
        test_run = test_future.result()
    return (
        ("source-integrity", "source", source_run, None, source_dir),
        ("core-deterministic", "tests", test_run, None, test_dir),
    )


def _run_service(
    *,
    root: Path,
    artifact_root: Path,
    contract: SdlcContract,
    route: Mapping[str, object],
) -> tuple[tuple[str, str, CommandRun, JUnitSummary | None, Path], ...]:
    if route["service_required"] is not True:
        raise WorkflowLaneError("service_not_required")
    gate_dir = _gate_directory(artifact_root, "service-neo4j", "tests")
    reports = gate_dir / "reports"
    reports.mkdir(mode=0o700)
    spec = _expected_spec(
        root=root,
        artifact_root=artifact_root,
        contract=contract,
        route=route,
        gate_id="service-neo4j",
        phase="tests",
    )
    deadline = start_lane_deadline(contract, "service-neo4j")
    run = _execute(contract=contract, spec=spec, deadline=deadline)
    return (("service-neo4j", "tests", run, None, gate_dir),)


def _context_route(
    *,
    root: Path,
    route_path: str | Path,
    lane_id: str,
) -> tuple[SdlcContract, object, dict[str, object]]:
    contract = load_contract(root)
    context = context_from_environment(root)
    if lane_id not in {"core", "service"} or context.job_id != lane_id:
        raise WorkflowLaneError("lane_identity")
    route = _validate_route(contract, _load_json(root, route_path))
    _validate_test_topology(contract, route)
    if (
        route["head_sha"] != context.evaluated_sha
        or route["head_tree_sha"] != context.evaluated_tree_sha
    ):
        raise WorkflowLaneError("route_identity")
    return contract, context, route


def _existing_artifact_root(repo_root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
    ):
        raise WorkflowLaneError("artifact_root")
    current = repo_root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise WorkflowLaneError("artifact_root")
    resolved = current.resolve()
    if not resolved.is_relative_to(repo_root) or not resolved.is_dir():
        raise WorkflowLaneError("artifact_root")
    return resolved


def _layout(
    artifact_root: Path, lane_id: str
) -> tuple[tuple[str, str, Path, Path], ...]:
    if lane_id == "core":
        values = (
            ("source-integrity", "source", False),
            ("core-deterministic", "tests", True),
        )
    elif lane_id == "service":
        values = (("service-neo4j", "tests", True),)
    else:
        raise WorkflowLaneError("lane_identity")
    return tuple(
        (
            gate_id,
            phase,
            artifact_root / "gates" / gate_id / phase / "command-run.json",
            artifact_root / "gates" / gate_id / phase / "reports" / "pytest.xml",
        )
        for gate_id, phase, _ in values
    )


def execute_lane(
    *,
    repo_root: str | Path,
    route_path: str | Path,
    lane_id: str,
    artifact_root: str | Path,
) -> LaneExecutionOutput:
    root = Path(repo_root).resolve()
    contract, context, route = _context_route(
        root=root, route_path=route_path, lane_id=lane_id
    )
    output = _prepare_artifact_root(root, artifact_root)
    complete = False
    try:
        _private_write(output / "route.json", route)
        selected = (
            _run_core(root=root, artifact_root=output, contract=contract, route=route)
            if lane_id == "core"
            else _run_service(
                root=root, artifact_root=output, contract=contract, route=route
            )
        )
        gate_results: list[tuple[str, str, str]] = []
        for gate_id, phase, run, _summary, gate_dir in selected:
            run_path = gate_dir / "command-run.json"
            _private_write(run_path, run.as_dict())
            gate_results.append((gate_id, phase, run.gate_run.result))
        complete = True
        return LaneExecutionOutput(
            lane_id, artifact_name(context), tuple(sorted(gate_results))
        )
    finally:
        if not complete:
            shutil.rmtree(output, ignore_errors=True)


def finalize_lane(
    *,
    repo_root: str | Path,
    route_path: str | Path,
    lane_id: str,
    artifact_root: str | Path,
) -> LaneOutput:
    root = Path(repo_root).resolve()
    contract, context, route = _context_route(
        root=root, route_path=route_path, lane_id=lane_id
    )
    output = _existing_artifact_root(root, artifact_root)
    retained_route = _validate_route(contract, _load_json(root, output / "route.json"))
    if retained_route != route:
        raise WorkflowLaneError("route_changed")
    files: list[tuple[str, str]] = [("route", "route.json")]
    gate_results: list[tuple[str, str, str]] = []
    optional = _OPTIONAL_CORE_TEST_IDS if lane_id == "core" else ()
    prepared: list[tuple[Path, object]] = []
    for gate_id, phase, run_path, report in _layout(output, lane_id):
        try:
            command_run = _validate_command_run(_load_json(root, run_path))
        except ArtifactReceiptError as exc:
            raise WorkflowLaneError("command_run") from exc
        gate_run = command_run["gate_run"]
        if gate_run["gate_id"] != gate_id or gate_run["phase"] != phase:
            raise WorkflowLaneError("command_run_identity")
        expected = _expected_spec(
            root=root,
            artifact_root=output,
            contract=contract,
            route=route,
            gate_id=gate_id,
            phase=phase,
        )
        if command_run["command_spec_digest"] != expected.digest:
            raise WorkflowLaneError("command_spec_digest")
        files.append(("command_run", run_path.relative_to(output).as_posix()))
        if gate_id == "service-neo4j":
            _discard_incomplete_shard_reports(
                report=report,
                shard_count=_SERVICE_SHARD_COUNT,
            )
        summary = _report_summary(
            repo_root=root,
            artifact_root=output,
            report=report,
            optional_test_ids=optional,
        )
        if summary is not None:
            summary_path = run_path.parent / "junit-summary.json"
            prepared.append((summary_path, summary.as_dict()))
            files.append(("junit_summary", summary_path.relative_to(output).as_posix()))
        evidence = _evidence(
            repo_root=root,
            contract=contract,
            route=route,
            command_run=command_run,
            summary=summary,
            runner_kind=context.runner_environment,
            service_digest=(
                service_compatibility_digest() if lane_id == "service" else None
            ),
        )
        evidence_path = run_path.parent / "gate-evidence.json"
        prepared.append((evidence_path, evidence))
        files.append(("gate_evidence", evidence_path.relative_to(output).as_posix()))
        gate_results.append((gate_id, phase, str(evidence["result"])))

    created: list[Path] = []
    try:
        for path, value in prepared:
            _private_write(path, value)
            created.append(path)
        envelope = create_envelope(
            repo_root=root, artifact_root=output, context=context, files=files
        )
        validate_envelope(envelope.as_dict())
        envelope_path = output / "envelope.json"
        _private_write(envelope_path, envelope.as_dict())
        created.append(envelope_path)
        return LaneOutput(
            lane_id,
            artifact_name(context),
            envelope.envelope_identity,
            tuple(sorted(gate_results)),
        )
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def _run_subprocess(argv: Sequence[str]) -> int:
    completed = subprocess.run(tuple(argv), check=False)
    return completed.returncode


def source_check(*, repo_root: str | Path, base_sha: str, head_sha: str) -> int:
    root = Path(repo_root).resolve()
    load_contract(root)
    for directory in (root / "newsroom", root / "scripts"):
        for path in sorted(directory.rglob("*.py")):
            if path.is_symlink() or not path.is_file():
                raise WorkflowLaneError("source_file")
            compile(
                path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True
            )
    commands = (
        ("uv", "lock", "--check"),
        ("git", "diff", "--check", base_sha, head_sha, "--"),
    )
    for command in commands:
        code = _run_subprocess(command)
        if code:
            return code
    return 0


def _core_test_files(root: Path) -> tuple[str, ...]:
    test_root = root / "newsroom" / "tests"
    if test_root.is_symlink() or not test_root.is_dir():
        raise WorkflowLaneError("core_test_root")
    values: list[str] = []
    for path in sorted(test_root.rglob("test_*.py")):
        if path.is_symlink() or not path.is_file():
            raise WorkflowLaneError("core_test_file")
        values.append(path.relative_to(root).as_posix())
    if len(values) < _CORE_WORKER_COUNT:
        raise WorkflowLaneError("core_test_count")
    return tuple(values)


def _collect_core_node_ids(
    root: Path, *, deadline: LaneDeadline | None = None
) -> tuple[str, ...]:
    command = (
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
        "--rootdir=.",
        *_CORE_TESTS,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True,
            text=True,
            check=False,
            timeout=None if deadline is None else deadline.remaining_seconds(),
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowLaneError(
            "BUDGET_EXCEEDED:core-deterministic:collection"
        ) from exc
    except OSError as exc:
        raise WorkflowLaneError("core_collection") from exc
    if completed.returncode:
        raise WorkflowLaneError("core_collection")
    files = frozenset(_core_test_files(root))
    values = tuple(
        sorted(
            line.strip()
            for line in completed.stdout.splitlines()
            if "::" in line and line.strip().split("::", 1)[0] in files
        )
    )
    if (
        not values
        or len(values) != len(set(values))
        or any(node_id.split("::", 1)[0] not in files for node_id in values)
    ):
        raise WorkflowLaneError("core_collection")
    return values


def _core_node_shards(node_ids: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    inventory = tuple(sorted(node_ids))
    if not inventory or len(inventory) != len(set(inventory)):
        raise WorkflowLaneError("core_node_inventory")
    ordered = sorted(
        inventory,
        key=lambda value: (hashlib.sha256(value.encode("utf-8")).digest(), value),
    )
    shards = tuple(
        tuple(sorted(ordered[index::_CORE_SHARD_COUNT]))
        for index in range(_CORE_SHARD_COUNT)
    )
    flattened = tuple(item for shard in shards for item in shard)
    if (
        any(not shard for shard in shards)
        or len(flattened) != len(set(flattened))
        or tuple(sorted(flattened)) != inventory
        or max(map(len, shards)) - min(map(len, shards)) > 1
    ):
        raise WorkflowLaneError("core_node_coverage")
    return shards


def _core_worker_command(
    *,
    report: Path,
    basetemp: Path,
    test_files: Sequence[str] = _CORE_TESTS,
) -> tuple[str, ...]:
    test_paths = tuple(test_files)
    if not test_paths or len(test_paths) != len(set(test_paths)):
        raise WorkflowLaneError("core_test_topology")
    return (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
        "-p",
        "xdist.plugin",
        "-n",
        str(_CORE_WORKER_COUNT),
        f"--dist={_CORE_DISTRIBUTION}",
        "--max-worker-restart=0",
        *test_paths,
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


def _core_shard_spec(
    *,
    contract: SdlcContract,
    shard_index: int,
    node_inventory: Sequence[str],
    selected_node_ids: Sequence[str],
    report: Path,
    basetemp: Path,
    clustering: bool,
) -> CommandSpec:
    inventory = tuple(node_inventory)
    selected = tuple(selected_node_ids)
    if (
        shard_index not in range(_CORE_SHARD_COUNT)
        or inventory != tuple(sorted(inventory))
        or len(inventory) != len(set(inventory))
        or selected != _core_node_shards(inventory)[shard_index]
    ):
        raise WorkflowLaneError("core_shard_index")
    environment = _portable_static_environment()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return _spec(
        contract=contract,
        gate_id="core-deterministic",
        phase="tests",
        argv=_uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "core-shard-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(contract.repo_root).as_posix(),
            "--basetemp",
            basetemp.relative_to(contract.repo_root).as_posix(),
            "--shard-index",
            str(shard_index),
            "--node-inventory-digest",
            sha256_identity(list(inventory)),
            "--selected-node-ids-digest",
            sha256_identity(list(selected)),
            *(("--clustering",) if clustering else ()),
        ),
        static_env=environment,
    )


def _source_fragment_spec(
    *, contract: SdlcContract, route: Mapping[str, object]
) -> CommandSpec:
    return _spec(
        contract=contract,
        gate_id="source-integrity",
        phase="source",
        argv=_uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "source-check",
            "--repo-root",
            ".",
            "--base-sha",
            str(route["base_sha"]),
            "--head-sha",
            str(route["head_sha"]),
        ),
        static_env=_portable_static_environment(),
    )


def _file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise WorkflowLaneError("fragment_report")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fragment_identity(value: Mapping[str, object]) -> str:
    return sha256_identity(value)


def _fragment_provenance(*, contract: SdlcContract, context: object) -> dict[str, str]:
    python_version = platform.python_version()
    uv_version = installed_uv_version()
    return {
        "contract_version": contract.contract_version,
        "contract_digest": _file_digest(contract.source_path),
        "lockfile_digest": git_blob_digest(
            contract.repo_root,
            str(context.evaluated_sha),
            "uv.lock",
        ),
        "python_version": python_version,
        "uv_version": uv_version,
        "toolchain_digest": sha256_identity(
            {
                "python_implementation": platform.python_implementation(),
                "python_version": python_version,
                "runner_arch": platform.machine(),
                "runner_os": platform.system().lower(),
                "uv_version": uv_version,
            }
        ),
    }


def _core_timeout_ms(contract: SdlcContract) -> int:
    core = contract.data["lanes"]["core"]
    return int(core["per_shard_hard_timeout_seconds"] * 1000)


def _deadline_elapsed_ms(deadline: LaneDeadline) -> int:
    return max(0, (time.monotonic_ns() - deadline.started_ns) // 1_000_000)


def _require_deadline(deadline: LaneDeadline, phase: str) -> None:
    if _deadline_elapsed_ms(deadline) >= deadline.timeout_ms:
        raise WorkflowLaneError(f"BUDGET_EXCEEDED:core-deterministic:{phase}")


def _checked_fragment_write(
    root: Path,
    path: Path,
    value: object,
    deadline: LaneDeadline,
    head_sha: str,
    stage: bool = False,
) -> int:
    target = path.with_name(f".{path.name}.stage") if stage else path
    published = False
    try:
        _private_write(target, value)
        verify_tracked_checkout(root, head_sha)
        published = True
        return _deadline_elapsed_ms(deadline)
    finally:
        if stage or not published:
            target.unlink(missing_ok=True)


def _valid_elapsed_ms(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _lifecycle_result(result: str, *, elapsed_ms: int, timeout_ms: int) -> str:
    if result not in _LIFECYCLE_RESULTS:
        raise WorkflowLaneError("core_lifecycle_result")
    if not timeout_ms or not all(map(_valid_elapsed_ms, (elapsed_ms, timeout_ms))):
        raise WorkflowLaneError("core_lifecycle_time")
    if result not in {"PASS", "FAIL", "BUDGET_EXCEEDED"}:
        return result
    if result == "BUDGET_EXCEEDED" or elapsed_ms > timeout_ms:
        return "BUDGET_EXCEEDED"
    return result


def _producer_exit_status(
    fragment: object,
    *,
    fragment_schema: str,
    lifecycle_field: str,
    lifecycle_schema: str,
    gate_id: str,
    phase: str,
    fragment_keys: frozenset[str],
    expected_timeout_ms: int,
) -> int:
    if type(fragment) is not dict:
        raise WorkflowLaneError("producer_fragment")
    if frozenset(fragment) != fragment_keys:
        raise WorkflowLaneError("producer_fragment_shape")
    schema = fragment.get("schema_version")
    if type(schema) is not str or schema != fragment_schema:
        raise WorkflowLaneError("producer_fragment_schema")
    identity = fragment.get("fragment_identity")
    unsigned = dict(fragment)
    unsigned.pop("fragment_identity", None)
    if type(identity) is not str or identity != _fragment_identity(unsigned):
        raise WorkflowLaneError("producer_fragment_identity")
    try:
        command = _validate_command_run(fragment.get("command_run"))
    except ArtifactReceiptError as exc:
        raise WorkflowLaneError("producer_fragment_run") from exc
    gate_run = command["gate_run"]
    if gate_run["gate_id"] != gate_id or gate_run["phase"] != phase:
        raise WorkflowLaneError("producer_fragment_run_identity")
    lifecycle = fragment.get(lifecycle_field)
    if type(lifecycle) is not dict:
        raise WorkflowLaneError("producer_fragment_lifecycle")
    if (
        set(lifecycle) != {"schema_version", "elapsed_ms", "timeout_ms", "result"}
        or type(lifecycle.get("schema_version")) is not str
        or type(lifecycle.get("elapsed_ms")) is not int
        or type(lifecycle.get("timeout_ms")) is not int
        or type(lifecycle.get("result")) is not str
    ):
        raise WorkflowLaneError("producer_fragment_lifecycle")
    validated = _validate_shard_lifecycle(
        lifecycle,
        command_result=str(gate_run["result"]),
        command_execution_ms=int(gate_run["execution_ms"]),
        timeout_ms=expected_timeout_ms,
        schema_version=lifecycle_schema,
        error="producer_fragment_lifecycle",
    )
    result = str(validated["result"])
    if fragment_schema == _CORE_FRAGMENT_SCHEMA:
        try:
            junit = _validate_junit(fragment.get("junit_summary"))
        except EvidenceError as exc:
            raise WorkflowLaneError("producer_fragment_junit") from exc
        if result in {"PASS", "FAIL"}:
            if junit is None:
                raise WorkflowLaneError("producer_fragment_junit_required")
        elif junit is not None:
            raise WorkflowLaneError("producer_fragment_junit_unexpected")
        if result == "PASS" and junit is not None and junit["outcome"] == "FAIL":
            return 1
    if result == "PASS":
        return 0
    if result == "BUDGET_EXCEEDED":
        return 124
    return 1


def _shard_lifecycle(
    *,
    command_result: str,
    elapsed_ms: int,
    timeout_ms: int,
    schema_version: str = _CORE_SHARD_LIFECYCLE_SCHEMA,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "elapsed_ms": elapsed_ms,
        "timeout_ms": timeout_ms,
        "result": _lifecycle_result(
            command_result,
            elapsed_ms=elapsed_ms,
            timeout_ms=timeout_ms,
        ),
    }


def _publish_lifecycle_fragment(
    *,
    root: Path,
    path: Path,
    body: dict[str, object],
    field: str,
    schema: str,
    command_result: str,
    deadline: LaneDeadline,
    head_sha: str,
    on_budget: Callable[[], None] | None = None,
) -> dict[str, object]:
    def bind(elapsed_ms: int) -> dict[str, object]:
        body[field] = _shard_lifecycle(
            command_result=command_result,
            elapsed_ms=elapsed_ms,
            timeout_ms=deadline.timeout_ms,
            schema_version=schema,
        )
        return {**body, "fragment_identity": _fragment_identity(body)}

    def write(value: object, *, stage: bool = False) -> int:
        return _checked_fragment_write(root, path, value, deadline, head_sha, stage)

    elapsed_ms = write(bind(_deadline_elapsed_ms(deadline)), stage=True)
    fragment = bind(elapsed_ms)
    lifecycle = body[field]
    if lifecycle["result"] not in {"PASS", "FAIL"} and on_budget is not None:
        on_budget()
        fragment = bind(_deadline_elapsed_ms(deadline))
    published_ms = write(fragment)
    if lifecycle["result"] in {"PASS", "FAIL"} and published_ms > deadline.timeout_ms:
        path.unlink()
        if on_budget is not None:
            on_budget()
        fragment = bind(published_ms)
        write(fragment)
    return fragment


def _validate_shard_lifecycle(
    value: object,
    *,
    command_result: str,
    command_execution_ms: int,
    timeout_ms: int,
    schema_version: str = _CORE_SHARD_LIFECYCLE_SCHEMA,
    error: str = "core_fragment_lifecycle",
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkflowLaneError(error)
    elapsed_ms = value.get("elapsed_ms")
    if not _valid_elapsed_ms(elapsed_ms) or elapsed_ms < command_execution_ms:
        raise WorkflowLaneError(error)
    if value != _shard_lifecycle(
        command_result=command_result,
        elapsed_ms=elapsed_ms,
        timeout_ms=timeout_ms,
        schema_version=schema_version,
    ):
        raise WorkflowLaneError(error)
    return value


def _core_fragment_report_summary(
    *,
    repo_root: Path,
    artifact_root: Path,
    report: Path,
    result: str,
    optional_test_ids: Sequence[str],
) -> JUnitSummary | None:
    if result not in {"PASS", "FAIL"}:
        if report.is_symlink() or (report.exists() and not report.is_file()):
            raise WorkflowLaneError("core_fragment_report_cleanup")
        if not report.exists():
            return None
        try:
            report.unlink()
        except OSError as exc:
            raise WorkflowLaneError("core_fragment_report_cleanup") from exc
        return None
    summary = _report_summary(
        repo_root=repo_root,
        artifact_root=artifact_root,
        report=report,
        optional_test_ids=optional_test_ids,
    )
    if summary is None:
        raise WorkflowLaneError("core_fragment_report_required")
    return summary


def execute_core_shard(
    *,
    repo_root: str | Path,
    route_path: str | Path,
    shard_index: int,
    artifact_root: str | Path,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    contract = load_contract(root)
    context = context_from_environment(root)
    if context.job_id != "core_shard" or shard_index not in range(_CORE_SHARD_COUNT):
        raise WorkflowLaneError("core_shard_identity")
    route = _validate_route(contract, _load_json(root, route_path))
    _validate_test_topology(contract, route)
    if (route["head_sha"], route["head_tree_sha"]) != (
        context.evaluated_sha,
        context.evaluated_tree_sha,
    ):
        raise WorkflowLaneError("route_identity")
    deadline = start_lane_deadline(contract, "core-deterministic")
    timeout_ms = _core_timeout_ms(contract)
    if deadline.timeout_ms != timeout_ms:
        raise WorkflowLaneError("core_lifecycle_contract")
    output = _prepare_artifact_root(root, artifact_root)
    report = output / "pytest.xml"
    basetemp = output / "pytest-temp"
    files = _core_test_files(root)
    inventory = _collect_core_node_ids(root, deadline=deadline)
    verify_tracked_checkout(root, str(route["head_sha"]))
    _require_deadline(deadline, "collection")
    selected = _core_node_shards(inventory)[shard_index]
    spec = _core_shard_spec(
        contract=contract,
        shard_index=shard_index,
        node_inventory=inventory,
        selected_node_ids=selected,
        report=report,
        basetemp=basetemp,
        clustering=bool(route["clustering_required"]),
    )
    run = _execute(
        contract=contract,
        spec=spec,
        deadline=deadline,
    )
    shutil.rmtree(basetemp, ignore_errors=True)
    summary = _core_fragment_report_summary(
        repo_root=root,
        artifact_root=output,
        report=report,
        result=run.gate_run.result,
        optional_test_ids=_core_shard_optional_test_ids(selected),
    )
    report_digest = None if summary is None else _file_digest(report)
    provenance = _fragment_provenance(contract=contract, context=context)
    body: dict[str, object] = {
        "schema_version": _CORE_FRAGMENT_SCHEMA,
        "run_id": context.run_id,
        "run_attempt": context.run_attempt,
        "job_id": context.job_id,
        "evaluated_sha": context.evaluated_sha,
        "evaluated_tree_sha": context.evaluated_tree_sha,
        "route_digest": sha256_identity(route),
        "shard_index": shard_index,
        "shard_count": _CORE_SHARD_COUNT,
        "file_inventory": list(files),
        "file_inventory_digest": sha256_identity(list(files)),
        "node_inventory": list(inventory),
        "node_inventory_digest": sha256_identity(list(inventory)),
        "selected_node_ids": list(selected),
        "selected_node_ids_digest": sha256_identity(list(selected)),
        "command_spec": spec.as_dict(),
        "command_run": run.as_dict(),
        **provenance,
    }
    body.update(
        junit_summary=None if summary is None else summary.as_dict(),
        report_digest=report_digest,
    )

    def discard_report() -> None:
        _core_fragment_report_summary(
            repo_root=root,
            artifact_root=output,
            report=report,
            result="BUDGET_EXCEEDED",
            optional_test_ids=_core_shard_optional_test_ids(selected),
        )
        body.update(junit_summary=None, report_digest=None)

    return _publish_lifecycle_fragment(
        root=root,
        path=output / "fragment.json",
        body=body,
        field="shard_lifecycle",
        schema=_CORE_SHARD_LIFECYCLE_SCHEMA,
        command_result=run.gate_run.result,
        deadline=deadline,
        head_sha=str(route["head_sha"]),
        on_budget=discard_report,
    )


def _load_core_fragments(
    *,
    root: Path,
    fragment_root: Path,
    contract: SdlcContract,
    context: object,
    route: Mapping[str, object],
    deadline: LaneDeadline | None = None,
) -> tuple[tuple[dict[str, object], Path], ...]:
    expected_files = _core_test_files(root)
    expected_inventory = _collect_core_node_ids(root, deadline=deadline)
    if deadline is not None:
        _require_deadline(deadline, "reducer")
    expected_shards = _core_node_shards(expected_inventory)
    paths = tuple(sorted(fragment_root.glob("*/fragment.json")))
    root_entries = tuple(sorted(fragment_root.iterdir()))
    if (
        len(paths) != _CORE_SHARD_COUNT
        or len(root_entries) != _CORE_SHARD_COUNT
        or any(path.is_symlink() or not path.is_dir() for path in root_entries)
    ):
        raise WorkflowLaneError("core_fragment_count")
    expected_binding = _fragment_provenance(contract=contract, context=context)
    observed: dict[int, tuple[dict[str, object], Path]] = {}
    identities: set[str] = set()
    for path in paths:
        value = _load_json(root, path)
        if deadline is not None:
            _require_deadline(deadline, "reducer")
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "run_id",
            "run_attempt",
            "job_id",
            "evaluated_sha",
            "evaluated_tree_sha",
            "route_digest",
            "shard_index",
            "shard_count",
            "file_inventory",
            "file_inventory_digest",
            "node_inventory",
            "node_inventory_digest",
            "selected_node_ids",
            "selected_node_ids_digest",
            "command_spec",
            "command_run",
            "shard_lifecycle",
            "junit_summary",
            "report_digest",
            "fragment_identity",
            *_FRAGMENT_PROVENANCE_KEYS,
        }:
            raise WorkflowLaneError("core_fragment_shape")
        identity = value.pop("fragment_identity")
        if not isinstance(identity, str) or identity != _fragment_identity(value):
            raise WorkflowLaneError("core_fragment_identity")
        value["fragment_identity"] = identity
        index = value["shard_index"]
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index not in range(_CORE_SHARD_COUNT)
        ):
            raise WorkflowLaneError("core_fragment_index")
        if index in observed or identity in identities:
            raise WorkflowLaneError("core_fragment_duplicate")
        if (
            value["schema_version"] != _CORE_FRAGMENT_SCHEMA
            or value["run_id"] != context.run_id
            or value["run_attempt"] != context.run_attempt
            or value["job_id"] != "core_shard"
            or value["evaluated_sha"] != context.evaluated_sha
            or value["evaluated_tree_sha"] != context.evaluated_tree_sha
            or value["route_digest"] != sha256_identity(route)
            or value["shard_count"] != _CORE_SHARD_COUNT
            or value["file_inventory"] != list(expected_files)
            or value["file_inventory_digest"] != sha256_identity(list(expected_files))
            or value["node_inventory"] != list(expected_inventory)
            or value["node_inventory_digest"]
            != sha256_identity(list(expected_inventory))
            or value["selected_node_ids"] != list(expected_shards[index])
            or value["selected_node_ids_digest"]
            != sha256_identity(list(expected_shards[index]))
            or any(
                value[name] != expected_binding[name]
                for name in _FRAGMENT_PROVENANCE_KEYS
            )
        ):
            raise WorkflowLaneError("core_fragment_provenance")
        report = path.parent / "pytest.xml"
        expected_spec = _core_shard_spec(
            contract=contract,
            shard_index=index,
            node_inventory=expected_inventory,
            selected_node_ids=expected_shards[index],
            report=root / ".sdlc-run/core-fragment/pytest.xml",
            basetemp=root / ".sdlc-run/core-fragment/pytest-temp",
            clustering=bool(route["clustering_required"]),
        )
        if value["command_spec"] != expected_spec.as_dict():
            raise WorkflowLaneError("core_fragment_spec")
        try:
            command = _validate_command_run(value["command_run"])
        except ArtifactReceiptError as exc:
            raise WorkflowLaneError("core_fragment_run") from exc
        if (
            command["gate_run"]["gate_id"] != "core-deterministic"
            or command["gate_run"]["phase"] != "tests"
        ):
            raise WorkflowLaneError("core_fragment_run_identity")
        if command["command_spec_digest"] != expected_spec.digest:
            raise WorkflowLaneError("core_fragment_spec_digest")
        lifecycle = _validate_shard_lifecycle(
            value["shard_lifecycle"],
            command_result=str(command["gate_run"]["result"]),
            command_execution_ms=int(command["gate_run"]["execution_ms"]),
            timeout_ms=_core_timeout_ms(contract),
        )
        summary = value["junit_summary"]
        expected_names = {"fragment.json"}
        if summary is not None:
            expected_names.add("pytest.xml")
        if {item.name for item in path.parent.iterdir()} != expected_names:
            raise WorkflowLaneError("core_fragment_extra")
        run_result = lifecycle["result"]
        if summary is None:
            if value["report_digest"] is not None or report.exists():
                raise WorkflowLaneError("core_fragment_report")
            if run_result in {"PASS", "FAIL"}:
                raise WorkflowLaneError("core_fragment_report_required")
        else:
            if run_result not in {"PASS", "FAIL"}:
                raise WorkflowLaneError("core_fragment_report_unexpected")
            actual_summary = _report_summary(
                repo_root=root,
                artifact_root=path.parent,
                report=report,
                optional_test_ids=_core_shard_optional_test_ids(expected_shards[index]),
            )
            if (
                actual_summary is None
                or summary != actual_summary.as_dict()
                or value["report_digest"] != _file_digest(report)
            ):
                raise WorkflowLaneError("core_fragment_report_digest")
        if deadline is not None:
            _require_deadline(deadline, "reducer")
        observed[index] = (value, report)
        identities.add(identity)
    return tuple(observed[index] for index in range(_CORE_SHARD_COUNT))


def execute_source_fragment(
    *, repo_root: str | Path, route_path: str | Path, artifact_root: str | Path
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    contract = load_contract(root)
    context = context_from_environment(root)
    if context.job_id != "source":
        raise WorkflowLaneError("source_fragment_identity")
    route = _validate_route(contract, _load_json(root, route_path))
    _validate_test_topology(contract, route)
    if (route["head_sha"], route["head_tree_sha"]) != (
        context.evaluated_sha,
        context.evaluated_tree_sha,
    ):
        raise WorkflowLaneError("route_identity")
    deadline = start_lane_deadline(contract, "source-integrity")
    output = _prepare_artifact_root(root, artifact_root)
    spec = _source_fragment_spec(contract=contract, route=route)
    run = _execute(
        contract=contract,
        spec=spec,
        deadline=deadline,
    )
    verify_tracked_checkout(root, str(route["head_sha"]))
    body: dict[str, object] = {
        "schema_version": _SOURCE_FRAGMENT_SCHEMA,
        "run_id": context.run_id,
        "run_attempt": context.run_attempt,
        "job_id": context.job_id,
        "evaluated_sha": context.evaluated_sha,
        "evaluated_tree_sha": context.evaluated_tree_sha,
        "route_digest": sha256_identity(route),
        "command_spec": spec.as_dict(),
        "command_run": run.as_dict(),
        **_fragment_provenance(contract=contract, context=context),
    }
    return _publish_lifecycle_fragment(
        root=root,
        path=output / "source-fragment.json",
        body=body,
        field="source_lifecycle",
        schema=_SOURCE_LIFECYCLE_SCHEMA,
        command_result=run.gate_run.result,
        deadline=deadline,
        head_sha=str(route["head_sha"]),
    )


def _load_source_fragment(
    *,
    root: Path,
    source_root: Path,
    contract: SdlcContract,
    context: object,
    route: Mapping[str, object],
) -> dict[str, object]:
    paths = tuple(source_root.glob("*/source-fragment.json"))
    root_entries = tuple(source_root.iterdir())
    if (
        len(paths) != 1
        or len(root_entries) != 1
        or root_entries[0].is_symlink()
        or not root_entries[0].is_dir()
        or {item.name for item in root_entries[0].iterdir()} != {"source-fragment.json"}
    ):
        raise WorkflowLaneError("source_fragment_count")
    value = _load_json(root, paths[0])
    expected_binding = _fragment_provenance(contract=contract, context=context)
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "run_id",
        "run_attempt",
        "job_id",
        "evaluated_sha",
        "evaluated_tree_sha",
        "route_digest",
        "command_spec",
        "command_run",
        "source_lifecycle",
        "fragment_identity",
        *_FRAGMENT_PROVENANCE_KEYS,
    }:
        raise WorkflowLaneError("source_fragment_shape")
    identity = value.pop("fragment_identity")
    if not isinstance(identity, str) or identity != _fragment_identity(value):
        raise WorkflowLaneError("source_fragment_identity")
    value["fragment_identity"] = identity
    if (
        value["schema_version"] != _SOURCE_FRAGMENT_SCHEMA
        or value["run_id"] != context.run_id
        or value["run_attempt"] != context.run_attempt
        or value["job_id"] != "source"
        or value["evaluated_sha"] != context.evaluated_sha
        or value["evaluated_tree_sha"] != context.evaluated_tree_sha
        or value["route_digest"] != sha256_identity(route)
        or any(
            value[name] != expected_binding[name] for name in _FRAGMENT_PROVENANCE_KEYS
        )
    ):
        raise WorkflowLaneError("source_fragment_provenance")
    expected = _source_fragment_spec(contract=contract, route=route)
    if value["command_spec"] != expected.as_dict():
        raise WorkflowLaneError("source_fragment_spec")
    try:
        command = _validate_command_run(value["command_run"])
    except ArtifactReceiptError as exc:
        raise WorkflowLaneError("source_fragment_run") from exc
    if (
        command["gate_run"]["gate_id"] != "source-integrity"
        or command["gate_run"]["phase"] != "source"
    ):
        raise WorkflowLaneError("source_fragment_run_identity")
    if command["command_spec_digest"] != expected.digest:
        raise WorkflowLaneError("source_fragment_spec_digest")
    _validate_shard_lifecycle(
        value["source_lifecycle"],
        command_result=str(command["gate_run"]["result"]),
        command_execution_ms=int(command["gate_run"]["execution_ms"]),
        timeout_ms=_core_timeout_ms(contract),
        schema_version=_SOURCE_LIFECYCLE_SCHEMA,
        error="source_fragment_lifecycle",
    )
    return value


def _junit_case_ids(report: Path) -> frozenset[str]:
    try:
        document = ET.parse(report).getroot()
    except (OSError, ET.ParseError) as exc:
        raise WorkflowLaneError("core_fragment_report_xml") from exc
    values: list[str] = []
    for case in document.iter():
        if _xml_local_name(case.tag) != "testcase":
            continue
        classname = case.attrib.get("classname", "").strip()
        name = case.attrib.get("name", "").strip()
        if not classname or not name:
            raise WorkflowLaneError("core_fragment_report_case")
        values.append(f"{classname}::{name}")
    if not values or len(values) != len(set(values)):
        raise WorkflowLaneError("core_fragment_report_cases")
    return frozenset(values)


def _junit_id_for_node(node_id: str) -> str:
    unparameterised, bracket, parameters = node_id.partition("[")
    parts = unparameterised.split("::")
    parts[-1] += bracket + parameters
    module = parts[0][:-3].replace("/", ".")
    return f"{'.'.join((module, *parts[1:-1]))}::{parts[-1]}"


def _core_shard_optional_test_ids(node_ids: Sequence[str]) -> tuple[str, ...]:
    junit_ids = frozenset(_junit_id_for_node(node_id) for node_id in node_ids)
    return tuple(sorted(junit_ids.intersection(_OPTIONAL_CORE_TEST_IDS)))


def _reduced_core_outcome(
    results: Sequence[str],
    *,
    summaries: Sequence[Mapping[str, object] | None] | None = None,
) -> tuple[str, str, int | None]:
    if len(results) != _CORE_SHARD_COUNT:
        raise WorkflowLaneError("core_fragment_count")
    if summaries is not None and len(summaries) != _CORE_SHARD_COUNT:
        raise WorkflowLaneError("core_fragment_count")
    for exceptional in (
        "UNAUTHORISED_EFFECT",
        "EVIDENCE_MISMATCH",
        "ENVIRONMENT_ERROR",
        "CLASSIFIER_ERROR",
    ):
        if exceptional in results:
            return exceptional, f"{exceptional}:core-deterministic:tests", None
    if "BUDGET_EXCEEDED" in results:
        return (
            "BUDGET_EXCEEDED",
            "BUDGET_EXCEEDED:core-deterministic:tests",
            124,
        )
    junit_failed = summaries is not None and any(
        summary is not None and summary.get("outcome") == "FAIL"
        for summary in summaries
    )
    if any(item != "PASS" for item in results) or junit_failed:
        return "FAIL", "FAIL:core-deterministic:tests:exit=1", 1
    return "PASS", "PASS:core-deterministic:tests", 0


def reduce_core_lane(
    *,
    repo_root: str | Path,
    route_path: str | Path,
    fragment_root: str | Path,
    source_root: str | Path,
    artifact_root: str | Path,
) -> LaneExecutionOutput:
    root = Path(repo_root).resolve()
    contract, context, route = _context_route(
        root=root, route_path=route_path, lane_id="core"
    )
    reducer_deadline = start_lane_deadline(contract, "core-deterministic")
    timeout_ms = _core_timeout_ms(contract)
    if reducer_deadline.timeout_ms != timeout_ms:
        raise WorkflowLaneError("core_lifecycle_contract")
    fragments_dir = _existing_artifact_root(root, fragment_root)
    _require_deadline(reducer_deadline, "reducer")
    sources_dir = _existing_artifact_root(root, source_root)
    _require_deadline(reducer_deadline, "reducer")
    output = _prepare_artifact_root(root, artifact_root)
    _require_deadline(reducer_deadline, "reducer")
    complete = False
    try:
        fragments = _load_core_fragments(
            root=root,
            fragment_root=fragments_dir,
            contract=contract,
            context=context,
            route=route,
            deadline=reducer_deadline,
        )
        _require_deadline(reducer_deadline, "reducer")
        source = _load_source_fragment(
            root=root,
            source_root=sources_dir,
            contract=contract,
            context=context,
            route=route,
        )
        _require_deadline(reducer_deadline, "reducer")
        _private_write(output / "route.json", route)
        _require_deadline(reducer_deadline, "reducer")
        source_dir = _gate_directory(output, "source-integrity", "source")
        source_lifecycle = source["source_lifecycle"]
        source_command = dict(source["command_run"])
        source_gate_run = dict(source_command["gate_run"])
        source_gate_run["execution_ms"] = source_lifecycle["elapsed_ms"]
        if source_gate_run["result"] != source_lifecycle["result"]:
            source_gate_run.update(
                result=source_lifecycle["result"],
                result_reason=f"{source_lifecycle['result']}:source-integrity:source",
                returncode=None,
            )
        source_command["gate_run"] = source_gate_run
        _private_write(source_dir / "command-run.json", source_command)
        _require_deadline(reducer_deadline, "reducer")
        core_dir = _gate_directory(output, "core-deterministic", "tests")
        reports = core_dir / "reports"
        reports.mkdir(mode=0o700)
        lifecycles = [value["shard_lifecycle"] for value, _report in fragments]
        results = [str(lifecycle["result"]) for lifecycle in lifecycles]
        reports_available = all(
            value["junit_summary"] is not None for value, _ in fragments
        )
        for value, report in fragments:
            if value["junit_summary"] is None:
                continue
            expected_cases = frozenset(
                _junit_id_for_node(str(item)) for item in value["selected_node_ids"]
            )
            if _junit_case_ids(report) != expected_cases:
                raise WorkflowLaneError("core_fragment_report_inventory")
            _require_deadline(reducer_deadline, "reducer")
        if reports_available:
            report = reports / "pytest.xml"
            _merge_junit_reports(
                root=root,
                report=report,
                shard_reports=[item[1] for item in fragments],
                expected_count=_CORE_SHARD_COUNT,
                identity="core",
            )
            _require_deadline(reducer_deadline, "reducer")
            expected_all = frozenset(
                _junit_id_for_node(item)
                for item in _collect_core_node_ids(root, deadline=reducer_deadline)
            )
            _require_deadline(reducer_deadline, "reducer")
            if _junit_case_ids(report) != expected_all:
                raise WorkflowLaneError("core_reduced_report_inventory")
        reduced_outcome = _reduced_core_outcome(
            results,
            summaries=[value["junit_summary"] for value, _report in fragments],
        )
        expected_digest = _expected_spec(
            root=root,
            artifact_root=output,
            contract=contract,
            route=route,
            gate_id="core-deterministic",
            phase="tests",
        ).digest
        shard_ms = [int(value["elapsed_ms"]) for value in lifecycles]
        source_ms = int(source_lifecycle["elapsed_ms"])

        def build(elapsed_ms: int, base: tuple[str, str, int | None]) -> CommandRun:
            critical_path_ms = max(source_ms, max(shard_ms)) + elapsed_ms
            effective_outcome = (
                ("BUDGET_EXCEEDED", "BUDGET_EXCEEDED:core-deterministic:tests", 124)
                if _lifecycle_result(
                    base[0],
                    elapsed_ms=critical_path_ms,
                    timeout_ms=timeout_ms,
                )
                == "BUDGET_EXCEEDED"
                else base
            )
            result, reason, returncode = effective_outcome
            accounting = {
                "schema_version": "newsroom.sdlc.core-reduction-accounting.v1",
                "source_fragment_identity": source["fragment_identity"],
                "source_lifecycle_ms": source_ms,
                "shard_fragment_identities": [
                    value["fragment_identity"] for value, _report in fragments
                ],
                "shard_lifecycle_ms": shard_ms,
                "reducer_lifecycle_ms": elapsed_ms,
                "critical_path_ms": critical_path_ms,
            }
            return CommandRun(
                expected_digest,
                GateRunResult(
                    "core-deterministic",
                    "tests",
                    result,
                    reason,
                    returncode,
                    critical_path_ms,
                    canonical_json_bytes(accounting).decode("utf-8"),
                    "",
                    False,
                    False,
                ),
            )

        command_path = core_dir / "command-run.json"
        head_sha = str(route["head_sha"])

        def publish(command: CommandRun, stage: bool = False) -> int:
            return _checked_fragment_write(
                root, command_path, command.as_dict(), reducer_deadline, head_sha, stage
            )

        aggregate = build(_deadline_elapsed_ms(reducer_deadline), reduced_outcome)
        staged_ms = publish(aggregate, True)
        aggregate = build(staged_ms, reduced_outcome)
        published_ms = publish(aggregate)
        if aggregate.gate_run.result in {"PASS", "FAIL"} and published_ms > timeout_ms:
            command_path.unlink()
            aggregate = build(published_ms, reduced_outcome)
            publish(aggregate)
        complete = True
        return LaneExecutionOutput(
            "core",
            artifact_name(context),
            (
                ("source-integrity", "source", str(source_lifecycle["result"])),
                ("core-deterministic", "tests", aggregate.gate_run.result),
            ),
        )
    finally:
        if not complete:
            shutil.rmtree(output, ignore_errors=True)


def _run_pytest_shard(*, argv: Sequence[str], root: Path, log: Path) -> int:
    try:
        with log.open("wb") as stream:
            completed = subprocess.run(
                tuple(argv),
                cwd=root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        return completed.returncode
    except OSError as exc:
        try:
            log.write_text(
                f"EVIDENCE_MISMATCH:core-shard:{type(exc).__name__}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        return 2


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _publish_private_bytes(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise WorkflowLaneError("report_exists")
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(raw_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as exc:
        raise WorkflowLaneError("report_exists") from exc
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise WorkflowLaneError("report_publish") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _merge_junit_reports(
    *,
    root: Path,
    report: Path,
    shard_reports: Sequence[Path],
    expected_count: int,
    identity: str,
) -> None:
    if len(shard_reports) != expected_count:
        raise WorkflowLaneError(f"{identity}_shard_report_count")
    relative_reports: list[str] = []
    for shard_report in shard_reports:
        if not shard_report.is_file() or shard_report.is_symlink():
            raise WorkflowLaneError(f"{identity}_shard_report_missing")
        try:
            relative_reports.append(shard_report.relative_to(root).as_posix())
        except ValueError as exc:
            raise WorkflowLaneError("report_path") from exc
    source = summarize_junit(root, tuple(relative_reports))
    merged = ET.Element(
        "testsuites",
        {
            "tests": str(source.test_count),
            "failures": str(source.failure_count),
            "errors": str(source.error_count),
            "skipped": str(source.skip_count),
        },
    )
    for shard_report in shard_reports:
        try:
            document = ET.parse(shard_report).getroot()
        except ET.ParseError as exc:
            raise WorkflowLaneError(f"{identity}_shard_report_xml") from exc
        name = _xml_local_name(document.tag)
        if name == "testsuite":
            merged.append(document)
        elif name == "testsuites":
            suites = [
                child for child in document if _xml_local_name(child.tag) == "testsuite"
            ]
            if not suites:
                raise WorkflowLaneError(f"{identity}_shard_report_xml")
            merged.extend(suites)
        else:
            raise WorkflowLaneError(f"{identity}_shard_report_xml")
    payload = ET.tostring(merged, encoding="utf-8", xml_declaration=True)
    _publish_private_bytes(report, payload)
    relative_report = report.relative_to(root).as_posix()
    final = summarize_junit(root, (relative_report,))
    comparable_source = (
        source.test_ids_digest,
        source.test_count,
        source.failure_count,
        source.error_count,
        source.skip_count,
        source.required_skip_count,
        source.duration_ms,
        source.first_failure_fingerprint,
    )
    comparable_final = (
        final.test_ids_digest,
        final.test_count,
        final.failure_count,
        final.error_count,
        final.skip_count,
        final.required_skip_count,
        final.duration_ms,
        final.first_failure_fingerprint,
    )
    if comparable_source != comparable_final:
        report.unlink(missing_ok=True)
        raise WorkflowLaneError(f"{identity}_shard_report_merge")


def _merge_service_junit_reports(
    *,
    root: Path,
    report: Path,
    shard_reports: Sequence[Path],
) -> None:
    _merge_junit_reports(
        root=root,
        report=report,
        shard_reports=shard_reports,
        expected_count=_SERVICE_SHARD_COUNT,
        identity="service",
    )


def _run_core_pytest_workers(*, root: Path, report: Path) -> int:
    if report.exists() or report.is_symlink() or not report.parent.is_dir():
        raise WorkflowLaneError("report_exists")
    _core_test_files(root)
    with tempfile.TemporaryDirectory(prefix="newsroom-core-workers-") as raw_temp:
        command = _core_worker_command(
            report=report,
            basetemp=Path(raw_temp) / "pytest",
        )
        try:
            completed = subprocess.run(command, cwd=root, check=False)
        except OSError as exc:
            raise WorkflowLaneError("core_worker_process") from exc
    return completed.returncode


def core_shard_tests(
    *,
    repo_root: str | Path,
    report: str | Path,
    basetemp: str | Path,
    shard_index: int,
    node_inventory_digest: str,
    selected_node_ids_digest: str,
    clustering: bool,
) -> int:
    root = Path(repo_root).resolve()
    report_path = Path(report).resolve()
    basetemp_path = Path(basetemp).resolve()
    if (
        shard_index not in range(_CORE_SHARD_COUNT)
        or not report_path.is_relative_to(root)
        or not basetemp_path.is_relative_to(root)
    ):
        raise WorkflowLaneError("core_shard_command")
    inventory = _collect_core_node_ids(root)
    selected = _core_node_shards(inventory)[shard_index]
    if node_inventory_digest != sha256_identity(
        list(inventory)
    ) or selected_node_ids_digest != sha256_identity(list(selected)):
        raise WorkflowLaneError("core_shard_inventory")
    command = _core_worker_command(
        report=report_path,
        basetemp=basetemp_path,
        test_files=selected,
    )
    try:
        completed = subprocess.run(command, cwd=root, check=False)
    except OSError as exc:
        raise WorkflowLaneError("core_worker_process") from exc
    if completed.returncode or not clustering or shard_index != 0:
        return completed.returncode
    return _run_subprocess(
        (
            sys.executable,
            "scripts/eval_clustering_metrics.py",
            "--dataset",
            "newsroom/evals/clustering_eval_dataset_v1.jsonl",
            "--baseline",
            "newsroom/evals/clustering_eval_metrics_baseline_v1.json",
            "--fail-on-regression",
        )
    )


def core_tests(*, repo_root: str | Path, report: str | Path, clustering: bool) -> int:
    root = Path(repo_root).resolve()
    report_path = Path(report).resolve()
    if not report_path.is_relative_to(root):
        raise WorkflowLaneError("report_path")
    code = _run_core_pytest_workers(root=root, report=report_path)
    if code or not clustering:
        return code
    return _run_subprocess(
        (
            sys.executable,
            "scripts/eval_clustering_metrics.py",
            "--dataset",
            "newsroom/evals/clustering_eval_dataset_v1.jsonl",
            "--baseline",
            "newsroom/evals/clustering_eval_metrics_baseline_v1.json",
            "--fail-on-regression",
        )
    )


def _service_test_files(
    root: Path, test_paths: Sequence[str]
) -> tuple[tuple[str, int], ...]:
    expected = _repository_service_tests(root)
    selected = tuple(str(path) for path in test_paths)
    if (
        selected != expected
        or len(selected) != len(set(selected))
        or len(selected) < _SERVICE_SHARD_COUNT
    ):
        raise WorkflowLaneError("service_test_topology")
    values: list[tuple[str, int]] = []
    test_root = (root / "newsroom" / "tests").resolve()
    for relative in selected:
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
            size = len(resolved.read_bytes())
        except OSError as exc:
            raise WorkflowLaneError("service_test_file") from exc
        if (
            path.is_symlink()
            or not resolved.is_relative_to(test_root)
            or not resolved.is_file()
            or resolved.name != path.name
        ):
            raise WorkflowLaneError("service_test_file")
        values.append((relative, size))
    return tuple(values)


def _service_test_shards(
    root: Path, test_paths: Sequence[str]
) -> tuple[tuple[str, ...], ...]:
    files = _service_test_files(root, test_paths)
    shards: list[list[str]] = [[] for _ in range(_SERVICE_SHARD_COUNT)]
    weights = [0] * _SERVICE_SHARD_COUNT
    for relative, size in sorted(files, key=lambda item: (-item[1], item[0])):
        shard = min(
            range(_SERVICE_SHARD_COUNT),
            key=lambda index: (weights[index], index),
        )
        shards[shard].append(relative)
        weights[shard] += size
    result = tuple(tuple(sorted(shard)) for shard in shards)
    flattened = tuple(item for shard in result for item in shard)
    expected = tuple(sorted(relative for relative, _size in files))
    if (
        any(not shard for shard in result)
        or len(flattened) != len(set(flattened))
        or tuple(sorted(flattened)) != expected
    ):
        raise WorkflowLaneError("service_shard_coverage")
    return result


def _service_shard_command(
    *,
    test_files: Sequence[str],
    report: Path,
    basetemp: Path,
) -> tuple[str, ...]:
    if not test_files:
        raise WorkflowLaneError("service_shard_empty")
    return (
        sys.executable,
        "-m",
        "pytest",
        *_SERVICE_PYTEST_OPTIONS,
        *test_files,
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


def _run_service_pytest_shards(
    *,
    root: Path,
    report: Path,
    test_paths: Sequence[str],
) -> int:
    shards = _service_test_shards(root, test_paths)
    if report.exists() or report.is_symlink() or not report.parent.is_dir():
        raise WorkflowLaneError("report_exists")
    shard_reports = tuple(
        report.with_name(f"{report.stem}-shard-{index:02d}{report.suffix}")
        for index in range(_SERVICE_SHARD_COUNT)
    )
    if any(path.exists() or path.is_symlink() for path in shard_reports):
        raise WorkflowLaneError("service_shard_report_exists")
    with tempfile.TemporaryDirectory(prefix="newsroom-service-shards-") as raw_temp:
        temporary = Path(raw_temp)
        logs = tuple(
            temporary / f"shard-{index:02d}.log"
            for index in range(_SERVICE_SHARD_COUNT)
        )
        commands = tuple(
            _service_shard_command(
                test_files=shards[index],
                report=shard_reports[index],
                basetemp=temporary / f"pytest-{index:02d}",
            )
            for index in range(_SERVICE_SHARD_COUNT)
        )
        with ThreadPoolExecutor(max_workers=_SERVICE_SHARD_COUNT) as executor:
            futures = tuple(
                executor.submit(
                    _run_pytest_shard,
                    argv=commands[index],
                    root=root,
                    log=logs[index],
                )
                for index in range(_SERVICE_SHARD_COUNT)
            )
            codes = tuple(future.result() for future in futures)
        for log in logs:
            try:
                sys.stdout.buffer.write(log.read_bytes())
            except OSError as exc:
                raise WorkflowLaneError("service_shard_log") from exc
        sys.stdout.buffer.flush()
    _merge_service_junit_reports(root=root, report=report, shard_reports=shard_reports)
    for shard_report in shard_reports:
        shard_report.unlink(missing_ok=True)
    return next((code if code > 0 else 1 for code in codes if code), 0)


def service_tests(
    *, repo_root: str | Path, report: str | Path, test_paths: Sequence[str]
) -> int:
    root = Path(repo_root).resolve()
    report_path = Path(report).resolve()
    if not report_path.is_relative_to(root) or not test_paths:
        raise WorkflowLaneError("service_tests")
    return _run_service_pytest_shards(
        root=root,
        report=report_path,
        test_paths=test_paths,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exact Newsroom SDLC shadow lane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("execute", "finalize"):
        lane_parser = subparsers.add_parser(command)
        lane_parser.add_argument("--repo-root", default=".")
        lane_parser.add_argument("--route", required=True)
        lane_parser.add_argument("--lane", choices=("core", "service"), required=True)
        lane_parser.add_argument("--artifact-root", required=True)
        lane_parser.add_argument("--output")

    source_parser = subparsers.add_parser("source-check")
    source_parser.add_argument("--repo-root", default=".")
    source_parser.add_argument("--base-sha", required=True)
    source_parser.add_argument("--head-sha", required=True)

    core_parser = subparsers.add_parser("core-tests")
    core_parser.add_argument("--repo-root", default=".")
    core_parser.add_argument("--report", required=True)
    core_parser.add_argument("--clustering", action="store_true")

    shard_parser = subparsers.add_parser("execute-core-shard")
    shard_parser.add_argument("--repo-root", default=".")
    shard_parser.add_argument("--route", required=True)
    shard_parser.add_argument("--shard-index", required=True, type=int)
    shard_parser.add_argument("--artifact-root", required=True)

    shard_tests_parser = subparsers.add_parser("core-shard-tests")
    shard_tests_parser.add_argument("--repo-root", default=".")
    shard_tests_parser.add_argument("--report", required=True)
    shard_tests_parser.add_argument("--basetemp", required=True)
    shard_tests_parser.add_argument("--shard-index", required=True, type=int)
    shard_tests_parser.add_argument("--node-inventory-digest", required=True)
    shard_tests_parser.add_argument("--selected-node-ids-digest", required=True)
    shard_tests_parser.add_argument("--clustering", action="store_true")

    source_fragment_parser = subparsers.add_parser("execute-source")
    source_fragment_parser.add_argument("--repo-root", default=".")
    source_fragment_parser.add_argument("--route", required=True)
    source_fragment_parser.add_argument("--artifact-root", required=True)

    reduce_parser = subparsers.add_parser("reduce-core")
    reduce_parser.add_argument("--repo-root", default=".")
    reduce_parser.add_argument("--route", required=True)
    reduce_parser.add_argument("--fragment-root", required=True)
    reduce_parser.add_argument("--source-root", required=True)
    reduce_parser.add_argument("--artifact-root", required=True)

    service_parser = subparsers.add_parser("service-tests")
    service_parser.add_argument("--repo-root", default=".")
    service_parser.add_argument("--report", required=True)
    service_parser.add_argument("test_paths", nargs="+")

    arguments = parser.parse_args(argv)
    try:
        if arguments.command in {"execute", "finalize"}:
            if arguments.command == "execute":
                result = execute_lane(
                    repo_root=arguments.repo_root,
                    route_path=arguments.route,
                    lane_id=arguments.lane,
                    artifact_root=arguments.artifact_root,
                )
            else:
                result = finalize_lane(
                    repo_root=arguments.repo_root,
                    route_path=arguments.route,
                    lane_id=arguments.lane,
                    artifact_root=arguments.artifact_root,
                )
            rendered = canonical_json_bytes(result.as_dict()) + b"\n"
            if arguments.output:
                root = Path(arguments.repo_root).resolve()
                output = root / arguments.output
                if not output.parent.is_dir() or not output.resolve().is_relative_to(
                    root
                ):
                    raise WorkflowLaneError("output_path")
                _private_write(output, result.as_dict())
            else:
                sys.stdout.buffer.write(rendered)
            return 0
        if arguments.command == "source-check":
            return source_check(
                repo_root=arguments.repo_root,
                base_sha=arguments.base_sha,
                head_sha=arguments.head_sha,
            )
        if arguments.command == "core-tests":
            return core_tests(
                repo_root=arguments.repo_root,
                report=arguments.report,
                clustering=arguments.clustering,
            )
        if arguments.command == "execute-core-shard":
            fragment = execute_core_shard(
                repo_root=arguments.repo_root,
                route_path=arguments.route,
                shard_index=arguments.shard_index,
                artifact_root=arguments.artifact_root,
            )
            status = _producer_exit_status(
                fragment,
                fragment_schema=_CORE_FRAGMENT_SCHEMA,
                lifecycle_field="shard_lifecycle",
                lifecycle_schema=_CORE_SHARD_LIFECYCLE_SCHEMA,
                gate_id="core-deterministic",
                phase="tests",
                fragment_keys=_CORE_FRAGMENT_KEYS,
                expected_timeout_ms=_core_timeout_ms(
                    load_contract(arguments.repo_root)
                ),
            )
            sys.stdout.buffer.write(canonical_json_bytes(fragment) + b"\n")
            return status
        if arguments.command == "core-shard-tests":
            return core_shard_tests(
                repo_root=arguments.repo_root,
                report=arguments.report,
                basetemp=arguments.basetemp,
                shard_index=arguments.shard_index,
                node_inventory_digest=arguments.node_inventory_digest,
                selected_node_ids_digest=arguments.selected_node_ids_digest,
                clustering=arguments.clustering,
            )
        if arguments.command == "execute-source":
            fragment = execute_source_fragment(
                repo_root=arguments.repo_root,
                route_path=arguments.route,
                artifact_root=arguments.artifact_root,
            )
            status = _producer_exit_status(
                fragment,
                fragment_schema=_SOURCE_FRAGMENT_SCHEMA,
                lifecycle_field="source_lifecycle",
                lifecycle_schema=_SOURCE_LIFECYCLE_SCHEMA,
                gate_id="source-integrity",
                phase="source",
                fragment_keys=_SOURCE_FRAGMENT_KEYS,
                expected_timeout_ms=_core_timeout_ms(
                    load_contract(arguments.repo_root)
                ),
            )
            sys.stdout.buffer.write(canonical_json_bytes(fragment) + b"\n")
            return status
        if arguments.command == "reduce-core":
            result = reduce_core_lane(
                repo_root=arguments.repo_root,
                route_path=arguments.route,
                fragment_root=arguments.fragment_root,
                source_root=arguments.source_root,
                artifact_root=arguments.artifact_root,
            )
            sys.stdout.buffer.write(canonical_json_bytes(result.as_dict()) + b"\n")
            return 0
        return service_tests(
            repo_root=arguments.repo_root,
            report=arguments.report,
            test_paths=arguments.test_paths,
        )
    except (
        ArtifactProvenanceError,
        CommandSpecError,
        ContractError,
        EvidenceError,
        GateRunError,
        GitRouteError,
        JUnitEvidenceError,
        WorkflowLaneError,
        OSError,
        SyntaxError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        reason = str(exc) if str(exc) else type(exc).__name__
        prefix = (
            ""
            if reason.startswith("BUDGET_EXCEEDED:")
            else "EVIDENCE_MISMATCH:workflow-lane:"
        )
        print(f"{prefix}{reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
