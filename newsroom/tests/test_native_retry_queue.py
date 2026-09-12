from types import SimpleNamespace

from newsroom.control_plane.cycle import _queue
from newsroom.control_plane.store import connect, record_graphiti_failure
from newsroom.tests.test_native_graphiti import _native


def test_native_retry_queue_checks_dead_ingests_in_one_batch(tmp_path):
    connection = connect(str(tmp_path / "private.sqlite3"))
    retry, held, fresh = (_native(name) for name in ("retry", "held", "fresh"))
    for unit in (retry, held):
        for _ in range(3):
            record_graphiti_failure(
                connection, ingest_id=unit.ingest_id, source_id=unit.source_id,
                item_key=unit.item_key, outcome="FAILED", failure_code="LOCAL_REFUSAL",
            )
    connection.commit()
    calls = []

    def evidence_many(*, failed_attempts, max_attempts):
        calls.append((failed_attempts, max_attempts))
        return {
            unit.ingest_id: SimpleNamespace(
                zero_dispatch_attempts=(1,), settled_provider_attempts=(),
                unresolved_attempts=() if unit == retry else (2,),
            )
            for unit in (retry, held)
        }

    queued = _queue(
        connection, (retry, held, fresh),
        model_usage=SimpleNamespace(native_graphiti_ingest_retry_evidence_many=evidence_many),
    )
    assert calls == [({retry.ingest_id: 3, held.ingest_id: 3}, 6)]
    assert {row[-1].ingest_id for row in queued} == {retry.ingest_id, fresh.ingest_id}
    connection.close()
