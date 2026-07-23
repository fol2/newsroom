from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Mapping, Sequence

from .artifact_envelope import (
    ArtifactProvenanceError,
    GithubRunContext,
    artifact_name,
    context_from_environment,
    validate_envelope,
)
from .contracts import ContractError, SdlcContract, load_contract
from .emit_evidence import (
    EvidenceError,
    _validate_route,
    canonical_json_bytes,
    sha256_identity,
)
from .run_gate import (
    GateRunError,
    GateRunResult,
    run_configured_gate,
    start_lane_deadline,
)
from .workflow_event import WorkflowEvidenceError, validate_workflow_event
from .workflow_lane import _SERVICE_CONFIGURATION
from .workflow_orchestrator import (
    ROUTE_OUTPUT_SCHEMA,
    RouteOutput,
    WorkflowOrchestratorError,
    _canonical_load,
    _route_artifact_name,
    _safe_target,
)


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_CODE = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_RESULT_CODES = frozenset(
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
_GITHUB_CONTEXT_ENVIRONMENT = (
    "GITHUB_ACTIONS",
    "GITHUB_REPOSITORY",
    "GITHUB_REPOSITORY_ID",
    "GITHUB_EVENT_NAME",
    "GITHUB_SHA",
    "GITHUB_EVENT_PATH",
    "GITHUB_JOB",
    "GITHUB_WORKFLOW_SHA",
    "GITHUB_WORKFLOW_REF",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_REF",
    "RUNNER_ENVIRONMENT",
)
_OPTIONAL_STATIC_ENVIRONMENT = (
    "HOME",
    "RUNNER_TEMP",
    "TMPDIR",
    "UV_CACHE_DIR",
)
_ROUTE_OUTPUT_KEYS = frozenset(
    {
        "schema_version",
        "artifact_name",
        "service_required",
        "route_identity",
        "event_identity",
    }
)
_LANE_OUTPUT_KEYS = frozenset(
    {
        "schema_version",
        "lane_id",
        "artifact_name",
        "envelope_identity",
        "gate_results",
    }
)
_GATE_RESULT_KEYS = frozenset({"gate_id", "phase", "result"})
_LANE_GATE_KEYS = {
    "core": (
        ("core-deterministic", "tests"),
        ("source-integrity", "source"),
    ),
    "service": (("service-neo4j", "tests"),),
}


class WorkflowBudgetError(ValueError):
    """Raised when a workflow step cannot satisfy its accepted hard deadline."""


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise WorkflowBudgetError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WorkflowBudgetError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WorkflowBudgetError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise WorkflowBudgetError(code)
    return text


def _child_environment(
    *,
    ambient: Mapping[str, str] | None = None,
    service: bool,
    preserve_lane_static: bool,
) -> dict[str, str]:
    source = os.environ if ambient is None else ambient
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in source.items()
    ):
        raise WorkflowBudgetError("ambient_environment")
    if service and not preserve_lane_static:
        raise WorkflowBudgetError("service_environment")
    if preserve_lane_static:
        environment = {
            "CI": "true",
            "LANG": source.get("LANG", "C.UTF-8"),
            "LC_ALL": source.get("LC_ALL", "C.UTF-8"),
            "PATH": source.get("PATH", "/usr/bin:/bin"),
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
        }
        for name in _OPTIONAL_STATIC_ENVIRONMENT:
            value = source.get(name)
            if value:
                environment[name] = value
    else:
        temporary = source.get("RUNNER_TEMP", "/tmp")
        environment = {
            "CI": "true",
            "HOME": temporary,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
            "RUNNER_TEMP": temporary,
            "TMPDIR": temporary,
        }
    for name in _GITHUB_CONTEXT_ENVIRONMENT:
        value = source.get(name)
        if not value:
            raise WorkflowBudgetError("github_environment")
        environment[name] = value
    if environment["GITHUB_ACTIONS"] != "true":
        raise WorkflowBudgetError("github_environment")
    if service:
        if any(source.get(name) != value for name, value in _SERVICE_CONFIGURATION.items()):
            raise WorkflowBudgetError("service_environment")
        environment.update(_SERVICE_CONFIGURATION)
    forbidden = (
        "GITHUB_TOKEN",
        "NEO4J_ADMIN_PASSWORD",
        "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",
    )
    if any(name in environment for name in forbidden):
        raise WorkflowBudgetError("secret_environment")
    return environment


def _relative_existing_file(root: Path, value: str | Path) -> tuple[str, Path]:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else root / candidate
    absolute = path if path.is_absolute() else path.absolute()
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise WorkflowBudgetError("input_file") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise WorkflowBudgetError("input_file")
    relative = resolved.relative_to(root).as_posix()
    _canonical_load(absolute)
    return relative, absolute


def _relative_existing_directory(root: Path, value: str | Path) -> tuple[str, Path]:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else root / candidate
    absolute = path if path.is_absolute() else path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise WorkflowBudgetError("input_directory")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise WorkflowBudgetError("input_directory") from exc
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise WorkflowBudgetError("input_directory")
    return resolved.relative_to(root).as_posix(), resolved


