from __future__ import annotations

import sqlite3
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.triage_work_item_migrations import (
    TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS,
)
from newsroom.discovery import LeadDispositionDecisionId, LeadDispositionOutcome
from newsroom.increment6.outcomes import (
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)
from newsroom.increment6.proposals import WorkItemBinding
from newsroom.increment6.work_items import (
    DecisionLeadBinding,
    ReentryKind,
    RetrievalBindingState,
    RetrievalContextAuthority,
    RetrievalInputBinding,
    TriageWorkItem,
    TriageWorkItemStore,
    TriageWorkItemVersion,
    WatchConditionWorkItemBinding,
    WorkItemContractError,
)
from newsroom.tests import test_increment5d1_hybrid_composer as composer_helpers
from newsroom.tests import test_increment5d2_retrieval_context as retrieval_helpers
from newsroom.tests.check_3c_authority_helpers import proof
from newsroom.tests.discovery_3d_authority_helpers import (
    exact_admission_request,
    open_discovery_system,
    seed_check_lineage,
)
from newsroom.tests.discovery_3d_helpers import disposition_request, watch_request


def _id(number: int) -> str:
    return str(uuid.UUID(int=number))


def _decision(number: int, *, disposition: int | None = None) -> DecisionLeadBinding:
    lead_id = _id(number)
    gate_id = _id(number + 100)
    definition_id = _id(number + 200)
    definition_version_id = _id(number + 300)
    disposition_id = _id(number + 400 if disposition is None else disposition)
    lead = canonical_json_bytes(
        {
            "definition_id": definition_id,
            "definition_version_id": definition_version_id,
            "lead_id": lead_id,
            "promoting_gate_decision_id": gate_id,
        }
    )
    decision = canonical_json_bytes(
        {
            "decision_id": disposition_id,
            "decision_ordinal": 1,
            "lead_id": lead_id,
            "outcome": "LEAD_QUEUED_FOR_TRIAGE",
            "previous_decision_id": None,
        }
    )
    return DecisionLeadBinding(
        lead_id,
        digest_bytes(lead),
        _id(number + 500),
        1,
        gate_id,
        definition_id,
        definition_version_id,
        disposition_id,
        digest_bytes(decision),
        _id(number + 600),
        1,
        1,
        None,
        "LEAD_QUEUED_FOR_TRIAGE",
        lead,
        decision,
    )


def _pending(number: int = 900) -> RetrievalInputBinding:
    key = f"retrieval-{number}"
    request = canonical_json_bytes({"idempotency_key": key, "request_id": _id(number)})
    return RetrievalInputBinding(
        RetrievalBindingState.REQUEST_PENDING,
        _id(number),
        key,
        digest_bytes(request),
        request,
    )


def _version(item: TriageWorkItem, ordinal: int = 1) -> TriageWorkItemVersion:
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|{ordinal}"))
    previous = (
        None
        if ordinal == 1
        else str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|{ordinal - 1}"))
    )
    priority = PrioritySelection(
        item.work_item_id,
        version_id,
        PriorityLane.ROUTINE,
        (ReasonReference("fixture", "basis"),),
    )
    return TriageWorkItemVersion.create(
        work_item_id=item.work_item_id,
        ordinal=ordinal,
        previous_version_id=previous,
        decision_leads=item.decision_leads,
        context_leads=(),
        retrieval=_pending(),
        priority=priority,
    )


def test_identity_is_permutation_invariant_but_scope_and_initial_queue_sensitive() -> (
    None
):
    first, second = _decision(1), _decision(2)
    a = TriageWorkItem.create((first, second))
    b = TriageWorkItem.create((second, first))
    assert a == b
    assert TriageWorkItem.create((first,)).work_item_id != a.work_item_id
    changed = _decision(1, disposition=999)
    assert TriageWorkItem.create((changed, second)).work_item_id != a.work_item_id


