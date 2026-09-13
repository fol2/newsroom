"""Native retained/current checks share work only inside one operation."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from newsroom.increment5.native_retrieval import NativeRetrievalError
from newsroom.increment6.work_items import (
    RetrievalContextAuthority,
    TriageWorkItem,
    TriageWorkItemStore,
    WorkItemContractError,
)
from newsroom.tests import test_increment5d2_retrieval_context as retrieval_helpers
from newsroom.tests import test_increment6a2_work_items as work_helpers
from newsroom.tests.test_native_collision import _native_binding, _read_port


@pytest.fixture
def native_work_item(tmp_path):
    decision = work_helpers._decision(1)
    binding, receipt, context = _native_binding(
        tmp_path,
        SimpleNamespace(
            request=SimpleNamespace(lead_id=decision.lead_id),
            canonical_digest=decision.lead_digest,
        ),
    )
    contexts = {context.context_id: context}
    port = _read_port(contexts)
    journal = retrieval_helpers.RetrievalContextJournal(tmp_path / "retrieval.sqlite3")
    authority = RetrievalContextAuthority(
        journal.path, {}, native_context_read_port=port
    )
    connection, store = work_helpers._store(
        (decision,), retrieval_authority=authority
    )
    item = TriageWorkItem.create((decision,))
    version = replace(work_helpers._version(item), retrieval=binding)
    store.create_or_replay(item, version)
    try:
        yield connection, store, authority, port, contexts, version, receipt
    finally:
        connection.close()


@pytest.mark.parametrize(("operation", "expected_reads"), (("restart", 2), ("current", 1)))
def test_native_context_is_not_reread_for_identical_currentness_check(
    native_work_item, operation, expected_reads
):
    connection, store, authority, port, _, version, receipt = native_work_item
    reads = []
    original = port._read

    def read(retained):
        reads.append(retained)
        return original(retained)

    port._read = read
    for _ in range(2):
        reads.clear()
        if operation == "restart":
            TriageWorkItemStore(connection, authority)
        else:
            assert store.require_usable_current(version.work_item_id) == version
        # Opening also checks immutable lineage; ordinary currentness only
        # needs its one identical native retained/current verification.
        assert reads == [receipt] * expected_reads


@pytest.mark.parametrize("mutation", ("context", "rights", "source"))
def test_native_currentness_rechecks_changed_evidence_on_next_operation(
    native_work_item, mutation
):
    connection, store, _, port, contexts, version, receipt = native_work_item
    assert store.require_usable_current(version.work_item_id) == version
    if mutation == "context":
        contexts[receipt.context_id] = replace(
            contexts[receipt.context_id], context_id=work_helpers._id(9001)
        )
    elif mutation == "rights":
        def denied(_receipt):
            raise NativeRetrievalError("native document rights differ")

        port._read = denied
    else:
        connection.execute(
            "UPDATE source_definition_version_heads SET current_version_id=?",
            (work_helpers._id(9002),),
        )
    with pytest.raises(WorkItemContractError, match="retrieval|source"):
        store.require_usable_current(version.work_item_id)