def _mismatch(run: GateRunResult, code: str) -> GateRunResult:
    suffix = _text(code, "mismatch_code", maximum=128)
    if _SAFE_CODE.fullmatch(suffix) is None:
        raise WorkflowBudgetError("mismatch_code")
    return GateRunResult(
        gate_id=run.gate_id,
        phase=run.phase,
        result="EVIDENCE_MISMATCH",
        result_reason=f"EVIDENCE_MISMATCH:{run.gate_id}:{run.phase}:{suffix}",
        returncode=run.returncode,
        execution_ms=run.execution_ms,
        stdout=run.stdout,
        stderr=run.stderr,
        stdout_truncated=run.stdout_truncated,
        stderr_truncated=run.stderr_truncated,
    )


def _cleanup_directory(path: Path) -> None:
    if path.exists() and path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)


def validate_route_bundle(
    *,
    repo_root: str | Path,
    output_directory: str | Path,
    context: GithubRunContext,
    contract: SdlcContract,
) -> RouteOutput:
    root = Path(repo_root).resolve()
    _, directory = _relative_existing_directory(root, output_directory)
    entries = tuple(sorted(directory.iterdir(), key=lambda path: path.name))
    if (
        tuple(path.name for path in entries)
        != ("event.json", "route-output.json", "route.json")
        or any(path.is_symlink() or not path.is_file() for path in entries)
    ):
        raise WorkflowBudgetError("route_inventory")
    try:
        route = _validate_route(contract, _canonical_load(directory / "route.json"))
        event = validate_workflow_event(_canonical_load(directory / "event.json"))
        value = dict(_mapping(_canonical_load(directory / "route-output.json"), "route_output"))
    except (
        EvidenceError,
        WorkflowEvidenceError,
        WorkflowOrchestratorError,
    ) as exc:
        raise WorkflowBudgetError("route_output") from exc
    if frozenset(value) != _ROUTE_OUTPUT_KEYS or value.get("schema_version") != ROUTE_OUTPUT_SCHEMA:
        raise WorkflowBudgetError("route_output")
    service_required = value.get("service_required")
    if not isinstance(service_required, bool):
        raise WorkflowBudgetError("route_output")
    output = RouteOutput(
        artifact_name=_text(value.get("artifact_name"), "route_artifact", maximum=255),
        service_required=service_required,
        route_identity=_sha(value.get("route_identity"), "route_identity"),
        event_identity=_sha(value.get("event_identity"), "event_identity"),
    )
    event_value = event.as_dict()
    if (
        output.artifact_name != _route_artifact_name(context)
        or output.service_required is not route["service_required"]
        or output.route_identity != sha256_identity(route)
        or output.event_identity != event_value["event_identity"]
        or event.repository != context.repository
        or event.repository_id != context.repository_id
        or event.head_repository != context.head_repository
        or event.head_repository_id != context.head_repository_id
        or event.event_name != context.event_name
        or event.event_sha != context.event_sha
        or event.evaluated_sha != context.evaluated_sha
        or event.evaluated_tree_sha != context.evaluated_tree_sha
        or event.ref != context.ref
        or route["base_sha"] != event.base_sha
        or route["base_tree_sha"] != event.base_tree_sha
        or route["head_sha"] != event.evaluated_sha
        or route["head_tree_sha"] != event.evaluated_tree_sha
    ):
        raise WorkflowBudgetError("route_identity")
    return output


def run_bounded_route(
    *,
    repo_root: str | Path,
    output_directory: str | Path,
) -> GateRunResult:
    root = Path(repo_root).resolve()
    context = context_from_environment(root)
    if context.job_id != "route":
        raise WorkflowBudgetError("route_job")
    contract = load_contract(root)
    target = _safe_target(root, output_directory)
    relative = target.relative_to(root).as_posix()
    deadline = start_lane_deadline(contract, "route")
    run = run_configured_gate(
        contract=contract,
        gate_id="route",
        phase="classify",
        argv=(
            sys.executable,
            "-m",
            "scripts.sdlc.workflow_orchestrator",
            "route",
            "--repo-root",
            ".",
            "--output-directory",
            relative,
        ),
        deadline=deadline,
        cwd=root,
        env=_child_environment(service=False, preserve_lane_static=False),
        output_limit_bytes=65_536,
        termination_grace_seconds=0.25,
    )
    if run.result != "PASS":
        _cleanup_directory(target)
        return run
    try:
        validate_route_bundle(
            repo_root=root,
            output_directory=relative,
            context=context,
            contract=contract,
        )
    except WorkflowBudgetError:
        _cleanup_directory(target)
        return _mismatch(run, "route-output")
    return run


