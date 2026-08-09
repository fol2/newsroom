from __future__ import annotations

import sqlite3
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.triage_work_item_migrations import (
    TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS,
)
from newsroom.discovery import (
    DiscoveryContractError,
    DiscoverySignalId,
    GateDecisionId,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLead,
    NewsLeadId,
    SignalLeadAdmissionRequest,
)
from newsroom.increment6.outcomes import (
    OutcomeContractError,
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)
from newsroom.increment5._retrieval_context_core import _retrieval_context_purge_id
from newsroom.increment5.retrieval_context import (
    RetrievalContextPurgeReceipt,
    RetrievalContextRequest,
)
from newsroom.increment6.work_items import (
    ContextLeadBinding,
    DecisionLeadBinding,
    ReentryKind,
    RetrievalBindingState,
    RetrievalContextAuthority,
    RetrievalInputBinding,
    SupplementalDiscoveryReentry,
    SupplementalLineageBinding,
    TriageWorkItem,
    TriageWorkItemStore,
    TriageWorkItemVersion,
    WatchConditionWorkItemBinding,
    WorkItemPriorityBinding,
    WorkItemContractError,
)
from newsroom.sources import SourceDependency, SourceDependencyKind
from newsroom.sources import SourceDefinitionId, SourceDefinitionVersionId
from newsroom.tests import test_increment5d1_hybrid_composer as composer_helpers
from newsroom.tests import test_increment5d2_retrieval_context as retrieval_helpers
from newsroom.tests.check_3c_authority_helpers import proof
from newsroom.tests.check_3c_helpers import OUTCOME_ID, REQUEST_ID
from newsroom.tests.discovery_3d_authority_helpers import (
    exact_admission_request,
    open_discovery_system,
    seed_check_lineage,
)
from newsroom.tests.discovery_3d_helpers import disposition_request, watch_request


def _id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


def _decision(number: int, *, disposition: int | None = None) -> DecisionLeadBinding:
    lead_id = _id(number)
    gate_id = _id(number + 100)
    definition_id = _id(number + 200)
    definition_version_id = _id(number + 300)
    disposition_id = _id(number + 400 if disposition is None else disposition)
    base = exact_admission_request()
    lead = replace(
        base.lead,
        lead_id=NewsLeadId.parse(lead_id),
        promoting_gate_decision_id=GateDecisionId.parse(gate_id),
        definition_id=SourceDefinitionId.parse(definition_id),
        definition_version_id=SourceDefinitionVersionId.parse(
            definition_version_id
        ),
    )
    decision = replace(
        base.initial_disposition,
        decision_id=LeadDispositionDecisionId.parse(disposition_id),
        lead_id=NewsLeadId.parse(lead_id),
        gate_decision_id=GateDecisionId.parse(gate_id),
    )
    return DecisionLeadBinding(
        lead_id,
        lead.digest,
        _id(number + 500),
        1,
        gate_id,
        definition_id,
        definition_version_id,
        disposition_id,
        decision.digest,
        _id(number + 600),
        1,
        1,
        None,
        "LEAD_QUEUED_FOR_TRIAGE",
    )


def _authority_bytes(
    decision: DecisionLeadBinding,
) -> tuple[bytes, bytes]:
    base = exact_admission_request()
    lead = replace(
        base.lead,
        lead_id=NewsLeadId.parse(decision.lead_id),
        promoting_gate_decision_id=GateDecisionId.parse(decision.gate_decision_id),
        definition_id=SourceDefinitionId.parse(decision.definition_id),
        definition_version_id=SourceDefinitionVersionId.parse(
            decision.definition_version_id
        ),
    )
    disposition = replace(
        base.initial_disposition,
        decision_id=LeadDispositionDecisionId.parse(decision.disposition_id),
        lead_id=NewsLeadId.parse(decision.lead_id),
        gate_decision_id=GateDecisionId.parse(decision.gate_decision_id),
    )
    return lead.canonical_bytes, disposition.canonical_bytes


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


def test_version_identity_ordinal_and_compact_priority_backrefs() -> (
    None
):
    item = TriageWorkItem.create((_decision(1),))
    first = _version(item)
    second = _version(item, 2)
    assert first.version_id != second.version_id
    assert second.previous_version_id == first.version_id
    assert second.priority.work_identity == item.work_item_id
    assert second.priority.work_version == second.version_id
    assert second.priority.basis_count == 1
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
    with pytest.raises(WorkItemContractError, match="Priority Selection must be typed"):
        TriageWorkItemVersion.create(
            work_item_id=item.work_item_id,
            ordinal=1,
            previous_version_id=None,
            decision_leads=item.decision_leads,
            context_leads=(),
            retrieval=_pending(),
            priority=first.priority,  # type: ignore[arg-type]
        )
    with pytest.raises(WorkItemContractError, match="compact binding"):
        replace(first.priority, basis_digest=digest_bytes(b"forged basis"))
    value = first.priority.canonical_value()
    value["selection_digest"] = digest_bytes(b"forged selection")
    with pytest.raises(WorkItemContractError, match="digest"):
        WorkItemPriorityBinding.from_value(value)


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
    huge_integer = b'{"value":' + b"9" * 5000 + b"}"
    with pytest.raises(WorkItemContractError, match="invalid"):
        TriageWorkItem.from_canonical_bytes(huge_integer)
    with pytest.raises(WorkItemContractError, match="aggregate_version"):
        replace(item.decision_leads[0], lead_aggregate_version=True)


