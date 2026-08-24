from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.cycle_governor import (
    CycleLeaseConflict,
    CycleNotEligible,
    CycleOutcomeInput,
    DurableCycleGovernor,
    EvaluationCyclePolicy,
    WriterRouteHealthProof,
)
from newsroom.control_plane.model_usage import (
    InvocationEfficiencyPolicy,
    ModelUsageService,
    WorkloadClass,
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


def _healthy_route() -> WriterRouteHealthProof:
    return WriterRouteHealthProof(
        executable_ok=True,
        authentication_ok=True,
        configuration_ok=True,
        provider_available=True,
        provider_dispatched=False,
        provider_receipt_reference=None,
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


def test_fresh_store_binds_configured_conservative_policy(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    policy = EvaluationCyclePolicy(
        normal_cooldown_seconds=600,
        unproductive_cooldown_seconds=1200,
    )

    governor = DurableCycleGovernor(str(path), policy=policy)

    assert governor.status().policy_version == policy.version


def test_legacy_health_probe_rows_migrate_without_inventing_terminal_truth(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE unpublished_route_health_probes("
        "probe_id TEXT PRIMARY KEY, route TEXT NOT NULL, "
        "bound_failure_reason TEXT NOT NULL, attempted_at TEXT NOT NULL, "
        "outcome TEXT NOT NULL CHECK(outcome IN ('PASSED','FAILED')), "
        "provider_dispatched INTEGER NOT NULL CHECK(provider_dispatched IN (0,1)), "
        "provider_receipt_reference TEXT, evidence_json TEXT NOT NULL, "
        "evidence_digest TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO unpublished_route_health_probes VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "probe-legacy",
            "CONT",
            "PROVIDER_CONFIGURATION_FAILURE",
            "2026-08-24T00:00:00.000000Z",
            "PASSED",
            1,
            "receipt://legacy",
            "{}",
            "sha256:legacy",
        ),
    )
    connection.commit()
    connection.close()

    DurableCycleGovernor(str(path))

    connection = sqlite3.connect(path)
    migrated = connection.execute(
        "SELECT probe_state, terminal_at, outcome FROM "
        "unpublished_route_health_probes WHERE probe_id='probe-legacy'"
    ).fetchone()
    connection.close()
    assert migrated == ("LEGACY_UNKNOWN", None, None)


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


def test_restart_reuses_retained_normal_cooldown(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    first_process = _governor(path, clocks)
    lease = first_process.claim(owner_id="worker-a")
    first_process.complete(lease, _productive())

    with pytest.raises(CycleNotEligible) as early:
        _governor(path, clocks).claim(owner_id="worker-after-restart")

    assert early.value.remaining_seconds == 300.0


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


def test_concurrent_claimers_yield_exactly_one_active_cycle(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    _governor(path, clocks)

    def claim(owner: str) -> str:
        try:
            return _governor(path, clocks).claim(owner_id=owner).cycle_id
        except CycleLeaseConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(claim, ("worker-a", "worker-b")))

    assert results.count("CONFLICT") == 1
    connection = sqlite3.connect(path)
    active = connection.execute(
        "SELECT COUNT(*) FROM unpublished_governed_cycles WHERE lease_state='ACTIVE'"
    ).fetchone()[0]
    connection.close()
    assert active == 1


def test_active_worker_renews_lease_before_dispatch_boundary(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        lease_seconds=30,
    )
    lease = governor.claim(owner_id="worker-a")
    clocks.advance(25)
    renewed_until = governor.renew(lease)
    clocks.advance(10)

    with pytest.raises(CycleLeaseConflict):
        DurableCycleGovernor(
            str(path),
            utc_clock=clocks.utc_now,
            monotonic_clock=clocks.monotonic_now,
            lease_seconds=30,
        ).claim(owner_id="worker-b")

    assert renewed_until == "2026-08-24T00:00:55.000000Z"
    governor.complete(lease, _productive())


def test_expired_worker_cannot_revive_its_stale_lease(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        lease_seconds=30,
    )
    lease = governor.claim(owner_id="worker-a")
    clocks.advance(30)

    with pytest.raises(CycleNotEligible) as expired:
        governor.renew(lease)

    assert expired.value.reason == "STALE_LEASE_EXPIRED"
    with pytest.raises(CycleNotEligible) as recovered:
        DurableCycleGovernor(
            str(path),
            utc_clock=clocks.utc_now,
            monotonic_clock=clocks.monotonic_now,
            lease_seconds=30,
        ).claim(owner_id="worker-b")
    assert recovered.value.reason == "STALE_LEASE_RECOVERED"


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
    governor = DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        writer_route_health_probe=_healthy_route,
    )
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
            bound_failure_reason=result.writer_circuit_open_reason,
        )
    assert early.value.reason == "HEALTH_PROBE_INTERVAL"
    clocks.advance(3600)
    evidence = governor.release_with_health_probe(
        bound_failure_reason=result.writer_circuit_open_reason,
    )
    assert evidence.release_kind == "DETERMINISTIC_HEALTH_PROBE"
    assert governor.status().writer_circuit_state == "CLOSED"


def test_failed_provider_health_probe_is_receipted_and_rate_limited(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))

    def unhealthy_route() -> WriterRouteHealthProof:
        return WriterRouteHealthProof(
            executable_ok=True,
            authentication_ok=False,
            configuration_ok=True,
            provider_available=True,
            provider_dispatched=True,
            provider_receipt_reference="receipt://health/1",
        )

    governor = DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        writer_route_health_probe=unhealthy_route,
    )
    lease = governor.claim(owner_id="worker-a")
    failed = governor.complete(
        lease,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=1,
            accepted_payload_count=0,
            systemic_provider_failure_reason="PROVIDER_CONFIGURATION_FAILURE",
        ),
    )
    clocks.advance(3600)

    with pytest.raises(ValueError, match="did not prove"):
        governor.release_with_health_probe(
            bound_failure_reason=failed.writer_circuit_open_reason,
        )
    with pytest.raises(CycleNotEligible) as throttled:
        governor.release_with_health_probe(
            bound_failure_reason=failed.writer_circuit_open_reason,
        )
    assert throttled.value.reason == "HEALTH_PROBE_INTERVAL"
    assert throttled.value.remaining_seconds == 3600.0
    connection = sqlite3.connect(path)
    probe = connection.execute(
        "SELECT outcome, provider_dispatched, provider_receipt_reference "
        "FROM unpublished_route_health_probes"
    ).fetchone()
    connection.close()
    assert probe == ("FAILED", 1, "receipt://health/1")


