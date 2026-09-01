"""#790 Step 23 binds its qualified fresh event exactly."""

from __future__ import annotations

import sqlite3
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.control_plane import issue_790_canary as canary_module
from newsroom.control_plane import cycle as cycle_module
from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_contract as contract_module
from newsroom.control_plane import issue_790_disposition as disposition_module
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    Issue790DispositionError,
    _require_sequence_predecessor,
    issue_790_checked_approval,
    qualify_issue_790_candidate_event,
    seal_issue_790_step16_plan,
)
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_prepared_canary import (
    BOUNDED_CANARY_AUTHORITY_CONSUMED,
    PreparedCanaryError,
    _candidate_from_plan,
    prepare_issue_790_canary,
)
from newsroom.tests.test_issue_790_rehearsal_fixtures import (
    build_rehearsal_stores,
    insert_unused_queued_attempt_zero,
)

_EVENT_13696 = (
    "sha256:a50799d126f82a229e1630816ea27a0e3fff2731fee87b48c986bc0f9b51b7f2"
)
_EVENT_13702 = (
    "sha256:bf467ee5908bca49b84d8309cceb225503e627177e7065efefb0a54196e8ef15"
)
_UNRELATED_HIGHER_EVENT = "sha256:" + "f0" * 32
_STEP22_PLAN = "sha256:1a0711aad02e849e456293549e4f9b9a1b1100b7ba01603ca4dcf465a410c529"
_STEP22_ACTIVATION = "sha256:e6fe0a0f4eeaefc731071b550ea866979ebea1bf674ddfed42c57669bdbea310"
_OUTCOME_13696 = "sha256:6a3c9f19717104e42cda8ea5a06c692a99465a1e95104033e89d8fecf3151463"
_RECEIPT_13696 = "sha256:8a5c32f2e7327221e2fb082e0d25bc9530b4688a39ec9d6b193da49afaa1f9cc"
_ROOT = Path(__file__).resolve().parents[2]