def test_public_boundaries_normalise_nested_type_and_canonical_failures() -> None:
    item = TriageWorkItem.create((_decision(1),))
    version = _version(item)
    with pytest.raises(WorkItemContractError):
        TriageWorkItem.create(1)  # type: ignore[arg-type]
    with pytest.raises(WorkItemContractError):
        TriageWorkItemVersion.create(
            work_item_id=item.work_item_id,
            ordinal=1,
            previous_version_id=None,
            decision_leads=item.decision_leads,
            context_leads=1,  # type: ignore[arg-type]
            retrieval=version.retrieval,
            priority=version.priority,
        )
    with pytest.raises(WorkItemContractError, match="Priority"):
        replace(version, priority=1)  # type: ignore[arg-type]
    with pytest.raises(WorkItemContractError, match="typed"):
        RetrievalInputBinding.request_pending(object())  # type: ignore[arg-type]
    with pytest.raises(WorkItemContractError, match="authority"):
        ContextLeadBinding.from_authority(object())  # type: ignore[arg-type]
    with pytest.raises(WorkItemContractError, match="typed Work Item"):
        connection, store = _store(item.decision_leads)
        try:
            store.create_or_replay(object(), version)  # type: ignore[arg-type]
        finally:
            connection.close()
    object.__setattr__(version, "priority", object())
    with pytest.raises(WorkItemContractError, match="fields"):
        _ = version.canonical_bytes

    value = _version(item).canonical_value()
    value["decision_leads"] = 1
    with pytest.raises(WorkItemContractError, match="sequence"):
        TriageWorkItemVersion.from_canonical_bytes(canonical_json_bytes(value))
    value = _version(item).canonical_value()
    value["priority"] = 1
    with pytest.raises(WorkItemContractError, match="Priority"):
        TriageWorkItemVersion.from_canonical_bytes(canonical_json_bytes(value))
    with pytest.raises(WorkItemContractError, match="float"):
        TriageWorkItem.from_canonical_bytes(b'{"value":1.5}')
    with pytest.raises(WorkItemContractError, match="immutable bytes"):
        TriageWorkItem.from_canonical_bytes(type("Raw", (bytes,), {})(b"{}"))
    with pytest.raises(WorkItemContractError, match="fields"):
        RetrievalInputBinding.from_value(type("Values", (dict,), {})())
    with pytest.raises(WorkItemContractError, match="authority record"):
        ContextLeadBinding.from_authority(object.__new__(NewsLead))
    with pytest.raises(WorkItemContractError, match="positive integer"):
        replace(
            item.decision_leads[0],
            lead_aggregate_version=2**63,
        )

    class DecisionSubclass(DecisionLeadBinding):
        pass

    subclass = DecisionSubclass(
        **{
            name: getattr(item.decision_leads[0], name)
            for name in DecisionLeadBinding.__dataclass_fields__
        }
    )
    with pytest.raises(WorkItemContractError, match="typed tuple"):
        TriageWorkItem.create((subclass,))
    with pytest.raises(WorkItemContractError):
        TriageWorkItem.create((object.__new__(DecisionLeadBinding),))
    with pytest.raises(WorkItemContractError):
        RetrievalInputBinding.request_pending(
            object.__new__(RetrievalContextRequest)
        )
    with pytest.raises(WorkItemContractError):
        WorkItemPriorityBinding.from_selection(object.__new__(PrioritySelection))
    with pytest.raises(WorkItemContractError, match="nested bindings"):
        replace(
            _version(item),
            priority=object.__new__(WorkItemPriorityBinding),
        )
    watch_value = {
        "watch_condition_id": _id(1),
        "watch_condition_digest": digest_bytes(b"watch"),
        "lead_id": _id(2),
        "watch_event_id": _id(3),
        "watch_aggregate_version": 1,
        "source_disposition_id": _id(4),
        "source_disposition_digest": digest_bytes(b"source"),
        "source_disposition_ordinal": 1,
        "source_previous_disposition_id": None,
        "source_disposition_event_id": _id(5),
        "source_disposition_aggregate_version": 1,
        "allowed_reentry_kinds": [object()],
        "observable_transition": False,
    }
    with pytest.raises(WorkItemContractError, match="exact text"):
        WatchConditionWorkItemBinding.from_value(watch_value)

    class EvilStr(str):
        def encode(self, *args, **kwargs):
            raise RuntimeError("hostile string")

    with pytest.raises(WorkItemContractError):
        replace(item.decision_leads[0], lead_id=EvilStr(item.decision_leads[0].lead_id))


def test_maximum_news_lead_dependency_envelope_round_trips(tmp_path) -> None:
    dependencies = tuple(
        SourceDependency(
            f"dependency-{index:03d}",
            SourceDependencyKind.OTHER,
            "x" * 2_048,
        )
        for index in range(160)
    )
    database = tmp_path / "maximum-lead.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        admitted = system.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=proof()
        )
        assert admitted.lead is not None and admitted.initial_disposition is not None
        request = replace(admitted.lead.request, source_dependencies=dependencies)
        lead = replace(
            admitted.lead,
            request=request,
            canonical_digest=request.digest,
        )
        binding = DecisionLeadBinding.from_authority(
            lead, admitted.initial_disposition
        )
        item = TriageWorkItem.create((binding,))
        assert len(item.canonical_bytes) < 32 * 1_024
        assert TriageWorkItem.from_canonical_bytes(item.canonical_bytes) == item
        assert TriageWorkItemVersion.from_canonical_bytes(
            _version(item).canonical_bytes
        ) == _version(item)


