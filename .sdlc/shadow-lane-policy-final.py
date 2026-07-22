from pathlib import Path

source = Path("scripts/sdlc/shadow_lane.py")
text = source.read_text(encoding="utf-8")
replacements = (
    (
        '_LANE_GATE_IDS = {\n'
        '    "core": frozenset({"source-integrity", "core-deterministic"}),\n'
        '    "service": frozenset({"service-neo4j"}),\n'
        '}\n',
        '',
    ),
    (
        'class LanePolicy:\n'
        '    lane_id: str\n'
        '    producer_job_id: str\n'
        '    bootstrap_end_step: str\n'
        '    finalization_step: str\n'
        '    ready_after_jobs: tuple[str, ...] = ()\n',
        'class LanePolicy:\n'
        '    lane_id: str\n'
        '    producer_job_id: str\n'
        '    consumer_job_id: str\n'
        '    gate_keys: frozenset[tuple[str, str]]\n'
        '    bootstrap_end_step: str\n'
        '    finalization_step: str\n'
        '    ready_after_jobs: tuple[str, ...] = ()\n',
    ),
    (
        '        producer_job_id="core",\n'
        '        bootstrap_end_step="Sync locked environment",\n',
        '        producer_job_id="core",\n'
        '        consumer_job_id="decision",\n'
        '        gate_keys=frozenset(\n'
        '            {("source-integrity", "source"), ("core-deterministic", "tests")}\n'
        '        ),\n'
        '        bootstrap_end_step="Sync locked environment",\n',
    ),
    (
        '        producer_job_id="service",\n'
        '        bootstrap_end_step="Wait for authenticated Neo4j",\n',
        '        producer_job_id="service",\n'
        '        consumer_job_id="decision",\n'
        '        gate_keys=frozenset({("service-neo4j", "tests")}),\n'
        '        bootstrap_end_step="Wait for authenticated Neo4j",\n',
    ),
    (
        '        or telemetry.ready_after_jobs != policy.ready_after_jobs\n'
        '        or receipt.producer_job_id != policy.producer_job_id\n',
        '        or telemetry.ready_after_jobs != policy.ready_after_jobs\n'
        '        or receipt.producer_job_id != policy.producer_job_id\n'
        '        or receipt.consumer_job_id != policy.consumer_job_id\n',
    ),
    (
        '    gate_ids = frozenset(decision.gate_id for decision in receipt.gate_decisions)\n'
        '    if gate_ids != _LANE_GATE_IDS[policy.lane_id]:\n'
        '        raise ShadowLaneError("lane_gates")\n',
        '    gate_keys = frozenset(\n'
        '        (decision.gate_id, decision.phase)\n'
        '        for decision in receipt.gate_decisions\n'
        '    )\n'
        '    if gate_keys != policy.gate_keys:\n'
        '        raise ShadowLaneError("lane_gates")\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"source replacement mismatch: {old[:140]!r}")
    text = text.replace(old, new)
source.write_text(text, encoding="utf-8")

tests = Path("newsroom/tests/test_sdlc_shadow_lane.py")
text = tests.read_text(encoding="utf-8")
replacements = (
    (
        'class _GateDecision:\n'
        '    gate_id: str\n',
        'class _GateDecision:\n'
        '    gate_id: str\n'
        '    phase: str\n',
    ),
    (
        '    producer_job_id: str = "core"\n'
        '    event_name: str = "pull_request"\n'
        '    gate_decisions: tuple[_GateDecision, ...] = (\n'
        '        _GateDecision("source-integrity"),\n'
        '        _GateDecision("core-deterministic"),\n',
        '    producer_job_id: str = "core"\n'
        '    consumer_job_id: str = "decision"\n'
        '    event_name: str = "pull_request"\n'
        '    gate_decisions: tuple[_GateDecision, ...] = (\n'
        '        _GateDecision("source-integrity", "source"),\n'
        '        _GateDecision("core-deterministic", "tests"),\n',
    ),
    (
        '        gate_decisions=(_GateDecision("service-neo4j"),),\n',
        '        gate_decisions=(_GateDecision("service-neo4j", "tests"),),\n',
    ),
    (
        '            _Receipt(_Metadata(), event_name="push"),\n'
        '            _telemetry(),\n'
        '            "run_event",\n'
        '        ),\n',
        '            _Receipt(_Metadata(), event_name="push"),\n'
        '            _telemetry(),\n'
        '            "run_event",\n'
        '        ),\n'
        '        (\n'
        '            _Receipt(_Metadata(), consumer_job_id="other"),\n'
        '            _telemetry(),\n'
        '            "producer_identity",\n'
        '        ),\n',
    ),
    (
        '        gate_decisions=(_GateDecision("service-neo4j"),),\n',
        '        gate_decisions=(_GateDecision("service-neo4j", "tests"),),\n',
    ),
    (
        '        gate_decisions=(_GateDecision("core-deterministic"),),\n',
        '        gate_decisions=(\n'
        '            _GateDecision("source-integrity", "source"),\n'
        '            _GateDecision("core-deterministic", "extra"),\n'
        '        ),\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"test replacement mismatch: {old[:140]!r}")
    text = text.replace(old, new)
tests.write_text(text, encoding="utf-8")
