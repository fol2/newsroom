from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.increment6.dispositions import (
    DispositionContractError,
    ProposalDispositionStore,
)

from . import test_increment6a2_work_items as work_item_helpers
from .test_increment6c2_dispositions import (
    DIGEST_A,
    _persisted_disposition_store,
)


def test_current_disposition_verifies_only_its_complete_proposal_group(
    tmp_path,
) -> None:
    connection, _, _, _, store, proof, disposition = (
        _persisted_disposition_store(tmp_path, name="bounded-current")
    )
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        connection.execute("BEGIN IMMEDIATE")
        assert (
            store.require_current_in_transaction(
                disposition.disposition_id, proof=proof
            )
            == disposition
        )
        connection.execute("ROLLBACK")
    finally:
        connection.set_trace_callback(None)

    normalised = tuple(" ".join(item.split()) for item in statements)
    disposition_reads = tuple(
        item
        for item in normalised
        if "FROM triage_proposal_dispositions" in item
        or "FROM triage_proposal_validation_findings" in item
    )
    assert disposition_reads
    assert all(" WHERE " in item for item in disposition_reads)
    assert not any("SELECT name FROM sqlite_master" in item for item in normalised)


@pytest.mark.parametrize(
    "mutation",
    ("disposition_scalar", "disposition_digest", "linked_finding"),
)
def test_bounded_current_disposition_rejects_exact_group_tamper(
    tmp_path, mutation: str
) -> None:
    connection, _, _, _, store, proof, disposition = (
        _persisted_disposition_store(tmp_path, name=f"bounded-{mutation}")
    )
    if mutation == "disposition_scalar":
        connection.execute(
            "DROP TRIGGER immutable_triage_proposal_dispositions_update"
        )
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "UPDATE triage_proposal_dispositions SET proposal_id=?",
            ("00000000-0000-4000-8000-000000009999",),
        )
        connection.execute("PRAGMA foreign_keys=ON")
    elif mutation == "disposition_digest":
        connection.execute(
            "DROP TRIGGER immutable_triage_proposal_dispositions_update"
        )
        connection.execute(
            "UPDATE triage_proposal_dispositions SET canonical_digest=?",
            (DIGEST_A,),
        )
    else:
        connection.execute(
            "DROP TRIGGER immutable_triage_proposal_findings_update"
        )
        connection.execute(
            "UPDATE triage_proposal_validation_findings SET canonical_digest=?",
            (DIGEST_A,),
        )

    connection.execute("BEGIN IMMEDIATE")
    with pytest.raises(DispositionContractError, match="retained"):
        store.require_current_in_transaction(
            disposition.disposition_id, proof=proof
        )
    connection.execute("ROLLBACK")


def test_bounded_current_disposition_keeps_current_work_item_boundary(
    tmp_path,
) -> None:
    connection, work_store, item, version, store, proof, disposition = (
        _persisted_disposition_store(tmp_path, name="bounded-stale")
    )
    successor = replace(
        work_item_helpers._version(item, 2), retrieval=version.retrieval
    )
    work_store.append_version(
        version.version_id, version.canonical_digest, successor
    )

    connection.execute("BEGIN IMMEDIATE")
    with pytest.raises(DispositionContractError, match="no longer current"):
        store.require_current_in_transaction(
            disposition.disposition_id, proof=proof
        )
    connection.execute("ROLLBACK")


def test_full_store_initialisation_still_rejects_unrelated_history_tamper(
    tmp_path,
) -> None:
    connection, _, _, _, store, _, _ = _persisted_disposition_store(
        tmp_path, name="full-reopen-tamper"
    )
    connection.execute("DROP TRIGGER immutable_triage_proposal_findings_update")
    connection.execute(
        "UPDATE triage_proposal_validation_findings SET canonical_digest=?",
        (DIGEST_A,),
    )

    with pytest.raises(DispositionContractError, match="retained"):
        ProposalDispositionStore(
            connection,
            store._retrieval_authority,
            store._authenticator,
            store._current_candidate_citations,
            work_items=store._work_items,
        )