def test_maximum_lead_scopes_and_priority_envelope_round_trip() -> None:
    decisions = tuple(_decision(index) for index in range(1, 33))
    contexts = tuple(
        ContextLeadBinding(
            value.lead_id,
            value.lead_digest,
            value.lead_event_id,
            value.lead_aggregate_version,
            value.gate_decision_id,
            value.definition_id,
            value.definition_version_id,
        )
        for value in (_decision(index) for index in range(33, 65))
    )
    item = TriageWorkItem.create(decisions)
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|1"))
    references = tuple(
        ReasonReference("fixture", f"priority-{index:05d}")
        for index in range(256)
    )
    version = TriageWorkItemVersion.create(
        work_item_id=item.work_item_id,
        ordinal=1,
        previous_version_id=None,
        decision_leads=decisions,
        context_leads=contexts,
        retrieval=_pending(),
        priority=PrioritySelection(
            item.work_item_id,
            version_id,
            PriorityLane.ROUTINE,
            references,
        ),
    )
    assert TriageWorkItemVersion.from_canonical_bytes(version.canonical_bytes) == version
    with pytest.raises(WorkItemContractError, match="exceeds Work Item bound"):
        TriageWorkItemVersion.create(
            work_item_id=item.work_item_id,
            ordinal=1,
            previous_version_id=None,
            decision_leads=decisions,
            context_leads=contexts,
            retrieval=_pending(),
            priority=PrioritySelection(
                item.work_item_id,
                version_id,
                PriorityLane.ROUTINE,
                references + (ReasonReference("fixture", "priority-over-bound"),),
            ),
        )


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
        lead_bytes, disposition_bytes = _authority_bytes(decision)
        connection.execute(
            "INSERT INTO news_leads VALUES(?,?,?,?,?,?)",
            (
                decision.lead_id,
                signal,
                digest_bytes(lead_bytes),
                lead_bytes,
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
                digest_bytes(disposition_bytes),
                decision.disposition_outcome,
                disposition_bytes,
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
    # Pending retrieval is auditable but unusable, so it does not monopolise scope.
    assert store.create_or_replay(competing, _version(competing))

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
    _, replacement_disposition_bytes = _authority_bytes(replacement)
    connection.execute(
        "INSERT INTO lead_disposition_decisions VALUES(?,?,?,?,?,?,?,?,?)",
        (
            replacement.disposition_id,
            digest_bytes(replacement_disposition_bytes),
            replacement.disposition_outcome,
            replacement_disposition_bytes,
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


def test_direct_unusable_overlap_does_not_brick_restart(tmp_path) -> None:
    decision, peer = _decision(1), _decision(2)
    connection, store = _store((decision, peer))
    item = TriageWorkItem.create((decision,))
    first = _version(item)
    store.create_or_replay(item, first)
    competing = TriageWorkItem.create((decision, peer))
    competing_version = _version(competing)
    connection.execute(
        "INSERT INTO triage_work_items VALUES(?,?,?,?,?,?,?)",
        (
            competing.work_item_id,
            competing.schema_identity,
            competing.decision_scope_digest,
            2,
            competing.canonical_bytes,
            competing.canonical_digest,
            "1970-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO triage_work_item_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            competing_version.version_id,
            competing_version.schema_identity,
            competing.work_item_id,
            1,
            None,
            competing.decision_scope_digest,
            competing_version.retrieval.state.value,
            None,
            None,
            competing_version.canonical_bytes,
            competing_version.canonical_digest,
            "1970-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO triage_work_item_heads VALUES(?,?,?,?,?)",
        (
            competing.work_item_id,
            competing_version.version_id,
            1,
            competing_version.canonical_digest,
            "1970-01-01T00:00:00Z",
        ),
    )
    database = tmp_path / "overlap.sqlite3"
    target = sqlite3.connect(database)
    connection.backup(target)
    target.close()
    connection.close()
    reopened = sqlite3.connect(database, isolation_level=None)
    restarted = TriageWorkItemStore(reopened)
    assert restarted.current_version(item.work_item_id) == first
    reopened.close()


def test_actual_retrieval_journal_is_exact_indexed_and_tamper_or_purge_fails(
    tmp_path,
) -> None:
    inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    (
        builder,
        composer,
        cas_root,
        _journal,
        journal_path,
        request,
        receipt,
        _content,
    ) = retrieval_helpers._retained_complete_context(
        tmp_path, inputs, name="work-item-authority"
    )
    missing_builder = retrieval_helpers._builder(
        tmp_path, name="missing", composer=composer, cas_root=cas_root
    )
    missing_builder.journal.path.unlink()
    with pytest.raises(WorkItemContractError, match="absent"):
        RetrievalContextAuthority(
            missing_builder.journal.path,
            {request.request_digest: (request, receipt)},
        )
    journal_connection = sqlite3.connect(journal_path)
    unrelated = [
        (
            f"unrelated-{index}",
            "sha256:" + "1" * 64,
            digest_bytes(b"{}"),
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
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    with pytest.raises(WorkItemContractError, match="records"):
        RetrievalContextAuthority(
            builder.journal.path,
            type("Records", (dict,), {})(
                {request.request_digest: (request, receipt)}
            ),
        )
    decision, peer = _decision(1), _decision(2)
    wrong_journal = retrieval_helpers.RetrievalContextJournal(
        tmp_path / "wrong-context.sqlite3"
    )
    wrong_builder = retrieval_helpers.RetrievalContextBuilder(
        composition_replayer=composer,
        journal=wrong_journal,
        hydrator=builder.hydrator,
    )
    wrong_authority = RetrievalContextAuthority(
        wrong_builder.journal.path,
        {request.request_digest: (request, receipt)},
    )
    _, wrong_store = _store((decision,), retrieval_authority=wrong_authority)
    wrong_item = TriageWorkItem.create((decision,))
    wrong_version = replace(
        _version(wrong_item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    with pytest.raises(WorkItemContractError, match="retrieval"):
        wrong_store.create_or_replay(wrong_item, wrong_version)
    pending_authority = RetrievalContextAuthority(
        wrong_builder.journal.path,
        {request.request_digest: (request, None)},
    )
    pending_connection, pending_store = _store(
        (decision,), retrieval_authority=pending_authority
    )
    pending_item = TriageWorkItem.create((decision,))
    pending_version = replace(
        _version(pending_item),
        retrieval=RetrievalInputBinding.request_pending(request),
    )
    assert pending_store.create_or_replay(pending_item, pending_version) == (
        pending_version
    )
    with pytest.raises(WorkItemContractError, match="retrieval_not_complete"):
        pending_store.require_usable_current(pending_item.work_item_id)
    source_journal = sqlite3.connect(builder.journal.path)
    completed_row = source_journal.execute(
        "SELECT * FROM increment5d2_retrieval_contexts WHERE idempotency_key=?",
        (request.idempotency_key,),
    ).fetchone()
    source_journal.close()
    assert completed_row is not None
    pending_connection.execute(
        "INSERT INTO retrieval_authority.increment5d2_retrieval_contexts "
        "VALUES(?,?,?,?)",
        completed_row,
    )
    completed_authority = RetrievalContextAuthority(
        wrong_builder.journal.path,
        {request.request_digest: (request, receipt)},
    )
    completed_store = TriageWorkItemStore(
        pending_connection, retrieval_authority=completed_authority
    )
    completed_version = replace(
        _version(pending_item, 2),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    assert completed_store.append_version(
        pending_version.version_id,
        pending_version.canonical_digest,
        completed_version,
    ) == completed_version
    assert completed_store.require_usable_current(pending_item.work_item_id) == (
        completed_version
    )
    pending_database = tmp_path / "pending-work-items.sqlite3"
    pending_target = sqlite3.connect(pending_database)
    pending_connection.backup(pending_target)
    pending_target.close()
    pending_connection.close()
    restarted_pending_connection = sqlite3.connect(
        pending_database, isolation_level=None
    )
    restarted_pending = TriageWorkItemStore(
        restarted_pending_connection, retrieval_authority=completed_authority
    )
    assert restarted_pending.current_version(pending_item.work_item_id) == (
        completed_version
    )
    restarted_pending_connection.close()

    connection, store = _store((decision, peer), retrieval_authority=authority)
    item = TriageWorkItem.create((decision,))
    original = _version(item)
    version = replace(
        original,
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    assert store.create_or_replay(item, version) == version
    assert store.require_usable_current(item.work_item_id) == version

    claim_database = tmp_path / "atomic-claim.sqlite3"
    claim_seed = sqlite3.connect(claim_database)
    connection.backup(claim_seed)
    claim_seed.execute(
        "CREATE TABLE simulated_claims(work_item_id TEXT PRIMARY KEY,version_id TEXT)"
    )
    claim_seed.commit()
    claim_seed.close()
    claim_one = sqlite3.connect(claim_database, isolation_level=None, timeout=0)
    claim_two = sqlite3.connect(claim_database, isolation_level=None, timeout=0)
    claim_store_one = TriageWorkItemStore(claim_one, retrieval_authority=authority)
    claim_store_two = TriageWorkItemStore(claim_two, retrieval_authority=authority)
    with pytest.raises(WorkItemContractError, match="active transaction"):
        claim_store_one.require_usable_current_in_transaction(item.work_item_id)
    claim_one.execute("BEGIN IMMEDIATE")
    checked = claim_store_one.require_usable_current_in_transaction(item.work_item_id)
    claim_one.execute(
        "INSERT INTO simulated_claims VALUES(?,?)",
        (item.work_item_id, checked.version_id),
    )
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        claim_two.execute("BEGIN IMMEDIATE")
    claim_one.execute("COMMIT")
    claim_two.execute("BEGIN IMMEDIATE")
    assert (
        claim_store_two.require_usable_current_in_transaction(item.work_item_id)
        == version
    )
    claim_two.execute("ROLLBACK")
    claim_one.close()
    claim_two.close()

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
        "DELETE FROM retrieval_authority.increment5d2_retrieval_contexts "
        "WHERE idempotency_key LIKE 'unrelated-%'"
    )
    purges = builder.journal.purge_affected(
        admission_ids=(receipt.items[0].passage.admission_id,),
        reason_code="RIGHTS_WITHDRAWN",
    )
    assert purges
    with pytest.raises(WorkItemContractError, match="retrieval"):
        store.require_usable_current(item.work_item_id)

    (
        _fresh_builder,
        _fresh_composer,
        _fresh_cas,
        _fresh_journal,
        fresh_journal_path,
        fresh_request,
        fresh_receipt,
        _fresh_content,
    ) = retrieval_helpers._retained_complete_context(
        tmp_path, inputs, name="work-item-fresh"
    )
    fresh_connection = sqlite3.connect(fresh_journal_path)
    fresh_row = fresh_connection.execute(
        "SELECT * FROM increment5d2_retrieval_contexts WHERE idempotency_key=?",
        (fresh_request.idempotency_key,),
    ).fetchone()
    fresh_connection.close()
    assert fresh_row is not None
    connection.execute(
        "INSERT INTO retrieval_authority.increment5d2_retrieval_contexts "
        "VALUES(?,?,?,?)",
        fresh_row,
    )
    refreshed_authority = RetrievalContextAuthority(
        builder.journal.path,
        {
            request.request_digest: (request, receipt),
            fresh_request.request_digest: (fresh_request, fresh_receipt),
        },
    )
    refreshed_store = TriageWorkItemStore(
        connection, retrieval_authority=refreshed_authority
    )
    competing = TriageWorkItem.create((decision, peer))
    competing_version = replace(
        _version(competing),
        retrieval=RetrievalInputBinding.from_receipt(
            fresh_request, fresh_receipt
        ),
    )
    assert refreshed_store.create_or_replay(competing, competing_version)
    fresh_second = replace(
        _version(item, 2),
        retrieval=RetrievalInputBinding.from_receipt(
            fresh_request, fresh_receipt
        ),
    )
    with pytest.raises(WorkItemContractError, match="overlap"):
        refreshed_store.append_version(
            version.version_id, version.canonical_digest, fresh_second
        )
    work_database = tmp_path / "purged-work-items.sqlite3"
    work_target = sqlite3.connect(work_database)
    connection.backup(work_target)
    work_target.close()
    connection.close()
    reopened_connection = sqlite3.connect(work_database, isolation_level=None)
    reopened = TriageWorkItemStore(
        reopened_connection, retrieval_authority=refreshed_authority
    )
    assert reopened.create_or_replay(item, version) == version
    assert not reopened.assess_current(item.work_item_id).usable
    reopened_connection.close()
    journal_connection = sqlite3.connect(builder.journal.path)
    retained_purge = journal_connection.execute(
        "SELECT * FROM increment5d2_retrieval_context_purges "
        "WHERE idempotency_key=?",
        (request.idempotency_key,),
    ).fetchone()
    assert retained_purge is not None
    first_purge = RetrievalContextPurgeReceipt.from_canonical_bytes(
        bytes(retained_purge[5])
    )
    second_reason = "SECOND_RIGHTS_WITHDRAWAL_PASSAGE"
    second_purge_id = _retrieval_context_purge_id(
        idempotency_key=first_purge.idempotency_key,
        context_id=first_purge.context_id,
        request_digest=first_purge.request_digest,
        prior_receipt_digest=first_purge.prior_receipt_digest,
        purged_derivative_identities=first_purge.purged_derivative_identities,
        context_derivative_identities=first_purge.context_derivative_identities,
        reason_code=second_reason,
        raw_context_bytes_deleted_in_event=False,
    )
    second_purge = replace(
        first_purge,
        purge_id=second_purge_id,
        reason_code=second_reason,
        raw_context_bytes_deleted_in_event=False,
    )
    journal_connection.execute(
        "INSERT INTO increment5d2_retrieval_context_purges VALUES(?,?,?,?,?,?)",
        (
            second_purge.purge_id,
            second_purge.idempotency_key,
            second_purge.request_digest,
            second_purge.prior_receipt_digest,
            second_purge.receipt_digest,
            second_purge.canonical_bytes,
        ),
    )
    journal_connection.commit()
    multiple_connection = sqlite3.connect(work_database, isolation_level=None)
    with pytest.raises(WorkItemContractError, match="retrieval"):
        TriageWorkItemStore(
            multiple_connection, retrieval_authority=refreshed_authority
        )
    multiple_connection.close()
    journal_connection.execute(
        "DELETE FROM increment5d2_retrieval_context_purges WHERE purge_id=?",
        (second_purge.purge_id,),
    )
    for changes in (
        {"prior_receipt_digest": digest_bytes(b"foreign prior")},
        {"context_id": _id(4998)},
    ):
        values = {
            "idempotency_key": first_purge.idempotency_key,
            "context_id": changes.get("context_id", first_purge.context_id),
            "request_digest": first_purge.request_digest,
            "prior_receipt_digest": changes.get(
                "prior_receipt_digest", first_purge.prior_receipt_digest
            ),
            "purged_derivative_identities": first_purge.purged_derivative_identities,
            "context_derivative_identities": first_purge.context_derivative_identities,
            "reason_code": "FOREIGN_SELF_CONSISTENT_PURGE",
            "raw_context_bytes_deleted_in_event": False,
        }
        forged_purge = replace(
            first_purge,
            purge_id=_retrieval_context_purge_id(**values),
            context_id=values["context_id"],
            prior_receipt_digest=values["prior_receipt_digest"],
            reason_code=values["reason_code"],
            raw_context_bytes_deleted_in_event=False,
        )
        journal_connection.execute(
            "INSERT INTO increment5d2_retrieval_context_purges VALUES(?,?,?,?,?,?)",
            (
                forged_purge.purge_id,
                forged_purge.idempotency_key,
                forged_purge.request_digest,
                forged_purge.prior_receipt_digest,
                forged_purge.receipt_digest,
                forged_purge.canonical_bytes,
            ),
        )
        journal_connection.commit()
        forged_connection = sqlite3.connect(work_database, isolation_level=None)
        with pytest.raises(WorkItemContractError, match="retrieval"):
            TriageWorkItemStore(
                forged_connection, retrieval_authority=refreshed_authority
            )
        forged_connection.close()
        journal_connection.execute(
            "DELETE FROM increment5d2_retrieval_context_purges WHERE purge_id=?",
            (forged_purge.purge_id,),
        )

    journal_connection.execute(
        "INSERT INTO increment5d2_retrieval_contexts VALUES(?,?,?,?)",
        completed_row,
    )
    journal_connection.commit()
    contradictory_connection = sqlite3.connect(
        work_database, isolation_level=None
    )
    with pytest.raises(WorkItemContractError, match="retrieval"):
        TriageWorkItemStore(
            contradictory_connection, retrieval_authority=refreshed_authority
        )
    contradictory_connection.close()
    journal_connection.execute(
        "DELETE FROM increment5d2_retrieval_contexts WHERE idempotency_key=?",
        (request.idempotency_key,),
    )
    journal_connection.execute(
        "INSERT INTO increment5d2_retrieval_context_purges VALUES(?,?,?,?,?,?)",
        (_id(4999), *retained_purge[1:]),
    )
    journal_connection.commit()
    malformed_connection = sqlite3.connect(work_database, isolation_level=None)
    with pytest.raises(WorkItemContractError, match="retrieval"):
        TriageWorkItemStore(
            malformed_connection, retrieval_authority=refreshed_authority
        )
    malformed_connection.close()
    journal_connection.execute(
        "DELETE FROM increment5d2_retrieval_context_purges WHERE purge_id=?",
        (_id(4999),),
    )
    journal_connection.execute(
        "UPDATE increment5d2_retrieval_context_purges SET purge_receipt_bytes=? "
        "WHERE purge_id=?",
        (b"{}", first_purge.purge_id),
    )
    journal_connection.commit()
    journal_connection.close()
    tampered_connection = sqlite3.connect(work_database, isolation_level=None)
    with pytest.raises(WorkItemContractError, match="retrieval"):
        TriageWorkItemStore(
            tampered_connection, retrieval_authority=refreshed_authority
        )
    tampered_connection.close()


def test_actual_retrieval_complete_no_match_is_usable_and_incomplete_is_not(
    tmp_path,
) -> None:
    branch_inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    no_match_inputs = retrieval_helpers._no_match_inputs(branch_inputs)
    composer, composition_request, composition = retrieval_helpers._compose(
        tmp_path,
        no_match_inputs,
        key="hybrid:work-item-no-match",
        request_id="00000000-0000-4000-8000-000000009300",
    )
    collision_digest = retrieval_helpers.context_collision_key_digest(composition)
    database, _ = retrieval_helpers._authority_database(
        tmp_path,
        name="work-item-no-match",
        admission_id="object:work-item-no-match",
        passage_id=None,
        content=None,
        collision_digest=None,
    )
    cas_root = retrieval_helpers._cas_root(tmp_path, name="cas-work-item-no-match")
    authority_request, authority_result = retrieval_helpers._authority_execution(
        tmp_path,
        name="work-item-no-match",
        database=database,
        composition=composition,
        object_ids=("object:work-item-no-match",),
    )
    request = retrieval_helpers._context_request(
        key="work-item-no-match",
        composition_request=composition_request,
        composition=composition,
        inputs=no_match_inputs,
        authority_request=authority_request,
        authority_result=authority_result,
    )
    builder = retrieval_helpers._builder(
        tmp_path,
        name="work-item-no-match",
        composer=composer,
        cas_root=cas_root,
    )
    receipt = builder.execute(request)
    assert collision_digest and receipt.no_match and receipt.outcome.value == "COMPLETE"
    complete_authority = RetrievalContextAuthority(
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    complete_decision = _decision(2)
    _, complete_store = _store(
        (complete_decision,), retrieval_authority=complete_authority
    )
    complete_item = TriageWorkItem.create((complete_decision,))
    complete_version = replace(
        _version(complete_item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    complete_store.create_or_replay(complete_item, complete_version)
    assert complete_store.require_usable_current(complete_item.work_item_id) == (
        complete_version
    )

    incomplete_inputs = retrieval_helpers._exact_only_inputs(branch_inputs)
    composer, composition_request, composition = retrieval_helpers._compose(
        tmp_path,
        incomplete_inputs,
        key="hybrid:work-item-incomplete",
        request_id="00000000-0000-4000-8000-000000009301",
    )
    incomplete_request = retrieval_helpers._context_request(
        key="work-item-incomplete",
        composition_request=composition_request,
        composition=composition,
        inputs=incomplete_inputs,
    )
    incomplete_builder = retrieval_helpers._builder(
        tmp_path,
        name="work-item-incomplete",
        composer=composer,
        cas_root=retrieval_helpers._cas_root(tmp_path, name="cas-work-item-incomplete"),
    )
    incomplete_receipt = incomplete_builder.execute(incomplete_request)
    assert incomplete_receipt.outcome.value == "INCOMPLETE"
    incomplete_authority = RetrievalContextAuthority(
        incomplete_builder.journal.path,
        {incomplete_request.request_digest: (incomplete_request, incomplete_receipt)},
    )
    incomplete_decision = _decision(3)
    _, incomplete_store = _store(
        (incomplete_decision,), retrieval_authority=incomplete_authority
    )
    incomplete_item = TriageWorkItem.create((incomplete_decision,))
    incomplete_version = replace(
        _version(incomplete_item),
        retrieval=RetrievalInputBinding.from_receipt(
            incomplete_request, incomplete_receipt
        ),
    )
    assert (
        incomplete_store.create_or_replay(incomplete_item, incomplete_version)
        == incomplete_version
    )
    with pytest.raises(WorkItemContractError, match="retrieval_not_complete"):
        incomplete_store.require_usable_current(incomplete_item.work_item_id)


def test_two_passage_purge_history_is_disjoint_and_restart_safe(tmp_path) -> None:
    branch_inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    root_a = "authority:work-item-root-a"
    root_b = "authority:work-item-root-b"
    inputs = retrieval_helpers._selected_passage_inputs(
        branch_inputs, {1: root_a, 2: root_b}
    )
    composer, composition_request, composition = retrieval_helpers._compose(
        tmp_path,
        inputs,
        key="hybrid:work-item-two-passage",
        request_id=_id(9601),
    )
    passages = {
        candidate.dependency_root_id: retrieval_helpers._candidate_passage_id(
            candidate
        )
        for candidate in composition.candidates
    }
    passage_a, passage_b = passages[root_a], passages[root_b]
    admission_a = "object:work-item-a"
    admission_b = "object:work-item-b"
    content = b"governed two-passage Work Item bytes"
    database, blob = retrieval_helpers._authority_database(
        tmp_path,
        name="work-item-two-passage",
        admission_id=admission_a,
        passage_id=passage_a,
        content=content,
    )
    assert blob is not None
    with sqlite3.connect(database) as authority_connection:
        retrieval_helpers.authority_helpers.seed_object(
            authority_connection,
            admission_id=admission_b,
            passage_id=passage_b,
            run_id="run:work-item-two-passage:b",
            allowed=1,
        )
        retrieval_helpers._retarget_seeded_passage_to_existing_blob(
            authority_connection,
            admission_id=admission_b,
            passage_id=passage_b,
            content=content,
            blob_digest=blob,
        )
    cas_root = retrieval_helpers._cas_root(
        tmp_path,
        name="cas-work-item-two-passage",
        blob_digest=blob,
        content=content,
    )
    authority_request, authority_result = retrieval_helpers._authority_execution(
        tmp_path,
        name="work-item-two-passage",
        database=database,
        composition=composition,
        passage_ids=tuple(sorted((passage_a, passage_b))),
    )
    request = retrieval_helpers._context_request(
        key="work-item-two-passage",
        composition_request=composition_request,
        composition=composition,
        inputs=inputs,
        authority_request=authority_request,
        authority_result=authority_result,
    )
    journal = retrieval_helpers.RetrievalContextJournal(
        tmp_path / "work-item-two-passage.sqlite3"
    )
    builder = retrieval_helpers.RetrievalContextBuilder(
        composition_replayer=composer,
        journal=journal,
        hydrator=retrieval_helpers.GovernedCasPassageHydrator(cas_root),
    )
    pending_authority = RetrievalContextAuthority(
        journal.path, {request.request_digest: (request, None)}
    )
    pending_decision = _decision(2)
    pending_connection, pending_store = _store(
        (pending_decision,), retrieval_authority=pending_authority
    )
    pending_item = TriageWorkItem.create((pending_decision,))
    pending_version = replace(
        _version(pending_item),
        retrieval=RetrievalInputBinding.request_pending(request),
    )
    pending_store.create_or_replay(pending_item, pending_version)
    pending_database = tmp_path / "two-passage-pending.sqlite3"
    pending_target = sqlite3.connect(pending_database)
    pending_connection.backup(pending_target)
    pending_target.close()
    pending_connection.close()

    receipt = builder.execute(request)
    assert len(receipt.items) == 2
    journal_connection = sqlite3.connect(journal.path)
    live_row = journal_connection.execute(
        "SELECT * FROM increment5d2_retrieval_contexts WHERE idempotency_key=?",
        (request.idempotency_key,),
    ).fetchone()
    journal_connection.close()
    assert live_row is not None
    retrieval_authority = RetrievalContextAuthority(
        journal.path, {request.request_digest: (request, receipt)}
    )
    decision = _decision(1)
    connection, store = _store(
        (decision,), retrieval_authority=retrieval_authority
    )
    item = TriageWorkItem.create((decision,))
    version = replace(
        _version(item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    store.create_or_replay(item, version)
    work_database = tmp_path / "two-passage-work-items.sqlite3"
    target = sqlite3.connect(work_database)
    connection.backup(target)
    target.close()
    connection.close()

    first = journal.purge_affected(
        admission_ids=(admission_a,), reason_code="RIGHTS_WITHDRAWN_A"
    )
    second = journal.purge_affected(
        admission_ids=(admission_b,), reason_code="RIGHTS_WITHDRAWN_B"
    )
    relevant = tuple(
        purge
        for purge in (*first, *second)
        if purge.idempotency_key == request.idempotency_key
    )
    assert len(relevant) == 2
    assert set(relevant[0].purged_derivative_identities).isdisjoint(
        relevant[1].purged_derivative_identities
    )
    restarted_connection = sqlite3.connect(work_database, isolation_level=None)
    restarted = TriageWorkItemStore(
        restarted_connection, retrieval_authority=retrieval_authority
    )
    assert restarted.assess_current(item.work_item_id).usable is False
    restarted_connection.close()

    journal_connection = sqlite3.connect(journal.path)
    journal_connection.execute(
        "INSERT INTO increment5d2_retrieval_contexts VALUES(?,?,?,?)", live_row
    )
    journal_connection.commit()
    journal_connection.close()
    contradictory_pending = sqlite3.connect(
        pending_database, isolation_level=None
    )
    with pytest.raises(WorkItemContractError, match="retrieval"):
        TriageWorkItemStore(
            contradictory_pending, retrieval_authority=retrieval_authority
        )
    contradictory_pending.close()
    journal_connection = sqlite3.connect(journal.path)
    journal_connection.execute(
        "DELETE FROM increment5d2_retrieval_contexts WHERE idempotency_key=?",
        (request.idempotency_key,),
    )
    journal_connection.commit()
    journal_connection.close()


def test_sql_successor_scope_retarget_is_rejected(tmp_path) -> None:
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
        "INSERT INTO triage_work_item_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            retargeted.version_id,
            retargeted.schema_identity,
            retargeted.work_item_id,
            retargeted.ordinal,
            retargeted.previous_version_id,
            item.decision_scope_digest,
            retargeted.retrieval.state.value,
            None,
            None,
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
    database = tmp_path / "retargeted.sqlite3"
    target = sqlite3.connect(database)
    connection.backup(target)
    target.close()
    connection.close()
    reopened = sqlite3.connect(database, isolation_level=None)
    with pytest.raises(WorkItemContractError, match="retained bytes"):
        TriageWorkItemStore(reopened)
    reopened.close()


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
    divergent = replace(second, retrieval=_pending(901))
    with pytest.raises(WorkItemContractError, match="diverge"):
        second_store.append_version(first.version_id, first.canonical_digest, divergent)
    first_connection.close()
    second_connection.close()
    restarted_connection = sqlite3.connect(database, isolation_level=None)
    restarted = TriageWorkItemStore(restarted_connection)
    assert restarted.create_or_replay(item, first) == first
    assert restarted.current_version(item.work_item_id) == second
    restarted_connection.execute(
        "DROP TRIGGER retained_triage_work_item_heads_delete"
    )
    restarted_connection.execute(
        "DELETE FROM triage_work_item_heads WHERE work_item_id=?",
        (item.work_item_id,),
    )
    with pytest.raises(WorkItemContractError, match="chain or head"):
        restarted.create_or_replay(item, first)
    restarted_connection.close()


def test_exact_replay_checks_the_retained_current_chain_immediately() -> None:
    decision = _decision(1)
    connection, store = _store((decision,))
    item = TriageWorkItem.create((decision,))
    first = _version(item)
    second = _version(item, 2)
    store.create_or_replay(item, first)
    store.append_version(first.version_id, first.canonical_digest, second)

    corrupt = b"{}"
    connection.execute("DROP TRIGGER immutable_triage_work_item_versions_update")
    connection.execute(
        "UPDATE triage_work_item_versions SET canonical_bytes=?,canonical_digest=? "
        "WHERE version_id=?",
        (corrupt, digest_bytes(corrupt), second.version_id),
    )
    with pytest.raises(WorkItemContractError):
        store.create_or_replay(item, first)
    with pytest.raises(WorkItemContractError):
        store.append_version(first.version_id, first.canonical_digest, second)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("retrieval_outcome", "FORGED"),
        ("watch_condition_id", _id(9701)),
    ),
)
def test_exact_replay_checks_all_retained_version_metadata(
    column: str, value: str
) -> None:
    decision = _decision(1)
    connection, store = _store((decision,))
    item = TriageWorkItem.create((decision,))
    version = _version(item)
    store.create_or_replay(item, version)
    connection.execute("DROP TRIGGER immutable_triage_work_item_versions_update")
    connection.execute(
        f"UPDATE triage_work_item_versions SET {column}=? WHERE version_id=?",
        (value, version.version_id),
    )
    with pytest.raises(WorkItemContractError, match="chain"):
        store.create_or_replay(item, version)


def test_exact_replay_checks_retained_item_metadata() -> None:
    decision = _decision(1)
    connection, store = _store((decision,))
    item = TriageWorkItem.create((decision,))
    version = _version(item)
    store.create_or_replay(item, version)
    connection.execute("DROP TRIGGER immutable_triage_work_items_update")
    connection.execute(
        "UPDATE triage_work_items SET decision_lead_count=2 WHERE work_item_id=?",
        (item.work_item_id,),
    )
    with pytest.raises(WorkItemContractError, match="retained bytes"):
        store.create_or_replay(item, version)


def test_restart_requires_exact_item_version_and_head_coverage(tmp_path) -> None:
    decision = _decision(1)
    for missing in ("versions", "head"):
        connection, store = _store((decision,))
        item = TriageWorkItem.create((decision,))
        first = _version(item)
        store.create_or_replay(item, first)
        connection.execute("DROP TRIGGER retained_triage_work_item_heads_delete")
        if missing == "versions":
            connection.execute(
                "DELETE FROM triage_work_item_heads WHERE work_item_id=?",
                (item.work_item_id,),
            )
            connection.execute(
                "DROP TRIGGER retained_triage_work_item_versions_delete"
            )
            connection.execute(
                "DELETE FROM triage_work_item_versions WHERE work_item_id=?",
                (item.work_item_id,),
            )
        else:
            connection.execute(
                "DELETE FROM triage_work_item_heads WHERE work_item_id=?",
                (item.work_item_id,),
            )
        database = tmp_path / f"missing-{missing}.sqlite3"
        target = sqlite3.connect(database)
        connection.backup(target)
        target.close()
        connection.close()
        reopened = sqlite3.connect(database, isolation_level=None)
        with pytest.raises(WorkItemContractError, match="coverage"):
            TriageWorkItemStore(reopened)
        reopened.close()


def test_restart_integrity_is_linear_query_bounded(tmp_path) -> None:
    decisions = tuple(_decision(index) for index in range(1, 101))
    connection, store = _store(decisions)
    for decision in decisions:
        item = TriageWorkItem.create((decision,))
        store.create_or_replay(item, _version(item))
    database = tmp_path / "linear-integrity.sqlite3"
    target = sqlite3.connect(database)
    connection.backup(target)
    target.close()
    connection.close()

    reopened = sqlite3.connect(database, isolation_level=None)
    statements = 0

    def count_statement(_statement: str) -> None:
        nonlocal statements
        statements += 1

    reopened.set_trace_callback(count_statement)
    TriageWorkItemStore(reopened)
    assert statements < 300
    reopened.close()


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
        deadline_binding = replace(
            watch_binding,
            allowed_reentry_kinds=tuple(
                sorted((*watch_binding.allowed_reentry_kinds, "DEADLINE"))
            ),
        )
        forged_deadline = replace(
            second, watch=deadline_binding, reentry_kind=ReentryKind.DEADLINE
        )
        with pytest.raises(WorkItemContractError, match="watch"):
            store.append_version(
                first.version_id, first.canonical_digest, forged_deadline
            )
        assert (
            store.append_version(first.version_id, first.canonical_digest, second)
            == second
        )
        third_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|3"))
        third = replace(
            second,
            version_id=third_id,
            ordinal=3,
            previous_version_id=second.version_id,
            priority=WorkItemPriorityBinding.from_selection(
                PrioritySelection(
                    item.work_item_id,
                    third_id,
                    PriorityLane.ROUTINE,
                    (ReasonReference("fixture", "watch-reuse"),),
                )
            ),
        )
        with pytest.raises(WorkItemContractError, match="already claimed"):
            store.append_version(second.version_id, second.canonical_digest, third)
        with pytest.raises(WorkItemContractError, match="typed"):
            replace(second, reentry_kind="REVIEW")
        with pytest.raises(WorkItemContractError, match="condition"):
            replace(second, reentry_kind=ReentryKind.OPERATOR_CONDITION)
        assert replace(second, reentry_kind=ReentryKind.EXPIRY).reentry_kind is (
            ReentryKind.EXPIRY
        )
        with pytest.raises(WorkItemContractError, match="source disposition"):
            WatchConditionWorkItemBinding.from_authority(
                watch, admitted.initial_disposition
            )

        operator_binding = replace(
            watch_binding,
            allowed_reentry_kinds=tuple(
                sorted((*watch_binding.allowed_reentry_kinds, "OPERATOR_CONDITION"))
            ),
        )
        forged_operator = replace(
            second,
            watch=operator_binding,
            reentry_kind=ReentryKind.OPERATOR_CONDITION,
        )
        assert forged_operator.reentry_kind is ReentryKind.OPERATOR_CONDITION

        transition_binding = replace(watch_binding, observable_transition=True)
        with pytest.raises(WorkItemContractError, match="new Lead"):
            replace(second, watch=transition_binding)
        with pytest.raises(WorkItemContractError, match="does not belong"):
            replace(second, watch=replace(watch_binding, lead_id=_id(9992)))
        with pytest.raises(WorkItemContractError, match="immediate successor"):
            replace(
                second,
                watch=replace(watch_binding, source_disposition_ordinal=1),
            )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO triage_work_item_versions "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    third.version_id,
                    third.schema_identity,
                    third.work_item_id,
                    third.ordinal,
                    third.previous_version_id,
                    item.decision_scope_digest,
                    third.retrieval.state.value,
                    TriageWorkItemStore._causal_ids(third)[0],
                    TriageWorkItemStore._causal_ids(third)[1],
                    third.canonical_bytes,
                    third.canonical_digest,
                    "1970-01-01T00:00:00Z",
                ),
            )
        connection.close()
        reopened_connection = sqlite3.connect(database, isolation_level=None)
        TriageWorkItemStore(reopened_connection)
        reopened_connection.close()


def test_actual_supplemental_lineage_persists_replays_and_restarts(tmp_path) -> None:
    database = tmp_path / "supplemental-authority.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        source_admitted = system.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=proof()
        )
        assert source_admitted.lead is not None
        assert source_admitted.initial_disposition is not None

        base = exact_admission_request()
        signal_id = DiscoverySignalId.parse("00000000-0000-4000-8000-000000009401")
        gate_id = GateDecisionId.parse("00000000-0000-4000-8000-000000009402")
        lead_id = NewsLeadId.parse("00000000-0000-4000-8000-000000009403")
        disposition_id = LeadDispositionDecisionId.parse(
            "00000000-0000-4000-8000-000000009404"
        )
        signal = replace(
            base.signal,
            signal_id=signal_id,
            purpose="SUPPLEMENTAL_GOVERNED_DISCOVERY",
            discriminator="SUPPLEMENTAL_GOVERNED_DISCOVERY_V1",
            idempotency_key="supplemental-signal",
        )
        gate = replace(
            base.gate,
            decision_id=gate_id,
            signal_id=signal_id,
            idempotency_key="supplemental-gate",
        )
        lead = replace(
            base.lead,
            lead_id=lead_id,
            signal_id=signal_id,
            promoting_gate_decision_id=gate_id,
            idempotency_key="supplemental-lead",
        )
        disposition = replace(
            base.initial_disposition,
            decision_id=disposition_id,
            lead_id=lead_id,
            gate_decision_id=gate_id,
            idempotency_key="supplemental-queued-disposition",
        )
        target_admitted = system.discovery.admit_signal_to_lead(
            SignalLeadAdmissionRequest(signal, gate, lead, disposition),
            proof=proof(),
        )
        assert target_admitted.lead is not None
        assert target_admitted.initial_disposition is not None
        check_request = system.checks.request(REQUEST_ID, proof=proof())
        check_outcome = system.checks.outcome(OUTCOME_ID, proof=proof())

    lineage = (
        SupplementalLineageBinding.from_authority(check_request.request.trigger),
        SupplementalLineageBinding.from_authority(check_request),
        SupplementalLineageBinding.from_authority(check_outcome),
        SupplementalLineageBinding.from_authority(target_admitted.signal),
        SupplementalLineageBinding.from_authority(target_admitted.gate),
        SupplementalLineageBinding.from_authority(target_admitted.lead),
        SupplementalLineageBinding.from_authority(target_admitted.initial_disposition),
    )
    source_decision = DecisionLeadBinding.from_authority(
        source_admitted.lead, source_admitted.initial_disposition
    )
    target_decision = DecisionLeadBinding.from_authority(
        target_admitted.lead, target_admitted.initial_disposition
    )
    approval_id = _id(9501)
    approval_digest = digest_bytes(b"fixture-supplemental-approval")
    approval_event_id = _id(9502)
    connection = sqlite3.connect(database, isolation_level=None)
    store = TriageWorkItemStore(connection)
    source_item = TriageWorkItem.create((source_decision,))
    source_version = _version(source_item)
    store.create_or_replay(source_item, source_version)
    target_item = TriageWorkItem.create((target_decision,))
    target_version_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{target_item.work_item_id}|1")
    )
    proof_value = SupplementalDiscoveryReentry(
        source_item.work_item_id,
        source_version.version_id,
        source_version.canonical_digest,
        approval_id,
        approval_digest,
        approval_event_id,
        1,
        "LEAD_SUPPLEMENTAL_DISCOVERY",
        "REQUEST_SUPPLEMENTAL_DISCOVERY",
        lineage[0].identifier,
        lineage[1].identifier,
        lineage[2].identifier,
        lineage[3].identifier,
        lineage[4].identifier,
        lineage[5].identifier,
        lineage[6].identifier,
        target_item.work_item_id,
        target_version_id,
        lineage_bindings=lineage,
    )
    target_version = TriageWorkItemVersion.create(
        work_item_id=target_item.work_item_id,
        ordinal=1,
        previous_version_id=None,
        decision_leads=(target_decision,),
        context_leads=(),
        retrieval=_pending(),
        priority=PrioritySelection(
            target_item.work_item_id,
            target_version_id,
            PriorityLane.ROUTINE,
            (ReasonReference("fixture", "supplemental"),),
        ),
        supplemental_reentry=proof_value,
    )
    with pytest.raises(WorkItemContractError, match="authority_unavailable_v18"):
        store.create_or_replay(target_item, target_version)

    second_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{target_item.work_item_id}|2"))
    with pytest.raises(WorkItemContractError, match="ordinal"):
        TriageWorkItemVersion.create(
            work_item_id=target_item.work_item_id,
            ordinal=2,
            previous_version_id=target_version.version_id,
            decision_leads=(target_decision,),
            context_leads=(),
            retrieval=_pending(),
            priority=PrioritySelection(
                target_item.work_item_id,
                second_id,
                PriorityLane.ROUTINE,
                (ReasonReference("fixture", "supplemental-successor"),),
            ),
            supplemental_reentry=replace(
                proof_value,
                target_version_id=second_id,
            ),
        )
    with pytest.raises(WorkItemContractError, match="lineage"):
        replace(proof_value, lineage_bindings=lineage[:-1])
    with pytest.raises(WorkItemContractError, match="route"):
        replace(proof_value, source_approval_route="RESUME_ON_WATCH")

    class NoOp:
        @staticmethod
        def verify(*_args: object) -> None:
            return None

    with pytest.raises(TypeError, match="supplemental_authority"):
        TriageWorkItemStore(connection, supplemental_authority=NoOp())  # type: ignore[call-arg]
    connection.close()
