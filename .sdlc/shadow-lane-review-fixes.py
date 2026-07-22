from pathlib import Path

source = Path("scripts/sdlc/shadow_lane.py")
text = source.read_text(encoding="utf-8")
replacements = (
    (
        'SCHEMA_VERSION = "newsroom.sdlc.shadow-lane.v1"\n'
        'POLICY_VERSION = "sdlc-shadow-lane-v1"\n',
        'SCHEMA_VERSION = "newsroom.sdlc.shadow-lane.v1"\n'
        'POLICY_VERSION = "sdlc-shadow-lane-v1"\n'
        'CONTRACT_VERSION = "sdlc-v2.2"\n'
        'CLASSIFIER_VERSION = "sdlc-risk-v1"\n',
    ),
    (
        'def _identity_inputs(record: ShadowLaneRecord) -> dict[str, object]:\n'
        '    return {\n'
        '        "schema_version": SCHEMA_VERSION,\n'
        '        "policy_version": POLICY_VERSION,\n'
        '        "lane_id": record.lane_id,\n'
        '        "run_event": record.run_event,\n'
        '        "run_created_at": record.run_created_at,\n'
        '        "replay_identity": record.replay.replay_identity,\n'
        '        "receipt_identity": record.receipt.receipt_identity,\n'
        '        "telemetry_identity": record.telemetry.as_dict()["telemetry_identity"],\n'
        '    }\n',
        'def _identity_values(\n'
        '    *,\n'
        '    lane_id: str,\n'
        '    run_event: str,\n'
        '    run_created_at: str,\n'
        '    replay: TransportReplay,\n'
        '    receipt: ArtifactReceipt,\n'
        '    telemetry: JobTelemetry,\n'
        ') -> dict[str, object]:\n'
        '    return {\n'
        '        "schema_version": SCHEMA_VERSION,\n'
        '        "policy_version": POLICY_VERSION,\n'
        '        "lane_id": lane_id,\n'
        '        "run_event": run_event,\n'
        '        "run_created_at": run_created_at,\n'
        '        "replay_identity": replay.replay_identity,\n'
        '        "receipt_identity": receipt.receipt_identity,\n'
        '        "telemetry_identity": telemetry.as_dict()["telemetry_identity"],\n'
        '    }\n\n\n'
        'def _identity_inputs(record: ShadowLaneRecord) -> dict[str, object]:\n'
        '    return _identity_values(\n'
        '        lane_id=record.lane_id,\n'
        '        run_event=record.run_event,\n'
        '        run_created_at=record.run_created_at,\n'
        '        replay=record.replay,\n'
        '        receipt=record.receipt,\n'
        '        telemetry=record.telemetry,\n'
        '    )\n',
    ),
    (
        '    if receipt.event_name != run_event:\n'
        '        raise ShadowLaneError("run_event")\n'
        '    if not receipt.gate_decisions:\n'
        '        raise ShadowLaneError("gate_decisions")\n',
        '    if receipt.event_name != run_event:\n'
        '        raise ShadowLaneError("run_event")\n'
        '    if (\n'
        '        receipt.route.contract_version != CONTRACT_VERSION\n'
        '        or receipt.route.risk_classifier_version != CLASSIFIER_VERSION\n'
        '    ):\n'
        '        raise ShadowLaneError("route_contract")\n'
        '    if not receipt.gate_decisions:\n'
        '        raise ShadowLaneError("gate_decisions")\n',
    ),
    (
        '    provisional = ShadowLaneRecord(\n'
        '        lane_id=policy.lane_id,\n'
        '        run_event=run_event,\n'
        '        run_created_at=run_created_at,\n'
        '        replay=transport.replay,\n'
        '        receipt=receipt,\n'
        '        telemetry=telemetry,\n'
        '        lane_identity="sha256:" + "0" * 64,\n'
        '    )\n'
        '    lane_identity = sha256_identity(_identity_inputs(provisional))\n',
        '    lane_identity = sha256_identity(\n'
        '        _identity_values(\n'
        '            lane_id=policy.lane_id,\n'
        '            run_event=run_event,\n'
        '            run_created_at=run_created_at,\n'
        '            replay=transport.replay,\n'
        '            receipt=receipt,\n'
        '            telemetry=telemetry,\n'
        '        )\n'
        '    )\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"source replacement mismatch: {old[:100]!r}")
    text = text.replace(old, new)
source.write_text(text, encoding="utf-8")

tests = Path("newsroom/tests/test_sdlc_shadow_lane.py")
text = tests.read_text(encoding="utf-8")
replacements = (
    (
        '@dataclass(frozen=True)\n'
        'class _Receipt:\n'
        '    metadata: _Metadata\n',
        '@dataclass(frozen=True)\n'
        'class _Route:\n'
        '    contract_version: str = "sdlc-v2.2"\n'
        '    risk_classifier_version: str = "sdlc-risk-v1"\n\n\n'
        '@dataclass(frozen=True)\n'
        'class _Receipt:\n'
        '    metadata: _Metadata\n'
        '    route: _Route = _Route()\n',
    ),
    (
        'def _patch_nested_validators(monkeypatch: pytest.MonkeyPatch) -> None:\n'
        '    monkeypatch.setattr(lane_module, "validate_transport_replay", lambda value: value)\n'
        '    monkeypatch.setattr(lane_module, "validate_receipt", lambda value, contract=None: value)\n'
        '    monkeypatch.setattr(lane_module, "validate_job_telemetry", lambda value: value)\n',
        'def _patch_receipt_validator(\n'
        '    monkeypatch: pytest.MonkeyPatch,\n'
        '    receipt: _Receipt,\n'
        ') -> None:\n'
        '    monkeypatch.setattr(\n'
        '        lane_module,\n'
        '        "validate_receipt",\n'
        '        lambda value, contract=None: receipt,\n'
        '    )\n',
    ),
    (
        '    _patch_nested_validators(monkeypatch)\n'
        '    replay = _replay(artifact_name=(receipt or _Receipt(_Metadata())).metadata.name)\n'
        '    selected_receipt = receipt or _Receipt(_Metadata())\n',
        '    selected_receipt = receipt or _Receipt(_Metadata())\n'
        '    _patch_receipt_validator(monkeypatch, selected_receipt)\n'
        '    replay = _replay(artifact_name=selected_receipt.metadata.name)\n',
    ),
    (
        '    _patch_nested_validators(monkeypatch)\n'
        '    contract = SimpleNamespace(repo_root=tmp_path)\n',
        '    _patch_receipt_validator(monkeypatch, receipt)\n'
        '    contract = SimpleNamespace(repo_root=tmp_path)\n',
    ),
    (
        '    _patch_nested_validators(monkeypatch)\n\n'
        '    record = verify_shadow_lane(\n',
        '    _patch_receipt_validator(monkeypatch, receipt)\n\n'
        '    record = verify_shadow_lane(\n',
    ),
    (
        '    _patch_nested_validators(monkeypatch)\n'
        '    replay = _replay(artifact_name=receipt.metadata.name)\n',
        '    _patch_receipt_validator(monkeypatch, receipt)\n'
        '    replay = _replay(artifact_name=receipt.metadata.name)\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"test replacement mismatch: {old[:100]!r}")
    text = text.replace(old, new)
tests.write_text(text, encoding="utf-8")