def test_provider_health_probe_reservation_is_durable_before_dispatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))

    def interrupted_route() -> WriterRouteHealthProof:
        connection = sqlite3.connect(path)
        probe = connection.execute(
            "SELECT probe_state, terminal_at, outcome, provider_dispatched FROM "
            "unpublished_route_health_probes"
        ).fetchone()
        last_probe_at = connection.execute(
            "SELECT last_probe_at FROM unpublished_route_circuits WHERE route='CONT'"
        ).fetchone()
        connection.close()
        assert probe == ("RESERVED", None, None, 0)
        assert last_probe_at == ("2026-08-24T01:00:00.000000Z",)
        raise KeyboardInterrupt

    governor = DurableCycleGovernor(
        str(path),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        writer_route_health_probe=interrupted_route,
    )
    lease = governor.claim(owner_id="worker-a")
    failed = governor.complete(
        lease,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=1,
            accepted_payload_count=0,
            systemic_provider_failure_reason="PROVIDER_CONFIGURATION_FAILURE",
        ),
    )
    clocks.advance(3600)

    with pytest.raises(KeyboardInterrupt):
        governor.release_with_health_probe(
            bound_failure_reason=failed.writer_circuit_open_reason,
        )
    with pytest.raises(CycleNotEligible) as throttled:
        governor.release_with_health_probe(
            bound_failure_reason=failed.writer_circuit_open_reason,
        )

    assert throttled.value.reason == "HEALTH_PROBE_INTERVAL"
    assert throttled.value.remaining_seconds == 3600.0


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
    with pytest.raises(ValueError, match="authority proof"):
        governor.authorised_operator_reset(
            bound_failure_reason=failed.writer_circuit_open_reason,
            policy_version=EvaluationCyclePolicy().version,
            authorised_by="operator:fixture",
            evidence_reference="fixture://reset/1",
        )
    authorised = DurableCycleGovernor(
        str(tmp_path / "unpublished.sqlite3"),
        utc_clock=clocks.utc_now,
        monotonic_clock=clocks.monotonic_now,
        operator_reset_verifier=lambda request: (
            request.authorised_by == "operator:fixture"
            and request.evidence_reference == "fixture://reset/1"
        ),
    )
    with pytest.raises(ValueError, match="current circuit failure"):
        authorised.authorised_operator_reset(
            bound_failure_reason="SOME_OTHER_FAILURE",
            policy_version=EvaluationCyclePolicy().version,
            authorised_by="operator:fixture",
            evidence_reference="fixture://reset/1",
        )
    evidence = authorised.authorised_operator_reset(
        bound_failure_reason=failed.writer_circuit_open_reason,
        policy_version=EvaluationCyclePolicy().version,
        authorised_by="operator:fixture",
        evidence_reference="fixture://reset/1",
    )
    assert evidence.release_kind == "AUTHORISED_OPERATOR_RESET"
    assert authorised.status().writer_circuit_state == "CLOSED"


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
    assert (
        EvaluationCyclePolicy().version
        != EvaluationCyclePolicy(normal_cooldown_seconds=600).version
    )


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
    assert callable(captured["writer_dispatch_fence"])
    assert terminal.outcome_class == "IDLE_QUALIFIED_ZERO"
    with pytest.raises(CycleNotEligible, match="POST_CYCLE_COOLDOWN"):
        hermes._governed_unit(args, cooldown_seconds=300)


def test_governed_cli_rejects_zero_max_writes_without_claiming_cycle(
    tmp_path: Path,
) -> None:
    import scripts.hermes_control_plane as hermes

    args = SimpleNamespace(
        proving=str(tmp_path / "proving.sqlite3"),
        unpublished=str(tmp_path / "unpublished.sqlite3"),
        max_writes=0,
    )

    with pytest.raises(ValueError, match="between 1 and 5"):
        hermes._governed_unit(args, cooldown_seconds=300)

    assert not (tmp_path / "unpublished.sqlite3").exists()


