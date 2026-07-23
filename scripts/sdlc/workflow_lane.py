from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

from .artifact_envelope import (
    ArtifactProvenanceError,
    artifact_name,
    context_from_environment,
    create_envelope,
    validate_envelope,
)
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
    _validate_route,
    build_gate_evidence,
    canonical_json_bytes,
    installed_uv_version,
    sha256_identity,
)
from .junit_evidence import JUnitEvidenceError, JUnitSummary, summarize_junit
from .run_gate import GateRunError, LaneDeadline, run_configured_gate, start_lane_deadline


SCHEMA_VERSION = "newsroom.sdlc.workflow-lane.v1"
_SERVICE_IMAGE = "neo4j:2026.06.0-community-trixie"
_SERVICE_SERVER = "2026.06.0"
_SERVICE_DRIVER = "6.2.0"
_MAX_JSON_BYTES = 8 * 1024 * 1024
_OPTIONAL_CORE_TEST_IDS = (
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_public_round_trip_duplicate_and_generation_isolation",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_requires_explicit_authentication_configuration",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_wrong_projector_credential_fails_closed_without_secret",
)


class WorkflowLaneError(ValueError):
    """Raised when a workflow lane cannot produce exact evidence."""


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
            "driver_version": _SERVICE_DRIVER,
            "edition": "community",
            "image": _SERVICE_IMAGE,
            "server_version": _SERVICE_SERVER,
        }
    )


def _load_json(root: Path, value: str | Path) -> object:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else root / candidate
    absolute = path if path.is_absolute() else path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise WorkflowLaneError("input_path")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise WorkflowLaneError("input_path") from exc
    if not resolved.is_relative_to(root):
        raise WorkflowLaneError("input_path")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise WorkflowLaneError("input_file") from exc
    if not payload or len(payload) > _MAX_JSON_BYTES:
        raise WorkflowLaneError("input_file")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowLaneError("input_json") from exc


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
    report: Path,
    optional_test_ids: Sequence[str],
) -> JUnitSummary | None:
    if not report.is_file():
        return None
    return summarize_junit(
        repo_root,
        (report.relative_to(repo_root).as_posix(),),
        optional_test_ids=optional_test_ids,
    )


