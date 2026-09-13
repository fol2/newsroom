"""One-pass retained/current Work Item validation within a constructor transaction."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from newsroom.increment5.retrieval_context import RetrievalContextJournal
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment6.work_items import (
    ContextLeadBinding, RetrievalContextAuthority, TriageWorkItem, TriageWorkItemStore,
    WorkItemContractError,
)
from newsroom.tests.test_increment6a2_work_items import (
    _authority_bytes, _decision, _store, _version,
)
from newsroom.tests.test_native_collision import _native_binding, _read_port


def _native_items(tmp_path, count, *, with_context_lead=False):
    decisions = tuple(_decision(index) for index in range(1, count + 1))
    contexts, bindings, reads = {}, {}, []
    for index, decision in enumerate(decisions):
        binding, receipt, context = _native_binding(
            tmp_path / f"native-{index}",
            SimpleNamespace(request=SimpleNamespace(lead_id=decision.lead_id),
                            canonical_digest=decision.lead_digest),
        )
        bindings[decision.lead_id] = binding
        contexts[receipt.context_id] = context
    port = _read_port(contexts)
    original_read = port._read

    def read(receipt):
        reads.append(receipt.context_id)
        return original_read(receipt)

    object.__setattr__(port, "_read", read)
    journal = RetrievalContextJournal(tmp_path / "retrieval.sqlite3")
    authority = RetrievalContextAuthority(
        journal.path, {}, native_context_read_port=port,
    )
    peer = _decision(50)
    connection, store = _store(
        decisions + ((peer,) if with_context_lead else ()),
        retrieval_authority=authority,
    )
    versions = []
    for decision in decisions:
        item = TriageWorkItem.create((decision,))
        version = replace(_version(item), retrieval=bindings[decision.lead_id])
        if with_context_lead:
            version = replace(version, context_leads=(ContextLeadBinding(
                peer.lead_id, peer.lead_digest, peer.lead_event_id,
                peer.lead_aggregate_version, peer.gate_decision_id,
                peer.definition_id, peer.definition_version_id,
            ),))
        assert store.create_or_replay(item, version) == version
        versions.append(version)
    reads.clear()
    return connection, authority, versions, contexts, reads


@pytest.mark.parametrize("heads", (1, 10))
def test_open_reads_each_current_usable_native_context_once(tmp_path, heads):
    connection, authority, versions, contexts, reads = _native_items(tmp_path, heads)
    try:
        for _ in range(2):
            reads.clear()
            TriageWorkItemStore(connection, retrieval_authority=authority)
            assert len(reads) == heads
            assert set(reads) == set(contexts)
            assert not connection.in_transaction
    finally:
        connection.close()


def _advance_disposition_head(connection):
    replacement = _decision(1, disposition=999)
    _, raw = _authority_bytes(replacement)
    connection.execute("INSERT INTO lead_disposition_decisions VALUES(?,?,?,?,?,?,?,?,?)", (
        replacement.disposition_id, digest_bytes(raw), replacement.disposition_outcome,
        raw, replacement.disposition_event_id, replacement.disposition_aggregate_version,
        replacement.disposition_ordinal, replacement.previous_disposition_id,
        replacement.lead_id,
    ))
    connection.execute(
        "UPDATE lead_disposition_heads SET current_decision_id=? WHERE lead_id=?",
        (replacement.disposition_id, replacement.lead_id),
    )


def test_stale_current_head_remains_valid_but_inactive(tmp_path):
    connection, authority, versions, _, reads = _native_items(tmp_path, 1)
    try:
        _advance_disposition_head(connection)
        store = TriageWorkItemStore(connection, retrieval_authority=authority)
        assert len(reads) == 1
        assessment = store.assess_current(versions[0].work_item_id)
        assert not assessment.current and not assessment.usable
        assert assessment.stale_reasons == (
            f"disposition:{versions[0].decision_leads[0].lead_id}",
        )
    finally:
        connection.close()


@pytest.mark.parametrize("fault", (
    "lead", "disposition", "context_lead", "missing_context",
    "context_binding", "context_read_failure", "missing_retrieval_authority",
    "receipt", "head_digest", "head_ordinal",
))
def test_stale_head_does_not_hide_retained_corruption(tmp_path, fault):
    connection, authority, versions, contexts, _ = _native_items(
        tmp_path, 1, with_context_lead=(fault == "context_lead"),
    )
    version = versions[0]
    try:
        _advance_disposition_head(connection)
        if fault in {"lead", "context_lead"}:
            lead = (version.context_leads if fault == "context_lead"
                    else version.decision_leads)[0]
            connection.execute(
                "UPDATE news_leads SET canonical_bytes=?,canonical_digest=? WHERE lead_id=?",
                (b"{}", digest_bytes(b"{}"), lead.lead_id),
            )
        elif fault == "disposition":
            connection.execute(
                "UPDATE lead_disposition_decisions SET canonical_bytes=?,canonical_digest=? "
                "WHERE decision_id=?",
                (b"{}", digest_bytes(b"{}"), version.decision_leads[0].disposition_id),
            )
        elif fault == "missing_context":
            contexts.clear()
        elif fault == "context_binding":
            key = version.retrieval.context_id
            contexts[key] = replace(contexts[key], request_digest=digest_bytes(b"other"))
        elif fault == "context_read_failure":
            def failed_read(_receipt):
                raise ValueError("retained governed context bytes differ")
            object.__setattr__(authority._native_context_read_port, "_read", failed_read)
        elif fault == "missing_retrieval_authority":
            authority = None
        elif fault == "receipt":
            value = json.loads(version.canonical_bytes)
            value["retrieval"]["receipt"] = {}
            raw = canonical_json_bytes(value)
            connection.execute("DROP TRIGGER immutable_triage_work_item_versions_update")
            connection.execute(
                "UPDATE triage_work_item_versions SET canonical_bytes=?,canonical_digest=? "
                "WHERE version_id=?", (raw, digest_bytes(raw), version.version_id),
            )
        else:
            connection.execute("DROP TRIGGER triage_work_item_head_forward_guard")
            column, value = (
                ("current_version_digest", digest_bytes(b"wrong-head"))
                if fault == "head_digest" else ("current_ordinal", 2)
            )
            connection.execute(f"UPDATE triage_work_item_heads SET {column}=?", (value,))
        with pytest.raises(WorkItemContractError):
            TriageWorkItemStore(connection, retrieval_authority=authority)
        assert not connection.in_transaction
    finally:
        connection.close()


def test_historical_versions_keep_independent_retained_validation(tmp_path):
    connection, authority, versions, contexts, reads = _native_items(tmp_path, 1)
    first = versions[0]
    try:
        store = TriageWorkItemStore(connection, retrieval_authority=authority)
        item = TriageWorkItem.create(first.decision_leads)
        second = replace(_version(item, 2), retrieval=first.retrieval)
        store.append_version(first.version_id, first.canonical_digest, second)
        reads.clear()
        TriageWorkItemStore(connection, retrieval_authority=authority)
        assert len(reads) == 2  # One historical and one current version, not three.
        contexts.clear()
        with pytest.raises(WorkItemContractError, match="retrieval"):
            TriageWorkItemStore(connection, retrieval_authority=authority)
    finally:
        connection.close()