def test_cli_reports_ambiguous_systemic_terminal_as_structured_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.hermes_control_plane as hermes

    clocks = InjectedClocks(datetime(2026, 8, 24, tzinfo=UTC))
    governor = _governor(tmp_path / "unpublished.sqlite3", clocks)
    lease = governor.claim(owner_id="worker-a")
    terminal = governor.fail_ambiguous(
        lease,
        failure_reason="GOVERNED_UNIT_EXCEPTION:RuntimeError",
    )

    def fail_unit(*_args: object, **_kwargs: object) -> None:
        raise hermes.GovernedUnitFailure("RuntimeError", terminal)

    monkeypatch.setattr(hermes, "_governed_unit", fail_unit)
    monkeypatch.setattr(hermes, "ensure_control_plane_state_root", lambda: None)

    return_code = hermes.main(
        [
            "cycle",
            "--proving",
            str(tmp_path / "proving.sqlite3"),
            "--unpublished",
            str(tmp_path / "unused.sqlite3"),
        ]
    )

    body = json.loads(capsys.readouterr().out)
    assert return_code == 2
    assert body["event"] == "GOVERNED_CYCLE_SYSTEMIC_FAILURE"
    assert body["cycle_governor"]["outcome_class"] == "SYSTEMIC_PROVIDER_FAILURE"
    assert body["cycle_governor"]["writer_provider_dispatch_count"] is None


def test_grok_route_probe_checks_pinned_model_without_article_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.control_plane import writer

    captured: dict[str, object] = {}

    def run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="grok-4.6\n", stderr="")

    monkeypatch.setattr(writer, "grok_cli_ready", lambda: True)
    monkeypatch.setattr(writer.subprocess, "run", run)

    proof = writer.probe_grok_writer_route()

    assert captured["command"] == (writer.GROK_BIN, "models")
    assert proof.executable_ok is True
    assert proof.authentication_ok is True
    assert proof.configuration_ok is True
    assert proof.provider_available is True
    assert proof.provider_dispatched is True
    assert proof.provider_receipt_reference.startswith("sha256:")


def test_cli_health_probe_releases_open_route_with_configured_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.hermes_control_plane as hermes

    path = tmp_path / "unpublished.sqlite3"
    governor = DurableCycleGovernor(str(path))
    lease = governor.claim(owner_id="worker-a")
    failed = governor.complete(
        lease,
        CycleOutcomeInput(
            write_ready=1,
            provider_dispatches=1,
            accepted_payload_count=0,
            systemic_provider_failure_reason="PROVIDER_CONFIGURATION_FAILURE",
        ),
    )
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_route_circuits SET opened_at=? WHERE route='CONT'",
        (
            (datetime.now(tz=UTC) - timedelta(hours=2)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
        ),
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(hermes, "ensure_control_plane_state_root", lambda: None)
    monkeypatch.setattr(hermes, "_probe_cont_writer_route", _healthy_route)
    usage = ModelUsageService(str(path))
    usage.register_policy(
        InvocationEfficiencyPolicy.create(
            policy_id="fixture-health-probe",
            version="v1",
            workload_class=WorkloadClass.CONT_ROUTE_HEALTH_PROBE,
            provider=hermes.CONT_HEALTH_PROBE_PROVIDER,
            route=hermes.CONT_HEALTH_PROBE_ROUTE,
            model=hermes.CONT_HEALTH_PROBE_MODEL,
            reasoning=hermes.CONT_HEALTH_PROBE_REASONING,
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            max_prompt_bytes=1_000,
            max_context_tokens=1,
            max_output_tokens=1,
            max_total_tokens=1,
            prompt_contract_version=hermes.CONT_HEALTH_PROBE_PROMPT_CONTRACT,
            output_schema_digest=digest_canonical(
                {"schema": "writer-route-health"}
            ),
            allowed_context_identities=(
                hermes.CONT_HEALTH_PROBE_CONTEXT_IDENTITY,
            ),
            evidence_digest=digest_canonical({"fixture": "health-probe"}),
            qualified=True,
        )
    )

    return_code = hermes.main(
        [
            "writer-health-probe",
            "--unpublished",
            str(path),
            "--proving",
            str(tmp_path / "proving.sqlite3"),
        ]
    )

    body = json.loads(capsys.readouterr().out)
    assert failed.writer_circuit_state == "OPEN"
    assert return_code == 0
    assert body["event"] == "CONT_WRITER_HEALTH_PROBE_PASSED"
    assert governor.status().writer_circuit_state == "CLOSED"
    leaves = usage.query(
        start=datetime.now(tz=UTC) - timedelta(minutes=1),
        end=datetime.now(tz=UTC) + timedelta(minutes=1),
    )["leaves"]
    assert len(leaves) == 1
    assert leaves[0]["workload_class"] == "CONT_ROUTE_HEALTH_PROBE"
    assert leaves[0]["total_tokens"] == 0