def test_version_identity_ordinal_priority_backrefs_and_proposal_compatibility() -> (
    None
):
    item = TriageWorkItem.create((_decision(1),))
    first = _version(item)
    second = _version(item, 2)
    assert first.version_id != second.version_id
    assert second.previous_version_id == first.version_id
    assert second.proposal_binding == WorkItemBinding(
        item.work_item_id, second.version_id, second.canonical_digest
    )
    assert TriageWorkItemVersion.from_canonical_bytes(second.canonical_bytes) == second


def test_wrong_deterministic_predecessor_and_priority_backref_fail_closed() -> None:
    item = TriageWorkItem.create((_decision(1),))
    first = _version(item)
    with pytest.raises(WorkItemContractError, match="predecessor"):
        TriageWorkItemVersion(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|2")),
            item.work_item_id,
            2,
            _id(42),
            item.decision_leads,
            (),
            _pending(),
            first.priority,
        )


def test_parser_rejects_duplicate_unknown_noncanonical_and_deep_input() -> None:
    item = TriageWorkItem.create((_decision(1),))
    with pytest.raises(WorkItemContractError, match="duplicate"):
        TriageWorkItem.from_canonical_bytes(b'{"a":1,"a":2}')
    with pytest.raises(WorkItemContractError):
        TriageWorkItem.from_canonical_bytes(item.canonical_bytes[:-1] + b',"x":1}')
    deep = b'{"a":' * 40 + b"null" + b"}" * 40
    with pytest.raises(WorkItemContractError, match="structural"):
        TriageWorkItem.from_canonical_bytes(deep)


def test_public_parser_rejects_bool_ordinal_and_enum_or_boolean_coercion() -> None:
    item = TriageWorkItem.create((_decision(1),))
    version = _version(item)
    with pytest.raises(WorkItemContractError, match="ordinal"):
        replace(version, ordinal=True)
    retrieval = version.retrieval.canonical_value()
    retrieval["state"] = "NOT_A_STATE"
    with pytest.raises(WorkItemContractError, match="state"):
        RetrievalInputBinding.from_value(retrieval)
    retrieval = version.retrieval.canonical_value()
    retrieval["no_match"] = 0
    with pytest.raises(WorkItemContractError, match="boolean"):
        RetrievalInputBinding.from_value(retrieval)


