from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from newsroom.increment5.final_closeout import (
    INCREMENT5_FINAL_REQUIREMENTS,
    INCREMENT5E2_FINAL_CLOSEOUT_CASES,
    INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT5E2_FINAL_NON_EFFECTS,
    FinalCloseoutLane,
)
from newsroom.increment5.retrieval_qualification import (
    QUALIFICATION_CORPUS,
    QUALIFICATION_TARGET,
    QualificationDecision,
    QualificationReport,
    RetrievalQualificationError,
    RetrievalQualificationEvaluator,
    build_qualification_epoch,
    run_fixture_qualification,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
)
from scripts.sdlc.contracts import ContractError, load_contract
from scripts.sdlc.emit_evidence import canonical_json_bytes, sha256_identity
from scripts.sdlc.shadow_decision import (
    ShadowDecisionError,
    validate_shadow_decision,
)
from scripts.sdlc.transport_replay import (
    TransportReplayError,
    load_verified_transport,
)
from scripts.sdlc.workflow_lane import service_compatibility_digest

ACTUAL_SERVICE_SCHEMA_VERSION = (
    "newsroom.increment5e2.actual-service-closeout-receipt.v1"
)
FINAL_SCHEMA_VERSION = "newsroom.increment5e2.final-closeout-receipt.v1"
_MAX_REPORT_BYTES = 16 * 1024 * 1024
_MAX_DECISION_BYTES = 8 * 1024 * 1024
_MAX_TESTS = 100_000
_MAX_TEST_NAME_CHARS = 64 * 1024
_QUALIFICATION_STARTED_AT = "2026-08-08T20:00:00Z"
_QUALIFICATION_COMPLETED_AT = "2026-08-08T20:01:00Z"
_TARGET_TEST_ID = (
    "newsroom.tests.test_projection_b2_increment5e2_neo4j_service::"
    "test_actual_service_increment5e2_target_and_report"
)
_TARGET_PROPERTIES = {
    "increment5e2_epoch_digest",
    "increment5e2_epoch_json",
    "increment5e2_report_digest",
    "increment5e2_report_json",
    "increment5e2_closeout_inventory_digest",
    "increment5e2_closeout_case_count",
    "increment5e2_non_effects",
    "increment5e2_source_head_sha",
    "increment5e2_source_tree_sha",
    "increment5e2_neo4j_image",
    "increment5e2_neo4j_server_version",
    "increment5e2_neo4j_edition",
    "increment5e2_neo4j_driver_version",
    "increment5e2_neo4j_database",
    "increment5e2_neo4j_projector_username",
    "increment5e2_service_compatibility_digest",
}


class Increment5E2CloseoutReceiptError(ValueError):
    """Raised when closed-world Increment 5E2 evidence is not exact."""


@dataclass(frozen=True, slots=True)
class _JUnitCase:
    test_id: str
    outcome: str
    properties: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _ParsedReport:
    path: Path
    payload: bytes
    digest: str
    cases: tuple[_JUnitCase, ...]


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Increment5E2CloseoutReceiptError("duplicate_json_key")
        result[key] = value
    return result


