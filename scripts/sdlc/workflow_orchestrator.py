from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Mapping, Sequence

from .artifact_envelope import (
    ArtifactProvenanceError,
    GithubRunContext,
    _context_from_mapping,
    _safe_machine_file,
    _unique_object,
    _validate_context,
    _validate_json_depth,
    artifact_name,
    context_from_environment,
)
from .classify_change import GitRouteError, build_git_route
from .contracts import ContractError, SdlcContract, load_contract
from .emit_evidence import EvidenceError, canonical_json_bytes, sha256_identity
from .github_transport import (
    GitHubActionsClient,
    GitHubTransportError,
    fetch_artifact_bundle,
)
from .run_gate import GateRunError, GateRunResult, run_configured_gate, start_lane_deadline
from .shadow_decision import (
    ShadowDecision,
    ShadowDecisionError,
    aggregate_shadow_decision,
    failure_shadow_decision,
    validate_shadow_decision,
)
from .shadow_lane import (
    ShadowLaneError,
    ShadowLaneRecord,
    validate_shadow_lane_record,
    verify_shadow_lane,
)
from .workflow_event import (
    WorkflowEvent,
    WorkflowEvidenceError,
    derive_workflow_event,
    validate_workflow_event,
)


ROUTE_OUTPUT_SCHEMA = "newsroom.sdlc.workflow-route-output.v1"
COLLECTION_SCHEMA = "newsroom.sdlc.decision-collection.v1"
_SAFE_CODE = re.compile(r"[A-Za-z0-9_.-]{1,128}")
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
_MAX_JSON_BYTES = 64 * 1024 * 1024


class WorkflowOrchestratorError(ValueError):
    """Raised when the shadow workflow cannot produce trustworthy orchestration."""


@dataclass(frozen=True)
class RouteOutput:
    artifact_name: str
    service_required: bool
    route_identity: str
    event_identity: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": ROUTE_OUTPUT_SCHEMA,
            "artifact_name": self.artifact_name,
            "service_required": self.service_required,
            "route_identity": self.route_identity,
            "event_identity": self.event_identity,
        }


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise WorkflowOrchestratorError(code)
    return value