def _causal_report() -> dict[str, object]:
    path = _ROOT / (
        "docs/operations/2026-09-01-issue-790-step-23-causal-report.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _reviewed_fix(report: dict[str, object]) -> dict[str, object]:
    assert report["report_digest"] == (
        "sha256:215355c6f247856ce141d40bc90fd3a30b4d05fc0af82bfa5e8119641f8fb3ae"
    )
    return json.loads(
        (
            _ROOT
            / "docs/operations/2026-09-01-issue-790-step-23-reviewed-fix-record.json"
        ).read_text(encoding="utf-8")
    )


def _pending23() -> dict[str, object]:
    pending = json.loads(
        (_ROOT / disposition_module.ISSUE_790_STEP23_PENDING_PLAN_PATH).read_text()
    )
    report = _causal_report()
    fix = _reviewed_fix(report)
    assert pending["sequence"]["predecessor_causal_report"] == report
    assert pending["sequence"]["reviewed_fix"] == fix

    checked = {
        "approved_by": "checked:issue-790-step23-sealer",
        "approval_reference": f"checked:{pending['canonical_digest']}",
        "approved_at": disposition_module.ISSUE_790_STEP23_CHECKED_APPROVED_AT,
        "scope": "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION",
    }
    candidate = deepcopy(pending)
    candidate["sequence"].pop("hold_comment", None)
    candidate["schema_version"] = contract_module.ISSUE_790_STEP16_CANDIDATE_SCHEMA
    candidate["plan_status"] = "CHECKED_CANDIDATE"
    candidate["approval"] = checked
    candidate.pop("canonical_digest", None)
    candidate["canonical_digest"] = digest_canonical(candidate)
    contract = contract_module.issue_790_checked_candidate_contract_for_pending(
        str(pending["canonical_digest"])
    )
    assert candidate["canonical_digest"] == contract.candidate_digest
    return pending


def _step23_predecessor_plan(**sequence_overrides: object) -> dict[str, object]:
    report = _causal_report()
    sequence: dict[str, object] = {
        "sequence_ordinal": 23,
        "constraint_change": "REVIEWED_NON_TIMEOUT_FIX",
        "predecessor": {
            "plan_digest": _STEP22_PLAN,
            "outcome_digest": _OUTCOME_13696,
            "event_id": _EVENT_13696,
            "ledger_seq": 13696,
        },
        "predecessor_causal_report": report,
        "reviewed_fix": _reviewed_fix(report),
        "predecessor_activation_digest": _STEP22_ACTIVATION,
        "predecessor_canary_receipt_digest": _RECEIPT_13696,
    }
    sequence.update(sequence_overrides)
    return {"sequence": sequence}


class _PredecessorRepository:
    def __init__(self, *, truthful: bool = True) -> None:
        self.truthful = truthful
        self.lookup: tuple[str, str, int] | None = None

    def existing_consumption(
        self, *, approved_plan_digest: str, event_id: str, ledger_seq: int
    ) -> dict[str, object]:
        self.lookup = (approved_plan_digest, event_id, ledger_seq)
        return {
            "approved_plan_digest": approved_plan_digest,
            "consumption_digest": "sha256:" + "3" * 64,
            "event_id": event_id,
            "ledger_seq": ledger_seq,
        }

    def existing_outcome(self, *, consumption_digest: str) -> dict[str, object]:
        assert consumption_digest == "sha256:" + "3" * 64
        return {
            "schema_version": "newsroom.issue-790.canary-outcome.v3",
            "outcome_digest": _OUTCOME_13696,
            "approved_plan_digest": _STEP22_PLAN,
            "event_id": _EVENT_13696,
            "ledger_seq": 13696,
            "retry_authorised": False,
            "result_class": (
                "TRUTHFUL_PROVIDER_SUCCESS"
                if self.truthful
                else "UNCLASSIFIED_NON_SUCCESS"
            ),
            "state_before_seal": "TERMINAL",
            "state_after_seal": "TERMINAL",
            "attempt_count": 1,
            "provider_dispatched": True,
            "process_result": {"state": "TERMINAL"},
            "causal_report": None,
        }


def test_step23_contract_is_the_only_registered_next_ordinal() -> None:
    assert contract_module.issue_790_owner_activated_sequence(23) is True
    assert contract_module.issue_790_owner_activated_sequence(24) is False
    contract = contract_module.issue_790_checked_candidate_contract_for_pending(
        contract_module.ISSUE_790_STEP23_PENDING_DIGEST
    )
    assert contract.sequence_ordinal == 23
    assert contract.candidate_event_id == _EVENT_13702
    assert contract.candidate_ledger_seq == 13702


def test_step23_reviewed_fix_and_pending_packet_bind_reviewed_head() -> None:
    report = _causal_report()
    fix = _reviewed_fix(report)
    fix_unsigned = {key: value for key, value in fix.items() if key != "record_digest"}
    pending = json.loads(
        (_ROOT / disposition_module.ISSUE_790_STEP23_PENDING_PLAN_PATH).read_text(
            encoding="utf-8"
        )
    )
    pending_unsigned = {
        key: value for key, value in pending.items() if key != "canonical_digest"
    }

    assert fix["reviewed_fix_revision"] == (
        "475497f00d6610c707a3237f7c6b1fccf2ad5665"
    )
    assert fix["corrected_red_revision"] == (
        "59d356368bc9df97841c4359d38333dc28123a97"
    )
    assert fix["review_receipt_digest"] == (
        "sha256:8e650bbde4c4518355fe54415c9a1e31e4728b70e855428ddc92e69f8a06a77a"
    )
    assert fix["provider_free_qualification_digest"] == (
        "sha256:6d5b861ea665c5959a20beae9eb663b0744caeefebf93bfcee8076a4c2f21b84"
    )
    assert fix["record_digest"] == digest_canonical(fix_unsigned)
    assert pending["canonical_digest"] == digest_canonical(pending_unsigned)
    assert pending["canonical_digest"] == contract_module.ISSUE_790_STEP23_PENDING_DIGEST
    assert pending["release"] == {
        "kind": "PENDING_OWNER_APPROVAL",
        "evidence": "REVIEWED_FIX_RECORD",
        "reviewed_fix_record_digest": fix["record_digest"],
        "merged_commit": "c0b60ad1a67b5380c6e83d36e880fd6c7fd7fc9c",
        "merged_tree": "ca2be4f677ec1490b2f2ddcbfcde44ea872f7706",
    }
    assert pending["sequence"]["candidate_event_preparation_digest"] == (
        "sha256:90ef3df005e95df3f0343ecd312d47859b4698387d8b27d91fb3abba2f3f650d"
    )


def test_step23_is_the_global_immutable_retry_frontier() -> None:
    current = disposition_module._RETRY_FORBIDDEN_EVENTS_CURRENT
    current_seqs = {
        int(item["ledger_seq"])
        for item in current
    }

    assert current == disposition_module._RETRY_FORBIDDEN_EVENTS_STEP23
    assert {13665, 13671, 13677, 13683, 13689, 13690, 13696}.issubset(
        current_seqs
    )
    assert disposition_module._RETRY_FORBIDDEN_LEDGER_SEQS == current_seqs
    assert max(current_seqs) == 13696
    assert 13702 not in current_seqs


@pytest.mark.parametrize(
    ("event_id", "ledger_seq"),
    tuple(
        (str(item["event_id"]), int(item["ledger_seq"]))
        for item in disposition_module._RETRY_FORBIDDEN_EVENTS_STEP23
        if int(item["ledger_seq"]) >= 13665
    ),
)
def test_step23_global_qualification_rejects_every_newly_spent_identity_before_store_open(
    tmp_path: Path, event_id: str, ledger_seq: int
) -> None:
    with pytest.raises(Issue790DispositionError, match="candidate event is forbidden"):
        qualify_issue_790_candidate_event(
            store=tmp_path / "missing.sqlite3",
            proving_store=tmp_path / "missing-proving.sqlite3",
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=datetime(2026, 9, 1, 1, 31, 53, tzinfo=UTC),
        )


def test_step23_global_qualification_allows_13702(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path.resolve() / "unpublished.sqlite3"
    proving_store = tmp_path.resolve() / "proving.sqlite3"
    Issue790CanaryRepository(str(store))
    with sqlite3.connect(proving_store) as connection:
        connection.execute("CREATE TABLE proving_fixture(value INTEGER)")
    preflight = {
        "event_id": _EVENT_13702,
        "ledger_seq": 13702,
        "event_manifest_digest": "sha256:" + "1" * 64,
        "resolved_units": [{"ingest_id": "ingest-13702"}],
        "provider_calls": 0,
        "store_mutations": 0,
    }
    preflight["evidence_digest"] = digest_canonical(preflight)
    monkeypatch.setattr(
        cycle_module,
        "qualify_fresh_graphiti_event",
        lambda **_values: preflight,
    )
    monkeypatch.setattr(
        canary_module,
        "validate_graphiti_canary_target_unused",
        lambda *_args, **_kwargs: None,
    )

    receipt = qualify_issue_790_candidate_event(
        store=store,
        proving_store=proving_store,
        event_id=_EVENT_13702,
        ledger_seq=13702,
        observed_at=datetime(2026, 9, 1, 1, 31, 53, tzinfo=UTC),
    )

    assert receipt["status"] == "READY_FOR_OWNER_PACKET"
    assert (receipt["event_id"], receipt["ledger_seq"]) == (_EVENT_13702, 13702)


def test_step23_exact_authority_drift_predecessor_is_accepted() -> None:
    repository = _PredecessorRepository()

    retained = _require_sequence_predecessor(
        repository,  # type: ignore[arg-type]
        plan=_step23_predecessor_plan(),
    )

    assert retained is not None
    assert repository.lookup == (_STEP22_PLAN, _EVENT_13696, 13696)
    assert retained["outcome"]["outcome_digest"] == _OUTCOME_13696


@pytest.mark.parametrize(
    "sequence_overrides",
    (
        {"sequence_ordinal": 22},
        {"predecessor_canary_receipt_digest": "sha256:" + "4" * 64},
        {
            "predecessor": {
                "plan_digest": _STEP22_PLAN,
                "outcome_digest": _OUTCOME_13696,
                "event_id": "sha256:" + "5" * 64,
                "ledger_seq": 13690,
            }
        },
    ),
)
def test_truthful_success_outside_exact_step23_boundary_is_rejected(
    sequence_overrides: dict[str, object],
) -> None:
    with pytest.raises(Issue790DispositionError):
        _require_sequence_predecessor(
            _PredecessorRepository(),  # type: ignore[arg-type]
            plan=_step23_predecessor_plan(**sequence_overrides),
        )


def test_step23_plan_selects_only_qualified_event_not_higher_unrelated_queue(
    tmp_path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_EVENT_13702,
        ledger_seq=13702,
    )
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_UNRELATED_HIGHER_EVENT,
        ledger_seq=13708,
    )
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 23
    sequence["candidate_event_qualification"] = {
        "schema_version": "newsroom.issue-790.candidate-event-qualification.v1",
        "status": "READY_FOR_OWNER_PACKET",
        "event_id": _EVENT_13702,
        "ledger_seq": 13702,
        "event_manifest_digest": (
            "sha256:3e3fb1143091b9e8f364a1db22503b803a859da098a67dcc36964cf1565f774b"
        ),
        "event_preflight_digest": (
            "sha256:22dda71d2a9ae6a6ef69a679b5662300ff9adf4c2263d2b7920f29a0defe5f7a"
        ),
        "resolved_unit_count": 1,
        "provider_calls": 0,
        "store_mutations": 0,
        "observed_at": "2026-09-01T01:31:53.722227Z",
        "qualification_digest": (
            "sha256:c1dca544d0de449d7a951d3673858ce7700e5271ad56a372ba0706a3fae6604c"
        ),
    }
    plan["sequence"] = sequence

    assert _candidate_from_plan(
        plan,
        event_id=None,
        ledger_seq=None,
        role="preflight",
        store=stores.work_unpublished,
    ) == (_EVENT_13702, 13702)
    assert _candidate_from_plan(
        plan,
        event_id=_EVENT_13702,
        ledger_seq=13702,
        role="canary",
        store=stores.work_unpublished,
    ) == (_EVENT_13702, 13702)
    with pytest.raises(PreparedCanaryError) as unrelated:
        _candidate_from_plan(
            plan,
            event_id=_UNRELATED_HIGHER_EVENT,
            ledger_seq=13708,
            role="canary",
            store=stores.work_unpublished,
        )
    assert unrelated.value.failure_code == "CANDIDATE_IDENTITY"


def test_step23_seal_and_provider_free_apply_preflight_bind_same_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending = _pending23()
    pre_dispatch = json.loads(
        (_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text(encoding="utf-8")
    )
    candidate = seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )
    stores = build_rehearsal_stores(tmp_path)
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_EVENT_13702,
        ledger_seq=13702,
    )
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_UNRELATED_HIGHER_EVENT,
        ledger_seq=13708,
    )
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute(
            "UPDATE unpublished_graphiti_revision_events SET manifest_digest=? "
            "WHERE event_id=? AND ledger_seq=?",
            (
                "sha256:3e3fb1143091b9e8f364a1db22503b803a859da098a67dcc36964cf1565f774b",
                _EVENT_13702,
                13702,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(
        disposition_module,
        "_require_retry_events_unchanged",
        lambda _store, plan: [dict(item) for item in plan["retry_forbidden_events"]],
    )
    preflight_evidence: dict[str, object] = {
        "schema_version": "newsroom.issue-790.iterative-fresh-event-preflight.v2",
        "event_id": _EVENT_13702,
        "ledger_seq": 13702,
        "event_state": "QUEUED",
        "event_attempt_count": 0,
        "event_manifest_digest": "sha256:3e3fb1143091b9e8f364a1db22503b803a859da098a67dcc36964cf1565f774b",
        "resolved_units": [],
        "rights_decision_digests": [],
        "owner_emergency_stop_clear": True,
        "provider_calls": 0,
        "store_mutations": 0,
        "evaluated_at": "2026-09-01T01:31:54.000000Z",
        "approved_plan_digest": candidate["canonical_digest"],
        "fallback_mode": "DISABLED_BEFORE_PROVIDER_DISPATCH",
        "fixed_constraints_digest": candidate["sequence"]["fixed_constraints_digest"],
    }
    preflight_evidence["evidence_digest"] = digest_canonical(preflight_evidence)
    monkeypatch.setattr(
        disposition_module,
        "_qualify_issue_790_event",
        lambda **_values: preflight_evidence,
    )

    prepared = [
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=candidate,
            observed_at=datetime(2026, 9, 1, 1, 31, 54, tzinfo=UTC),
            exact_head="1" * 40,
            role=role,
        )
        for role in ("preflight", "apply")
    ]
    assert {item.candidate_identity["event_id"] for item in prepared} == {
        _EVENT_13702
    }
    assert {item.candidate_identity["ledger_seq"] for item in prepared} == {13702}
    assert {item.plan_identity["pending_digest"] for item in prepared} == {
        contract_module.ISSUE_790_STEP23_PENDING_DIGEST
    }


def test_corrupt_consumption_schema_fails_closed(tmp_path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute("DROP TABLE issue_790_bounded_canary_consumptions")
        connection.execute(
            "CREATE TABLE issue_790_bounded_canary_consumptions(corrupt TEXT)"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(PreparedCanaryError) as caught:
        _candidate_from_plan(
            stores.plan,
            event_id=None,
            ledger_seq=None,
            role="preflight",
            store=stores.work_unpublished,
        )
    assert caught.value.failure_code == BOUNDED_CANARY_AUTHORITY_CONSUMED
    assert str(caught.value) == "bounded canary consumption authority schema differs"


def test_completed_consumption_exhausts_plan_before_dynamic_successor_selection(
    tmp_path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_UNRELATED_HIGHER_EVENT,
        ledger_seq=13702,
    )
    plan_digest = str(stores.plan["canonical_digest"])
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_consumptions VALUES(?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "11" * 32,
                plan_digest,
                "sha256:" + "22" * 32,
                _EVENT_13696,
                13696,
                "issue-790-canary:spent",
                "2026-09-01T01:00:00.000000Z",
                "{}",
            ),
        )
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_outcomes VALUES(?,?,?,?,?,?)",
            (
                "sha256:" + "33" * 32,
                "sha256:" + "11" * 32,
                _EVENT_13696,
                13696,
                "2026-09-01T01:01:00.000000Z",
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(PreparedCanaryError) as caught:
        _candidate_from_plan(
            stores.plan,
            event_id=None,
            ledger_seq=None,
            role="preflight",
            store=stores.work_unpublished,
        )
    assert caught.value.failure_code == BOUNDED_CANARY_AUTHORITY_CONSUMED


def test_consume_rejects_second_event_for_same_completed_plan(
    tmp_path, monkeypatch
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan_digest = str(stores.plan["canonical_digest"])
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_consumptions VALUES(?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "11" * 32,
                plan_digest,
                "sha256:" + "22" * 32,
                _EVENT_13696,
                13696,
                "issue-790-canary:spent",
                "2026-09-01T01:00:00.000000Z",
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(
        canary_module,
        "_require_effective_plan_contract",
        lambda *_args, **_kwargs: SimpleNamespace(invocation_id="invocation"),
    )

    repository = Issue790CanaryRepository.open_existing(
        str(stores.work_unpublished)
    )
    with pytest.raises(
        Issue790CanaryIntegrityError,
        match="bounded canary authority is already consumed",
    ):
        repository.consume(
            approved_plan_digest=plan_digest,
            disposition_digest="sha256:" + "44" * 32,
            event_id=_EVENT_13702,
            ledger_seq=13702,
            owner_id="issue-790-canary:successor",
            preflight_evidence={},
            consumed_at=datetime(2026, 9, 1, 1, 2, tzinfo=UTC),
        )
