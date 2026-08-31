"""PreparedCanary is the unique pre-dispatch authority after #870."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from newsroom.control_plane import issue_790_disposition as disposition
from newsroom.control_plane.issue_790_prepared_canary import (
    CANDIDATE_EVENT_ID,
    CANDIDATE_LEDGER_SEQ,
    FAIL_BRANCH_INVENTORY,
    FIELD_CLASSIFICATION,
    PREPARED_CANARY_ABSENT,
    PREPARED_CANARY_DIGEST_DRIFT,
    PreparedCanaryError,
    consume_prepared_canary,
    prepare_issue_790_canary,
)
from newsroom.control_plane.issue_790_rehearsal import (
    RehearsalRealGraphitiAdapter,
    live_issue_790_store_paths,
    refuse_live_issue_790_store_paths,
    run_prepared_canary_rehearsal,
    sqlite_backup_copy,
)
from newsroom.tests.issue_790_rehearsal_fixtures import (
    EVENT_13361,
    EXACT_HEAD,
    LIVE_13361_AVAILABLE_AT,
    OBSERVED_AT,
    SEALED_13361_AVAILABLE_AT,
    build_rehearsal_stores,
    candidate_identity,
    dispatch_started_count,
    file_digest,
    mutate_retry_field,
    retry_available_at,
)

_TEST_FILE = Path(__file__)


def _prepare(stores, *, store=None, role="preflight", **kwargs):
    return prepare_issue_790_canary(
        store=store or stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        exact_head=EXACT_HEAD,
        role=role,
        **kwargs,
    )


def test_field_classification_keeps_available_at_as_audit_only() -> None:
    assert FIELD_CLASSIFICATION["available_at"] == "C"
    assert FIELD_CLASSIFICATION["exact_head"] == "A"
    assert FIELD_CLASSIFICATION["retry_safety_states"] == "B"
    assert FIELD_CLASSIFICATION["provider_response"] == "D"


def test_prepared_canary_accepts_13361_available_at_drift(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    assert retry_available_at(stores.work_unpublished, 13361) == LIVE_13361_AVAILABLE_AT
    sealed = next(
        item
        for item in stores.plan["retry_forbidden_events"]
        if item["ledger_seq"] == 13361
    )
    assert sealed["available_at"] == SEALED_13361_AVAILABLE_AT
    prepared = _prepare(stores)
    assert prepared.candidate_identity["event_id"] == CANDIDATE_EVENT_ID
    assert prepared.candidate_identity["ledger_seq"] == CANDIDATE_LEDGER_SEQ
    assert prepared.decision_digest.startswith("sha256:")
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID


def test_ready_digest_is_stable_for_unchanged_copy(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    first = _prepare(stores)
    second = _prepare(stores, role="canary")
    assert first.decision_digest == second.decision_digest
    assert first.as_decision_payload() == second.as_decision_payload()
    assert file_digest(stores.sealed_unpublished) == stores.sealed_digest
    assert file_digest(stores.work_unpublished) == stores.sealed_digest


def test_ready_implies_dispatch_started(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    before = file_digest(stores.work_unpublished)
    prepared = _prepare(stores)
    assert file_digest(stores.work_unpublished) == before
    result = run_prepared_canary_rehearsal(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        exact_head=EXACT_HEAD,
        prepared=prepared,
    )
    assert result["decision_digest"] == prepared.decision_digest
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) >= 1
    assert file_digest(stores.sealed_unpublished) == stores.sealed_digest
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID


def test_event_13665_identity_is_not_mutated(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    _prepare(stores)
    mutate_retry_field(
        stores.work_unpublished, ledger_seq=13361, field="state", value="QUEUED"
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"
    event_id, ledger_seq, _state = candidate_identity(stores.work_unpublished)
    assert event_id == CANDIDATE_EVENT_ID
    assert ledger_seq == CANDIDATE_LEDGER_SEQ
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("state", "QUEUED"),
        ("attempt_count", 2),
        ("provider_dispatched", 0),
        (
            "last_failure_code",
            "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:PRODUCER_INTERNAL_ERROR",
        ),
    ),
)
def test_exhausted_safety_mutation_fail_closes(
    tmp_path: Path, field: str, value: object
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    mutate_retry_field(
        stores.work_unpublished, ledger_seq=13361, field=field, value=value
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert candidate_identity(stores.work_unpublished)[0] == CANDIDATE_EVENT_ID


def test_claim_or_lease_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    mutate_retry_field(
        stores.work_unpublished,
        ledger_seq=13361,
        field="claim_owner",
        value="issue-790-canary:test",
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"


def test_candidate_claim_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    mutate_retry_field(
        stores.work_unpublished,
        ledger_seq=CANDIDATE_LEDGER_SEQ,
        field="claim_owner",
        value="issue-790-canary:test",
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "CANDIDATE_NOT_FRESH"


def test_alias_proving_live_paths_fail_close(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.work_unpublished,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            role="preflight",
        )
    assert caught.value.failure_code == "PATHS_ALIAS"


def test_missing_store_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=tmp_path / "missing.sqlite3",
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            role="preflight",
        )
    assert caught.value.failure_code == "STORE_ABSENT"


def test_missing_exact_head_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head="",
            role="preflight",
        )
    assert caught.value.failure_code == "EXACT_HEAD_ABSENT"


def test_retry_forbidden_target_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 16
    sequence.pop("candidate_event_qualification", None)
    plan["sequence"] = sequence
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            event_id=EVENT_13361,
            ledger_seq=13361,
            role="preflight",
        )
    assert caught.value.failure_code == "RETRY_FORBIDDEN_TARGET"


def test_unique_prepare_is_consumed_by_preflight_apply_and_canary() -> None:
    root = _TEST_FILE.resolve().parents[2]
    sources = (
        (root / "scripts/issue_790_live_canary_preflight.py").read_text(encoding="utf-8"),
        inspect.getsource(disposition._execute_issue_790_plan),
        inspect.getsource(disposition.run_issue_790_canary),
    )
    for source in sources:
        assert "prepare_issue_790_canary" in source
    definitions = [
        node
        for node in ast.parse(
            (
                root / "newsroom/control_plane/issue_790_prepared_canary.py"
            ).read_text(encoding="utf-8")
        ).body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_issue_790_canary"
    ]
    assert len(definitions) == 1


def test_event_identity_invalid_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 16
    sequence.pop("candidate_event_qualification", None)
    plan["sequence"] = sequence
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            event_id="not-a-digest",
            ledger_seq=2000,
            role="canary",
        )
    assert caught.value.failure_code == "EVENT_IDENTITY_INVALID"


def test_missing_prepared_canary_fail_closes_before_dispatch(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    with pytest.raises(PreparedCanaryError) as caught:
        run_prepared_canary_rehearsal(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            prepared=None,
        )
    assert caught.value.failure_code == PREPARED_CANARY_ABSENT
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert candidate_identity(stores.work_unpublished)[2] == "QUEUED"


def test_digest_drift_fail_closes_before_dispatch(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    prepared = _prepare(stores)
    mutate_retry_field(
        stores.work_unpublished, ledger_seq=13361, field="state", value="QUEUED"
    )
    with pytest.raises(PreparedCanaryError) as caught:
        run_prepared_canary_rehearsal(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            prepared=prepared,
        )
    assert caught.value.failure_code in {
        PREPARED_CANARY_DIGEST_DRIFT,
        "RETRY_FORBIDDEN_SAFETY_STATE",
    }
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert dispatch_started_count(stores.work_unpublished) == 0


def test_dispatch_before_crash_leaves_candidate_unconsumed(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    prepared = _prepare(stores)
    with pytest.raises(PreparedCanaryError) as caught:
        run_prepared_canary_rehearsal(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            prepared=prepared,
            crash_before_dispatch=True,
        )
    assert caught.value.failure_code == "REHEARSAL_CRASH_BEFORE_DISPATCH"
    event_id, ledger_seq, state = candidate_identity(stores.work_unpublished)
    assert event_id == CANDIDATE_EVENT_ID
    assert ledger_seq == CANDIDATE_LEDGER_SEQ
    assert state == "QUEUED"
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert RehearsalRealGraphitiAdapter.provider_calls == 0


def test_rehearsal_refuses_canonical_live_store_paths() -> None:
    forbidden = next(iter(live_issue_790_store_paths()))
    with pytest.raises(PreparedCanaryError) as caught:
        refuse_live_issue_790_store_paths(forbidden)
    assert caught.value.failure_code == "LIVE_STORE_WRITE_REFUSED"


def test_sqlite_backup_refuses_overwrite(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        sqlite_backup_copy(stores.sealed_unpublished, stores.work_unpublished)
    assert caught.value.failure_code == "LIVE_STORE_WRITE_REFUSED"


def test_canary_consumes_prepared_digest_only() -> None:
    source = inspect.getsource(disposition.run_issue_790_canary)
    pre_consume, _sep, _post = source.partition("_consume_issue_790_event")
    assert "prepare_issue_790_canary" in pre_consume
    assert "consume_prepared_canary" in pre_consume
    assert "_require_retry_events_unchanged" not in pre_consume
    assert "retry_forbidden_safety_states_match" not in pre_consume
    assert "validate_retry_forbidden_safety_state" not in pre_consume


def test_fail_branch_inventory_has_named_parity_tests() -> None:
    names = {
        node.name
        for node in ast.parse(_TEST_FILE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    for branch in FAIL_BRANCH_INVENTORY:
        assert branch.positive_test in names, branch.invariant
        assert branch.negative_test in names, branch.invariant
        assert branch.zero_provider_calls is True


def test_prepared_failure_codes_are_inventoried() -> None:
    module = (
        Path(__file__).resolve().parents[2]
        / "newsroom/control_plane/issue_790_prepared_canary.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    codes = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.isupper()
        and "_" in node.value
        and node.value
        not in {
            "UTC",
            "QUEUED",
            "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT",
            "DISABLED_BEFORE_PROVIDER_DISPATCH",
            "PREDISPATCH_BINDING_FAILURE",
        }
    }
    inventoried = {branch.failure_code for branch in FAIL_BRANCH_INVENTORY}
    named = {
        "PREPARED_CANARY_ABSENT",
        "PREPARED_CANARY_DIGEST_DRIFT",
        "EXACT_HEAD_ABSENT",
        "CANDIDATE_IDENTITY",
        "STORE_ABSENT",
        "PATHS_ALIAS",
        "RETRY_FORBIDDEN_SAFETY_STATE",
        "RETRY_FORBIDDEN_TARGET",
        "EVENT_IDENTITY_INVALID",
        "CANDIDATE_NOT_FRESH",
        "LIVE_STORE_WRITE_REFUSED",
        "REHEARSAL_CRASH_BEFORE_DISPATCH",
    }
    assert named <= inventoried
    assert named <= codes | inventoried


def test_canary_rehearsal_path_uses_run_issue_790_canary(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    prepared = _prepare(stores)
    result = disposition.run_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        backup_path=tmp_path / "unused-backup.sqlite3",
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        repository_root=tmp_path,
        event_id=CANDIDATE_EVENT_ID,
        ledger_seq=CANDIDATE_LEDGER_SEQ,
        disposition_digest="sha256:" + "cd" * 32,
        prepared=prepared,
        rehearsal=True,
        exact_head=EXACT_HEAD,
    )
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert consume_prepared_canary(prepared, expected=prepared) is prepared