def _validate_lane_output(
    *,
    root: Path,
    lane_id: str,
    artifact_root: Path,
    output_path: Path,
    context: GithubRunContext,
) -> Mapping[str, object]:
    value = dict(_mapping(_canonical_load(output_path), "lane_output"))
    if frozenset(value) != _LANE_OUTPUT_KEYS or value.get("schema_version") != "newsroom.sdlc.workflow-lane.v1":
        raise WorkflowBudgetError("lane_output")
    if value.get("lane_id") != lane_id or value.get("artifact_name") != artifact_name(context):
        raise WorkflowBudgetError("lane_output")
    envelope_identity = _sha(value.get("envelope_identity"), "envelope_identity")
    try:
        envelope = validate_envelope(_canonical_load(artifact_root / "envelope.json"))
    except (ArtifactProvenanceError, WorkflowOrchestratorError) as exc:
        raise WorkflowBudgetError("lane_envelope") from exc
    if (
        envelope.context != context
        or envelope.artifact_name != artifact_name(context)
        or envelope.envelope_identity != envelope_identity
    ):
        raise WorkflowBudgetError("lane_envelope")
    raw_results = value.get("gate_results")
    if not isinstance(raw_results, list):
        raise WorkflowBudgetError("gate_results")
    normalized: list[tuple[str, str, str]] = []
    for raw in raw_results:
        item = _mapping(raw, "gate_result")
        if frozenset(item) != _GATE_RESULT_KEYS:
            raise WorkflowBudgetError("gate_result")
        gate_id = _text(item.get("gate_id"), "gate_id", maximum=128)
        phase = _text(item.get("phase"), "phase", maximum=128)
        result = _text(item.get("result"), "result", maximum=64)
        if result not in _RESULT_CODES:
            raise WorkflowBudgetError("result")
        normalized.append((gate_id, phase, result))
    if (
        normalized != sorted(normalized)
        or tuple((gate, phase) for gate, phase, _ in normalized)
        != _LANE_GATE_KEYS[lane_id]
    ):
        raise WorkflowBudgetError("gate_results")
    return value


def run_bounded_lane_finalization(
    *,
    repo_root: str | Path,
    route_path: str | Path,
    lane_id: str,
    artifact_root: str | Path,
    output_path: str | Path,
) -> GateRunResult:
    root = Path(repo_root).resolve()
    context = context_from_environment(root)
    if lane_id not in _LANE_GATE_KEYS or context.job_id != lane_id:
        raise WorkflowBudgetError("lane_job")
    contract = load_contract(root)
    route_relative, _ = _relative_existing_file(root, route_path)
    artifact_relative, artifact_directory = _relative_existing_directory(root, artifact_root)
    output = _safe_target(root, output_path, suffix=".json")
    if output.is_relative_to(artifact_directory):
        raise WorkflowBudgetError("output_path")
    output_relative = output.relative_to(root).as_posix()
    deadline = start_lane_deadline(contract, "evidence-finalize")
    run = run_configured_gate(
        contract=contract,
        gate_id="evidence-finalize",
        phase=f"{lane_id}-lane",
        argv=(
            sys.executable,
            "-m",
            "scripts.sdlc.workflow_lane",
            "finalize",
            "--repo-root",
            ".",
            "--route",
            route_relative,
            "--lane",
            lane_id,
            "--artifact-root",
            artifact_relative,
            "--output",
            output_relative,
        ),
        deadline=deadline,
        cwd=root,
        env=_child_environment(
            service=lane_id == "service", preserve_lane_static=True
        ),
        output_limit_bytes=65_536,
        termination_grace_seconds=0.25,
    )
    if run.result != "PASS":
        output.unlink(missing_ok=True)
        return run
    try:
        _validate_lane_output(
            root=root,
            lane_id=lane_id,
            artifact_root=artifact_directory,
            output_path=output,
            context=context,
        )
    except WorkflowBudgetError:
        output.unlink(missing_ok=True)
        return _mismatch(run, "lane-output")
    return run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply accepted hard deadlines to Newsroom workflow steps"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("route")
    route.add_argument("--repo-root", default=".")
    route.add_argument("--output-directory", required=True)

    finalize = subparsers.add_parser("finalize-lane")
    finalize.add_argument("--repo-root", default=".")
    finalize.add_argument("--route", required=True)
    finalize.add_argument("--lane", choices=("core", "service"), required=True)
    finalize.add_argument("--artifact-root", required=True)
    finalize.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "route":
            result = run_bounded_route(
                repo_root=arguments.repo_root,
                output_directory=arguments.output_directory,
            )
        else:
            result = run_bounded_lane_finalization(
                repo_root=arguments.repo_root,
                route_path=arguments.route,
                lane_id=arguments.lane,
                artifact_root=arguments.artifact_root,
                output_path=arguments.output,
            )
        sys.stdout.buffer.write(canonical_json_bytes(result.as_dict()) + b"\n")
        return {
            "PASS": 0,
            "FAIL": 1,
            "BUDGET_EXCEEDED": 2,
        }.get(result.result, 3)
    except (
        WorkflowBudgetError,
        WorkflowOrchestratorError,
        ArtifactProvenanceError,
        ContractError,
        EvidenceError,
        GateRunError,
        WorkflowEvidenceError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, WorkflowBudgetError)
            and str(exc)
            and _SAFE_CODE.fullmatch(str(exc))
            else type(exc).__name__
        )
        print(f"ENVIRONMENT_ERROR:workflow-budget:{reason}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
