from pathlib import Path

source = Path("scripts/sdlc/shadow_lane.py")
text = source.read_text(encoding="utf-8")
old = (
    '    gate_ids = frozenset(decision.gate_id for decision in receipt.gate_decisions)\n'
    '    if gate_ids != _LANE_GATE_IDS[policy.lane_id]:\n'
    '        raise ShadowLaneError("lane_gates")\n'
)
new = (
    '    if policy.lane_id == "service" and not route.service_required:\n'
    '        raise ShadowLaneError("lane_route")\n'
    '    gate_ids = frozenset(decision.gate_id for decision in receipt.gate_decisions)\n'
    '    if gate_ids != _LANE_GATE_IDS[policy.lane_id]:\n'
    '        raise ShadowLaneError("lane_gates")\n'
)
if text.count(old) != 1:
    raise SystemExit("source replacement mismatch")
source.write_text(text.replace(old, new), encoding="utf-8")

tests = Path("newsroom/tests/test_sdlc_shadow_lane.py")
text = tests.read_text(encoding="utf-8")
marker = (
    '    invalid_gates = _Receipt(\n'
    '        _Metadata(),\n'
    '        gate_decisions=(_GateDecision("core-deterministic"),),\n'
    '    )\n'
)
insert = (
    '    unexpected_service = _Receipt(\n'
    '        _Metadata(name=ARTIFACT_NAME.replace("-core-", "-service-")),\n'
    '        producer_job_id="service",\n'
    '        gate_decisions=(_GateDecision("service-neo4j"),),\n'
    '    )\n'
    '    _patch_receipt_validator(monkeypatch, unexpected_service)\n'
    '    service_replay = _replay(artifact_name=unexpected_service.metadata.name)\n'
    '    with pytest.raises(ShadowLaneError, match="lane_route"):\n'
    '        ShadowLaneRecord(\n'
    '            lane_id="service",\n'
    '            run_event="pull_request",\n'
    '            run_created_at="2026-07-22T12:00:00.000Z",\n'
    '            replay=service_replay,\n'
    '            receipt=unexpected_service,  # type: ignore[arg-type]\n'
    '            telemetry=_telemetry(job_name="service"),\n'
    '            lane_identity="sha256:" + "0" * 64,\n'
    '        )\n\n'
    + marker
)
if text.count(marker) != 1:
    raise SystemExit("test insertion mismatch")
tests.write_text(text.replace(marker, insert), encoding="utf-8")
