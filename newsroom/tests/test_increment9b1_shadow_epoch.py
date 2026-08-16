from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.increment9_shadow_migrations import (
    INCREMENT9_SHADOW_APPLICATION_ID,
    INCREMENT9_SHADOW_MIGRATION_CHECKSUM,
    INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
    INCREMENT9_SHADOW_SCHEMA_VERSION,
    Increment9ShadowMigrationError,
    install_increment9_shadow_schema,
    verify_increment9_shadow_schema,
)
from newsroom.increment9.epoch import (
    EFFECTIVE_MANIFEST_IDENTITY_KEYS,
    ChangeClassification,
    Checkpoint,
    CohortCloseout,
    CostRecord,
    EffectIntent,
    EffectKind,
    EffectResult,
    EffectiveManifest,
    EpochAuthorityError,
    EvaluationEpoch,
    ManifestCohort,
    RecordOutcome,
    ReplayController,
    RunAttempt,
    RunKind,
    RunOutcome,
    ShadowEpochAuthority,
    ShadowRun,
    classify_manifest_change,
    initialise_shadow_epoch_authority,
    qualify_final_cohort,
    validate_cohort_closeout,
    validate_cohort_chain,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

D = lambda character: "sha256:" + character * 64
T0 = "2042-01-01T00:00:00.000000Z"
T1 = "2042-01-01T00:01:00.000000Z"
T2 = "2042-01-01T00:02:00.000000Z"
T3 = "2042-01-01T00:03:00.000000Z"
T4 = "2042-01-01T00:04:00.000000Z"
T9 = "2042-01-29T00:00:00.000000Z"


def _epoch() -> EvaluationEpoch:
    return EvaluationEpoch(
        epoch_id="epoch-9-fixture",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        shadow_scope_digest=D("1"),
        source_portfolio_digest=D("2"),
        prospective_universe_digest=D("3"),
        slice_rules_digest=D("4"),
        thresholds_digest=D("5"),
        comparator_rules_digest=D("6"),
        reviewer_rules_digest=D("7"),
        budget_rules_digest=D("8"),
        rights_rules_digest=D("9"),
        opened_at=T0,
        cutoff_at=T0,
        closes_at=T9,
    )


def _manifest(character: str = "a", *, resolved: bool = True) -> EffectiveManifest:
    digits = "0123456789abcdef"
    identities = {
        key: D(digits[(index + int(character, 16)) % 16])
        for index, key in enumerate(sorted(EFFECTIVE_MANIFEST_IDENTITY_KEYS))
    }
    return EffectiveManifest(
        manifest_id=f"effective-manifest-{character}",
        identity_digests=identities,
        observed_at=T0,
        identity_resolved=resolved,
    )


def _cohort(
    epoch: EvaluationEpoch | None = None,
    manifest: EffectiveManifest | None = None,
    **changes: object,
) -> ManifestCohort:
    epoch = epoch or _epoch()
    manifest = manifest or _manifest()
    values: dict[str, object] = {
        "cohort_id": "cohort-1",
        "epoch_id": epoch.epoch_id,
        "epoch_digest": epoch.canonical_digest,
        "manifest_digest": manifest.canonical_digest,
        "ordinal": 1,
        "previous_cohort_digest": None,
        "exposure_contract_digest": D("b"),
        "required_slices": ("HONG_KONG", "UK"),
        "opened_at": T1,
        "decision_bearing": manifest.decision_bearing,
    }
    values.update(changes)
    return ManifestCohort(**values)  # type: ignore[arg-type]


def _closeout(
    epoch: EvaluationEpoch,
    cohorts: tuple[ManifestCohort, ...],
    **changes: object,
) -> CohortCloseout:
    final = cohorts[-1]
    values: dict[str, object] = {
        "closeout_id": "cohort-closeout-1",
        "epoch_id": epoch.epoch_id,
        "epoch_digest": epoch.canonical_digest,
        "final_cohort_digest": final.canonical_digest,
        "observed_slice_ids": final.required_slices,
        "exposure_minima_met": True,
        "complete_denominators": True,
        "unresolved_identity_count": 0,
        "qualifies": final.decision_bearing,
        "closed_at": T9,
    }
    values.update(changes)
    return CohortCloseout(**values)  # type: ignore[arg-type]


def _run(
    epoch: EvaluationEpoch | None = None,
    cohort: ManifestCohort | None = None,
    manifest: EffectiveManifest | None = None,
) -> ShadowRun:
    epoch = epoch or _epoch()
    manifest = manifest or _manifest()
    cohort = cohort or _cohort(epoch, manifest)
    return ShadowRun(
        run_id="run-1",
        epoch_id=epoch.epoch_id,
        epoch_digest=epoch.canonical_digest,
        cohort_id=cohort.cohort_id,
        cohort_digest=cohort.canonical_digest,
        manifest_digest=manifest.canonical_digest,
        production_snapshot_digest=D("c"),
        production_nonmutation_before_digest=D("d"),
        run_kind=RunKind.PROSPECTIVE_BASELINE,
        started_at=T2,
        prospective=True,
    )


def _attempt(run: ShadowRun | None = None, **changes: object) -> RunAttempt:
    run = run or _run()
    values: dict[str, object] = {
        "attempt_id": "attempt-1",
        "run_id": run.run_id,
        "run_digest": run.canonical_digest,
        "ordinal": 1,
        "previous_attempt_digest": None,
        "started_at": T2,
        "restart_reason": None,
    }
    values.update(changes)
    return RunAttempt(**values)  # type: ignore[arg-type]


def _intent(attempt: RunAttempt | None = None) -> EffectIntent:
    attempt = attempt or _attempt()
    return EffectIntent(
        intent_id="intent-1",
        attempt_id=attempt.attempt_id,
        attempt_digest=attempt.canonical_digest,
        sequence=1,
        effect_kind=EffectKind.SOURCE_REQUEST,
        request_digest=D("e"),
        budget_reservation_digest=D("f"),
        persisted_at=T3,
    )


def _records():
    epoch = _epoch()
    manifest = _manifest()
    cohort = _cohort(epoch, manifest)
    run = _run(epoch, cohort, manifest)
    attempt = _attempt(run)
    intent = _intent(attempt)
    result = EffectResult(
        result_id="result-1",
        intent_id=intent.intent_id,
        intent_digest=intent.canonical_digest,
        response_digest=D("1"),
        usage_digest=D("2"),
        outcome=RecordOutcome.COMPLETE,
        observed_valid_at=T3,
        completed_at=T4,
        recorded_at=T4,
    )
    checkpoint = Checkpoint(
        checkpoint_id="checkpoint-1",
        attempt_id=attempt.attempt_id,
        attempt_digest=attempt.canonical_digest,
        sequence=1,
        watermark="source:1",
        inventory_digest=D("3"),
        ledger_digest=D("4"),
        recorded_at=T4,
    )
    cost = CostRecord(
        cost_id="cost-1",
        attempt_id=attempt.attempt_id,
        intent_digest=intent.canonical_digest,
        provider="fixture",
        input_units=10,
        output_units=2,
        monetary_minor_units=1,
        storage_byte_days=0,
        recorded_at=T4,
    )
    outcome = RunOutcome(
        outcome_id="outcome-1",
        run_id=run.run_id,
        run_digest=run.canonical_digest,
        attempt_digest=attempt.canonical_digest,
        cohort_digest=cohort.canonical_digest,
        outcome=RecordOutcome.COMPLETE,
        evidence_inventory_digest=D("5"),
        production_nonmutation_after_digest=D("d"),
        decision_bearing=True,
        recorded_at=T4,
    )
    closeout = _closeout(epoch, (cohort,))
    return epoch, manifest, cohort, run, attempt, intent, result, checkpoint, cost, outcome, closeout


def test_all_public_records_round_trip_exact_canonical_bytes() -> None:
    for record in _records():
        reconstructed = type(record).from_bytes(record.canonical_bytes)
        assert reconstructed == record
        assert reconstructed.canonical_digest == record.canonical_digest


@pytest.mark.parametrize("kind", ("unknown", "duplicate", "noncanonical"))
def test_strict_epoch_parser_rejects_unknown_duplicate_and_noncanonical(kind: str) -> None:
    raw = _epoch().canonical_bytes
    if kind == "unknown":
        value = json.loads(raw)
        value["unknown"] = True
        raw = canonical_json_bytes(value)
    elif kind == "duplicate":
        raw = raw.replace(b'{"budget_rules_digest":', b'{"budget_rules_digest":null,"budget_rules_digest":', 1)
    else:
        raw += b"\n"
    with pytest.raises(EpochAuthorityError):
        EvaluationEpoch.from_bytes(raw)


def test_epoch_is_prospective_frozen_and_chronological() -> None:
    epoch = _epoch()
    with pytest.raises(FrozenInstanceError):
        epoch.epoch_id = "changed"  # type: ignore[misc]
    with pytest.raises(EpochAuthorityError, match="prospective"):
        replace(epoch, hindsight_changes_allowed=True)
    with pytest.raises(EpochAuthorityError, match="chronology"):
        replace(epoch, closes_at=epoch.cutoff_at)


def test_effective_manifest_requires_every_exact_identity_and_resolution_is_explicit() -> None:
    manifest = _manifest()
    assert manifest.decision_bearing is True
    unresolved = _manifest("b", resolved=False)
    assert unresolved.decision_bearing is False
    with pytest.raises(EpochAuthorityError, match="identity fields"):
        EffectiveManifest(
            manifest_id="broken",
            identity_digests={"model": D("1")},
            observed_at=T0,
            identity_resolved=True,
        )


def test_change_classifier_opens_cohort_or_requires_new_epoch() -> None:
    assert classify_manifest_change((), identities_resolved=True) is ChangeClassification.UNCHANGED
    assert classify_manifest_change(("model",), identities_resolved=True) is ChangeClassification.COMPATIBLE_NEW_COHORT
    assert classify_manifest_change(("thresholds",), identities_resolved=True) is ChangeClassification.INCOMPATIBLE_NEW_EPOCH
    assert classify_manifest_change(("model",), identities_resolved=False) is ChangeClassification.UNRESOLVED_NOT_DECISION_BEARING
    with pytest.raises(EpochAuthorityError, match="not classified"):
        classify_manifest_change(("mystery",), identities_resolved=True)


def test_cohorts_are_isolated_content_addressed_and_only_last_is_final() -> None:
    epoch = _epoch()
    first_manifest = _manifest("a")
    second_manifest = _manifest("b")
    first = _cohort(epoch, first_manifest)
    second = _cohort(
        epoch,
        second_manifest,
        cohort_id="cohort-2",
        ordinal=2,
        previous_cohort_digest=first.canonical_digest,
        opened_at=T3,
    )
    manifests = {
        first_manifest.canonical_digest: first_manifest,
        second_manifest.canonical_digest: second_manifest,
    }
    assert validate_cohort_chain(epoch, manifests, (first, second)) == (first, second)
    first_closeout = _closeout(
        epoch,
        (first,),
        final_cohort_digest=first.canonical_digest,
        closed_at=T2,
    )
    with pytest.raises(EpochAuthorityError, match="only the final"):
        validate_cohort_closeout(
            epoch,
            (first, second),
            first_closeout,
        )


def test_final_cohort_qualifies_only_with_independent_complete_exposure() -> None:
    epoch = _epoch()
    cohort = _cohort()
    cohorts = (cohort,)
    assert qualify_final_cohort(
        epoch,
        cohorts,
        _closeout(epoch, cohorts),
    ) is True
    for changes in (
        {"observed_slice_ids": ("UK",), "qualifies": False},
        {"unresolved_identity_count": 1, "qualifies": False},
        {"exposure_minima_met": False, "qualifies": False},
        {"complete_denominators": False, "qualifies": False},
    ):
        assert qualify_final_cohort(
            epoch,
            cohorts,
            _closeout(epoch, cohorts, **changes),
        ) is False
    with pytest.raises(EpochAuthorityError, match="qualification truth"):
        validate_cohort_closeout(
            epoch,
            cohorts,
            _closeout(epoch, cohorts, observed_slice_ids=("UK",), qualifies=True),
        )


def test_partial_stale_blocked_failed_and_early_stopped_cannot_be_decision_bearing() -> None:
    records = _records()
    complete = next(record for record in records if isinstance(record, RunOutcome))
    for outcome in (
        RecordOutcome.PARTIAL,
        RecordOutcome.STALE,
        RecordOutcome.UNAVAILABLE,
        RecordOutcome.BLOCKED,
        RecordOutcome.FAILED,
        RecordOutcome.EARLY_STOPPED,
        RecordOutcome.INCONCLUSIVE,
    ):
        with pytest.raises(EpochAuthorityError, match="cannot be decision-bearing"):
            replace(complete, outcome=outcome)


def test_lost_response_and_ambiguous_effect_are_retained_explicitly() -> None:
    intent = _intent()
    for outcome in (RecordOutcome.LOST_RESPONSE, RecordOutcome.AMBIGUOUS_EFFECT):
        result = EffectResult(
            result_id=f"result-{outcome.value.lower()}",
            intent_id=intent.intent_id,
            intent_digest=intent.canonical_digest,
            response_digest=None,
            usage_digest=D("1"),
            outcome=outcome,
            observed_valid_at=T3,
            completed_at=T4,
            recorded_at=T4,
        )
        assert result.response_digest is None

    with pytest.raises(EpochAuthorityError, match="transaction time"):
        replace(
            EffectResult(
                result_id="chronology",
                intent_id=intent.intent_id,
                intent_digest=intent.canonical_digest,
                response_digest=D("1"),
                usage_digest=D("1"),
                outcome=RecordOutcome.COMPLETE,
                observed_valid_at=T3,
                completed_at=T4,
                recorded_at=T4,
            ),
            recorded_at=T3,
        )
    with pytest.raises(EpochAuthorityError, match="missing response"):
        EffectResult(
            result_id="bad",
            intent_id=intent.intent_id,
            intent_digest=intent.canonical_digest,
            response_digest=None,
            usage_digest=D("1"),
            outcome=RecordOutcome.COMPLETE,
            observed_valid_at=T3,
            completed_at=T4,
            recorded_at=T4,
        )


def test_restart_requires_exact_predecessor_and_reason() -> None:
    first = _attempt()
    second = _attempt(
        attempt_id="attempt-2",
        ordinal=2,
        previous_attempt_digest=first.canonical_digest,
        restart_reason="LOST_RESPONSE_RECONCILED",
        started_at=T3,
    )
    assert second.previous_attempt_digest == first.canonical_digest
    with pytest.raises(EpochAuthorityError, match="restart reason"):
        replace(second, restart_reason=None)


def test_standalone_schema_rejects_production_or_contaminated_database() -> None:
    production = sqlite3.connect(":memory:", isolation_level=None)
    production.execute("PRAGMA user_version=32")
    with pytest.raises(Increment9ShadowMigrationError, match="production"):
        install_increment9_shadow_schema(production)
    contaminated = sqlite3.connect(":memory:", isolation_level=None)
    contaminated.execute("CREATE TABLE production_authority(id TEXT)")
    with pytest.raises(Increment9ShadowMigrationError, match="identity"):
        install_increment9_shadow_schema(contaminated)


def test_isolated_schema_identity_checksum_and_integrity_are_exact() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    install_increment9_shadow_schema(connection)
    verify_increment9_shadow_schema(connection)
    assert connection.execute("PRAGMA application_id").fetchone()[0] == INCREMENT9_SHADOW_APPLICATION_ID
    assert connection.execute("PRAGMA user_version").fetchone()[0] == INCREMENT9_SHADOW_SCHEMA_VERSION
    assert INCREMENT9_SHADOW_MIGRATION_CHECKSUM.startswith("sha256:")
    assert INCREMENT9_SHADOW_SCHEMA_FINGERPRINT.startswith("sha256:")
    connection.execute("DROP TRIGGER immutable_shadow_epoch_records")
    with pytest.raises(Increment9ShadowMigrationError, match="fingerprint"):
        verify_increment9_shadow_schema(connection)


def test_authority_enforces_persist_before_effect_and_exact_correlations() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    authority = initialise_shadow_epoch_authority(connection)
    epoch, manifest, cohort, run, attempt, intent, result, checkpoint, cost, outcome, closeout = _records()
    with pytest.raises(EpochAuthorityError, match="predecessor"):
        authority.append(result, epoch_id=epoch.epoch_id)
    for record in (epoch, manifest, cohort, run, attempt, intent, result, checkpoint, cost, outcome, closeout):
        authority.append(record, epoch_id=epoch.epoch_id)
    assert authority.read(result.canonical_digest) == result
    assert set(authority.inventory(epoch.epoch_id)) == {item.canonical_digest for item in _records()}
    rows = connection.execute(
        "SELECT record_schema,cohort_digest,run_id,attempt_id,sequence "
        "FROM shadow_epoch_records ORDER BY record_schema"
    ).fetchall()
    by_schema = {row[0]: row[1:] for row in rows}
    assert by_schema[EffectIntent.schema_version] == (
        cohort.canonical_digest,
        run.run_id,
        attempt.attempt_id,
        intent.sequence,
    )
    assert by_schema[CohortCloseout.schema_version] == (
        cohort.canonical_digest,
        None,
        None,
        None,
    )


def test_authority_rejects_orphan_manifest_stale_cohort_run_and_false_decision() -> None:
    orphan = initialise_shadow_epoch_authority(
        sqlite3.connect(":memory:", isolation_level=None)
    )
    with pytest.raises(EpochAuthorityError, match="predecessor"):
        orphan.append(_manifest(), epoch_id=_epoch().epoch_id)

    authority = initialise_shadow_epoch_authority(
        sqlite3.connect(":memory:", isolation_level=None)
    )
    epoch = _epoch()
    first_manifest = _manifest("a")
    first = _cohort(epoch, first_manifest)
    second_manifest = _manifest("b", resolved=False)
    second = _cohort(
        epoch,
        second_manifest,
        cohort_id="cohort-2",
        ordinal=2,
        previous_cohort_digest=first.canonical_digest,
        opened_at=T3,
    )
    for record in (epoch, first_manifest, first, second_manifest, second):
        authority.append(record, epoch_id=epoch.epoch_id)
    with pytest.raises(EpochAuthorityError, match="not current"):
        authority.append(_run(epoch, first, first_manifest), epoch_id=epoch.epoch_id)

    run = _run(epoch, second, second_manifest)
    attempt = _attempt(run)
    authority.append(run, epoch_id=epoch.epoch_id)
    authority.append(attempt, epoch_id=epoch.epoch_id)
    invalid = RunOutcome(
        outcome_id="false-decision",
        run_id=run.run_id,
        run_digest=run.canonical_digest,
        attempt_digest=attempt.canonical_digest,
        cohort_digest=second.canonical_digest,
        outcome=RecordOutcome.COMPLETE,
        evidence_inventory_digest=D("5"),
        production_nonmutation_after_digest=D("d"),
        decision_bearing=True,
        recorded_at=T4,
    )
    with pytest.raises(EpochAuthorityError, match="outcome binding"):
        authority.append(invalid, epoch_id=epoch.epoch_id)


def test_closeout_seals_epoch_and_authority_rechecks_schema_on_every_use() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    authority = initialise_shadow_epoch_authority(connection)
    records = _records()
    controller = ReplayController(authority)
    controller.replay(records, epoch_id=records[0].epoch_id)
    with pytest.raises(EpochAuthorityError, match="already closed out"):
        authority.append(_manifest("b"), epoch_id=records[0].epoch_id)
    connection.execute("DROP TRIGGER immutable_shadow_epoch_records")
    with pytest.raises(Increment9ShadowMigrationError, match="fingerprint"):
        authority.read(records[0].canonical_digest)
    with pytest.raises(Increment9ShadowMigrationError, match="fingerprint"):
        authority.inventory(records[0].epoch_id)


def test_authority_records_are_immutable_retained_and_idempotency_conflicts_fail() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    authority = initialise_shadow_epoch_authority(connection)
    epoch = _epoch()
    authority.append(epoch, epoch_id=epoch.epoch_id)
    with pytest.raises(EpochAuthorityError, match="append failed"):
        authority.append(epoch, epoch_id=epoch.epoch_id)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE shadow_epoch_records SET epoch_id='other'")
    with pytest.raises(sqlite3.IntegrityError, match="retained"):
        connection.execute("DELETE FROM shadow_epoch_records")


def test_two_authority_connections_serialize_and_reject_duplicate_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "increment9-shadow.sqlite3"
    first_connection = sqlite3.connect(path, isolation_level=None)
    first = initialise_shadow_epoch_authority(first_connection)
    second_connection = sqlite3.connect(path, isolation_level=None)
    second = ShadowEpochAuthority(second_connection)
    epoch = _epoch()
    first.append(epoch, epoch_id=epoch.epoch_id)
    with pytest.raises(EpochAuthorityError, match="append failed"):
        second.append(epoch, epoch_id=epoch.epoch_id)
    assert second.read(epoch.canonical_digest) == epoch


def test_authority_rejects_pre_cutoff_valid_time_for_prospective_result() -> None:
    authority = initialise_shadow_epoch_authority(
        sqlite3.connect(":memory:", isolation_level=None)
    )
    epoch, manifest, cohort, run, attempt, intent, result, *_ = _records()
    for record in (epoch, manifest, cohort, run, attempt, intent):
        authority.append(record, epoch_id=epoch.epoch_id)
    with pytest.raises(EpochAuthorityError, match="prospective cutoff"):
        authority.append(
            replace(result, observed_valid_at="2041-12-31T23:59:59.000000Z"),
            epoch_id=epoch.epoch_id,
        )


def test_replay_controller_replays_complete_ordered_fixture_without_effect() -> None:
    authority = initialise_shadow_epoch_authority(sqlite3.connect(":memory:", isolation_level=None))
    records = _records()
    controller = ReplayController(authority)
    observed = controller.replay(records, epoch_id=records[0].epoch_id)
    assert observed == tuple(record.canonical_digest for record in records)
    assert controller.authorises_live_call is False
    assert controller.authorises_external_egress is False
    assert controller.authorises_production_mutation is False


def test_every_record_and_authority_seam_has_no_external_effect_authority() -> None:
    authority = initialise_shadow_epoch_authority(sqlite3.connect(":memory:", isolation_level=None))
    for record in (*_records(), authority):
        assert record.authorises_live_call is False
        assert record.authorises_credentials is False
        assert record.authorises_external_egress is False
        assert record.authorises_spend is False
        assert record.authorises_publication is False
        assert record.authorises_production_mutation is False
