from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/shadow_decision.py")
TEST = Path("newsroom/tests/test_sdlc_shadow_decision.py")


def replace_exact(text: str, old: str, new: str, name: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"replacement mismatch: {name}")
    return text.replace(old, new)


source = SOURCE.read_text(encoding="utf-8")

source = replace_exact(
    source,
    '''    def __post_init__(self) -> None:
        _result(self.result, "result")
        reason = _text(self.result_reason, "result_reason", maximum=512)
        if not reason.startswith(self.result + ":"):
            raise ShadowDecisionError("result_reason")
        try:
            _validate_context(self.context)
        except ArtifactProvenanceError as exc:
            raise ShadowDecisionError("context") from exc
        if self.context.job_id != "decision":
            raise ShadowDecisionError("decision_job")
        _sha(self.decision_identity, "decision_identity")
''',
    '''    def __post_init__(self) -> None:
        _result(self.result, "result")
        reason = _text(self.result_reason, "result_reason", maximum=512)
        if not reason.startswith(self.result + ":"):
            raise ShadowDecisionError("result_reason")
        try:
            _validate_context(self.context)
        except ArtifactProvenanceError as exc:
            raise ShadowDecisionError("context") from exc
        if self.context.job_id != "decision":
            raise ShadowDecisionError("decision_job")
        if not isinstance(self.totals, DecisionTotals):
            raise ShadowDecisionError("totals")
        if self.event is not None and not isinstance(self.event, WorkflowEvent):
            raise ShadowDecisionError("event")
        if not isinstance(self.lanes, tuple) or len(self.lanes) > 2:
            raise ShadowDecisionError("lanes")
        try:
            lane_ids = tuple(lane.lane_id for lane in self.lanes)
        except AttributeError as exc:
            raise ShadowDecisionError("lanes") from exc
        if tuple(sorted(lane_ids)) != lane_ids or len(set(lane_ids)) != len(lane_ids):
            raise ShadowDecisionError("lanes")
        if self.first_failure is not None and not isinstance(
            self.first_failure, FailureSummary
        ):
            raise ShadowDecisionError("first_failure")
        if self.lanes:
            if self.event is None or "core" not in set(lane_ids):
                raise ShadowDecisionError("lane_event")
            if (self.result == "PASS") is not (self.first_failure is None):
                raise ShadowDecisionError("first_failure")
        elif (
            self.event is not None
            or self.result == "PASS"
            or self.first_failure is None
            or self.first_failure.lane_id != "decision"
        ):
            raise ShadowDecisionError("failure_record")
        identity = _sha(self.decision_identity, "decision_identity")
        if identity != sha256_identity(_identity_inputs(self)):
            raise ShadowDecisionError("decision_identity")
''',
    "decision post-init",
)

source = replace_exact(
    source,
    '''        if normalized_service.receipt.route.as_dict() != route.as_dict():
            raise ShadowDecisionError("route_mismatch")
        lanes.append(normalized_service)
''',
    '''        if normalized_service.receipt.route.as_dict() != route.as_dict():
            raise ShadowDecisionError("route_mismatch")
        if normalized_service.run_created_at != normalized_core.run_created_at:
            raise ShadowDecisionError("run_created_at_mismatch")
        lanes.append(normalized_service)
''',
    "workflow creation identity",
)

source = replace_exact(
    source,
    '''    provisional = ShadowDecision(
        result,
        reason,
        context,
        event,
        lanes,
        totals,
        first_failure,
        "sha256:" + "0" * 64,
    )
    return ShadowDecision(
        result,
        reason,
        context,
        event,
        lanes,
        totals,
        first_failure,
        sha256_identity(_identity_inputs(provisional)),
    )
''',
    '''    identity_inputs = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "result": result,
        "result_reason": reason,
        "context": context.as_dict(),
        "event": None if event is None else event.as_dict(),
        "lanes": [lane.as_dict() for lane in lanes],
        "totals": totals.as_dict(),
        "first_failure": (
            None if first_failure is None else first_failure.as_dict()
        ),
    }
    return ShadowDecision(
        result,
        reason,
        context,
        event,
        lanes,
        totals,
        first_failure,
        sha256_identity(identity_inputs),
    )
''',
    "direct identity build",
)

source = replace_exact(
    source,
    '''    try:
        contract = load_contract(root)
        try:
            context = _context_from_mapping(_load_json(root, arguments.context))
        except (ArtifactProvenanceError, ShadowDecisionError) as exc:
            print("EVIDENCE_MISMATCH:shadow-decision:context", file=sys.stderr)
            return 2
        try:
            event = validate_workflow_event(_load_json(root, arguments.event))
''',
    '''    try:
        try:
            context = _context_from_mapping(_load_json(root, arguments.context))
        except (ArtifactProvenanceError, ShadowDecisionError) as exc:
            print("EVIDENCE_MISMATCH:shadow-decision:context", file=sys.stderr)
            return 2
        try:
            contract = load_contract(root)
            event = validate_workflow_event(_load_json(root, arguments.event))
''',
    "always-reporting contract load",
)

SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
marker = "def test_service_lanes_must_share_workflow_creation_time("
if marker in tests:
    raise SystemExit("review tests already present")
tests += '''


def test_service_lanes_must_share_workflow_creation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route("R3_EXTERNAL_SERVICE_SECURITY")
    core = _lane("core", route)
    service = replace(
        _lane("service", route),
        run_created_at="2026-07-22T12:00:01.000Z",
    )
    _patch_lane_validator(monkeypatch, core, service)

    with pytest.raises(ShadowDecisionError, match="run_created_at_mismatch"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=core,  # type: ignore[arg-type]
            service=service,  # type: ignore[arg-type]
            contract=_contract(),
        )


def test_direct_record_construction_rechecks_shape_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    core = _lane("core", route)
    _patch_lane_validator(monkeypatch, core)
    decision = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=core,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )

    with pytest.raises(ShadowDecisionError, match="decision_identity"):
        replace(decision, decision_identity="sha256:" + "0" * 64)
    with pytest.raises(ShadowDecisionError, match="failure_record"):
        replace(decision, event=None, lanes=())
    with pytest.raises(ShadowDecisionError, match="lanes"):
        replace(decision, lanes=(object(),))  # type: ignore[arg-type]


def test_cli_contract_failure_after_context_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = tmp_path / "context.json"
    context.write_text(json.dumps(_context().as_dict()), encoding="utf-8")

    def reject_contract(_root):
        raise decision_module.ContractError("contract")

    monkeypatch.setattr(decision_module, "load_contract", reject_contract)
    output = tmp_path / "decision.json"
    assert decision_main(
        (
            "--repo-root",
            str(tmp_path),
            "--context",
            str(context),
            "--event",
            "missing-event.json",
            "--core",
            "missing-core.json",
            "--output",
            "decision.json",
        )
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["result"] == "EVIDENCE_MISMATCH"
    assert payload["result_reason"] == "EVIDENCE_MISMATCH:decision:invalid-input"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
'''
TEST.write_text(tests, encoding="utf-8")
