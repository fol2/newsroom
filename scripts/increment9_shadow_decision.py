#!/usr/bin/env python3
"""Build or verify the sealed Increment 9D2 blocked shadow decision."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.decision import (
    BlockedShadowDecision,
    DecisionError,
    build_blocked_active_coverage_decision,
)
from scripts.increment9_fault_campaign import (
    FaultCampaignError,
    verify_fault_bundle,
)
from scripts.increment9_shadow_campaign import CampaignError, verify_bundle

DEPENDENCY_SCHEMA = "newsroom.increment9.review-dependency-evidence.v1"
MAX_RECORD_BYTES = 1_048_576
_TIMESTAMP = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)
EXPECTED_DEPENDENCIES = (493, 495, 496)


class DecisionCommandError(ValueError):
    """9D2 command input differs from the sealed authorities."""


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if type(name) is not str or name in value:
            raise DecisionCommandError("dependency JSON names differ")
        value[name] = item
    return value


def _document(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise DecisionCommandError("dependency evidence is absent or unbounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except DecisionCommandError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
    ) as exc:
        raise DecisionCommandError("dependency evidence is not canonical") from exc
    if canonical != raw or type(value) is not dict:
        raise DecisionCommandError("dependency evidence bytes differ")
    return value


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise DecisionCommandError(f"{field} timestamp differs")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise DecisionCommandError(f"{field} timestamp differs") from exc
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise DecisionCommandError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise DecisionCommandError(f"{field} digest differs") from exc


def _git(repo: Path) -> tuple[str, str, str]:
    def run(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    values = (
        run("rev-parse", "HEAD"),
        run("rev-parse", "HEAD^{tree}"),
        run("rev-parse", "HEAD:newsroom/increment9/review.py"),
    )
    if any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in values):
        raise DecisionCommandError("checkout identity differs")
    if run("status", "--porcelain"):
        raise DecisionCommandError("checkout is not clean")
    return values


def _dependencies(raw: bytes, *, head: str, tree: str) -> dict[str, object]:
    value = _document(raw)
    if set(value) != {
        "evidence_digest",
        "exact_main_sha",
        "exact_main_tree",
        "issues",
        "observed_at",
        "schema_version",
    } or value["schema_version"] != DEPENDENCY_SCHEMA:
        raise DecisionCommandError("dependency evidence fields differ")
    _timestamp(value["observed_at"], "observed_at")
    if value["exact_main_sha"] != head or value["exact_main_tree"] != tree:
        raise DecisionCommandError("dependency checkout differs")
    issues = value["issues"]
    if type(issues) is not list or tuple(
        item.get("number") for item in issues
    ) != EXPECTED_DEPENDENCIES:
        raise DecisionCommandError("dependency inventory differs")
    for item in issues:
        if type(item) is not dict or set(item) != {
            "closed_at",
            "evidence_digest",
            "number",
            "state",
        }:
            raise DecisionCommandError("dependency issue fields differ")
        _timestamp(item["closed_at"], "dependency closed_at")
        _digest(item["evidence_digest"], "dependency issue evidence")
        if item["state"] != "CLOSED":
            raise DecisionCommandError("dependency remains open")
    claimed = _digest(value["evidence_digest"], "dependency evidence")
    body = dict(value)
    body.pop("evidence_digest")
    if digest_bytes(canonical_json_bytes(body)) != claimed:
        raise DecisionCommandError("dependency evidence digest differs")
    return value


def build_decision(
    *,
    repo: Path,
    campaign_raw: bytes,
    fault_raw: bytes,
    dependency_raw: bytes,
    decision_id: str,
    decided_at: str,
) -> BlockedShadowDecision:
    head, tree, review_blob = _git(repo)
    _timestamp(decided_at, "decided_at")
    try:
        campaign = verify_bundle(campaign_raw)
        fault = verify_fault_bundle(fault_raw)
    except (CampaignError, FaultCampaignError) as exc:
        raise DecisionCommandError("sealed campaign input is invalid") from exc
    if (
        campaign["outcome"]["outcome"] != "BLOCKED"
        or campaign["outcome"]["decision_bearing"] is not False
        or campaign["outcome"]["run_attempt_inventory"]
        or fault["outcome"]["campaign_outcome"] != "BLOCKED"
        or fault["outcome"]["executed_phase_count"] != 0
        or fault["outcome"]["not_run_phase_count"] != 26
    ):
        raise DecisionCommandError("inputs do not establish an empty sealed universe")
    dependencies = _dependencies(dependency_raw, head=head, tree=tree)
    findings = tuple(campaign["launch_receipt"]["finding_ids"])
    if not findings:
        raise DecisionCommandError("blocked source findings are absent")
    return build_blocked_active_coverage_decision(
        decision_id=decision_id,
        decided_at=decided_at,
        exact_main_sha=head,
        exact_main_tree=tree,
        campaign_bundle_digest=campaign["bundle_digest"],
        fault_bundle_digest=fault["bundle_digest"],
        dependency_evidence_digest=dependencies["evidence_digest"],
        review_contract_git_blob=review_blob,
        residual_blockers=findings,
    )


def _write(path: Path, raw: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise DecisionCommandError("protected output parent is too permissive")
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


def _self_test() -> None:
    assert EXPECTED_DEPENDENCIES == (493, 495, 496)
    assert BlockedShadowDecision.schema_version.endswith(".v1")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-blocked")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--campaign-bundle", type=Path, required=True)
    build.add_argument("--fault-bundle", type=Path, required=True)
    build.add_argument("--dependency-evidence", type=Path, required=True)
    build.add_argument("--decision-id", required=True)
    build.add_argument("--decided-at", required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--decision", type=Path, required=True)
    subparsers.add_parser("self-test")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            _self_test()
            print("SELF_TEST_PASS")
            return 0
        if args.command == "verify":
            value = BlockedShadowDecision.from_bytes(args.decision.read_bytes())
            print(
                json.dumps(
                    {
                        "decision_digest": value.canonical_digest,
                        "disposition": value.disposition.value,
                        "status": "VERIFIED",
                    },
                    sort_keys=True,
                )
            )
            return 0
        value = build_decision(
            repo=args.repo,
            campaign_raw=args.campaign_bundle.read_bytes(),
            fault_raw=args.fault_bundle.read_bytes(),
            dependency_raw=args.dependency_evidence.read_bytes(),
            decision_id=args.decision_id,
            decided_at=args.decided_at,
        )
        _write(args.output, value.canonical_bytes)
        print(
            json.dumps(
                {
                    "decision_digest": value.canonical_digest,
                    "disposition": value.disposition.value,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        CampaignError,
        DecisionCommandError,
        DecisionError,
        FaultCampaignError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"increment9_shadow_decision: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