def _json(payload: bytes | str, code: str) -> object:
    try:
        raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                Increment5E2CloseoutReceiptError(code)
            ),
        )
        pending = [(value, 0)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if depth > 64 or nodes > 100_000:
                raise Increment5E2CloseoutReceiptError(f"{code}_bounds")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except Increment5E2CloseoutReceiptError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Increment5E2CloseoutReceiptError(code) from exc


def _safe_file(path: str | Path, *, maximum: int, code: str) -> tuple[Path, bytes]:
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else candidate.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise Increment5E2CloseoutReceiptError(f"{code}_symlink")
    try:
        initial = os.lstat(absolute)
    except OSError as exc:
        raise Increment5E2CloseoutReceiptError(code) from exc
    if (
        not stat.S_ISREG(initial.st_mode)
        or initial.st_size <= 0
        or initial.st_size > maximum
    ):
        raise Increment5E2CloseoutReceiptError(code)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(absolute, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != initial.st_dev
            or opened.st_ino != initial.st_ino
            or opened.st_size != initial.st_size
        ):
            raise Increment5E2CloseoutReceiptError(code)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            payload = stream.read(maximum + 1)
    except Increment5E2CloseoutReceiptError:
        raise
    except OSError as exc:
        raise Increment5E2CloseoutReceiptError(code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) != initial.st_size or len(payload) > maximum:
        raise Increment5E2CloseoutReceiptError(code)
    return absolute, payload


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _field(value: str | None, code: str, *, maximum: int = 2 * 1024 * 1024) -> str:
    text = value or ""
    if not text or len(text) > maximum or "\x00" in text:
        raise Increment5E2CloseoutReceiptError(code)
    return text


def _parse_properties(case: ET.Element) -> Mapping[str, str]:
    values: dict[str, str] = {}
    containers = [child for child in case if _local_name(child.tag) == "properties"]
    if len(containers) > 1:
        raise Increment5E2CloseoutReceiptError("duplicate_properties")
    if not containers:
        return values
    children = list(containers[0])
    if len(children) > 128:
        raise Increment5E2CloseoutReceiptError("property_count")
    for child in children:
        if _local_name(child.tag) != "property":
            raise Increment5E2CloseoutReceiptError("property_shape")
        name = _field(child.attrib.get("name"), "property_name", maximum=256)
        if name in values:
            raise Increment5E2CloseoutReceiptError("duplicate_property")
        if "value" in child.attrib:
            value = child.attrib["value"]
            if child.text and child.text.strip():
                raise Increment5E2CloseoutReceiptError("property_shape")
        else:
            value = child.text or ""
        if len(value) > 2 * 1024 * 1024 or "\x00" in value:
            raise Increment5E2CloseoutReceiptError("property_value")
        values[name] = value
    return values


def _parse_junit(path: str | Path) -> _ParsedReport:
    absolute, payload = _safe_file(path, maximum=_MAX_REPORT_BYTES, code="junit_report")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Increment5E2CloseoutReceiptError("junit_xml_encoding") from exc
    upper = decoded.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise Increment5E2CloseoutReceiptError("junit_xml_declaration")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise Increment5E2CloseoutReceiptError("junit_xml") from exc
    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        raise Increment5E2CloseoutReceiptError("junit_root")
    cases: list[_JUnitCase] = []
    seen: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) != "testcase":
            continue
        name = _field(
            element.attrib.get("name"),
            "test_name",
            maximum=_MAX_TEST_NAME_CHARS,
        ).strip()
        owner = (element.attrib.get("classname") or "").strip() or (
            element.attrib.get("file") or ""
        ).strip()
        owner = _field(owner, "test_owner", maximum=1024)
        test_id = f"{owner}::{name}"
        if test_id in seen:
            raise Increment5E2CloseoutReceiptError("duplicate_test_id")
        seen.add(test_id)
        terminals = [
            child
            for child in element
            if _local_name(child.tag) in {"failure", "error", "skipped"}
        ]
        if len(terminals) > 1:
            raise Increment5E2CloseoutReceiptError("conflicting_test_outcome")
        outcome = _local_name(terminals[0].tag) if terminals else "passed"
        cases.append(_JUnitCase(test_id, outcome, _parse_properties(element)))
        if len(cases) > _MAX_TESTS:
            raise Increment5E2CloseoutReceiptError("junit_test_count")
    if not cases:
        raise Increment5E2CloseoutReceiptError("junit_no_tests")
    return _ParsedReport(absolute, payload, _digest(payload), tuple(cases))


def _git_identity(repo_root: str | Path) -> tuple[Path, str, str]:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise Increment5E2CloseoutReceiptError("repo_root")
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel", "HEAD", "HEAD^{tree}"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Increment5E2CloseoutReceiptError("git_identity") from exc
    if len(output) != 3 or Path(output[0]).resolve() != root:
        raise Increment5E2CloseoutReceiptError("repo_root")
    head, tree = output[1:]
    if any(len(value) != 40 or value.lower() != value for value in (head, tree)):
        raise Increment5E2CloseoutReceiptError("git_identity")
    return root, head, tree


def _require_git_identity(root: Path, head: str, tree: str) -> None:
    _same_root, current_head, current_tree = _git_identity(root)
    if (current_head, current_tree) != (head, tree):
        raise Increment5E2CloseoutReceiptError("stale_checkout_identity")


