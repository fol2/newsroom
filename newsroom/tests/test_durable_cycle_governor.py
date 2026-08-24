from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.control_plane.cycle_governor import (
    CONT_WRITER_ROUTE,
    CycleLeaseConflict,
    CycleNotEligible,
    CycleOutcomeInput,
    DurableCycleGovernor,
    EvaluationCyclePolicy,
)


@dataclass
class InjectedClocks:
    utc: datetime
    monotonic: float = 0.0

    def utc_now(self) -> datetime:
        return self.utc

    def monotonic_now(self) -> float:
        return self.monotonic

    def advance(self, seconds: int) -> None:
        self.utc += timedelta(seconds=seconds)
        self.monotonic += seconds


def _governor(path: Path, clocks: InjectedClocks) -> DurableCycleGovernor:
    return DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
    )


def _productive() -> CycleOutcomeInput:
    return CycleOutcomeInput(
        write_ready=1,
        provider_dispatches=1,
        accepted_payload_count=1,
    )


def _idle() -> CycleOutcomeInput:
    return CycleOutcomeInput(
        write_ready=0,
        provider_dispatches=0,
        accepted_payload_count=0,
    )


def _unproductive() -> CycleOutcomeInput:
    return CycleOutcomeInput(
        write_ready=1,
        provider_dispatches=1,
        accepted_payload_count=0,
    )


def test_productive_cooldown_starts_after_complete_work(tmp_path: Path) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)

    lease = governor.claim(owner_id="worker-a")
    clocks.advance(20)
    result = governor.complete(lease, _productive())

    assert result.outcome_class == "PRODUCTIVE"
    assert result.elapsed_seconds == 20.0
    assert result.cooldown_seconds == 300
    assert result.next_cycle_eligible_at == "2026-08-24T00:05:20.000000Z"
    with pytest.raises(CycleNotEligible) as early:
        governor.claim(owner_id="worker-b")
    assert early.value.reason == "POST_CYCLE_COOLDOWN"
    clocks.advance(299)
    with pytest.raises(CycleNotEligible):
        governor.claim(owner_id="worker-b")
    clocks.advance(1)
    assert governor.claim(owner_id="worker-b").cycle_id != lease.cycle_id


def test_long_cycle_has_no_fixed_rate_catch_up(tmp_path: Path) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)

    lease = governor.claim(owner_id="worker-a")
    clocks.advance(370)
    result = governor.complete(lease, _productive())

    assert result.next_cycle_eligible_at == "2026-08-24T00:11:10.000000Z"
    clocks.advance(299)
    with pytest.raises(CycleNotEligible):
        governor.claim(owner_id="worker-b")
    clocks.advance(1)
    governor.claim(owner_id="worker-b")


def test_idle_cycle_keeps_normal_cooldown_and_streak(tmp_path: Path) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    first = governor.claim(owner_id="worker-a")
    clocks.advance(20)
    unproductive = governor.complete(first, _unproductive())
    assert unproductive.writer_unproductive_streak_after == 1
    clocks.advance(900)

    idle_lease = governor.claim(owner_id="worker-b")
    clocks.advance(5)
    idle = governor.complete(idle_lease, _idle())

    assert idle.outcome_class == "IDLE_QUALIFIED_ZERO"
    assert idle.cooldown_seconds == 300
    assert idle.writer_unproductive_streak_before == 1
    assert idle.writer_unproductive_streak_after == 1


def test_first_unproductive_provider_cycle_uses_900_second_backoff(
    tmp_path: Path,
) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    lease = governor.claim(owner_id="worker-a")
    clocks.advance(20)

    result = governor.complete(lease, _unproductive())

    assert result.outcome_class == "UNPRODUCTIVE_PROVIDER"
    assert result.cooldown_seconds == 900
    assert result.next_cycle_eligible_at == "2026-08-24T00:15:20.000000Z"
    assert result.writer_unproductive_streak_after == 1


def test_second_unproductive_cycle_opens_cont_route_and_suppresses_dispatch(
    tmp_path: Path,
) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    first = governor.claim(owner_id="worker-a")
    governor.complete(first, _unproductive())
    clocks.advance(900)
    second = governor.claim(owner_id="worker-b")
    second_result = governor.complete(second, _unproductive())
    assert second_result.writer_circuit_state == "OPEN"
    assert second_result.writer_unproductive_streak_after == 2
    clocks.advance(900)

    suppressed = governor.claim(owner_id="worker-c")

    assert suppressed.writer_dispatch_permitted is False
    suppressed_result = governor.complete(
        suppressed,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=0,
            accepted_payload_count=0,
        ),
    )
    assert suppressed_result.outcome_class == "SYSTEMIC_PROVIDER_FAILURE"


