"""Issue #732 exact-main token-productivity closeout proofs."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.model_usage import (
    InvocationTerminal,
    ModelUsageService,
    UsageComponents,
    UsageStatus,
    WorkloadClass,
)
from newsroom.control_plane.store import list_payloads
from newsroom.tests.test_durable_cycle_governor import (
    InjectedClocks,
    _governor,
    _idle,
    _productive,
)
from newsroom.tests.test_model_usage_receipts import (
    T0,
    _digest,
    _envelope,
    _open_and_allocate,
    _policy,
    _reported,
    _service,
)
from newsroom.tests.test_zero_quota_write_loop import (
    _CLOCK,
    _WRITER_REVISION,
    _proving,
    _qualified_builder,
    CountingWriter,
    RecordingFixtureWriter,
)

CLOSEOUT_START = T0
CLOSEOUT_END = T0 + timedelta(minutes=20)
_REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSEOUT_JSON = (
    _REPO_ROOT / "docs/research/2026-08-21-control-plane-token-productivity-closeout.json"
)
AFTER_CSV = (
    _REPO_ROOT / "docs/research/2026-08-21-control-plane-token-consumption-after-300s.csv"
)
CLOSEOUT_MD = (
    _REPO_ROOT / "docs/research/2026-08-21-control-plane-token-productivity-closeout.md"
)
_NEW_BUCKET_COLUMNS = (
    "unreported_invocations",
    "ambiguous_invocations",
    "invalid_invocations",
    "admission_only_hold",
    "admission_only_reject",
    "idle_qualified_zero_cycles",
    "productive_cycles",
    "unproductive_provider_cycles",
    "systemic_provider_failure_cycles",
    "cont_reported_tokens",
    "graphiti_reported_tokens",
    "cycle_ids",
    "cycle_outcome_classes",
    "cooldown_seconds_values",
    "next_cycle_eligible_at_values",
)
_HISTORICAL_BUCKET_COLUMNS = (
    "bucket_start_utc",
    "bucket_end_utc",
    "cycle_results",
    "minted_reported",
    "graphiti_successes_reported",
    "grok_writer_sessions",
    "grok_completed_sessions",
    "grok_model_calls",
    "grok_input_tokens",
    "grok_output_tokens",
    "grok_total_tokens",
    "grok_cached_read_tokens",
    "grok_reasoning_tokens",
    "cursor_fallback_sessions",
    "stored_outputs",
    "stored_grok_outputs",
    "stored_cursor_outputs",
    "stored_other_outputs",
    "reported_tokens",
    "estimated_tokens",
    "unresolved_invocations",
    "productive_tokens",
    "no_result_tokens",
)


@pytest.fixture(autouse=True)
def _exact_writer_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "newsroom.control_plane.writer.cont_writer_implementation_identity",
        lambda: (_WRITER_REVISION, True),
    )


def _cycle_id(suffix: int) -> str:
    return f"00000000-0000-4000-8000-{suffix:012d}"


def _issue_732_closeout_fixture(tmp_path: Path) -> tuple[ModelUsageService, dict[str, str]]:
    """Deterministic unpublished sqlite covering the #732 after-CSV contract."""

    service = _service(tmp_path)
    path = tmp_path / "unpublished.sqlite3"
    identities: dict[str, str] = {}

    accepted_envelope, _accepted_policy, accepted = _open_and_allocate(
        service,
        envelope=_envelope(cycle_id=_cycle_id(101), candidate_id="accepted-cont"),
    )
    no_result_envelope, _no_result_policy, no_result = _open_and_allocate(
        service,
        envelope=_envelope(cycle_id=_cycle_id(102), candidate_id="no-result-cont"),
    )
    graphiti_envelope, _graphiti_policy, graphiti = _open_and_allocate(
        service,
        envelope=_envelope(
            cycle_id=_cycle_id(103),
            workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            candidate_id=None,
            ingest_id="ingest-closeout",
        ),
        policy=_policy(
            workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            provider="cursor-agent-cli",
            route="GRAPHITI_CHAT",
            model="composer-2.5",
        ),
    )
    _unreported_envelope, _unreported_policy, unreported = _open_and_allocate(
        service,
        envelope=_envelope(cycle_id=_cycle_id(104), candidate_id="unreported-cont"),
    )
    _ambiguous_envelope, _ambiguous_policy, ambiguous = _open_and_allocate(
        service,
        envelope=_envelope(cycle_id=_cycle_id(105), candidate_id="ambiguous-cont"),
    )
    _invalid_envelope, _invalid_policy, invalid = _open_and_allocate(
        service,
        envelope=_envelope(cycle_id=_cycle_id(106), candidate_id="invalid-cont"),
    )
    _estimated_envelope, estimated_policy, estimated = _open_and_allocate(
        service,
        envelope=_envelope(cycle_id=_cycle_id(107), candidate_id="estimated-cont"),
    )

    service.link_provider_attempt(
        invocation_id=accepted.invocation_id,
        provider_attempt_id="attempt-accepted-cont",
        linked_at=T0 + timedelta(seconds=1),
    )
    service.complete(
        _reported(
            accepted,
            total=125,
            outcome="ACCEPTED_OUTPUT",
            completed_at=T0 + timedelta(seconds=2),
        )
    )
    service.record_work_outcome(
        envelope_id=accepted_envelope.envelope_id,
        outcome="ACCEPTED",
        outcome_record_id="payload-accepted-cont",
        payload_digest=_digest({"payload": "accepted-cont"}),
        terminal_at=T0 + timedelta(seconds=3),
        accepted_provider_attempt_id="attempt-accepted-cont",
    )
    service.complete(
        _reported(
            no_result,
            total=80,
            outcome="REJECTED_OUTPUT",
            completed_at=T0 + timedelta(seconds=4),
        )
    )
    service.record_work_outcome(
        envelope_id=no_result_envelope.envelope_id,
        outcome="REJECTED",
        outcome_record_id="payload-no-result-cont",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=5),
    )
    service.complete(
        _reported(
            graphiti,
            total=90,
            outcome="COMPLETE",
            completed_at=T0 + timedelta(seconds=6),
        )
    )
    service.record_work_outcome(
        envelope_id=graphiti_envelope.envelope_id,
        outcome="GRAPHITI_SUCCESS_ZERO_PROPOSALS",
        outcome_record_id="graphiti-closeout",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=7),
        retained_proposal_count=0,
    )
    service.complete(
        InvocationTerminal.create(
            invocation_id=unreported.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="MISSING_TELEMETRY",
            usage_status=UsageStatus.UNREPORTED,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=8),
            completed_at=T0 + timedelta(seconds=9),
            observed_at=T0 + timedelta(seconds=9),
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    service.complete(
        InvocationTerminal.create(
            invocation_id=ambiguous.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="AMBIGUOUS_PROCESS",
            usage_status=UsageStatus.AMBIGUOUS,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=10),
            completed_at=T0 + timedelta(seconds=11),
            observed_at=T0 + timedelta(seconds=11),
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    service.complete(
        _reported(
            invalid,
            total=125,
            outcome="ACCEPTED_OUTPUT",
            completed_at=T0 + timedelta(seconds=13),
        ),
        provider_telemetry={"different": "content"},
    )
    service.complete(
        InvocationTerminal.create(
            invocation_id=estimated.invocation_id,
            outcome="REJECTED_OUTPUT",
            failure_class=None,
            usage_status=UsageStatus.ESTIMATED,
            components=UsageComponents(
                total_tokens=2_500, provenance="BOUNDED_ESTIMATE"
            ),
            dispatch_at=T0 + timedelta(seconds=14),
            completed_at=T0 + timedelta(seconds=15),
            observed_at=T0 + timedelta(seconds=15),
            estimate_policy_digest=estimated_policy.canonical_digest,
            estimate_calculation="hard_estimate_ceiling_tokens=2500",
            subscription_cli_chat_not_cash_debited=True,
        )
    )

    service.retain_zero_call_admission(
        decision_id="closeout-hold-1",
        decision="HOLD",
        cycle_id=_cycle_id(108),
        recorded_at=T0 + timedelta(seconds=20),
    )
    service.retain_zero_call_admission(
        decision_id="closeout-hold-2",
        decision="HOLD",
        cycle_id=_cycle_id(108),
        recorded_at=T0 + timedelta(seconds=21),
    )
    service.retain_zero_call_admission(
        decision_id="closeout-reject-1",
        decision="REJECT",
        cycle_id=_cycle_id(108),
        recorded_at=T0 + timedelta(minutes=10, seconds=1),
    )

    clocks = InjectedClocks(T0)
    governor = _governor(path, clocks)
    cycle_uuids = (
        UUID("00000000-0000-4000-8000-000000000201"),
        UUID("00000000-0000-4000-8000-000000000202"),
    )
    with patch(
        "newsroom.control_plane.cycle_governor.uuid.uuid4",
        side_effect=cycle_uuids,
    ):
        productive_lease = governor.claim(owner_id="closeout-productive")
        clocks.advance(10)
        productive = governor.complete(productive_lease, _productive())
        clocks.advance(590)
        idle_lease = governor.claim(owner_id="closeout-idle")
        clocks.advance(1)
        idle = governor.complete(idle_lease, _idle())
    identities["productive_cycle_id"] = productive.cycle_id
    identities["idle_cycle_id"] = idle.cycle_id
    identities["productive_next_cycle_eligible_at"] = productive.next_cycle_eligible_at
    identities["idle_next_cycle_eligible_at"] = idle.next_cycle_eligible_at
    identities["productive_cooldown_seconds"] = str(productive.cooldown_seconds)
    identities["idle_cooldown_seconds"] = str(idle.cooldown_seconds)
    return service, identities


def _issue_732_after_csv(tmp_path: Path) -> str:
    service, _identities = _issue_732_closeout_fixture(tmp_path)
    return service.export_bucket_csv(start=CLOSEOUT_START, end=CLOSEOUT_END)


def test_after_csv_distinguishes_usage_workload_admission_and_cycle_identities(
    tmp_path: Path,
) -> None:
    service, identities = _issue_732_closeout_fixture(tmp_path)
    exported = service.export_bucket_csv(start=CLOSEOUT_START, end=CLOSEOUT_END)
    rows = list(csv.DictReader(io.StringIO(exported)))
    fieldnames = tuple(csv.DictReader(io.StringIO(exported)).fieldnames or ())

    assert fieldnames[: len(_HISTORICAL_BUCKET_COLUMNS)] == _HISTORICAL_BUCKET_COLUMNS
    for column in _NEW_BUCKET_COLUMNS:
        assert column in fieldnames
    assert len(rows) == 4
    assert [row["bucket_start_utc"] for row in rows] == [
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:05:00Z",
        "2026-08-24T10:10:00Z",
        "2026-08-24T10:15:00Z",
    ]

    first = rows[0]
    empty = rows[1]
    idle_bucket = rows[2]
    trailing = rows[3]

    assert first["reported_tokens"] == "295"
    assert first["estimated_tokens"] == "2500"
    assert first["unreported_invocations"] == "1"
    assert first["ambiguous_invocations"] == "1"
    assert first["invalid_invocations"] == "1"
    assert first["unresolved_invocations"] == "3"
    assert first["productive_tokens"] == "215"
    assert first["no_result_tokens"] == "2580"
    assert first["admission_only_hold"] == "2"
    assert first["admission_only_reject"] == "0"
    assert first["idle_qualified_zero_cycles"] == "0"
    assert first["productive_cycles"] == "1"
    assert first["unproductive_provider_cycles"] == "0"
    assert first["systemic_provider_failure_cycles"] == "0"
    assert first["cont_reported_tokens"] == "205"
    assert first["graphiti_reported_tokens"] == "90"
    assert first["cycle_ids"] == json.dumps(
        [identities["productive_cycle_id"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert first["cycle_outcome_classes"] == json.dumps(
        ["PRODUCTIVE"], ensure_ascii=False, separators=(",", ":")
    )
    assert first["cooldown_seconds_values"] == json.dumps(
        [300], ensure_ascii=False, separators=(",", ":")
    )
    assert first["next_cycle_eligible_at_values"] == json.dumps(
        [identities["productive_next_cycle_eligible_at"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert first["minted_reported"] == "1"
    assert first["graphiti_successes_reported"] == "1"

    for column in (
        "reported_tokens",
        "estimated_tokens",
        "unresolved_invocations",
        "unreported_invocations",
        "ambiguous_invocations",
        "invalid_invocations",
        "productive_tokens",
        "no_result_tokens",
        "admission_only_hold",
        "admission_only_reject",
        "idle_qualified_zero_cycles",
        "productive_cycles",
        "unproductive_provider_cycles",
        "systemic_provider_failure_cycles",
        "cont_reported_tokens",
        "graphiti_reported_tokens",
        "minted_reported",
        "graphiti_successes_reported",
        "cycle_results",
    ):
        assert empty[column] == "0"
        assert trailing[column] == "0"
    assert empty["cycle_ids"] == "[]"
    assert empty["cycle_outcome_classes"] == "[]"
    assert empty["cooldown_seconds_values"] == "[]"
    assert empty["next_cycle_eligible_at_values"] == "[]"
    assert trailing["cycle_ids"] == "[]"

    assert idle_bucket["admission_only_hold"] == "0"
    assert idle_bucket["admission_only_reject"] == "1"
    assert idle_bucket["idle_qualified_zero_cycles"] == "1"
    assert idle_bucket["productive_cycles"] == "0"
    assert idle_bucket["reported_tokens"] == "0"
    assert idle_bucket["cycle_ids"] == json.dumps(
        [identities["idle_cycle_id"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert idle_bucket["cycle_outcome_classes"] == json.dumps(
        ["IDLE_QUALIFIED_ZERO"], ensure_ascii=False, separators=(",", ":")
    )
    assert idle_bucket["cooldown_seconds_values"] == json.dumps(
        [300], ensure_ascii=False, separators=(",", ":")
    )
    assert idle_bucket["next_cycle_eligible_at_values"] == json.dumps(
        [identities["idle_next_cycle_eligible_at"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    queried = service.query(start=CLOSEOUT_START, end=CLOSEOUT_END)
    cycles = {str(row["cycle_id"]): row for row in queried["cycle_outcomes"]}
    productive = cycles[identities["productive_cycle_id"]]
    idle = cycles[identities["idle_cycle_id"]]
    assert productive["outcome_class"] == "PRODUCTIVE"
    assert productive["cooldown_seconds"] == 300
    assert productive["next_cycle_eligible_at"] == identities[
        "productive_next_cycle_eligible_at"
    ]
    assert isinstance(productive["cooldown_policy_version"], str)
    assert productive["cooldown_policy_version"]
    assert idle["outcome_class"] == "IDLE_QUALIFIED_ZERO"
    assert idle["cooldown_seconds"] == 300
    assert idle["next_cycle_eligible_at"] == identities["idle_next_cycle_eligible_at"]

    report = service.report(start=CLOSEOUT_START, end=CLOSEOUT_END)
    assert report.get("normal_daily_hard_cut") is None


def test_zero_quota_run_cycle_retains_zero_call_admissions_without_provider_tokens(
    tmp_path: Path,
) -> None:
    unpublished = tmp_path / "unpublished.sqlite3"
    usage = ModelUsageService(str(unpublished))
    writer = CountingWriter()

    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(unpublished),
        writer=writer,
        max_writes=5,
        clock=_CLOCK,
        model_usage=usage,
    )
    usage_report = usage.report(
        start=_CLOCK(),
        end=_CLOCK() + timedelta(minutes=1),
    )

    assert report.write_ready == 0
    assert writer.calls == 0
    assert report.accepted_payload_count == 0
    assert list_payloads(str(unpublished)) == ()
    assert usage_report["leaf_dispatch_count"] == 0
    assert usage_report["observed_total_tokens"] == 0
    assert usage_report["reported_tokens"] == 0
    assert sum(usage_report["zero_call_admission_counts"].values()) > 0


def test_two_write_ready_run_cycle_attempts_two_not_three_with_usage_join(
    tmp_path: Path,
) -> None:
    unpublished = tmp_path / "unpublished.sqlite3"
    writer = RecordingFixtureWriter()

    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(unpublished),
        writer=writer,
        evidence_package_builder=_qualified_builder(frozenset({"HK-01", "UK-01"})),
        max_writes=5,
        clock=_CLOCK,
    )

    assert report.write_ready == 2
    assert report.candidate_attempts == 2
    assert report.provider_dispatches == 2
    assert len(writer.calls) == 2
    assert report.candidate_attempts != 3


def test_governed_cli_cycle_identities_are_visible_on_export_bucket_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.hermes_control_plane as hermes

    def fake_run_cycle(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            cycle_id=kwargs["cycle_id"],
            write_ready=0,
            admission_hold=0,
            admission_reject=0,
            provider_dispatches=0,
            accepted_payload_count=0,
            writer_circuit_open=False,
            writer_circuit_open_reason="",
        )

    monkeypatch.setattr(hermes, "run_intake", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(hermes, "run_cycle", fake_run_cycle)
    args = SimpleNamespace(
        proving=str(tmp_path / "proving.sqlite3"),
        unpublished=str(tmp_path / "unpublished.sqlite3"),
        max_writes=5,
    )

    _intake, report, terminal = hermes._governed_unit(args, cooldown_seconds=300)
    service = ModelUsageService(str(args.unpublished))
    terminal_at = datetime.strptime(
        terminal.terminal_at, "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=UTC)
    epoch = int(terminal_at.timestamp())
    start = datetime.fromtimestamp(epoch - (epoch % 300), tz=UTC)
    exported = service.export_bucket_csv(
        start=start,
        end=start + timedelta(seconds=300),
    )
    rows = list(csv.DictReader(io.StringIO(exported)))

    assert report.cycle_id == terminal.cycle_id
    assert terminal.outcome_class == "IDLE_QUALIFIED_ZERO"
    assert len(rows) == 1
    assert rows[0]["idle_qualified_zero_cycles"] == "1"
    assert rows[0]["cycle_ids"] == json.dumps(
        [terminal.cycle_id], ensure_ascii=False, separators=(",", ":")
    )
    assert rows[0]["cycle_outcome_classes"] == json.dumps(
        ["IDLE_QUALIFIED_ZERO"], ensure_ascii=False, separators=(",", ":")
    )
    assert rows[0]["cooldown_seconds_values"] == json.dumps(
        [terminal.cooldown_seconds], ensure_ascii=False, separators=(",", ":")
    )
    assert rows[0]["next_cycle_eligible_at_values"] == json.dumps(
        [terminal.next_cycle_eligible_at],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_issue_732_behaviour_mapping_names_exist() -> None:
    mapping = json.loads(CLOSEOUT_JSON.read_text(encoding="utf-8"))
    defined: set[str] = set()
    for path in (_REPO_ROOT / "newsroom/tests").rglob("test_*.py"):
        defined.update(
            re.findall(r"^def (test_[A-Za-z0-9_]+)\(", path.read_text(), re.M)
        )
    missing = [
        name
        for item in mapping["behaviour_tests"]
        for name in item.get("tests", [])
        if name not in defined
    ]
    assert mapping["issue"] == 732
    assert len(mapping["behaviour_tests"]) == 16
    assert missing == []
    assert mapping["behaviour_tests"][14]["suites"] == [
        "newsroom/tests/test_zero_quota_write_loop.py",
        "newsroom/tests/test_model_usage_receipts.py",
        "newsroom/tests/test_durable_cycle_governor.py",
        "newsroom/tests/test_cont_calibration.py",
        "newsroom/tests/test_graphiti_adapter_real_executor.py",
        "newsroom/tests/test_graphiti_corpus_ingest.py",
    ]


def test_committed_after_csv_matches_deterministic_fixture_export(
    tmp_path: Path,
) -> None:
    exported = _issue_732_after_csv(tmp_path)
    committed = AFTER_CSV.read_text(encoding="utf-8")
    assert exported == committed
    header = exported.split("\n", 1)[0]
    for column in _HISTORICAL_BUCKET_COLUMNS + _NEW_BUCKET_COLUMNS:
        assert column in header.split(",")


def test_closeout_markdown_retains_baseline_as_grok_writer_lower_bound() -> None:
    body = CLOSEOUT_MD.read_text(encoding="utf-8")
    assert "26,693,877" in body
    assert "37,479" in body
    assert "99.28%" in body
    lowered = body.lower()
    assert "lower bound" in lowered
    assert "grok" in lowered
    assert "writer" in lowered
    assert "not a whole-system total" in lowered
    assert "Measure" in body
    assert "Historical behaviour" in body
    assert "Required exact-head outcome" in body