def _selected_cases(
    reports: Sequence[_ParsedReport], lane: FinalCloseoutLane
) -> tuple[list[dict[str, object]], Mapping[str, str]]:
    all_cases: dict[str, _JUnitCase] = {}
    for report in reports:
        for case in report.cases:
            if case.test_id in all_cases:
                raise Increment5E2CloseoutReceiptError("duplicate_test_id")
            all_cases[case.test_id] = case
    selected: list[dict[str, object]] = []
    target_properties: Mapping[str, str] = {}
    for item in INCREMENT5E2_FINAL_CLOSEOUT_CASES:
        if item.lane is not lane:
            continue
        case = all_cases.get(item.test_id)
        if case is None:
            raise Increment5E2CloseoutReceiptError(
                f"selected_test_missing:{item.case_id}"
            )
        if case.outcome != "passed":
            raise Increment5E2CloseoutReceiptError(
                f"selected_test_not_passed:{item.case_id}:{case.outcome}"
            )
        selected.append({**item.canonical_value(), "outcome": "passed"})
        if item.test_id == _TARGET_TEST_ID:
            target_properties = case.properties
    return selected, target_properties


def _reject_unselected_failures(
    reports: Sequence[_ParsedReport], lane: FinalCloseoutLane
) -> None:
    selected_test_ids = {
        item.test_id for item in INCREMENT5E2_FINAL_CLOSEOUT_CASES if item.lane is lane
    }
    for report in reports:
        for case in report.cases:
            if case.test_id not in selected_test_ids and case.outcome in {
                "failure",
                "error",
            }:
                raise Increment5E2CloseoutReceiptError(
                    f"unselected_test_not_passed:{case.test_id}:{case.outcome}"
                )


def _semantic_identities(
    properties: Mapping[str, str], head: str, tree: str
) -> dict[str, object]:
    missing = _TARGET_PROPERTIES - properties.keys()
    extra = properties.keys() - _TARGET_PROPERTIES
    if missing or extra:
        raise Increment5E2CloseoutReceiptError("target_properties")
    expected_epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=tree,
    )
    epoch_value = _json(properties["increment5e2_epoch_json"], "epoch_json")
    if (
        epoch_value != expected_epoch.canonical_value()
        or properties["increment5e2_epoch_json"]
        != canonical_json_bytes(epoch_value).decode("utf-8")
        or properties["increment5e2_epoch_digest"] != expected_epoch.epoch_digest
    ):
        raise Increment5E2CloseoutReceiptError("epoch_identity")
    report_text = properties["increment5e2_report_json"]
    _json(report_text, "report_json")
    try:
        report = QualificationReport.from_canonical_bytes(report_text.encode("utf-8"))
    except RetrievalQualificationError as exc:
        raise Increment5E2CloseoutReceiptError("qualification_report") from exc
    expected_report = RetrievalQualificationEvaluator().evaluate(
        run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, expected_epoch.epoch_digest)),
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        epoch=expected_epoch,
        code_tree_sha=tree,
        observations=run_fixture_qualification(
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
        ),
        started_at=_QUALIFICATION_STARTED_AT,
        completed_at=_QUALIFICATION_COMPLETED_AT,
    )
    if (
        properties["increment5e2_report_digest"] != report.report_digest
        or report.canonical_bytes != expected_report.canonical_bytes
        or report.epoch_digest != expected_epoch.epoch_digest
        or report.code_tree_sha != tree
        or report.decision is not QualificationDecision.PASS
        or report.observation_count != 500
        or report.expected_observation_count != 500
        or report.external_call_count != 0
        or report.provider_spend_micros != 0
        or report.authority_effect != "NONE"
        or report.candidate_created
        or report.hypothesis_created
        or report.production_activation_authorized
    ):
        raise Increment5E2CloseoutReceiptError("qualification_report_semantics")
    if (
        properties["increment5e2_closeout_inventory_digest"]
        != INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST
        or properties["increment5e2_closeout_case_count"]
        != str(len(INCREMENT5E2_FINAL_CLOSEOUT_CASES))
        or properties["increment5e2_non_effects"]
        != ",".join(INCREMENT5E2_FINAL_NON_EFFECTS)
    ):
        raise Increment5E2CloseoutReceiptError("closeout_inventory")
    expected_service = {
        "increment5e2_source_head_sha": head,
        "increment5e2_source_tree_sha": tree,
        "increment5e2_neo4j_image": NEO4J_B2_IMAGE,
        "increment5e2_neo4j_server_version": NEO4J_B2_SERVER_VERSION,
        "increment5e2_neo4j_edition": "community",
        "increment5e2_neo4j_driver_version": NEO4J_B2_DRIVER_VERSION,
        "increment5e2_neo4j_database": "neo4j",
        "increment5e2_neo4j_projector_username": "newsroom_projector",
        "increment5e2_service_compatibility_digest": service_compatibility_digest(),
    }
    if any(properties[name] != value for name, value in expected_service.items()):
        raise Increment5E2CloseoutReceiptError("service_identity")
    return {
        "epoch": {
            "epoch_id": expected_epoch.epoch_id,
            "epoch_digest": expected_epoch.epoch_digest,
            "code_tree_sha": tree,
        },
        "qualification_report": {
            "report_id": report.report_id,
            "report_digest": report.report_digest,
            "epoch_digest": report.epoch_digest,
            "code_tree_sha": report.code_tree_sha,
            "decision": report.decision.value,
            "observation_count": report.observation_count,
        },
        "service": {
            "image": NEO4J_B2_IMAGE,
            "server_version": NEO4J_B2_SERVER_VERSION,
            "edition": "community",
            "driver_version": NEO4J_B2_DRIVER_VERSION,
            "database": "neo4j",
            "projector_username": "newsroom_projector",
            "compatibility_digest": service_compatibility_digest(),
        },
    }