def test_productive_cycle_resets_existing_unproductive_streak(tmp_path: Path) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    first = governor.claim(owner_id="worker-a")
    governor.complete(first, _unproductive())
    clocks.advance(900)

    second = governor.claim(owner_id="worker-b")
    result = governor.complete(second, _productive())

    assert result.writer_unproductive_streak_before == 1
    assert result.writer_unproductive_streak_after == 0
    assert result.writer_circuit_state == "CLOSED"


def test_systemic_failure_opens_cont_circuit_immediately(tmp_path: Path) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    lease = governor.claim(owner_id="worker-a")

    result = governor.complete(
        lease,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=1,
            accepted_payload_count=0,
            systemic_provider_failure_reason="PROVIDER_AUTHENTICATION_FAILURE",
        ),
    )

    assert result.outcome_class == "SYSTEMIC_PROVIDER_FAILURE"
    assert result.writer_circuit_state == "OPEN"
    assert result.writer_circuit_open_reason == "PROVIDER_AUTHENTICATION_FAILURE"


def test_systemic_failure_after_an_accept_resets_streak_but_still_opens_circuit(
    tmp_path: Path,
) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    first = governor.claim(owner_id="worker-a")
    governor.complete(first, _unproductive())
    clocks.advance(900)
    second = governor.claim(owner_id="worker-b")

    result = governor.complete(
        second,
        CycleOutcomeInput(
            write_ready=2,
            provider_dispatches=2,
            accepted_payload_count=1,
            systemic_provider_failure_reason="PROVIDER_QUOTA_FAILURE",
        ),
    )

    assert result.outcome_class == "SYSTEMIC_PROVIDER_FAILURE"
    assert result.writer_unproductive_streak_after == 0
    assert result.writer_circuit_state == "OPEN"


