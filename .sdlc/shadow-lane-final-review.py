from pathlib import Path

source = Path("scripts/sdlc/shadow_lane.py")
text = source.read_text(encoding="utf-8")
replacements = (
    (
        '        finalization_step="Finalize evidence",\n'
        '    ),\n'
        '    "service": LanePolicy(\n',
        '        finalization_step="Finalize evidence",\n'
        '        ready_after_jobs=("route",),\n'
        '    ),\n'
        '    "service": LanePolicy(\n',
    ),
    (
        '        finalization_step="Finalize evidence",\n'
        '    ),\n'
        '}\n',
        '        finalization_step="Finalize evidence",\n'
        '        ready_after_jobs=("route",),\n'
        '    ),\n'
        '}\n',
    ),
    (
        '        except (TransportReplayError, ArtifactReceiptError, WorkflowEvidenceError) as exc:\n'
        '            raise ShadowLaneError("nested_evidence") from exc\n'
        '        _cross_check(\n',
        '        except (TransportReplayError, ArtifactReceiptError, WorkflowEvidenceError) as exc:\n'
        '            raise ShadowLaneError("nested_evidence") from exc\n'
        '        if (\n'
        '            replay != self.replay\n'
        '            or receipt != self.receipt\n'
        '            or telemetry != self.telemetry\n'
        '        ):\n'
        '            raise ShadowLaneError("nested_evidence")\n'
        '        _cross_check(\n',
    ),
    (
        '        or telemetry.job_name != policy.producer_job_id\n'
        '        or receipt.producer_job_id != policy.producer_job_id\n',
        '        or telemetry.job_name != policy.producer_job_id\n'
        '        or telemetry.ready_after_jobs != policy.ready_after_jobs\n'
        '        or receipt.producer_job_id != policy.producer_job_id\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"source replacement mismatch: {old[:120]!r}")
    text = text.replace(old, new)
source.write_text(text, encoding="utf-8")

tests = Path("newsroom/tests/test_sdlc_shadow_lane.py")
text = tests.read_text(encoding="utf-8")
replacements = (
    (
        'def _telemetry(*, job_name: str = "core") -> JobTelemetry:\n'
        '    return JobTelemetry(\n',
        'def _telemetry(\n'
        '    *,\n'
        '    job_name: str = "core",\n'
        '    ready_after_jobs: tuple[str, ...] = ("route",),\n'
        ') -> JobTelemetry:\n'
        '    return JobTelemetry(\n',
    ),
    (
        '        ready_after_jobs=(),\n',
        '        ready_after_jobs=ready_after_jobs,\n',
    ),
    (
        '    assert calls["measure"][1]["job_name"] == "core"  # type: ignore[index]\n'
        '    assert calls["measure"][1]["bootstrap_end_step"] == "Sync locked environment"  # type: ignore[index]\n',
        '    assert calls["measure"][1]["job_name"] == "core"  # type: ignore[index]\n'
        '    assert calls["measure"][1]["ready_after_job_names"] == ("route",)  # type: ignore[index]\n'
        '    assert calls["measure"][1]["bootstrap_end_step"] == "Sync locked environment"  # type: ignore[index]\n',
    ),
    (
        '    assert calls["measure"]["job_name"] == "service"  # type: ignore[index]\n'
        '    assert calls["measure"]["bootstrap_end_step"] == "Wait for authenticated Neo4j"  # type: ignore[index]\n',
        '    assert calls["measure"]["job_name"] == "service"  # type: ignore[index]\n'
        '    assert calls["measure"]["ready_after_job_names"] == ("route",)  # type: ignore[index]\n'
        '    assert calls["measure"]["bootstrap_end_step"] == "Wait for authenticated Neo4j"  # type: ignore[index]\n',
    ),
    (
        '        (\n'
        '            _Receipt(_Metadata()),\n'
        '            _telemetry(job_name="other"),\n'
        '            "producer_identity",\n'
        '        ),\n',
        '        (\n'
        '            _Receipt(_Metadata()),\n'
        '            _telemetry(job_name="other"),\n'
        '            "producer_identity",\n'
        '        ),\n'
        '        (\n'
        '            _Receipt(_Metadata()),\n'
        '            _telemetry(ready_after_jobs=()),\n'
        '            "producer_identity",\n'
        '        ),\n',
    ),
    (
        '\ndef test_dependency_failures_use_stable_lane_categories(\n',
        '\n\ndef test_direct_record_rejects_validator_substitution(\n'
        '    monkeypatch: pytest.MonkeyPatch,\n'
        ') -> None:\n'
        '    receipt = _Receipt(_Metadata())\n'
        '    replay = _replay()\n'
        '    telemetry = _telemetry()\n'
        '    monkeypatch.setattr(\n'
        '        lane_module,\n'
        '        "validate_transport_replay",\n'
        '        lambda value: _replay(artifact_name=ARTIFACT_NAME.replace("core", "other")),\n'
        '    )\n'
        '    _patch_receipt_validator(monkeypatch, receipt)\n'
        '    with pytest.raises(ShadowLaneError, match="nested_evidence"):\n'
        '        ShadowLaneRecord(\n'
        '            lane_id="core",\n'
        '            run_event="pull_request",\n'
        '            run_created_at="2026-07-22T12:00:00.000Z",\n'
        '            replay=replay,\n'
        '            receipt=receipt,  # type: ignore[arg-type]\n'
        '            telemetry=telemetry,\n'
        '            lane_identity=_identity("core", replay, receipt, telemetry),\n'
        '        )\n\n\n'
        'def test_dependency_failures_use_stable_lane_categories(\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"test replacement mismatch: {old[:120]!r}")
    text = text.replace(old, new)
tests.write_text(text, encoding="utf-8")
