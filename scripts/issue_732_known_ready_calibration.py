#!/usr/bin/env python3
"""EVALUATION known-ready CONT calibration for #732.

Seeds three distinct-size #727 WRITE_READY Evidence Packages in isolated
stores. Does not read or write the live proving/unpublished pair, the stalled
LaunchAgent, or any public-effect path.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.cont_calibration import (
    assess_cont_calibration,
    stage_cont_calibration_policy,
)
from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.evidence import package_for
from newsroom.control_plane.model_usage import ModelUsageService
from newsroom.control_plane.store import list_payloads
from newsroom.control_plane.writer import (
    CliChainWriter,
    WriterCopy,
    cont_writer_implementation_identity,
    read_grok_command_semantic_version,
)


class _DryAdmissionWriter:
    writer_id = "issue-732-dry-admission-writer"

    def write(self, candidate, package) -> WriterCopy:
        del candidate, package
        raise AssertionError("dry admission must not reach the writer")
from newsroom.tests.test_control_plane_private_beta import _proving
from newsroom.tests.test_zero_quota_write_loop import _admit_package

_PASSAGE_PADDING = {
    "HK-01": 0,
    "UK-01": 40,
    "UK-02": 120,
}
_FIXTURE_CLOCK = lambda: datetime(2026, 8, 20, tzinfo=UTC)


def known_ready_builder(candidate):
    package = _admit_package(candidate, package_for(candidate))
    repeats = _PASSAGE_PADDING.get(candidate.items[0].source_id, 0)
    if repeats:
        padding = "Retained observation padding. " * repeats
        package = replace(package, passages=(*package.passages, padding))
    return package


def _write_ready_ids(unpublished: Path) -> tuple[str, ...]:
    connection = sqlite3.connect(unpublished)
    rows = connection.execute(
        "SELECT candidate_id FROM unpublished_write_admission_decisions "
        "WHERE decision='WRITE_READY' ORDER BY at, candidate_id"
    ).fetchall()
    connection.close()
    return tuple(row[0] for row in rows)


def _private_report(report) -> dict[str, object]:
    return {
        "cycle_id": report.cycle_id,
        "write_ready": report.write_ready,
        "admission_hold": report.admission_hold,
        "admission_reject": report.admission_reject,
        "selected_write_ready": report.selected_write_ready,
        "candidate_attempts": report.candidate_attempts,
        "provider_dispatches": report.provider_dispatches,
        "primary_dispatches": report.primary_dispatches,
        "fallback_dispatches": report.fallback_dispatches,
        "draft_accepted": report.draft_accepted,
        "draft_hold": report.draft_hold,
        "draft_reject": report.draft_reject,
        "accepted_payload_count": report.accepted_payload_count,
        "public_effects": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed and optionally dispatch #732 known-ready CONT calibration"
    )
    parser.add_argument(
        "--root",
        default="/tmp/newsroom-732-calibration",
        help="isolated EVALUATION store directory",
    )
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="run at most five hermetic Grok primaries after dry admission",
    )
    parser.add_argument("--max-writes", type=int, default=5)
    args = parser.parse_args(argv)
    if not 1 <= args.max_writes <= 5:
        parser.error("--max-writes must be between 1 and 5 inclusive")

    root = Path(args.root)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)
    proving = _proving(root)
    unpublished = root / "unpublished_store.sqlite3"
    dry = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=_DryAdmissionWriter(),
        evidence_package_builder=known_ready_builder,
        max_writes=args.max_writes,
        max_graphiti=0,
        max_writer_provider_dispatches=0,
        max_writer_fallback_dispatches=0,
        cycle_id=str(uuid.uuid4()),
        clock=_FIXTURE_CLOCK,
    )
    candidate_ids = _write_ready_ids(unpublished)
    body: dict[str, object] = {
        "stage": "KNOWN_READY_DRY_ADMISSION",
        "proving": str(proving),
        "unpublished": str(unpublished),
        "candidate_ids": list(candidate_ids),
        "dry": _private_report(dry),
        "public_effects": 0,
    }
    if len(candidate_ids) != 3 or dry.write_ready != 3 or dry.provider_dispatches != 0:
        sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        return 2
    if not args.dispatch:
        sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        return 0

    revision, worktree_clean = cont_writer_implementation_identity()
    if not worktree_clean:
        body["error"] = "writer-calibration requires a clean versioned exact-head worktree"
        sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        return 2
    grok_version = read_grok_command_semantic_version()
    usage = ModelUsageService(str(unpublished))
    exact_version = f"issue-732-v1+{revision[:12]}"
    usage.register_policy(
        stage_cont_calibration_policy(
            candidate_ids=candidate_ids,
            version=exact_version,
            implementation_revision=revision,
            max_prompt_bytes=131_072,
            command_semantic_version=grok_version,
        )
    )
    started = datetime(2026, 8, 19, tzinfo=UTC)
    live = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=CliChainWriter(),
        evidence_package_builder=known_ready_builder,
        max_writes=args.max_writes,
        max_graphiti=0,
        max_writer_provider_dispatches=5,
        max_writer_fallback_dispatches=0,
        cycle_id=str(uuid.uuid4()),
        model_usage=usage,
        clock=_FIXTURE_CLOCK,
    )
    ended = datetime(2026, 8, 21, tzinfo=UTC)
    payloads = [
        payload
        for payload in list_payloads(str(unpublished), limit=10_000)
        if payload.story_candidate_id in candidate_ids
    ]
    public_effect_count = sum(
        1
        for payload in payloads
        if payload.publication_bundle
        or payload.auto_publish
        or payload.status != "UNPUBLISHED"
    )
    packet = assess_cont_calibration(
        usage.query(start=started, end=ended)["leaves"],
        candidate_ids=candidate_ids,
        version=exact_version,
        implementation_revision=revision,
        public_effect_count=public_effect_count,
        unpublished_payload_candidate_ids=tuple(
            payload.story_candidate_id for payload in payloads
        ),
    )
    body.update(
        {
            "stage": "KNOWN_READY_LIVE_CALIBRATION",
            "implementation_revision": revision,
            "command_semantic_version": grok_version,
            "live": _private_report(live),
            "packet": packet.as_record(),
            "public_effects": public_effect_count,
        }
    )
    sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    return 0 if packet.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