def test_restart_reuses_retained_normal_and_longer_cooldowns(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    first_process = _governor(path, clocks)
    lease = first_process.claim(owner_id="worker-a")
    first_process.complete(lease, _unproductive())

    restarted = _governor(path, clocks)
    with pytest.raises(CycleNotEligible) as early:
        restarted.claim(owner_id="worker-after-restart")
    assert early.value.remaining_seconds == 900.0
    assert restarted.status().writer_unproductive_streak == 1


def test_two_governors_cannot_overlap_cycles(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    first = _governor(path, clocks)
    second = _governor(path, clocks)
    lease = first.claim(owner_id="worker-a")

    with pytest.raises(CycleLeaseConflict) as conflict:
        second.claim(owner_id="worker-b")

    assert conflict.value.cycle_id == lease.cycle_id
    assert second.status().active_cycle_id == lease.cycle_id


def test_stale_lease_is_recovered_once_and_cannot_create_early_start(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        lease_seconds=30,
    )
    abandoned = governor.claim(owner_id="dead-worker")
    clocks.advance(31)

    with pytest.raises(CycleNotEligible) as recovered:
        _governor(path, clocks).claim(owner_id="recovery-worker")

    assert recovered.value.reason == "STALE_LEASE_RECOVERED"
    connection = sqlite3.connect(path)
    rows = connection.execute(
        "SELECT cycle_id, lease_state, terminal_state, outcome_class "
        "FROM unpublished_governed_cycles"
    ).fetchall()
    connection.close()
    assert rows == [
        (
            abandoned.cycle_id,
            "RECOVERED",
            "RECOVERED_STALE_LEASE",
            "SYSTEMIC_PROVIDER_FAILURE",
        )
    ]
    with pytest.raises(CycleNotEligible) as still_early:
        _governor(path, clocks).claim(owner_id="other-worker")
    assert still_early.value.reason == "POST_CYCLE_COOLDOWN"


def test_backwards_utc_clock_fails_closed_and_records_refusal(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(path, clocks)
    lease = governor.claim(owner_id="worker-a")
    clocks.advance(20)
    governor.complete(lease, _productive())
    clocks.utc -= timedelta(seconds=10)

    with pytest.raises(CycleNotEligible) as refused:
        _governor(path, clocks).claim(owner_id="worker-b")

    assert refused.value.reason == "UTC_CLOCK_BACKWARDS"
    status = _governor(path, clocks).status()
    assert status.refused_early_start_count == 1
    assert status.refused_early_start_reason == "UTC_CLOCK_BACKWARDS"


def test_cont_circuit_release_requires_bound_probe_and_minimum_interval(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(path, clocks)
    lease = governor.claim(owner_id="worker-a")
    result = governor.complete(
        lease,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=1,
            accepted_payload_count=0,
            systemic_provider_failure_reason="PROVIDER_CONFIGURATION_FAILURE",
        ),
    )

    with pytest.raises(CycleNotEligible) as early:
        governor.release_with_health_probe(
            route=CONT_WRITER_ROUTE,
            bound_failure_reason=result.writer_circuit_open_reason,
            executable_ok=True,
            authentication_ok=True,
            configuration_ok=True,
            provider_available=True,
            provider_dispatched=False,
            provider_receipt_reference=None,
        )
    assert early.value.reason == "HEALTH_PROBE_INTERVAL"
    clocks.advance(3600)
    evidence = governor.release_with_health_probe(
        route=CONT_WRITER_ROUTE,
        bound_failure_reason=result.writer_circuit_open_reason,
        executable_ok=True,
        authentication_ok=True,
        configuration_ok=True,
        provider_available=True,
        provider_dispatched=False,
        provider_receipt_reference=None,
    )
    assert evidence.release_kind == "DETERMINISTIC_HEALTH_PROBE"
    assert governor.status().writer_circuit_state == "CLOSED"


def test_operator_reset_is_bound_to_current_failure_and_policy(tmp_path: Path) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    lease = governor.claim(owner_id="worker-a")
    failed = governor.complete(
        lease,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=1,
            accepted_payload_count=0,
            systemic_provider_failure_reason="PROVIDER_QUOTA_FAILURE",
        ),
    )
    with pytest.raises(ValueError, match="current circuit failure"):
        governor.authorised_operator_reset(
            route=CONT_WRITER_ROUTE,
            bound_failure_reason="SOME_OTHER_FAILURE",
            policy_version=EvaluationCyclePolicy().version,
            authorised_by="operator:fixture",
            evidence_reference="fixture://reset/1",
        )
    evidence = governor.authorised_operator_reset(
        route=CONT_WRITER_ROUTE,
        bound_failure_reason=failed.writer_circuit_open_reason,
        policy_version=EvaluationCyclePolicy().version,
        authorised_by="operator:fixture",
        evidence_reference="fixture://reset/1",
    )
    assert evidence.release_kind == "AUTHORISED_OPERATOR_RESET"
    assert governor.status().writer_circuit_state == "CLOSED"


def test_graphiti_route_state_is_not_rewritten_by_cont_backoff(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(path, clocks)
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO unpublished_route_circuits("
        "route, state, open_reason, opened_at, release_evidence_json, "
        "release_evidence_digest, last_probe_at) VALUES(?,?,?,?,?,?,?)",
        (
            "GRAPHITI",
            "OPEN",
            "GRAPHITI_FIXTURE_FAILURE",
            "2026-08-23T00:00:00.000000Z",
            None,
            None,
            None,
        ),
    )
    connection.commit()
    connection.close()
    lease = governor.claim(owner_id="worker-a")
    governor.complete(lease, _unproductive())
    connection = sqlite3.connect(path)
    graphiti = connection.execute(
        "SELECT state, open_reason FROM unpublished_route_circuits "
        "WHERE route='GRAPHITI'"
    ).fetchone()
    connection.close()
    assert graphiti == ("OPEN", "GRAPHITI_FIXTURE_FAILURE")


def test_policy_cannot_weaken_checked_in_evaluation_defaults() -> None:
    with pytest.raises(ValueError, match="at least 300"):
        EvaluationCyclePolicy(normal_cooldown_seconds=299)
    with pytest.raises(ValueError, match="at least 900"):
        EvaluationCyclePolicy(unproductive_cooldown_seconds=899)
    with pytest.raises(ValueError, match="at least 3600"):
        EvaluationCyclePolicy(health_probe_interval_seconds=3599)


def test_ambiguous_exception_terminalises_cycle_with_unknown_dispatch_count(
    tmp_path: Path,
) -> None:
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    lease = governor.claim(owner_id="worker-a")

    failed = governor.fail_ambiguous(
        lease,
        failure_reason="GOVERNED_UNIT_EXCEPTION:RuntimeError",
    )

    assert failed.terminal_state == "FAILED_AMBIGUOUS_PROVIDER_STATE"
    assert failed.outcome_class == "SYSTEMIC_PROVIDER_FAILURE"
    assert failed.writer_provider_dispatch_count is None
    assert failed.writer_circuit_state == "OPEN"
    assert failed.restart_observations == ("FRESH_STATE",)


def test_cli_cooldown_alias_conflicts_and_weak_values_fail_closed() -> None:
    from scripts.hermes_control_plane import _resolve_cooldown

    assert _resolve_cooldown(cooldown=None, interval=None) == 300
    assert _resolve_cooldown(cooldown=600, interval=600) == 600
    with pytest.raises(ValueError, match="conflict"):
        _resolve_cooldown(cooldown=300, interval=301)
    with pytest.raises(ValueError, match="at least 300"):
        _resolve_cooldown(cooldown=299, interval=None)


def test_cli_cycle_composition_uses_governed_cycle_id_and_circuit_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.hermes_control_plane as hermes

    captured: dict[str, object] = {}

    def fake_run_cycle(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
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

    _intake, report, terminal = hermes._governed_unit(
        args,
        cooldown_seconds=300,
    )

    assert report.cycle_id == terminal.cycle_id == captured["cycle_id"]
    assert captured["max_writer_provider_dispatches"] == 5
    with pytest.raises(CycleNotEligible, match="POST_CYCLE_COOLDOWN"):
        hermes._governed_unit(args, cooldown_seconds=300)
