from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.writer import CliChainWriter
from newsroom.tests.test_control_plane_private_beta import _proving
from scripts.issue_732_known_ready_calibration import (
    _DryAdmissionWriter,
    known_ready_builder,
    main,
)


def test_known_ready_dry_admission_seeds_three_write_ready_without_dispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--root", str(tmp_path / "calibration")])
    captured = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["stage"] == "KNOWN_READY_DRY_ADMISSION"
    assert captured["dry"]["write_ready"] == 3
    assert captured["dry"]["provider_dispatches"] == 0
    assert captured["dry"]["accepted_payload_count"] == 0
    assert captured["public_effects"] == 0
    assert len(captured["candidate_ids"]) == 3


def test_known_ready_packages_cover_three_evidence_size_bands(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    recorded: list = []

    def capture(candidate: StoryCandidateRecord):
        package = known_ready_builder(candidate)
        recorded.append((candidate, package))
        return package

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=_DryAdmissionWriter(),
        evidence_package_builder=capture,
        max_writer_provider_dispatches=0,
        max_writer_fallback_dispatches=0,
        max_graphiti=0,
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )
    assert report.write_ready == 3
    assert report.provider_dispatches == 0
    writer = CliChainWriter(
        primary=lambda _prompt: "unused", fallback=lambda _prompt: "unused"
    )
    sizes = [
        writer.invocation_manifest(candidate, package, route="PRIMARY").evidence_package_bytes
        for candidate, package in recorded
    ]
    assert len(set(sizes)) >= 3