def _inventory() -> dict[str, object]:
    return {
        "digest": INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST,
        "case_count": len(INCREMENT5E2_FINAL_CLOSEOUT_CASES),
        "requirements": sorted(INCREMENT5_FINAL_REQUIREMENTS),
        "non_effects": list(INCREMENT5E2_FINAL_NON_EFFECTS),
    }


def _with_identity(value: dict[str, object]) -> dict[str, object]:
    return {**value, "receipt_identity": sha256_identity(value)}


def build_actual_service_receipt(
    *, repo_root: str | Path, service_junit_report: str | Path
) -> dict[str, object]:
    _root, head, tree = _git_identity(repo_root)
    report = _parse_junit(service_junit_report)
    _reject_unselected_failures((report,), FinalCloseoutLane.ACTUAL_NEO4J)
    selected, properties = _selected_cases((report,), FinalCloseoutLane.ACTUAL_NEO4J)
    identities = _semantic_identities(properties, head, tree)
    _require_git_identity(_root, head, tree)
    return _with_identity(
        {
            "schema_version": ACTUAL_SERVICE_SCHEMA_VERSION,
            "evaluated_sha": head,
            "evaluated_tree_sha": tree,
            "junit_report": {
                "path": report.path.name,
                "size_bytes": len(report.payload),
                "digest": report.digest,
            },
            "selected_cases": selected,
            "inventory": _inventory(),
            **identities,
        }
    )


def _decision_payload(path: str | Path) -> object:
    _path, payload = _safe_file(path, maximum=_MAX_DECISION_BYTES, code="decision")
    return _json(payload, "decision_json")


def _lane_reports(verified: object, lane: object) -> tuple[_ParsedReport, ...]:
    if verified.replay != lane.replay:
        raise Increment5E2CloseoutReceiptError("transport_replay_identity")
    reports = []
    for raw in lane.receipt.raw_reports:
        report = _parse_junit(verified.artifact_root / raw.path)
        if len(report.payload) != raw.size_bytes or report.digest != raw.digest:
            raise Increment5E2CloseoutReceiptError("receipt_report_digest")
        reports.append(report)
    if not reports:
        raise Increment5E2CloseoutReceiptError("receipt_reports_missing")
    return tuple(reports)


