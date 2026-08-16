#!/usr/bin/env python3
"""Build and independently verify exact-main Increment 9G subjects."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.closeout import (
    EXPECTED_ISSUES,
    EXPECTED_TOPOLOGY,
    CloseoutInputs,
    Increment9CloseoutError,
    build_closeout_receipt,
    build_deployment_receipt,
    build_review_report,
    build_run_inventory,
    exact_json,
    validate_sdlc_decision,
    verify_closeout_receipt,
    verify_deployment_receipt,
    verify_review_report,
    verify_run_inventory,
)
from newsroom.increment9.decision import BlockedShadowDecision
from newsroom.increment9.plan import (
    INCREMENT_9_SHADOW_PLAN_DIGEST,
    SHADOW_PLAN_PATH,
)
from scripts.increment9_fault_campaign import (
    DEPENDENCY_SCHEMA as FAULT_DEPENDENCY_SCHEMA,
    build_stopped_bundle,
    verify_fault_bundle,
)
from scripts.increment9_shadow_campaign import (
    GateRecord,
    GateStatus,
    build_bundle as build_campaign_bundle,
    verify_bundle as verify_campaign_bundle,
)
from scripts.increment9_shadow_decision import (
    DEPENDENCY_SCHEMA as REVIEW_DEPENDENCY_SCHEMA,
    build_decision,
)
from scripts.sdlc.contracts import load_contract

ISSUE_INVENTORY_SCHEMA = "newsroom.increment9.closeout-issue-inventory.v1"
SUBJECT_MANIFEST_SCHEMA = "newsroom.increment9.closeout-subject-manifest.v1"
SUBJECT_FILES = (
    "increment9-campaign-bundle.json",
    "increment9-deployment-receipt.json",
    "increment9-fault-bundle.json",
    "increment9-issue-inventory.json",
    "increment9-review-metric-report.json",
    "increment9-run-inventory.json",
    "increment9-shadow-decision.json",
    "increment9-shadow-plan.json",
    "increment9g-final-closeout.json",
)
_DEPENDENCY_GATE_NAMES = {
    488: "ISSUE_488_OWNER_PLAN",
    489: "ISSUE_489_SHADOW_CONTRACT",
    490: "ISSUE_490_ISOLATED_DEPLOYMENT",
    491: "ISSUE_491_FROZEN_EPOCH",
    492: "ISSUE_492_CONTROLLER_QUALIFICATION",
}
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")


class Increment9CloseoutCommandError(ValueError):
    """Closeout command inputs or retained subjects differ."""


def _git(repo: Path) -> tuple[str, str]:
    def run(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    head, tree = run("rev-parse", "HEAD"), run("rev-parse", "HEAD^{tree}")
    if not _HEX40.fullmatch(head) or not _HEX40.fullmatch(tree):
        raise Increment9CloseoutCommandError("checkout identity differs")
    if run("status", "--porcelain"):
        raise Increment9CloseoutCommandError("checkout is not clean")
    return head, tree


def _write(path: Path, value: Mapping[str, object] | bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise Increment9CloseoutCommandError("subject output parent is too permissive")
    raw = value if type(value) is bytes else canonical_json_bytes(dict(value))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_issue(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment9CloseoutCommandError(f"invalid issue snapshot: {path.name}") from exc
    if type(value) is not dict or set(value) != {
        "closedAt",
        "number",
        "state",
        "title",
        "url",
    }:
        raise Increment9CloseoutCommandError("issue snapshot fields differ")
    return value


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _issue_inventory(issue_directory: Path) -> tuple[dict[str, object], dict[int, dict[str, object]]]:
    issues: dict[int, dict[str, object]] = {}
    entries: list[dict[str, object]] = []
    for number in EXPECTED_ISSUES:
        raw_path = issue_directory / f"issue-{number}.json"
        value = _load_issue(raw_path)
        if value["number"] != number or value["state"] != "CLOSED" or not value["closedAt"]:
            raise Increment9CloseoutCommandError(f"issue #{number} is not closed")
        if value["url"] != f"https://github.com/fol2/newsroom/issues/{number}":
            raise Increment9CloseoutCommandError(f"issue #{number} URL differs")
        issues[number] = value
        entries.append(
            {
                "closed_at": _timestamp(value["closedAt"]),
                "evidence_digest": digest_bytes(canonical_json_bytes(value)),
                "number": number,
                "state": "CLOSED",
                "url": value["url"],
            }
        )
    body = {
        "issues": entries,
        "schema_version": ISSUE_INVENTORY_SCHEMA,
    }
    return {**body, "inventory_digest": digest_bytes(canonical_json_bytes(body))}, issues


def _dependency_evidence(
    *,
    schema: str,
    numbers: tuple[int, ...],
    issues: Mapping[int, Mapping[str, object]],
    head: str,
    tree: str,
    observed_at: str,
) -> bytes:
    entries = [
        {
            "closed_at": _timestamp(str(issues[number]["closedAt"])),
            "evidence_digest": digest_bytes(canonical_json_bytes(dict(issues[number]))),
            "number": number,
            "state": "CLOSED",
        }
        for number in numbers
    ]
    body = {
        "exact_main_sha": head,
        "exact_main_tree": tree,
        "issues": entries,
        "observed_at": observed_at,
        "schema_version": schema,
    }
    return canonical_json_bytes(
        {**body, "evidence_digest": digest_bytes(canonical_json_bytes(body))}
    )


def _campaign_gates(
    *,
    root: Path,
    issues: Mapping[int, Mapping[str, object]],
    head: str,
    tree: str,
    observed_at: str,
) -> Path:
    gates = root / "campaign-gates"
    gates.mkdir(mode=0o700)
    observed = datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    expires = (observed + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for number, gate_id in _DEPENDENCY_GATE_NAMES.items():
        evidence = digest_bytes(canonical_json_bytes(dict(issues[number])))
        subject = INCREMENT_9_SHADOW_PLAN_DIGEST if number == 488 else evidence
        record = GateRecord(
            gate_id=gate_id,
            observed_at=observed_at,
            expires_at=expires,
            exact_main_sha=head,
            exact_main_tree=tree,
            subject_digest=subject,
            evidence_digest=evidence,
            issuer_id="github-fol2-exact-main-closeout",
            status=GateStatus.PASS,
        )
        _write(gates / f"{gate_id}.json", record.primitive())
    return gates


def _topology(repo: Path) -> dict[str, object]:
    contract = load_contract(repo)
    data = contract.data
    strategy = data["test_strategy"]
    core = data["lanes"]["core"]
    gate = data["gate"]["core-deterministic"]
    observed = {
        "core_shards": core["shard_count"],
        "persistent_workers_per_shard": core["workers_per_shard"],
        "required_error_count": 0,
        "required_failure_count": 0,
        "required_skip_count": 0,
        "shard_hard_seconds": gate["hard_timeout_seconds"],
        "shard_warning_seconds": core["per_shard_warning_seconds"],
        "testcase_hard_seconds": strategy["individual_testcase_hard_timeout_seconds"],
        "testcase_warning_seconds": strategy["individual_testcase_warning_seconds"],
    }
    if observed != EXPECTED_TOPOLOGY:
        raise Increment9CloseoutCommandError("topology differs")
    return observed


def build_subjects(
    *,
    repo: Path,
    issue_directory: Path,
    sdlc_decision_path: Path,
    readiness_path: Path,
    restart_path: Path,
    observed_at: str,
    output_directory: Path,
) -> dict[str, object]:
    head, tree = _git(repo)
    output_directory = output_directory.resolve()
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(output_directory.stat().st_mode) & 0o077:
        raise Increment9CloseoutCommandError("output directory is too permissive")
    issue_inventory, issues = _issue_inventory(issue_directory)
    sdlc_raw = sdlc_decision_path.read_bytes()
    sdlc = json.loads(sdlc_raw)
    sdlc_identity = validate_sdlc_decision(sdlc, head=head, tree=tree)
    readiness = exact_json(readiness_path.read_bytes())
    restart = exact_json(restart_path.read_bytes())
    deployment = build_deployment_receipt(readiness=readiness, restart=restart)
    with tempfile.TemporaryDirectory(prefix="increment9g-") as temporary:
        temporary_path = Path(temporary)
        os.chmod(temporary_path, 0o700)
        gates = _campaign_gates(
            root=temporary_path,
            issues=issues,
            head=head,
            tree=tree,
            observed_at=observed_at,
        )
        campaign = build_campaign_bundle(
            repo=repo,
            gate_directory=gates,
            campaign_id="increment9-final-blocked-epoch",
            observed_at=observed_at,
        )
        if len(campaign["launch_receipt"]["finding_ids"]) != 20:
            raise Increment9CloseoutCommandError("final campaign blocker inventory differs")
        fault_dependencies = _dependency_evidence(
            schema=FAULT_DEPENDENCY_SCHEMA,
            numbers=(490, 491, 492, 493, 494),
            issues=issues,
            head=head,
            tree=tree,
            observed_at=observed_at,
        )
        fault = build_stopped_bundle(
            repo=repo,
            campaign_bundle_raw=canonical_json_bytes(campaign),
            dependency_evidence_raw=fault_dependencies,
            observed_at=observed_at,
        )
        review_dependencies = _dependency_evidence(
            schema=REVIEW_DEPENDENCY_SCHEMA,
            numbers=(493, 495, 496),
            issues=issues,
            head=head,
            tree=tree,
            observed_at=observed_at,
        )
        decision = build_decision(
            repo=repo,
            campaign_raw=canonical_json_bytes(campaign),
            fault_raw=canonical_json_bytes(fault),
            dependency_raw=review_dependencies,
            decision_id="increment9-final-blocked-shadow-decision",
            decided_at=observed_at,
        )
    run_inventory = build_run_inventory(campaign=campaign, fault=fault)
    review_report = build_review_report(decision)
    plan_raw = (repo / SHADOW_PLAN_PATH).read_bytes()
    if digest_bytes(plan_raw) != INCREMENT_9_SHADOW_PLAN_DIGEST:
        raise Increment9CloseoutCommandError("owner plan file differs")
    closeout = build_closeout_receipt(
        CloseoutInputs(
            exact_main_sha=head,
            exact_main_tree=tree,
            closed_at=observed_at,
            issue_evidence_digest=issue_inventory["inventory_digest"],
            sdlc_decision_identity=sdlc_identity,
            plan_file_digest=digest_bytes(plan_raw),
            deployment_receipt_digest=deployment["receipt_digest"],
            run_inventory_digest=run_inventory["inventory_digest"],
            review_report_digest=review_report["report_digest"],
            shadow_decision_digest=decision.canonical_digest,
            topology=_topology(repo),
            production_nonmutation=True,
            public_effect_count=0,
            residual_blockers=decision.residual_blockers,
        )
    )
    subjects: dict[str, bytes] = {
        "increment9-campaign-bundle.json": canonical_json_bytes(campaign),
        "increment9-deployment-receipt.json": canonical_json_bytes(deployment),
        "increment9-fault-bundle.json": canonical_json_bytes(fault),
        "increment9-issue-inventory.json": canonical_json_bytes(issue_inventory),
        "increment9-review-metric-report.json": canonical_json_bytes(review_report),
        "increment9-run-inventory.json": canonical_json_bytes(run_inventory),
        "increment9-shadow-decision.json": decision.canonical_bytes,
        "increment9-shadow-plan.json": plan_raw,
        "increment9g-final-closeout.json": canonical_json_bytes(closeout),
    }
    for name, raw in subjects.items():
        _write(output_directory / name, raw)
    manifest_body = {
        "exact_main_sha": head,
        "exact_main_tree": tree,
        "schema_version": SUBJECT_MANIFEST_SCHEMA,
        "subjects": [
            {"file": name, "sha256": digest_bytes(subjects[name])}
            for name in SUBJECT_FILES
        ],
    }
    manifest = {
        **manifest_body,
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest_body)),
    }
    _write(output_directory / "increment9-subject-manifest.json", manifest)
    verify_subjects(
        repo=repo,
        subject_directory=output_directory,
        sdlc_decision_path=sdlc_decision_path,
    )
    return manifest


def verify_subjects(
    *, repo: Path, subject_directory: Path, sdlc_decision_path: Path
) -> dict[str, object]:
    head, tree = _git(repo)
    manifest = exact_json((subject_directory / "increment9-subject-manifest.json").read_bytes())
    if manifest.get("schema_version") != SUBJECT_MANIFEST_SCHEMA or manifest.get("exact_main_sha") != head or manifest.get("exact_main_tree") != tree:
        raise Increment9CloseoutCommandError("subject manifest checkout differs")
    entries = manifest.get("subjects")
    if not isinstance(entries, list) or tuple(item.get("file") for item in entries) != SUBJECT_FILES:
        raise Increment9CloseoutCommandError("subject manifest inventory differs")
    for item in entries:
        raw = (subject_directory / item["file"]).read_bytes()
        if digest_bytes(raw) != item["sha256"]:
            raise Increment9CloseoutCommandError("signed subject file digest differs")
    manifest_body = dict(manifest)
    claimed = manifest_body.pop("manifest_digest")
    if digest_bytes(canonical_json_bytes(manifest_body)) != claimed:
        raise Increment9CloseoutCommandError("subject manifest digest differs")
    plan_raw = (subject_directory / "increment9-shadow-plan.json").read_bytes()
    if plan_raw != (repo / SHADOW_PLAN_PATH).read_bytes() or digest_bytes(plan_raw) != INCREMENT_9_SHADOW_PLAN_DIGEST:
        raise Increment9CloseoutCommandError("signed plan differs")
    campaign = verify_campaign_bundle((subject_directory / "increment9-campaign-bundle.json").read_bytes())
    fault = verify_fault_bundle((subject_directory / "increment9-fault-bundle.json").read_bytes())
    decision = BlockedShadowDecision.from_bytes((subject_directory / "increment9-shadow-decision.json").read_bytes())
    closeout = verify_closeout_receipt((subject_directory / "increment9g-final-closeout.json").read_bytes())
    sdlc = json.loads(sdlc_decision_path.read_bytes())
    sdlc_identity = validate_sdlc_decision(sdlc, head=head, tree=tree)
    run_inventory = verify_run_inventory(
        (subject_directory / "increment9-run-inventory.json").read_bytes()
    )
    review_report = verify_review_report(
        (subject_directory / "increment9-review-metric-report.json").read_bytes()
    )
    deployment = verify_deployment_receipt(
        (subject_directory / "increment9-deployment-receipt.json").read_bytes()
    )
    issue_inventory = exact_json(
        (subject_directory / "increment9-issue-inventory.json").read_bytes()
    )
    issue_body = dict(issue_inventory)
    issue_claimed = issue_body.pop("inventory_digest", None)
    issue_entries = issue_inventory.get("issues")
    if (
        issue_inventory.get("schema_version") != ISSUE_INVENTORY_SCHEMA
        or not isinstance(issue_entries, list)
        or tuple(item.get("number") for item in issue_entries) != EXPECTED_ISSUES
        or digest_bytes(canonical_json_bytes(issue_body)) != issue_claimed
    ):
        raise Increment9CloseoutCommandError("signed issue inventory differs")
    if (
        closeout["sdlc_decision_identity"] != sdlc_identity
        or closeout["shadow_decision_digest"] != decision.canonical_digest
        or closeout["run_inventory_digest"] != run_inventory["inventory_digest"]
        or closeout["review_report_digest"] != review_report["report_digest"]
        or closeout["deployment_receipt_digest"] != deployment["receipt_digest"]
        or closeout["issue_evidence_digest"] != issue_inventory["inventory_digest"]
        or closeout["shadow_disposition"] != decision.disposition.value
        or campaign["outcome"]["outcome"] != "BLOCKED"
        or fault["outcome"]["campaign_outcome"] != "BLOCKED"
    ):
        raise Increment9CloseoutCommandError("closeout subject binding differs")
    return manifest


def _self_test() -> None:
    assert len(SUBJECT_FILES) == 9
    assert EXPECTED_ISSUES == (*range(488, 498), 500, 521)
    assert EXPECTED_TOPOLOGY["core_shards"] == 18


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--issue-directory", type=Path, required=True)
    build.add_argument("--sdlc-decision", type=Path, required=True)
    build.add_argument("--deployment-readiness", type=Path, required=True)
    build.add_argument("--deployment-restart", type=Path, required=True)
    build.add_argument("--observed-at", required=True)
    build.add_argument("--output-directory", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo-root", type=Path, required=True)
    verify.add_argument("--subject-directory", type=Path, required=True)
    verify.add_argument("--sdlc-decision", type=Path, required=True)
    subparsers.add_parser("self-test")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            _self_test()
            print("SELF_TEST_PASS")
            return 0
        if args.command == "verify":
            value = verify_subjects(
                repo=args.repo_root,
                subject_directory=args.subject_directory,
                sdlc_decision_path=args.sdlc_decision,
            )
        else:
            value = build_subjects(
                repo=args.repo_root,
                issue_directory=args.issue_directory,
                sdlc_decision_path=args.sdlc_decision,
                readiness_path=args.deployment_readiness,
                restart_path=args.deployment_restart,
                observed_at=args.observed_at,
                output_directory=args.output_directory,
            )
        print(
            json.dumps(
                {
                    "manifest_digest": value["manifest_digest"],
                    "status": "VERIFIED",
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        Increment9CloseoutCommandError,
        Increment9CloseoutError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as exc:
        print(f"increment9g_closeout_receipt: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