def _evidence(
    *,
    repo_root: Path,
    contract: SdlcContract,
    route: object,
    run: CommandRun,
    summary: JUnitSummary | None,
    service_digest: str | None,
) -> dict[str, object]:
    return build_gate_evidence(
        repo_root=repo_root,
        contract=contract,
        route=route,
        gate_run=run.gate_run.as_dict(),
        junit_summary=None if summary is None else summary.as_dict(),
        runner_kind="github-hosted",
        queue_ms=0,
        bootstrap_ms=0,
        finalize_ms=0,
        cache_key=None,
        cache_hit=False,
        uv_version=installed_uv_version(),
        command_spec_digest=run.command_spec_digest,
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
    report = reports / "pytest.xml"
    deadline = start_lane_deadline(contract, "source-integrity")
    base_env = _static_environment()
    source_spec = _spec(
        contract=contract,
        gate_id="source-integrity",
        phase="source",
        argv=(
            sys.executable,
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
        static_env=base_env,
    )
    source_run = _execute(contract=contract, spec=source_spec, deadline=deadline)
    test_argv = [
        sys.executable,
        "-m",
        "scripts.sdlc.workflow_lane",
        "core-tests",
        "--repo-root",
        ".",
        "--report",
        report.relative_to(root).as_posix(),
    ]
    if route["clustering_required"]:
        test_argv.append("--clustering")
    test_spec = _spec(
        contract=contract,
        gate_id="core-deterministic",
        phase="tests",
        argv=test_argv,
        static_env=base_env,
    )
    test_run = _execute(contract=contract, spec=test_spec, deadline=deadline)
    summary = _report_summary(
        repo_root=root,
        report=report,
        optional_test_ids=_OPTIONAL_CORE_TEST_IDS,
    )
    return (
        ("source-integrity", "source", source_run, None, source_dir),
        ("core-deterministic", "tests", test_run, summary, test_dir),
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
    report = reports / "pytest.xml"
    static_env = _static_environment()
    static_env.update(
        {
            "NEWSROOM_NEO4J_DATABASE": os.environ.get(
                "NEWSROOM_NEO4J_DATABASE", "neo4j"
            ),
            "NEWSROOM_NEO4J_PROJECTOR_USERNAME": os.environ.get(
                "NEWSROOM_NEO4J_PROJECTOR_USERNAME", "newsroom_projector"
            ),
            "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
            "NEWSROOM_NEO4J_URI": os.environ.get(
                "NEWSROOM_NEO4J_URI", "bolt://localhost:7687"
            ),
        }
    )
    spec = _spec(
        contract=contract,
        gate_id="service-neo4j",
        phase="tests",
        argv=(
            sys.executable,
            "-m",
            "scripts.sdlc.workflow_lane",
            "service-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
            *[str(item) for item in route["service_tests"]],
        ),
        static_env=static_env,
        pass_env=("NEWSROOM_NEO4J_PROJECTOR_PASSWORD",),
    )
    deadline = start_lane_deadline(contract, "service-neo4j")
    run = _execute(contract=contract, spec=spec, deadline=deadline)
    summary = _report_summary(repo_root=root, report=report, optional_test_ids=())
    return (("service-neo4j", "tests", run, summary, gate_dir),)


def run_lane(
    *,
    repo_root: str | Path,
    route_path: str | Path,
    lane_id: str,
    artifact_root: str | Path,
) -> LaneOutput:
    root = Path(repo_root).resolve()
    contract = load_contract(root)
    context = context_from_environment(root)
    if lane_id not in {"core", "service"} or context.job_id != lane_id:
        raise WorkflowLaneError("lane_identity")
    route = _validate_route(contract, _load_json(root, route_path))
    if (
        route["head_sha"] != context.evaluated_sha
        or route["head_tree_sha"] != context.evaluated_tree_sha
    ):
        raise WorkflowLaneError("route_identity")
    output = _prepare_artifact_root(root, artifact_root)
    complete = False
    try:
        _private_write(output / "route.json", route)
        selected = (
            _run_core(
                root=root,
                artifact_root=output,
                contract=contract,
                route=route,
            )
            if lane_id == "core"
            else _run_service(
                root=root,
                artifact_root=output,
                contract=contract,
                route=route,
            )
        )
        files: list[tuple[str, str]] = [("route", "route.json")]
        gate_results: list[tuple[str, str, str]] = []
        for gate_id, phase, run, summary, gate_dir in selected:
            run_path = gate_dir / "command-run.json"
            _private_write(run_path, run.as_dict())
            files.append(("command_run", run_path.relative_to(output).as_posix()))
            if summary is not None:
                summary_path = gate_dir / "junit-summary.json"
                _private_write(summary_path, summary.as_dict())
                files.append(("junit_summary", summary_path.relative_to(output).as_posix()))
            evidence = _evidence(
                repo_root=root,
                contract=contract,
                route=route,
                run=run,
                summary=summary,
                service_digest=(
                    service_compatibility_digest() if lane_id == "service" else None
                ),
            )
            evidence_path = gate_dir / "gate-evidence.json"
            _private_write(evidence_path, evidence)
            files.append(("gate_evidence", evidence_path.relative_to(output).as_posix()))
            gate_results.append((gate_id, phase, str(evidence["result"])))
        envelope = create_envelope(
            repo_root=root,
            artifact_root=output,
            context=context,
            files=files,
        )
        validate_envelope(envelope.as_dict())
        _private_write(output / "envelope.json", envelope.as_dict())
        complete = True
        return LaneOutput(
            lane_id,
            artifact_name(context),
            envelope.envelope_identity,
            tuple(sorted(gate_results)),
        )
    finally:
        if not complete:
            shutil.rmtree(output, ignore_errors=True)


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
            compile(path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True)
    commands = (
        ("uv", "lock", "--check"),
        ("git", "diff", "--check", base_sha, head_sha, "--"),
    )
    for command in commands:
        code = _run_subprocess(command)
        if code:
            return code
    return 0


def core_tests(*, repo_root: str | Path, report: str | Path, clustering: bool) -> int:
    root = Path(repo_root).resolve()
    report_path = Path(report).resolve()
    if not report_path.is_relative_to(root):
        raise WorkflowLaneError("report_path")
    code = _run_subprocess(
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "newsroom/tests",
            f"--junitxml={report_path}",
        )
    )
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


def service_tests(
    *, repo_root: str | Path, report: str | Path, test_paths: Sequence[str]
) -> int:
    root = Path(repo_root).resolve()
    report_path = Path(report).resolve()
    if not report_path.is_relative_to(root) or not test_paths:
        raise WorkflowLaneError("service_tests")
    return _run_subprocess(
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *test_paths,
            f"--junitxml={report_path}",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exact Newsroom SDLC shadow lane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--repo-root", default=".")
    run_parser.add_argument("--route", required=True)
    run_parser.add_argument("--lane", choices=("core", "service"), required=True)
    run_parser.add_argument("--artifact-root", required=True)
    run_parser.add_argument("--output")

    source_parser = subparsers.add_parser("source-check")
    source_parser.add_argument("--repo-root", default=".")
    source_parser.add_argument("--base-sha", required=True)
    source_parser.add_argument("--head-sha", required=True)

    core_parser = subparsers.add_parser("core-tests")
    core_parser.add_argument("--repo-root", default=".")
    core_parser.add_argument("--report", required=True)
    core_parser.add_argument("--clustering", action="store_true")

    service_parser = subparsers.add_parser("service-tests")
    service_parser.add_argument("--repo-root", default=".")
    service_parser.add_argument("--report", required=True)
    service_parser.add_argument("test_paths", nargs="+")

    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "run":
            result = run_lane(
                repo_root=arguments.repo_root,
                route_path=arguments.route,
                lane_id=arguments.lane,
                artifact_root=arguments.artifact_root,
            )
            rendered = canonical_json_bytes(result.as_dict()) + b"\n"
            if arguments.output:
                root = Path(arguments.repo_root).resolve()
                output = root / arguments.output
                if not output.parent.is_dir() or not output.resolve().is_relative_to(root):
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
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        reason = str(exc) if str(exc) else type(exc).__name__
        print(f"EVIDENCE_MISMATCH:workflow-lane:{reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