def build_final_receipt(
    *,
    repo_root: str | Path,
    core_transport_bundle_root: str | Path,
    service_transport_bundle_root: str | Path,
    decision_path: str | Path,
) -> dict[str, object]:
    root, head, tree = _git_identity(repo_root)
    try:
        contract = load_contract(root)
        decision = validate_shadow_decision(
            _decision_payload(decision_path), contract=contract
        )
        core_transport = load_verified_transport(core_transport_bundle_root)
        service_transport = load_verified_transport(service_transport_bundle_root)
    except (ContractError, ShadowDecisionError, TransportReplayError) as exc:
        raise Increment5E2CloseoutReceiptError("validated_input") from exc
    if decision.result != "PASS" or {lane.lane_id for lane in decision.lanes} != {
        "core",
        "service",
    }:
        raise Increment5E2CloseoutReceiptError("decision_not_exact_pass")
    if (
        decision.context.evaluated_sha != head
        or decision.context.evaluated_tree_sha != tree
    ):
        raise Increment5E2CloseoutReceiptError("checkout_identity")
    lane_map = {lane.lane_id: lane for lane in decision.lanes}
    transports = {"core": core_transport, "service": service_transport}
    selected_all: list[dict[str, object]] = []
    report_values: dict[str, list[dict[str, object]]] = {}
    identities: dict[str, object] | None = None
    lane_values: list[dict[str, object]] = []
    manifest_digests: set[str] = set()
    for lane_id, inventory_lane in (
        ("core", FinalCloseoutLane.DETERMINISTIC),
        ("service", FinalCloseoutLane.ACTUAL_NEO4J),
    ):
        lane = lane_map[lane_id]
        verified = transports[lane_id]
        if (
            lane.receipt.evaluated_sha != head
            or lane.receipt.evaluated_tree_sha != tree
            or verified.replay.head_sha != head
        ):
            raise Increment5E2CloseoutReceiptError("lane_checkout_identity")
        reports = _lane_reports(verified, lane)
        selected, properties = _selected_cases(reports, inventory_lane)
        selected_all.extend(selected)
        if inventory_lane is FinalCloseoutLane.ACTUAL_NEO4J:
            identities = _semantic_identities(properties, head, tree)
        report_values[lane_id] = [
            {
                "path": raw.path,
                "size_bytes": raw.size_bytes,
                "digest": raw.digest,
            }
            for raw in lane.receipt.raw_reports
        ]
        manifest_digests.add(lane.receipt.route.selected_test_manifest_digest)
        lane_values.append(
            {
                "lane_id": lane_id,
                "lane_identity": lane.lane_identity,
                "receipt_identity": lane.receipt.receipt_identity,
                "envelope_identity": lane.receipt.envelope_identity,
                "transport_identity": verified.bundle.transport_identity,
                "replay_identity": verified.replay.replay_identity,
            }
        )
    if identities is None or len(manifest_digests) != 1:
        raise Increment5E2CloseoutReceiptError("selected_test_manifest")
    _require_git_identity(root, head, tree)
    return _with_identity(
        {
            "schema_version": FINAL_SCHEMA_VERSION,
            "decision_identity": decision.decision_identity,
            "evaluated_sha": head,
            "evaluated_tree_sha": tree,
            "selected_test_manifest_digest": manifest_digests.pop(),
            "lanes": lane_values,
            "junit_reports": report_values,
            "selected_cases": sorted(
                selected_all, key=lambda item: str(item["case_id"])
            ),
            "inventory": _inventory(),
            **identities,
        }
    )


def _write_output(path: str | Path, receipt: Mapping[str, object]) -> None:
    output = Path(path)
    absolute = output if output.is_absolute() else output.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        if current.is_symlink():
            raise Increment5E2CloseoutReceiptError("output_path")
    if (
        not absolute.parent.is_dir()
        or absolute.suffix != ".json"
        or absolute.is_symlink()
    ):
        raise Increment5E2CloseoutReceiptError("output_path")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(absolute, flags, 0o600)
    except FileExistsError as exc:
        raise Increment5E2CloseoutReceiptError("output_exists") from exc
    except OSError as exc:
        raise Increment5E2CloseoutReceiptError("output_open") from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json_bytes(dict(receipt)) + b"\n")


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in {"actual-service", "final"}:
        raw = ["--mode", raw[0], *raw[1:]]
    parser = argparse.ArgumentParser(
        description="Emit exact Increment 5E2 closeout receipts"
    )
    parser.add_argument("--mode", required=True, choices=("actual-service", "final"))
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--service-junit-report", "--report")
    parser.add_argument("--core-transport-bundle-root", "--core-transport-root")
    parser.add_argument("--service-transport-bundle-root", "--service-transport-root")
    parser.add_argument("--decision", "--validated-decision")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(raw)
    try:
        if arguments.mode == "actual-service":
            if not arguments.service_junit_report:
                raise Increment5E2CloseoutReceiptError("service_junit_report")
            receipt = build_actual_service_receipt(
                repo_root=arguments.repo_root,
                service_junit_report=arguments.service_junit_report,
            )
        else:
            if not all(
                (
                    arguments.core_transport_bundle_root,
                    arguments.service_transport_bundle_root,
                    arguments.decision,
                )
            ):
                raise Increment5E2CloseoutReceiptError("final_inputs")
            receipt = build_final_receipt(
                repo_root=arguments.repo_root,
                core_transport_bundle_root=arguments.core_transport_bundle_root,
                service_transport_bundle_root=arguments.service_transport_bundle_root,
                decision_path=arguments.decision,
            )
        _write_output(arguments.output, receipt)
    except Increment5E2CloseoutReceiptError as exc:
        print(f"EVIDENCE_MISMATCH:increment5e2-closeout:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
