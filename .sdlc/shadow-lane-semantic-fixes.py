from pathlib import Path

source = Path("scripts/sdlc/shadow_lane.py")
text = source.read_text(encoding="utf-8")
replacements = (
    (
        'CLASSIFIER_VERSION = "sdlc-risk-v1"\n'
        '_SAFE_ID = re.compile',
        'CLASSIFIER_VERSION = "sdlc-risk-v1"\n'
        '_SERVICE_RISKS = frozenset({"R3_EXTERNAL_SERVICE_SECURITY", "R4_RELEASE_OPERATIONAL"})\n'
        '_OWNER_RISKS = frozenset({"R4_RELEASE_OPERATIONAL"})\n'
        '_LANE_GATE_IDS = {\n'
        '    "core": frozenset({"source-integrity", "core-deterministic"}),\n'
        '    "service": frozenset({"service-neo4j"}),\n'
        '}\n'
        '_SAFE_ID = re.compile',
    ),
    (
        '    if (\n'
        '        receipt.route.contract_version != CONTRACT_VERSION\n'
        '        or receipt.route.risk_classifier_version != CLASSIFIER_VERSION\n'
        '    ):\n'
        '        raise ShadowLaneError("route_contract")\n'
        '    if not receipt.gate_decisions:\n'
        '        raise ShadowLaneError("gate_decisions")\n',
        '    route = receipt.route\n'
        '    if (\n'
        '        route.contract_version != CONTRACT_VERSION\n'
        '        or route.risk_classifier_version != CLASSIFIER_VERSION\n'
        '        or route.service_required is not (route.risk_tier in _SERVICE_RISKS)\n'
        '        or route.owner_authority_required is not (route.risk_tier in _OWNER_RISKS)\n'
        '    ):\n'
        '        raise ShadowLaneError("route_contract")\n'
        '    gate_ids = frozenset(decision.gate_id for decision in receipt.gate_decisions)\n'
        '    if gate_ids != _LANE_GATE_IDS[policy.lane_id]:\n'
        '        raise ShadowLaneError("lane_gates")\n',
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
        '@dataclass(frozen=True)\n'
        'class _Route:\n'
        '    contract_version: str = "sdlc-v2.2"\n'
        '    risk_classifier_version: str = "sdlc-risk-v1"\n\n\n'
        '@dataclass(frozen=True)\n'
        'class _Receipt:\n',
        '@dataclass(frozen=True)\n'
        'class _Route:\n'
        '    contract_version: str = "sdlc-v2.2"\n'
        '    risk_classifier_version: str = "sdlc-risk-v1"\n'
        '    risk_tier: str = "R1_LOCAL_CODE"\n'
        '    service_required: bool = False\n'
        '    owner_authority_required: bool = False\n\n\n'
        '@dataclass(frozen=True)\n'
        'class _GateDecision:\n'
        '    gate_id: str\n\n\n'
        '@dataclass(frozen=True)\n'
        'class _Receipt:\n',
    ),
    (
        '    gate_decisions: tuple[object, ...] = (object(),)\n',
        '    gate_decisions: tuple[_GateDecision, ...] = (\n'
        '        _GateDecision("source-integrity"),\n'
        '        _GateDecision("core-deterministic"),\n'
        '    )\n',
    ),
    (
        '    receipt = _Receipt(\n'
        '        _Metadata(name=ARTIFACT_NAME.replace("-core-", "-service-")),\n'
        '        producer_job_id="service",\n'
        '    )\n',
        '    receipt = _Receipt(\n'
        '        _Metadata(name=ARTIFACT_NAME.replace("-core-", "-service-")),\n'
        '        route=_Route(\n'
        '            risk_tier="R3_EXTERNAL_SERVICE_SECURITY",\n'
        '            service_required=True,\n'
        '        ),\n'
        '        producer_job_id="service",\n'
        '        gate_decisions=(_GateDecision("service-neo4j"),),\n'
        '    )\n',
    ),
    (
        '\ndef test_record_rejects_shape_policy_and_identity_tampering(\n',
        '\n\ndef test_route_and_lane_gate_semantics_fail_closed(\n'
        '    monkeypatch: pytest.MonkeyPatch,\n'
        ') -> None:\n'
        '    invalid_route = _Receipt(\n'
        '        _Metadata(),\n'
        '        route=_Route(\n'
        '            risk_tier="R1_LOCAL_CODE",\n'
        '            service_required=True,\n'
        '        ),\n'
        '    )\n'
        '    _patch_receipt_validator(monkeypatch, invalid_route)\n'
        '    replay = _replay()\n'
        '    with pytest.raises(ShadowLaneError, match="route_contract"):\n'
        '        ShadowLaneRecord(\n'
        '            lane_id="core",\n'
        '            run_event="pull_request",\n'
        '            run_created_at="2026-07-22T12:00:00.000Z",\n'
        '            replay=replay,\n'
        '            receipt=invalid_route,  # type: ignore[arg-type]\n'
        '            telemetry=_telemetry(),\n'
        '            lane_identity="sha256:" + "0" * 64,\n'
        '        )\n\n'
        '    invalid_gates = _Receipt(\n'
        '        _Metadata(),\n'
        '        gate_decisions=(_GateDecision("core-deterministic"),),\n'
        '    )\n'
        '    _patch_receipt_validator(monkeypatch, invalid_gates)\n'
        '    with pytest.raises(ShadowLaneError, match="lane_gates"):\n'
        '        ShadowLaneRecord(\n'
        '            lane_id="core",\n'
        '            run_event="pull_request",\n'
        '            run_created_at="2026-07-22T12:00:00.000Z",\n'
        '            replay=replay,\n'
        '            receipt=invalid_gates,  # type: ignore[arg-type]\n'
        '            telemetry=_telemetry(),\n'
        '            lane_identity="sha256:" + "0" * 64,\n'
        '        )\n\n\n'
        'def test_record_rejects_shape_policy_and_identity_tampering(\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"test replacement mismatch: {old[:120]!r}")
    text = text.replace(old, new)
tests.write_text(text, encoding="utf-8")