def _code(value: object, code: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise WorkflowOrchestratorError(code)
    return value


def _result(value: object, code: str) -> str:
    selected = _code(value, code)
    if selected not in _RESULTS or selected == "PASS":
        raise WorkflowOrchestratorError(code)
    return selected


def _canonical_load(path: Path, *, maximum: int = _MAX_JSON_BYTES) -> object:
    try:
        payload = _safe_machine_file(path.resolve(), maximum=maximum, code="machine_file")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(value)
    except (ArtifactProvenanceError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowOrchestratorError("machine_json") from exc
    if payload != canonical_json_bytes(value) + b"\n":
        raise WorkflowOrchestratorError("machine_canonical")
    return value


def _safe_target(root: Path, relative: str | Path, *, suffix: str | None = None) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
        or (suffix is not None and candidate.suffix != suffix)
    ):
        raise WorkflowOrchestratorError("output_path")
    current = root
    for part in candidate.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise WorkflowOrchestratorError("output_parent")
    parent = current.resolve()
    if not parent.is_relative_to(root) or not parent.is_dir():
        raise WorkflowOrchestratorError("output_parent")
    target = current / candidate.name
    if target.exists() or target.is_symlink():
        raise WorkflowOrchestratorError("output_exists")
    return target


def _private_write(path: Path, value: object) -> None:
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
            raise WorkflowOrchestratorError("output_exists") from exc
        except OSError as exc:
            if linked:
                path.unlink(missing_ok=True)
            raise WorkflowOrchestratorError("output_publish") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _prepare_directory(root: Path, relative: str | Path) -> Path:
    target = _safe_target(root, relative)
    target.mkdir(mode=0o700)
    return target.resolve()


def _route_artifact_name(context: GithubRunContext) -> str:
    return (
        f"newsroom-sdlc-route-{context.run_id}-{context.run_attempt}-"
        f"{context.evaluated_sha}"
    )


def prepare_route(
    *, repo_root: str | Path, output_directory: str | Path
) -> RouteOutput:
    root = Path(repo_root).resolve()
    context = context_from_environment(root)
    if context.job_id != "route":
        raise WorkflowOrchestratorError("route_job")
    event = derive_workflow_event(root)
    route = build_git_route(
        root,
        base_reference=event.base_sha,
        head_reference=event.evaluated_sha,
    )
    if (
        route.get("base_sha") != event.base_sha
        or route.get("base_tree_sha") != event.base_tree_sha
        or route.get("head_sha") != event.evaluated_sha
        or route.get("head_tree_sha") != event.evaluated_tree_sha
    ):
        raise WorkflowOrchestratorError("route_event_identity")
    target = _prepare_directory(root, output_directory)
    complete = False
    try:
        _private_write(target / "route.json", route)
        _private_write(target / "event.json", event.as_dict())
        output = RouteOutput(
            artifact_name=_route_artifact_name(context),
            service_required=route.get("service_required") is True,
            route_identity=sha256_identity(route),
            event_identity=str(event.as_dict()["event_identity"]),
        )
        _private_write(target / "route-output.json", output.as_dict())
        complete = True
        return output
    finally:
        if not complete:
            shutil.rmtree(target, ignore_errors=True)


def _producer_context(context: GithubRunContext, job_id: str) -> GithubRunContext:
    producer = GithubRunContext(
        repository=context.repository,
        repository_id=context.repository_id,
        head_repository=context.head_repository,
        head_repository_id=context.head_repository_id,
        run_id=context.run_id,
        run_attempt=context.run_attempt,
        job_id=job_id,
        workflow_ref=context.workflow_ref,
        workflow_sha=context.workflow_sha,
        event_name=context.event_name,
        event_sha=context.event_sha,
        evaluated_sha=context.evaluated_sha,
        evaluated_tree_sha=context.evaluated_tree_sha,
        ref=context.ref,
        runner_environment=context.runner_environment,
    )
    return _validate_context(producer)


def _collection_identity(value: Mapping[str, object]) -> str:
    return sha256_identity(
        {key: item for key, item in value.items() if key != "collection_identity"}
    )


def _collection_value(
    *,
    context: GithubRunContext,
    event: WorkflowEvent | None,
    core: ShadowLaneRecord | None,
    service: ShadowLaneRecord | None,
    status: str,
    failure_result: str | None,
    failure_code: str | None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": COLLECTION_SCHEMA,
        "collection_identity": "",
        "status": status,
        "failure_result": failure_result,
        "failure_code": failure_code,
        "context": context.as_dict(),
        "event": None if event is None else event.as_dict(),
        "core": None if core is None else core.as_dict(),
        "service": None if service is None else service.as_dict(),
    }
    value["collection_identity"] = _collection_identity(value)
    return value


def validate_collection(
    value: object, *, contract: SdlcContract | None
) -> dict[str, object]:
    item = dict(_mapping(value, "collection"))
    if set(item) != {
        "schema_version",
        "collection_identity",
        "status",
        "failure_result",
        "failure_code",
        "context",
        "event",
        "core",
        "service",
    } or item.get("schema_version") != COLLECTION_SCHEMA:
        raise WorkflowOrchestratorError("collection_shape")
    try:
        context = _context_from_mapping(item.get("context"))
    except ArtifactProvenanceError as exc:
        raise WorkflowOrchestratorError("collection_context") from exc
    if context.job_id != "decision":
        raise WorkflowOrchestratorError("collection_context")
    status = item.get("status")
    if status not in {"READY", "ERROR"}:
        raise WorkflowOrchestratorError("collection_status")
    event_value = item.get("event")
    core_value = item.get("core")
    service_value = item.get("service")
    if status == "READY":
        if item.get("failure_result") is not None or item.get("failure_code") is not None:
            raise WorkflowOrchestratorError("collection_failure")
        if contract is None:
            raise WorkflowOrchestratorError("collection_contract")
        try:
            event = validate_workflow_event(event_value)
            core = validate_shadow_lane_record(core_value, contract=contract)
            service = (
                None
                if service_value is None
                else validate_shadow_lane_record(service_value, contract=contract)
            )
        except (WorkflowEvidenceError, ShadowLaneError) as exc:
            raise WorkflowOrchestratorError("collection_evidence") from exc
        if core.lane_id != "core" or (service is not None and service.lane_id != "service"):
            raise WorkflowOrchestratorError("collection_lane")
        if core.receipt.route.service_required is not (service is not None):
            raise WorkflowOrchestratorError("collection_service")
        item["event"] = event.as_dict()
        item["core"] = core.as_dict()
        item["service"] = None if service is None else service.as_dict()
    else:
        if (
            event_value is not None
            or core_value is not None
            or service_value is not None
        ):
            raise WorkflowOrchestratorError("collection_failure")
        item["failure_result"] = _result(
            item.get("failure_result"), "collection_failure_result"
        )
        item["failure_code"] = _code(
            item.get("failure_code"), "collection_failure_code"
        )
    item["context"] = context.as_dict()
    expected = _collection_identity(item)
    if item.get("collection_identity") != expected:
        raise WorkflowOrchestratorError("collection_identity")
    return item


def _unexpected_artifact(
    client: GitHubActionsClient, *, run_id: int, name: str
) -> bool:
    listing = client.list_artifacts(run_id)
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        raise WorkflowOrchestratorError("artifact_listing")
    return any(isinstance(item, dict) and item.get("name") == name for item in artifacts)


def collect_decision_inputs(
    *, repo_root: str | Path, output_directory: str | Path
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    context = context_from_environment(root)
    if context.job_id != "decision":
        raise WorkflowOrchestratorError("decision_job")
    target = _prepare_directory(root, output_directory)
    try:
        _private_write(target / "context.json", context.as_dict())
        event: WorkflowEvent | None = None
        core: ShadowLaneRecord | None = None
        service: ShadowLaneRecord | None = None
        failure_result: str | None = None
        failure_code: str | None = None
        contract: SdlcContract | None = None
        try:
            contract = load_contract(root)
            event = derive_workflow_event(root)
            client = GitHubActionsClient.from_environment()
            core_name = artifact_name(_producer_context(context, "core"))
            fetch_artifact_bundle(
                client=client,
                output_parent=target,
                output_name="core-transport",
                run_id=context.run_id,
                run_attempt=context.run_attempt,
                artifact_name=core_name,
            )
            core = verify_shadow_lane(
                repo_root=root,
                bundle_root=target / "core-transport",
                lane_id="core",
                decision_context=context,
                contract=contract,
            )
            service_name = artifact_name(_producer_context(context, "service"))
            if core.receipt.route.service_required:
                fetch_artifact_bundle(
                    client=client,
                    output_parent=target,
                    output_name="service-transport",
                    run_id=context.run_id,
                    run_attempt=context.run_attempt,
                    artifact_name=service_name,
                )
                service = verify_shadow_lane(
                    repo_root=root,
                    bundle_root=target / "service-transport",
                    lane_id="service",
                    decision_context=context,
                    contract=contract,
                )
            elif _unexpected_artifact(
                client, run_id=context.run_id, name=service_name
            ):
                raise WorkflowOrchestratorError("service_artifact_unexpected")
        except WorkflowOrchestratorError as exc:
            event = core = service = None
            failure_result = "EVIDENCE_MISMATCH"
            failure_code = _code(str(exc) or "collection", "collection_error")
        except GitHubTransportError:
            event = core = service = None
            failure_result = "EVIDENCE_MISMATCH"
            failure_code = "artifact-transport"
        except ShadowLaneError:
            event = core = service = None
            failure_result = "EVIDENCE_MISMATCH"
            failure_code = "lane-verification"
        except (ContractError, WorkflowEvidenceError, ArtifactProvenanceError):
            event = core = service = None
            failure_result = "EVIDENCE_MISMATCH"
            failure_code = "collection-input"
        except (OSError, UnicodeError, json.JSONDecodeError):
            event = core = service = None
            failure_result = "ENVIRONMENT_ERROR"
            failure_code = "collection-environment"
        collection = _collection_value(
            context=context,
            event=event,
            core=core,
            service=service,
            status="READY" if failure_code is None else "ERROR",
            failure_result=failure_result,
            failure_code=failure_code,
        )
        normalized = validate_collection(collection, contract=contract)
        _private_write(target / "collection.json", normalized)
        return normalized
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _safe_input(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    absolute = candidate if candidate.is_absolute() else root / candidate
    absolute = absolute if absolute.is_absolute() else absolute.absolute()
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise WorkflowOrchestratorError("input_path") from exc
    if not resolved.is_relative_to(root):
        raise WorkflowOrchestratorError("input_path")
    return absolute


def _load_context(root: Path, value: str | Path) -> GithubRunContext:
    path = _safe_input(root, value)
    try:
        context = _context_from_mapping(_canonical_load(path))
    except ArtifactProvenanceError as exc:
        raise WorkflowOrchestratorError("decision_context") from exc
    if context.job_id != "decision":
        raise WorkflowOrchestratorError("decision_context")
    return context


def decision_from_collection(
    *, repo_root: str | Path, context_path: str | Path, collection_path: str | Path
) -> ShadowDecision:
    root = Path(repo_root).resolve()
    context = _load_context(root, context_path)
    try:
        contract = load_contract(root)
        collection = validate_collection(
            _canonical_load(_safe_input(root, collection_path)), contract=contract
        )
        retained = _context_from_mapping(collection["context"])
        if retained != context:
            raise WorkflowOrchestratorError("collection_context")
        if collection["status"] == "ERROR":
            return failure_shadow_decision(
                context=context,
                code=str(collection["failure_code"]),
                result=str(collection["failure_result"]),
            )
        event = validate_workflow_event(collection["event"])
        core = validate_shadow_lane_record(collection["core"], contract=contract)
        service = (
            None
            if collection["service"] is None
            else validate_shadow_lane_record(collection["service"], contract=contract)
        )
        return aggregate_shadow_decision(
            context=context,
            event=event,
            core=core,
            service=service,
            contract=contract,
        )
    except (
        WorkflowOrchestratorError,
        ContractError,
        WorkflowEvidenceError,
        ShadowLaneError,
        ShadowDecisionError,
        ArtifactProvenanceError,
        EvidenceError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ):
        return failure_shadow_decision(context=context, code="invalid-collection")


def _decision_environment() -> dict[str, str]:
    return {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
    }


def _fallback_result(result: GateRunResult) -> tuple[str, str]:
    if result.result == "BUDGET_EXCEEDED":
        return "BUDGET_EXCEEDED", "finalization-timeout"
    if result.result == "ENVIRONMENT_ERROR":
        return "ENVIRONMENT_ERROR", "finalization-environment"
    if result.result == "UNAUTHORISED_EFFECT":
        return "UNAUTHORISED_EFFECT", "finalization-effect"
    return "EVIDENCE_MISMATCH", "finalization-process"


def run_bounded_decision(
    *,
    repo_root: str | Path,
    context_path: str | Path,
    collection_path: str | Path,
    output_path: str | Path,
) -> ShadowDecision:
    root = Path(repo_root).resolve()
    context = _load_context(root, context_path)
    output = _safe_target(root, output_path, suffix=".json")
    try:
        contract = load_contract(root)
    except ContractError:
        decision = failure_shadow_decision(
            context=context, code="contract-load", result="EVIDENCE_MISMATCH"
        )
        _private_write(output, decision.as_dict())
        return decision
    temporary = Path(tempfile.mkdtemp(prefix=".shadow-decision.", dir=output.parent))
    try:
        child = temporary / "decision.json"
        deadline = start_lane_deadline(contract, "evidence-finalize")
        run = run_configured_gate(
            contract=contract,
            gate_id="evidence-finalize",
            phase="decision",
            argv=(
                sys.executable,
                "-m",
                "scripts.sdlc.workflow_orchestrator",
                "decision-child",
                "--repo-root",
                str(root),
                "--context",
                str(_safe_input(root, context_path)),
                "--collection",
                str(_safe_input(root, collection_path)),
                "--output",
                str(child),
            ),
            deadline=deadline,
            cwd=root,
            env=_decision_environment(),
            output_limit_bytes=65_536,
            termination_grace_seconds=0.25,
        )
        decision: ShadowDecision
        if run.result == "PASS" and child.is_file():
            try:
                decision = validate_shadow_decision(
                    _canonical_load(child), contract=contract
                )
            except (WorkflowOrchestratorError, ShadowDecisionError):
                decision = failure_shadow_decision(
                    context=context, code="invalid-decision-output"
                )
        else:
            result, code = _fallback_result(run)
            decision = failure_shadow_decision(
                context=context, code=code, result=result
            )
        decision = validate_shadow_decision(decision.as_dict(), contract=contract)
        _private_write(output, decision.as_dict())
        return decision
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _decision_child(
    *,
    repo_root: str | Path,
    context_path: str | Path,
    collection_path: str | Path,
    output_path: str | Path,
) -> ShadowDecision:
    root = Path(repo_root).resolve()
    output = Path(output_path)
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or not output.parent.is_dir()
        or not output.parent.resolve().is_relative_to(root)
    ):
        raise WorkflowOrchestratorError("child_output")
    decision = decision_from_collection(
        repo_root=root,
        context_path=context_path,
        collection_path=collection_path,
    )
    _private_write(output, decision.as_dict())
    return decision


def enforce_decision(*, repo_root: str | Path, decision_path: str | Path) -> int:
    root = Path(repo_root).resolve()
    contract = load_contract(root)
    decision = validate_shadow_decision(
        _canonical_load(_safe_input(root, decision_path)), contract=contract
    )
    print(f"{decision.result}:{decision.decision_identity}")
    return 0 if decision.result == "PASS" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orchestrate exact Newsroom SDLC shadow evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("route")
    route.add_argument("--repo-root", default=".")
    route.add_argument("--output-directory", required=True)

    collect = subparsers.add_parser("collect")
    collect.add_argument("--repo-root", default=".")
    collect.add_argument("--output-directory", required=True)

    child = subparsers.add_parser("decision-child")
    child.add_argument("--repo-root", default=".")
    child.add_argument("--context", required=True)
    child.add_argument("--collection", required=True)
    child.add_argument("--output", required=True)

    decide = subparsers.add_parser("decide")
    decide.add_argument("--repo-root", default=".")
    decide.add_argument("--context", required=True)
    decide.add_argument("--collection", required=True)
    decide.add_argument("--output", required=True)

    enforce = subparsers.add_parser("enforce")
    enforce.add_argument("--repo-root", default=".")
    enforce.add_argument("--decision", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "route":
            value = prepare_route(
                repo_root=arguments.repo_root,
                output_directory=arguments.output_directory,
            ).as_dict()
        elif arguments.command == "collect":
            value = collect_decision_inputs(
                repo_root=arguments.repo_root,
                output_directory=arguments.output_directory,
            )
        elif arguments.command == "decision-child":
            value = _decision_child(
                repo_root=arguments.repo_root,
                context_path=arguments.context,
                collection_path=arguments.collection,
                output_path=arguments.output,
            ).as_dict()
        elif arguments.command == "decide":
            value = run_bounded_decision(
                repo_root=arguments.repo_root,
                context_path=arguments.context,
                collection_path=arguments.collection,
                output_path=arguments.output,
            ).as_dict()
        else:
            return enforce_decision(
                repo_root=arguments.repo_root,
                decision_path=arguments.decision,
            )
        sys.stdout.buffer.write(canonical_json_bytes(value) + b"\n")
        return 0
    except (
        WorkflowOrchestratorError,
        ArtifactProvenanceError,
        ContractError,
        EvidenceError,
        GitHubTransportError,
        GitRouteError,
        GateRunError,
        ShadowDecisionError,
        ShadowLaneError,
        WorkflowEvidenceError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, WorkflowOrchestratorError)
            and str(exc)
            and _SAFE_CODE.fullmatch(str(exc))
            else type(exc).__name__
        )
        print(f"EVIDENCE_MISMATCH:workflow-orchestrator:{reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
