from __future__ import annotations

import sqlite3
import uuid

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.triage_work_item_migrations import (
    TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS,
)
from newsroom.increment6.outcomes import (
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)
from newsroom.increment6.proposals import WorkItemBinding
from newsroom.increment6.work_items import (
    DecisionLeadBinding,
    RetrievalBindingState,
    RetrievalInputBinding,
    TriageWorkItem,
    TriageWorkItemStore,
    TriageWorkItemVersion,
    WorkItemContractError,
)


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
    request = canonical_json_bytes({"request_id": _id(number)})
    return RetrievalInputBinding(
        RetrievalBindingState.REQUEST_PENDING,
        _id(number),
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


def _store(
    decisions: tuple[DecisionLeadBinding, ...],
) -> tuple[sqlite3.Connection, TriageWorkItemStore]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE news_leads(lead_id TEXT PRIMARY KEY,signal_id TEXT,canonical_digest TEXT,canonical_bytes BLOB);
        CREATE TABLE discovery_gate_decision_heads(signal_id TEXT PRIMARY KEY,current_decision_id TEXT);
        CREATE TABLE source_definition_version_heads(definition_id TEXT PRIMARY KEY,current_version_id TEXT);
        CREATE TABLE lead_disposition_decisions(decision_id TEXT PRIMARY KEY,canonical_digest TEXT,outcome TEXT,canonical_bytes BLOB);
        CREATE TABLE lead_disposition_heads(lead_id TEXT PRIMARY KEY,current_decision_id TEXT);
        CREATE TABLE discovery_watch_conditions(watch_condition_id TEXT PRIMARY KEY,canonical_digest TEXT);
        """
    )
    for statement in TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS:
        connection.execute(statement)
    for index, decision in enumerate(decisions):
        signal = f"signal-{index}"
        connection.execute(
            "INSERT INTO news_leads VALUES(?,?,?,?)",
            (decision.lead_id, signal, decision.lead_digest, decision.lead_bytes),
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
            "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?)",
            (
                decision.disposition_id,
                decision.disposition_digest,
                decision.disposition_outcome,
                decision.disposition_bytes,
            ),
        )
        connection.execute(
            "INSERT INTO lead_disposition_heads VALUES(?,?)",
            (decision.lead_id, decision.disposition_id),
        )
    return connection, TriageWorkItemStore(connection)


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
        "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?)",
        (_id(777), "sha256:" + "7" * 64, "LEAD_OPERATIONAL_HOLD", b"{}"),
    )
    replacement = _decision(1, disposition=999)
    connection.execute(
        "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?)",
        (
            replacement.disposition_id,
            replacement.disposition_digest,
            replacement.disposition_outcome,
            replacement.disposition_bytes,
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
