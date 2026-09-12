from dataclasses import replace

import pytest

from newsroom.control_plane.native_progress import NativeRevisionJournal
from newsroom.control_plane.store import connect
from newsroom.tests.test_native_graphiti import _native


def test_native_journal_reopens_progress_without_repeating_landing_or_state(tmp_path):
    path = str(tmp_path / "private.sqlite3")
    unit = _native()
    connection = connect(path)
    journal = NativeRevisionJournal(connection)
    journal.land((unit,))
    journal.advance(unit.revision_id, stage="GRAPHITI_HOLD", facts={"reason": "RIGHTS_HOLD"})
    connection.close()
    connection = connect(path)
    journal = NativeRevisionJournal(connection)
    assert journal.units[unit.revision_id] == (unit,)
    journal.land((unit,))
    journal.advance(unit.revision_id, stage="GRAPHITI_HOLD", facts={"reason": "RIGHTS_HOLD"})
    assert connection.execute("SELECT count(*) FROM ledger").fetchone()[0] == 2
    journal.advance(unit.revision_id, stage="GRAPHITI_COMPLETE", facts={"receipt": unit.digest})
    assert journal.progress[unit.revision_id]["ordinal"] == 2
    connection.close()


def test_native_journal_rejects_missing_chunk_without_writing(tmp_path):
    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    with pytest.raises(ValueError, match="chunk coverage"):
        journal.land((replace(_native(), chunk_count=2),))
    assert connection.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0
    connection.close()


def test_native_journal_retains_old_binding_on_unchanged_reobservation(tmp_path):
    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    unit = _native()
    journal.land((unit,))
    journal.land((replace(unit, observation_digest="sha256:" + "e" * 64),))
    assert journal.units[unit.revision_id] == (unit,)
    assert connection.execute("SELECT count(*) FROM ledger").fetchone()[0] == 1
    connection.close()


def test_native_journal_reopen_retains_one_body_per_multichunk_revision(tmp_path):
    connection = connect(str(tmp_path / "private.sqlite3"))
    unit = replace(_native(), body="A complete retained paragraph. " * 1000, chunk_count=3)
    units = tuple(replace(unit, chunk_ordinal=ordinal) for ordinal in range(1, 4))
    NativeRevisionJournal(connection).land(units)
    reopened = NativeRevisionJournal(connection)
    retained = reopened.units[unit.revision_id]
    assert retained == units
    # Every chunk owns its identity, not a second copy of the full source body.
    assert len({id(item.body) for item in retained}) == 1
    connection.close()


def test_native_journal_rejects_tampered_payload_on_reopen(tmp_path):
    connection = connect(str(tmp_path / "private.sqlite3"))
    NativeRevisionJournal(connection).land((_native(),))
    connection.execute("UPDATE ledger SET payload_json='{}'")
    connection.commit()
    with pytest.raises(ValueError, match="payload differs"):
        NativeRevisionJournal(connection)
    connection.close()


def test_native_journal_retains_page_references_and_per_item_holds_across_poll(tmp_path):
    from newsroom.control_plane.native_source_intake import NativeSourceDisposition
    path = str(tmp_path / "private.sqlite3")
    connection = connect(path)
    journal = NativeRevisionJournal(connection)
    reference = ("https://www.gov.uk/api/content/item", "sha256:" + "d" * 64, "admission", "access")
    journal.sources((NativeSourceDisposition(
        "UK-01", "HOLD", "SOURCE_ITEMS_HELD", observations=(reference,),
        item_holds=(("https://www.gov.uk/other", "UNSUPPORTED_TYPE"),),
    ),))
    assert journal.portfolio[0]["item_holds"] == [["https://www.gov.uk/other", "UNSUPPORTED_TYPE"]]
    journal.sources((NativeSourceDisposition("UK-01", "READY", "UNCHANGED"),))
    connection.close()
    connection = connect(path)
    reopened = NativeRevisionJournal(connection)
    assert reopened.observations[reference[1]] == reference
    connection.close()


def _retrieval_facts():
    return {
        "retrieval_binding": {"request": {"nodes": ["Retained graph record. " * 200]}},
        "retrieval_rights_inventory": [{"source_id": "UK-01", "rights": "retained"}],
        "retrieval_embeddings": {"passage": {"state": "STARTED", "cycle_id": "cycle"}},
        "reason": "EVIDENCE_NOT_READY",
    }


def test_unchanged_retrieval_pair_references_previous_record_but_returns_full_facts(tmp_path):
    import json

    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    revision = _native().revision_id
    journal.land((_native(),))
    facts = _retrieval_facts()
    journal.advance(revision, stage="RETRIEVAL_COMPLETE", facts=facts)
    previous = connection.execute("SELECT seq,payload_digest FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    result = journal.advance(revision, stage="EVIDENCE_HOLD", facts=facts)
    raw = json.loads(connection.execute("SELECT payload_json FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert raw["retrieval_facts_ref"] == {"seq": previous[0], "payload_digest": previous[1], "ordinal": 1}
    assert "retrieval_binding" not in raw["facts"]
    assert "retrieval_rights_inventory" not in raw["facts"]
    assert raw["facts"]["retrieval_embeddings"] == facts["retrieval_embeddings"]
    assert result["facts"] == facts
    assert result == NativeRevisionJournal(connection).progress[revision]
    connection.close()


def test_mutated_previous_pair_is_not_mistaken_for_committed_content(tmp_path):
    import json

    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    revision = _native().revision_id
    journal.land((_native(),))
    retained = journal.advance(revision, stage="RETRIEVAL_COMPLETE", facts=_retrieval_facts())
    retained["facts"]["retrieval_binding"]["request"]["nodes"].append("new record")
    result = journal.advance(revision, stage="RETRIEVAL_COMPLETE", facts=retained["facts"])
    assert result["ordinal"] == 2
    raw = json.loads(connection.execute("SELECT payload_json FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert "retrieval_facts_ref" not in raw
    assert result == NativeRevisionJournal(connection).progress[revision]
    connection.close()


def test_failed_append_rolls_back_without_advancing_reference(tmp_path, monkeypatch):
    import newsroom.control_plane.native_progress as progress

    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    revision = _native().revision_id
    journal.land((_native(),))
    before = journal.advance(revision, stage="RETRIEVAL_COMPLETE", facts=_retrieval_facts())
    original = progress.append_ledger
    def fail_after_insert(*args):
        original(*args)
        raise RuntimeError("injected append failure")
    monkeypatch.setattr(progress, "append_ledger", fail_after_insert)
    with pytest.raises(RuntimeError, match="injected"):
        journal.advance(revision, stage="EVIDENCE_HOLD", facts=_retrieval_facts())
    assert not connection.in_transaction
    assert connection.execute("SELECT count(*) FROM ledger").fetchone()[0] == 2
    assert journal.progress[revision] == before
    assert NativeRevisionJournal(connection).progress[revision] == before
    connection.close()