def _store(
    decisions: tuple[DecisionLeadBinding, ...],
    *,
    retrieval_authority: RetrievalContextAuthority | None = None,
) -> tuple[sqlite3.Connection, TriageWorkItemStore]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE news_leads(lead_id TEXT PRIMARY KEY,signal_id TEXT,canonical_digest TEXT,canonical_bytes BLOB,authority_event_id TEXT,authority_aggregate_version INTEGER);
        CREATE TABLE discovery_gate_decision_heads(signal_id TEXT PRIMARY KEY,current_decision_id TEXT);
        CREATE TABLE source_definition_version_heads(definition_id TEXT PRIMARY KEY,current_version_id TEXT);
        CREATE TABLE lead_disposition_decisions(decision_id TEXT PRIMARY KEY,canonical_digest TEXT,outcome TEXT,canonical_bytes BLOB,authority_event_id TEXT,authority_aggregate_version INTEGER,decision_ordinal INTEGER,previous_decision_id TEXT,lead_id TEXT);
        CREATE TABLE lead_disposition_heads(lead_id TEXT PRIMARY KEY,current_decision_id TEXT);
        CREATE TABLE discovery_watch_conditions(watch_condition_id TEXT PRIMARY KEY,canonical_digest TEXT);
        """
    )
    for statement in TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS:
        connection.execute(statement)
    for index, decision in enumerate(decisions):
        signal = f"signal-{index}"
        connection.execute(
            "INSERT INTO news_leads VALUES(?,?,?,?,?,?)",
            (
                decision.lead_id,
                signal,
                decision.lead_digest,
                decision.lead_bytes,
                decision.lead_event_id,
                decision.lead_aggregate_version,
            ),
        )
        connection.execute(
            "INSERT INTO discovery_gate_decision_heads VALUES(?,?)",
            (signal, decision.gate_decision_id),
        )
        connection.execute(
            "INSERT OR REPLACE INTO source_definition_version_heads VALUES(?,?)",
            (decision.definition_id, decision.definition_version_id),
        )
        connection.execute(
            "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                decision.disposition_id,
                decision.disposition_digest,
                decision.disposition_outcome,
                decision.disposition_bytes,
                decision.disposition_event_id,
                decision.disposition_aggregate_version,
                decision.disposition_ordinal,
                decision.previous_disposition_id,
                decision.lead_id,
            ),
        )
        connection.execute(
            "INSERT INTO lead_disposition_heads VALUES(?,?)",
            (decision.lead_id, decision.disposition_id),
        )
    return connection, TriageWorkItemStore(
        connection, retrieval_authority=retrieval_authority
    )


def test_store_exact_replay_cas_stale_and_active_overlap() -> None:
    decision, peer = _decision(1), _decision(2)
    connection, store = _store((decision, peer))
    item = TriageWorkItem.create((decision,))
    first = _version(item)
    assert store.create_or_replay(item, first) == first
    assert store.create_or_replay(item, first) == first
    second = _version(item, 2)
    assert (
        store.append_version(first.version_id, first.canonical_digest, second) == second
    )
    assert store.create_or_replay(item, first) == first
    assert (
        store.append_version(first.version_id, first.canonical_digest, second) == second
    )
    with pytest.raises(WorkItemContractError, match="stale expected"):
        store.append_version(
            first.version_id, first.canonical_digest, _version(item, 3)
        )

    competing = TriageWorkItem.create((decision, peer))
    with pytest.raises(WorkItemContractError, match="overlap"):
        store.create_or_replay(competing, _version(competing))

    connection.execute(
        "UPDATE lead_disposition_heads SET current_decision_id=?", (_id(777),)
    )
    connection.execute(
        "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?,?,?,?,?,?)",
        (
            _id(777),
            "sha256:" + "7" * 64,
            "LEAD_OPERATIONAL_HOLD",
            b"{}",
            _id(778),
            1,
            2,
            decision.disposition_id,
            decision.lead_id,
        ),
    )
    replacement = _decision(1, disposition=999)
    connection.execute(
        "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?,?,?,?,?,?)",
        (
            replacement.disposition_id,
            replacement.disposition_digest,
            replacement.disposition_outcome,
            replacement.disposition_bytes,
            replacement.disposition_event_id,
            replacement.disposition_aggregate_version,
            replacement.disposition_ordinal,
            replacement.previous_disposition_id,
            replacement.lead_id,
        ),
    )
    connection.execute(
        "UPDATE lead_disposition_heads SET current_decision_id=?",
        (replacement.disposition_id,),
    )
    # The stale old scope does not permanently monopolise its Lead.
    replacement_item = TriageWorkItem.create((replacement,))
    assert (
        store.create_or_replay(
            replacement_item, _version(replacement_item)
        ).work_item_id
        == replacement_item.work_item_id
    )


def test_actual_retrieval_journal_is_exact_indexed_and_tamper_or_purge_fails(
    tmp_path,
) -> None:
    inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    (
        _builder,
        _composer,
        _cas_root,
        _journal,
        journal_path,
        request,
        receipt,
        _content,
    ) = retrieval_helpers._retained_complete_context(
        tmp_path, inputs, name="work-item-authority"
    )
    journal_connection = sqlite3.connect(journal_path)
    unrelated = [
        (
            f"unrelated-{index}",
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            b"{}",
        )
        for index in range(1025)
    ]
    journal_connection.executemany(
        "INSERT INTO increment5d2_retrieval_contexts VALUES(?,?,?,?)",
        unrelated,
    )
    journal_connection.commit()
    journal_connection.close()

    authority = RetrievalContextAuthority(
        journal_path,
        lambda digest: (request, receipt) if digest == request.request_digest else None,
    )
    decision = _decision(1)
    wrong_journal = retrieval_helpers.RetrievalContextJournal(
        tmp_path / "wrong-context.sqlite3"
    )
    wrong_authority = RetrievalContextAuthority(
        wrong_journal.path,
        lambda _digest: (request, receipt),
    )
    _, wrong_store = _store((decision,), retrieval_authority=wrong_authority)
    wrong_item = TriageWorkItem.create((decision,))
    wrong_version = replace(
        _version(wrong_item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    with pytest.raises(WorkItemContractError, match="retrieval"):
        wrong_store.create_or_replay(wrong_item, wrong_version)

    connection, store = _store((decision,), retrieval_authority=authority)
    item = TriageWorkItem.create((decision,))
    original = _version(item)
    version = replace(
        original,
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    assert store.create_or_replay(item, version) == version
    assert store.require_usable_current(item.work_item_id) == version

    connection.execute(
        "UPDATE retrieval_authority.increment5d2_retrieval_contexts "
        "SET receipt_bytes=? WHERE idempotency_key=?",
        (b"{}", request.idempotency_key),
    )
    with pytest.raises(WorkItemContractError, match="retrieval"):
        store.require_usable_current(item.work_item_id)
    connection.execute(
        "UPDATE retrieval_authority.increment5d2_retrieval_contexts "
        "SET receipt_bytes=? WHERE idempotency_key=?",
        (receipt.canonical_bytes, request.idempotency_key),
    )
    connection.execute(
        "INSERT INTO retrieval_authority.increment5d2_retrieval_context_purges "
        "VALUES(?,?,?,?,?,?)",
        (
            _id(4000),
            request.idempotency_key,
            request.request_digest,
            receipt.receipt_digest,
            "sha256:" + "3" * 64,
            b"{}",
        ),
    )
    with pytest.raises(WorkItemContractError, match="retrieval"):
        store.require_usable_current(item.work_item_id)


def test_sql_successor_scope_retarget_is_rejected() -> None:
    decision, peer = _decision(1), _decision(2)
    connection, store = _store((decision, peer))
    item = TriageWorkItem.create((decision,))
    first = _version(item)
    store.create_or_replay(item, first)
    second = _version(item, 2)
    store.append_version(first.version_id, first.canonical_digest, second)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE triage_work_item_versions SET decision_scope_digest=? "
            "WHERE version_id=?",
            ("sha256:" + "9" * 64, second.version_id),
        )

    third_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|3"))
    retargeted = TriageWorkItemVersion.create(
        work_item_id=item.work_item_id,
        ordinal=3,
        previous_version_id=second.version_id,
        decision_leads=(peer,),
        context_leads=(),
        retrieval=_pending(),
        priority=PrioritySelection(
            item.work_item_id,
            third_id,
            PriorityLane.ROUTINE,
            (ReasonReference("fixture", "retarget"),),
        ),
    )
    connection.execute(
        "INSERT INTO triage_work_item_versions VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            retargeted.version_id,
            retargeted.schema_identity,
            retargeted.work_item_id,
            retargeted.ordinal,
            retargeted.previous_version_id,
            item.decision_scope_digest,
            retargeted.retrieval.state.value,
            retargeted.canonical_bytes,
            retargeted.canonical_digest,
            "1970-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "UPDATE triage_work_item_heads SET current_version_id=?,current_ordinal=?,"
        "current_version_digest=? WHERE work_item_id=?",
        (
            retargeted.version_id,
            3,
            retargeted.canonical_digest,
            item.work_item_id,
        ),
    )
    with pytest.raises(WorkItemContractError, match="retained bytes"):
        TriageWorkItemStore(connection)


def test_two_connection_lost_response_replays_survive_restart(tmp_path) -> None:
    decision = _decision(1)
    seed, _ = _store((decision,))
    database = tmp_path / "work-items.sqlite3"
    target = sqlite3.connect(database)
    seed.backup(target)
    target.close()
    seed.close()

    first_connection = sqlite3.connect(database, isolation_level=None)
    second_connection = sqlite3.connect(database, isolation_level=None)
    first_store = TriageWorkItemStore(first_connection)
    second_store = TriageWorkItemStore(second_connection)
    item = TriageWorkItem.create((decision,))
    first = _version(item)
    assert first_store.create_or_replay(item, first) == first
    assert second_store.create_or_replay(item, first) == first
    second = _version(item, 2)
    assert (
        first_store.append_version(first.version_id, first.canonical_digest, second)
        == second
    )
    assert (
        second_store.append_version(first.version_id, first.canonical_digest, second)
        == second
    )
    first_connection.close()
    second_connection.close()
    restarted_connection = sqlite3.connect(database, isolation_level=None)
    restarted = TriageWorkItemStore(restarted_connection)
    assert restarted.create_or_replay(item, first) == first
    assert restarted.current_version(item.work_item_id) == second
    restarted_connection.close()


def test_watch_reentry_requires_exact_causal_successor_and_matching_condition(
    tmp_path,
) -> None:
    database = tmp_path / "watch-authority.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        admitted = system.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=proof()
        )
        assert admitted.lead is not None and admitted.initial_disposition is not None
        initial = DecisionLeadBinding.from_authority(
            admitted.lead, admitted.initial_disposition
        )
        connection = sqlite3.connect(database, isolation_level=None)
        store = TriageWorkItemStore(connection)
        item = TriageWorkItem.create((initial,))
        first = _version(item)
        store.create_or_replay(item, first)

        watch_request_value = replace(
            watch_request(),
            resume_transition_kinds=(),
            expected_occurrence=None,
            idempotency_key="fixture-timer-watch",
        )
        watch = system.discovery.record_watch_condition(
            watch_request_value, proof=proof()
        )
        deferred_request = replace(
            disposition_request(outcome=LeadDispositionOutcome.WATCH_DEFER),
            decision_id=LeadDispositionDecisionId.parse(
                "00000000-0000-4000-8000-000000008199"
            ),
            previous_decision_id=admitted.initial_disposition.request.decision_id,
            idempotency_key="fixture-timer-watch-defer",
        )
        deferred = system.discovery.record_lead_disposition(
            deferred_request, proof=proof()
        )
        queued_request = replace(
            disposition_request(),
            decision_id=LeadDispositionDecisionId.parse(
                "00000000-0000-4000-8000-000000008200"
            ),
            decision_ordinal=3,
            previous_decision_id=deferred.request.decision_id,
            idempotency_key="fixture-timer-watch-requeue",
        )
        queued = system.discovery.record_lead_disposition(queued_request, proof=proof())
        target = DecisionLeadBinding.from_authority(admitted.lead, queued)
        watch_binding = WatchConditionWorkItemBinding.from_authority(watch, deferred)
        second_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|2"))
        priority = PrioritySelection(
            item.work_item_id,
            second_id,
            PriorityLane.ROUTINE,
            (ReasonReference("fixture", "watch-reentry"),),
        )
        second = TriageWorkItemVersion.create(
            work_item_id=item.work_item_id,
            ordinal=2,
            previous_version_id=first.version_id,
            decision_leads=(target,),
            context_leads=(),
            retrieval=_pending(),
            priority=priority,
            watch=watch_binding,
            reentry_kind=ReentryKind.REVIEW,
        )
        assert (
            store.append_version(first.version_id, first.canonical_digest, second)
            == second
        )
        with pytest.raises(WorkItemContractError, match="typed"):
            replace(second, reentry_kind="REVIEW")
        with pytest.raises(WorkItemContractError, match="condition"):
            replace(second, reentry_kind=ReentryKind.OPERATOR_CONDITION)
        connection.close()
