"""#790 Step 17 successor authority is a new family; Step 16 stays exhausted."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.control_plane import issue_790_contract as issue_790_contract_module
from newsroom.control_plane.cycle import (
    consume_next_graphiti_event,
    qualify_fresh_graphiti_event,
)
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.graphiti import GraphitiCycleResult
from newsroom.control_plane.graphiti_events import graphiti_unit_binding_reason
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PENDING_PLAN_PATH,
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    ISSUE_790_STEP17_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _require_approved_plan,
    activate_issue_790_step16_plan,
    issue_790_checked_approval,
    issue_790_step16_checked_approval,
    qualify_issue_790_candidate_event,
    seal_issue_790_step16_plan,
    validate_issue_790_plan,
    validate_issue_790_step16_candidate,
)
from newsroom.tests.test_graphiti_corpus_ingest import _complete
from newsroom.tests.test_graphiti_event_consumer import (
    MutableClock,
    _EVENT_8835_LANDED_INGEST_ID,
    _binding_event,
    _projected_zero_ref_event,
    _rewrite_landed_ingest_ids,
    _unit,
)
from newsroom.tests.test_issue_790_step16_activation import (
    _COMMENT_ID,
    _FakeGitHub,
    _comment,
    _payload,
)

_ROOT = Path(__file__).resolve().parents[2]
_STEP17_COMMENT_ID = _COMMENT_ID + 17
_EVENT_8835 = (
    "sha256:2c6941748dce73271a0d4aae2e94766384d0dd16bc29707524f74b8026d7c3b9"
)


def _pre_dispatch() -> dict[str, object]:
    return json.loads((_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text())


def _seal16() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP16_PENDING_PLAN_PATH).read_text())
    return seal_issue_790_step16_plan(
        pending,
        issue_790_step16_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=_pre_dispatch(),
    )


def _seal17() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP17_PENDING_PLAN_PATH).read_text())
    return seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=_pre_dispatch(),
    )


def _activate(candidate: dict[str, object], tmp_path: Path, comment_id: int):
    payload = _payload(candidate, final_correction_pr=848)
    comment = _comment(payload)
    comment["id"] = comment_id
    comment["html_url"] = (
        f"https://github.com/fol2/newsroom/issues/790#issuecomment-{comment_id}"
    )
    comment["url"] = (
        "https://api.github.com/repos/fol2/newsroom/issues/comments/"
        f"{comment_id}"
    )
    store = tmp_path / "authority.sqlite"
    return activate_issue_790_step16_plan(
        candidate,
        comment_id=comment_id,
        pre_dispatch=_pre_dispatch(),
        store=store,
        github_api=_FakeGitHub(comment),
    ) | {"store": store, "candidate": candidate}


def test_successor_checked_candidate_is_a_new_identity() -> None:
    candidate16 = _seal16()
    candidate17 = _seal17()
    validate_issue_790_step16_candidate(candidate16)
    validate_issue_790_step16_candidate(candidate17)
    assert candidate16["canonical_digest"] == (
        issue_790_contract_module.ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST
    )
    assert candidate17["canonical_digest"] == (
        issue_790_contract_module.ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST
    )
    assert candidate17["canonical_digest"] != candidate16["canonical_digest"]
    assert candidate17["sequence"]["sequence_ordinal"] == 17
    assert candidate17["sequence"]["predecessor"]["plan_digest"] == (
        issue_790_contract_module.ISSUE_790_STEP16_ACTIVATED_PLAN_DIGEST
    )
    assert candidate17["sequence"]["predecessor_activation_digest"] == (
        issue_790_contract_module.ISSUE_790_STEP16_ACTIVATION_DIGEST
    )
    assert [item["ledger_seq"] for item in candidate17["retry_forbidden_events"]] == [
        1932,
        1972,
        8835,
    ]
    assert candidate17["executable"] is False
    assert candidate17["live_canary_authorised"] is False
    contract = issue_790_contract_module.issue_790_checked_candidate_contract(
        candidate17["canonical_digest"]
    )
    assert contract.sequence_ordinal == 17
    with pytest.raises(KeyError):
        issue_790_contract_module.issue_790_approved_plan_contract(
            candidate17["canonical_digest"]
        )
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        _require_approved_plan(candidate17)


def test_step16_sealer_and_payload_cannot_reuse_successor_family(
    tmp_path: Path,
) -> None:
    pending17 = json.loads((_ROOT / ISSUE_790_STEP17_PENDING_PLAN_PATH).read_text())
    with pytest.raises(Issue790DispositionError, match="checked approval"):
        seal_issue_790_step16_plan(
            pending17,
            issue_790_step16_checked_approval(str(pending17["canonical_digest"])),
            pre_dispatch=_pre_dispatch(),
        )
    candidate16 = _seal16()
    candidate17 = _seal17()
    with pytest.raises(Issue790DispositionError):
        activate_issue_790_step16_plan(
            candidate17,
            comment_id=_COMMENT_ID,
            pre_dispatch=_pre_dispatch(),
            store=tmp_path / "cross-17.sqlite",
            github_api=_FakeGitHub(_comment(_payload(candidate16))),
        )
    with pytest.raises(Issue790DispositionError):
        activate_issue_790_step16_plan(
            candidate16,
            comment_id=_COMMENT_ID,
            pre_dispatch=_pre_dispatch(),
            store=tmp_path / "cross-16.sqlite",
            github_api=_FakeGitHub(_comment(_payload(candidate17))),
        )


def test_step16_and_step17_activations_coexist_and_are_single_use(
    tmp_path: Path,
) -> None:
    first16 = _activate(_seal16(), tmp_path, _COMMENT_ID)
    first17 = _activate(_seal17(), tmp_path, _STEP17_COMMENT_ID)
    assert first16["activation"]["activation_digest"] != (
        first17["activation"]["activation_digest"]
    )
    assert first16["plan"]["canonical_digest"] != first17["plan"]["canonical_digest"]
    assert first16["plan"]["sequence"]["sequence_ordinal"] == 16
    assert first17["plan"]["sequence"]["sequence_ordinal"] == 17
    assert first16["plan"]["canary"]["fallback_mode"] == (
        "DISABLED_BEFORE_PROVIDER_DISPATCH"
    )
    assert first17["plan"]["canary"]["fresh_provider_backed_attempt_count"] == 1
    assert first17["plan"]["sequence"]["owner_activation"]["caps"]["retry_cap"] == 0
    assert first17["plan"]["sequence"]["owner_activation"]["caps"]["fallback_cap"] == 0
    connection = Issue790CanaryRepository(str(first16["store"]))._connection()
    try:
        rows = connection.execute(
            "SELECT checked_candidate_digest FROM issue_790_step16_activations "
            "ORDER BY comment_id"
        ).fetchall()
    finally:
        connection.close()
    assert [str(row[0]) for row in rows] == [
        issue_790_contract_module.ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST,
        issue_790_contract_module.ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST,
    ]


def test_event_8835_cannot_be_selected_for_canary(tmp_path: Path) -> None:
    store = tmp_path / "canary.sqlite"
    Issue790CanaryRepository(str(store))
    repository = Issue790CanaryRepository.open_existing(str(store))
    with pytest.raises(Issue790CanaryIntegrityError, match="retained failure"):
        repository.consume(
            approved_plan_digest="sha256:" + "ab" * 32,
            disposition_digest="sha256:" + "cd" * 32,
            event_id=_EVENT_8835,
            ledger_seq=8835,
            owner_id="issue-790-canary:test",
            preflight_evidence={},
            consumed_at=datetime(2026, 8, 29, tzinfo=UTC),
        )


def test_landed_resolved_mismatch_holds_before_ready() -> None:
    unit = _unit(1)
    event = _binding_event(
        unit,
        landed_ingest_ids=(_EVENT_8835_LANDED_INGEST_ID,),
        unit_refs=(),
        expected_unit_count=0,
    )
    assert (
        graphiti_unit_binding_reason(event, (unit,))
        == "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED"
    )


def test_successor_qualify_and_live_gate_share_binding_policy(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, unpublished, event_id, ledger_seq = _projected_zero_ref_event(
        tmp_path, clock
    )
    evidence = qualify_fresh_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        event_id=event_id,
        ledger_seq=ledger_seq,
        clock=clock,
    )
    assert evidence["provider_calls"] == 0
    assert evidence["resolved_units"]

    class FixtureGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return _complete(unit)

    ready = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=FixtureGraphiti(),
        owner_id="worker",
        clock=clock,
        event_id=event_id,
        require_fresh=True,
        recover_model_usage=False,
    )
    assert ready is not None and ready.state == "TERMINAL"

    mismatch_root = tmp_path / "mismatch"
    mismatch_root.mkdir()
    proving2, unpublished2, event_id2, ledger_seq2 = _projected_zero_ref_event(
        mismatch_root, clock
    )
    _rewrite_landed_ingest_ids(
        unpublished2, event_id2, (_EVENT_8835_LANDED_INGEST_ID,)
    )
    with pytest.raises(ValueError, match="RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED"):
        qualify_fresh_graphiti_event(
            proving_store=str(proving2),
            unpublished_store=str(unpublished2),
            event_id=event_id2,
            ledger_seq=ledger_seq2,
            clock=clock,
        )

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(f"provider boundary reached for {unit.ingest_id}")

    held = consume_next_graphiti_event(
        proving_store=str(proving2),
        unpublished_store=str(unpublished2),
        graphiti=MustNotDispatch(),
        owner_id="worker",
        clock=clock,
        event_id=event_id2,
        require_fresh=True,
        recover_model_usage=False,
    )
    assert held is not None and held.state == "RIGHTS_HELD"


def test_candidate_qualification_precedes_owner_packet_and_rejects_step17_shape(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, unpublished, event_id, ledger_seq = _projected_zero_ref_event(
        tmp_path, clock
    )
    Issue790CanaryRepository(str(unpublished))
    receipt = qualify_issue_790_candidate_event(
        store=unpublished,
        proving_store=proving,
        event_id=event_id,
        ledger_seq=ledger_seq,
        observed_at=clock.value,
    )
    assert receipt["status"] == "READY_FOR_OWNER_PACKET"
    assert receipt["event_id"] == event_id
    assert receipt["ledger_seq"] == ledger_seq
    assert receipt["resolved_unit_count"] > 0
    assert receipt["provider_calls"] == 0
    assert receipt["store_mutations"] == 0

    _rewrite_landed_ingest_ids(
        unpublished,
        event_id,
        (_EVENT_8835_LANDED_INGEST_ID,),
    )
    with pytest.raises(
        Issue790DispositionError,
        match="selected event is not provider-free ready: "
        "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED",
    ):
        qualify_issue_790_candidate_event(
            store=unpublished,
            proving_store=proving,
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=clock.value,
        )


def test_candidate_qualification_rejects_consumed_event_which_still_looks_fresh(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, unpublished, event_id, ledger_seq = _projected_zero_ref_event(
        tmp_path, clock
    )
    repository = Issue790CanaryRepository(str(unpublished))
    connection = repository._connection()
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_consumptions("
            "consumption_digest,approved_plan_digest,disposition_digest,event_id,"
            "ledger_seq,owner_id,consumed_at,record_json) VALUES(?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "11" * 32,
                "sha256:" + "22" * 32,
                "sha256:" + "33" * 32,
                event_id,
                ledger_seq,
                "issue-790-canary:test",
                "2026-08-20T00:00:00.000000Z",
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(Issue790DispositionError, match="already consumed"):
        qualify_issue_790_candidate_event(
            store=unpublished,
            proving_store=proving,
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=clock.value,
        )


def test_candidate_qualification_rejects_prior_execution_evidence(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, unpublished, event_id, ledger_seq = _projected_zero_ref_event(
        tmp_path, clock
    )
    Issue790CanaryRepository(str(unpublished))
    connection = sqlite3.connect(str(unpublished))
    try:
        connection.execute(
            "CREATE TABLE model_work_envelopes("
            "envelope_id TEXT,cycle_id TEXT,workload_class TEXT,"
            "reservation_id TEXT,record_json TEXT)"
        )
        connection.execute(
            "INSERT INTO model_work_envelopes("
            "envelope_id,cycle_id,workload_class,reservation_id,record_json) "
            "VALUES(?,?,?,?,?)",
            (
                "sha256:" + "44" * 32,
                event_id,
                "GRAPHITI_CHAT_PRIMARY",
                "sha256:" + "55" * 32,
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(Issue790DispositionError, match="prior execution evidence"):
        qualify_issue_790_candidate_event(
            store=unpublished,
            proving_store=proving,
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=clock.value,
        )


def test_candidate_qualification_requires_disjoint_store_files(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, _, event_id, ledger_seq = _projected_zero_ref_event(tmp_path, clock)
    with pytest.raises(Issue790DispositionError, match="operation paths alias"):
        qualify_issue_790_candidate_event(
            store=proving,
            proving_store=proving,
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=clock.value,
        )


def test_operator_can_qualify_candidate_before_activation(tmp_path: Path) -> None:
    from scripts import issue_790_conservative_disposition as cli

    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, unpublished, event_id, ledger_seq = _projected_zero_ref_event(
        tmp_path, clock
    )
    Issue790CanaryRepository(str(unpublished))
    receipt_path = tmp_path / "candidate-event-qualification.json"
    assert (
        cli.main(
            [
                "qualify-event",
                "--store",
                str(unpublished),
                "--proving-store",
                str(proving),
                "--canary-event-id",
                event_id,
                "--canary-ledger-seq",
                str(ledger_seq),
                "--observed-at",
                clock.value.isoformat(),
                "--receipt",
                str(receipt_path),
            ]
        )
        == 0
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "READY_FOR_OWNER_PACKET"
    assert receipt["event_id"] == event_id
    assert receipt["provider_calls"] == 0


def test_historical_step16_and_step15_remain_replayable() -> None:
    candidate16 = _seal16()
    validate_issue_790_step16_candidate(candidate16)
    step15 = json.loads(
        (
            _ROOT / "docs/operations/2026-08-28-issue-790-success-sequence-step-15.json"
        ).read_text()
    )
    validate_issue_790_plan(step15)
    assert step15["sequence"]["sequence_ordinal"] == 15
    assert candidate16["sequence"]["sequence_ordinal"] == 16
