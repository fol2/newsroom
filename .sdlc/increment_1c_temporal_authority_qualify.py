from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old[:120]}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    store = "newsroom/authority/_integrated_store.py"
    replace_exact(
        store,
        '''        event = conn.execute(
            "SELECT event_type,aggregate_type,aggregate_id,object_admission_id,"
            "payload_digest,trust_scope,security_scope,retention_scope "
            "FROM ledger_events WHERE event_id=?",
            (str(row["fixture_event_id"]),),
        ).fetchone()''',
        '''        event = conn.execute(
            "SELECT event_type,aggregate_type,aggregate_id,object_admission_id,"
            "payload_digest,trust_scope,security_scope,retention_scope,recorded_at "
            "FROM ledger_events WHERE event_id=?",
            (str(row["fixture_event_id"]),),
        ).fetchone()''',
    )
    replace_exact(
        store,
        '''            or str(event["security_scope"]) != "authority.protected"
            or str(event["retention_scope"]) != "source.short"
        ):''',
        '''            or str(event["security_scope"]) != "authority.protected"
            or str(event["retention_scope"]) != "source.short"
            or UtcTimestamp.parse(str(event["recorded_at"])).value
            > context.metadata.serving_time.value
        ):''',
    )
    replace_exact(
        store,
        '''        if not isinstance(cutoff, dict):
            raise AuthorityPersistenceError(
                "integrated hydration decision lacks an exact state cutoff"
            )
        if (
            str(access["admission_id"]) != str(row["admission_id"])''',
        '''        if not isinstance(cutoff, dict):
            raise AuthorityPersistenceError(
                "integrated hydration decision lacks an exact state cutoff"
            )
        blob = conn.execute(
            "SELECT b.size_bytes FROM object_admissions a "
            "JOIN blob_identities b ON b.blob_digest=a.blob_digest "
            "WHERE a.admission_id=?",
            (str(row["admission_id"]),),
        ).fetchone()
        if (
            blob is None
            or str(access["admission_id"]) != str(row["admission_id"])''',
    )
    replace_exact(
        store,
        '''            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) <= 0
            or cutoff.get("admission_id") != str(row["admission_id"])''',
        '''            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) != int(blob["size_bytes"])
            or str(access["decided_at"]) != str(row["recorded_at"])
            or access_value.get("decided_at") != str(row["recorded_at"])
            or cutoff.get("admission_id") != str(row["admission_id"])''',
    )

    replace_exact(
        store,
        '''        generation = conn.execute(
            "SELECT g.family_id,d.definition_version,d.projector_version,"
            "d.ontology_contract_digest,d.mapping_contract_digest "
            "FROM projection_generations g "
            "JOIN projection_families f ON f.family_id=g.family_id "
            "JOIN projection_family_definitions d "
            "ON d.definition_digest=f.definition_digest "
            "WHERE g.generation_id=?",
            (str(row["generation_id"]),),
        ).fetchone()
        active_version = conn.execute(
            "SELECT 1 FROM projection_generation_versions "
            "WHERE generation_id=? AND state='ACTIVE' LIMIT 1",
            (str(row["generation_id"]),),
        ).fetchone()
        checkpoint = conn.execute(
            "SELECT 1 FROM projection_checkpoint_versions "
            "WHERE generation_id=? AND contiguous_ledger_seq=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
            ),
        ).fetchone()
        validation = conn.execute(
            "SELECT 1 FROM projection_generation_validations "
            "WHERE generation_id=? AND checkpoint_ledger_seq=? "
            "AND ontology_contract_digest=? AND mapping_contract_digest=? "
            "AND projector_version=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
                context.metadata.ontology_contract_digest,
                context.metadata.mapping_contract_digest,
                context.metadata.projector_version,
            ),
        ).fetchone()
        promotion = conn.execute(
            "SELECT 1 FROM projection_generation_promotions "
            "WHERE generation_id=? AND checkpoint_ledger_seq<=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
            ),
        ).fetchone()''',
        '''        serving_time = context.metadata.serving_time
        serving_text = serving_time.to_text()
        generation = conn.execute(
            "SELECT g.family_id,f.definition_digest,d.definition_version,"
            "d.projector_version,d.ontology_contract_digest,"
            "d.mapping_contract_digest FROM projection_generations g "
            "JOIN projection_families f ON f.family_id=g.family_id "
            "JOIN projection_family_definitions d "
            "ON d.definition_digest=f.definition_digest "
            "WHERE g.generation_id=?",
            (str(row["generation_id"]),),
        ).fetchone()
        active_version = conn.execute(
            "SELECT state,recorded_at FROM projection_generation_versions "
            "WHERE generation_id=? AND recorded_at<=? "
            "ORDER BY lifecycle_version DESC LIMIT 1",
            (str(row["generation_id"]), serving_text),
        ).fetchone()
        checkpoint = conn.execute(
            "SELECT recorded_at FROM projection_checkpoint_versions "
            "WHERE generation_id=? AND contiguous_ledger_seq=? "
            "AND recorded_at<=? ORDER BY checkpoint_version DESC LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
                serving_text,
            ),
        ).fetchone()
        validation = conn.execute(
            "SELECT recorded_at FROM projection_generation_validations "
            "WHERE generation_id=? AND checkpoint_ledger_seq=? "
            "AND definition_digest=? AND ontology_contract_digest=? "
            "AND mapping_contract_digest=? AND projector_version=? "
            "AND recorded_at<=? ORDER BY validation_version DESC LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
                None if generation is None else str(generation["definition_digest"]),
                context.metadata.ontology_contract_digest,
                context.metadata.mapping_contract_digest,
                context.metadata.projector_version,
                serving_text,
            ),
        ).fetchone()
        promotion = conn.execute(
            "SELECT recorded_at FROM projection_generation_promotions "
            "WHERE generation_id=? AND checkpoint_ledger_seq<=? "
            "AND recorded_at<=? ORDER BY recorded_at DESC LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
                serving_text,
            ),
        ).fetchone()''',
    )
    replace_exact(
        store,
        '''            or str(generation["mapping_contract_digest"])
            != context.metadata.mapping_contract_digest
            or active_version is None
            or checkpoint is None
            or validation is None
            or promotion is None
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks retained ACTIVE projection evidence"
            )''',
        '''            or str(generation["mapping_contract_digest"])
            != context.metadata.mapping_contract_digest
            or active_version is None
            or str(active_version["state"])
            != ProjectionGenerationState.ACTIVE.value
            or checkpoint is None
            or validation is None
            or promotion is None
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks retained ACTIVE projection evidence"
            )
        for evidence in (active_version, checkpoint, validation, promotion):
            if UtcTimestamp.parse(str(evidence["recorded_at"])).value > serving_time.value:
                raise AuthorityPersistenceError(
                    "integrated projection evidence postdates serving time"
                )''',
    )
    replace_exact(
        store,
        '''                or digest_canonical(asdict(source))
                != str(index_row["first_source_event_digest"])
            ):
                raise AuthorityPersistenceError(
                    "integrated exact index source event differs from ledger authority"
                )

    def _validate_candidate_version_row(''',
        '''                or digest_canonical(asdict(source))
                != str(index_row["first_source_event_digest"])
                or UtcTimestamp.parse(source.recorded_at).value
                > serving_time.value
            ):
                raise AuthorityPersistenceError(
                    "integrated exact index source event differs from ledger authority"
                )

        for relation in context.relations:
            source = self._source_event(conn, relation.ledger_seq)
            if (
                source.event_id != relation.source_event_id
                or source.event_type != relation.source_event_type
                or digest_canonical(asdict(source))
                != relation.source_event_digest
                or source.aggregate_type != relation.aggregate_type
                or source.aggregate_id != relation.aggregate_id
                or source.aggregate_version != relation.aggregate_version
                or source.payload_id != relation.payload_id
                or source.payload_digest != relation.payload_digest
                or source.object_admission_id != relation.object_admission_id
                or source.principal_id != relation.principal_id
                or source.trust_scope != relation.trust_scope.value
                or source.security_scope != relation.security_scope
                or source.retention_scope != relation.retention_scope
                or source.recorded_at != relation.recorded_at.to_text()
                or UtcTimestamp.parse(source.recorded_at).value
                > serving_time.value
            ):
                raise AuthorityPersistenceError(
                    "integrated graph relation differs from ledger authority"
                )

    def _validate_candidate_version_row(''',
    )

    test_path = Path("newsroom/tests/test_integrated_c1_temporal_authority.py")
    if test_path.exists():
        raise SystemExit(f"qualifier test path already exists: {test_path}")
    test_path.write_text(
        '''from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    UtcTimestamp,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.integrated import IntegratedRetrievalContextId

from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import (
    build_active_graph_context,
    candidate_request,
    proof,
    seed_fixture_authority,
)
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)
from .test_integrated_c1_context_integrity_faults import _insert_context


LATER = UtcTimestamp(FIXED_NOW.value + timedelta(minutes=1))


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{name}"')
    return sql


def _admit_primary(database, state, graph) -> None:
    system = _open_candidate_system(database, state, graph)
    try:
        system.candidates.admit(
            candidate_request(graph.context),
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
    finally:
        system.close()


def test_reopen_rejects_context_served_before_generation_activation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    state = seed_fixture_authority(
        database,
        object_root=object_root,
        clock=lambda: FIXED_NOW,
    )
    graph = build_active_graph_context(
        database,
        state,
        object_root=object_root,
        clock=lambda: LATER,
    )
    premature = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        metadata=replace(
            graph.context.metadata,
            serving_time=FIXED_NOW,
        ),
    )
    _insert_context(
        database,
        replace(graph, context=premature),
        premature.canonical_value(),
    )

    with pytest.raises(
        AuthorityPersistenceError,
        match="ACTIVE projection evidence",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_context_time_rebound_from_hydration_decision(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)
    conn = sqlite3.connect(database)
    try:
        trigger = _disable_trigger(conn, "immutable_integrated_context_update")
        conn.execute(
            "UPDATE integrated_retrieval_contexts SET recorded_at=?",
            (LATER.to_text(),),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="hydration decision",
    ):
        _open_candidate_system(database, state, graph)


@pytest.mark.parametrize(
    ("table", "trigger"),
    (
        (
            "projection_generation_validations",
            "immutable_projection_generation_validation_update",
        ),
        (
            "projection_generation_promotions",
            "immutable_projection_generation_promotion_update",
        ),
    ),
)
def test_reopen_rejects_projection_evidence_recorded_after_serving(
    tmp_path: Path,
    table: str,
    trigger: str,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)
    conn = sqlite3.connect(database)
    try:
        trigger_sql = _disable_trigger(conn, trigger)
        conn.execute(f'UPDATE "{table}" SET recorded_at=?', (LATER.to_text(),))
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="ACTIVE projection evidence|postdates serving",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_partial_hydration_rebinding(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        trigger = _disable_trigger(
            conn,
            "immutable_object_access_decisions_update",
        )
        row = conn.execute("SELECT * FROM object_access_decisions").fetchone()
        assert row is not None and int(row["allowed_bytes"]) > 1
        allowed = int(row["allowed_bytes"]) - 1
        cutoff = json.loads(bytes(row["state_cutoff_bytes"]).decode("utf-8"))
        canonical = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        cutoff["length"] = allowed
        cutoff_bytes = canonical_json_bytes(cutoff)
        cutoff_digest = digest_bytes(cutoff_bytes)
        canonical["allowed_bytes"] = allowed
        canonical["state_cutoff"] = cutoff
        canonical["state_cutoff_digest"] = cutoff_digest
        canonical_bytes = canonical_json_bytes(canonical)
        conn.execute(
            "UPDATE object_access_decisions SET allowed_bytes=?,"
            "state_cutoff_bytes=?,state_cutoff_digest=?,canonical_bytes=?,"
            "canonical_digest=?",
            (
                allowed,
                cutoff_bytes,
                cutoff_digest,
                canonical_bytes,
                digest_bytes(canonical_bytes),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="hydration decision",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_relation_rebound_from_ledger_authority(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    relations = list(graph.context.relations)
    relations[0] = replace(relations[0], principal_id="principal.tampered")
    tampered = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        relations=tuple(relations),
    )
    _insert_context(
        database,
        replace(graph, context=tampered),
        tampered.canonical_value(),
    )

    with pytest.raises(
        AuthorityPersistenceError,
        match="graph relation.*ledger authority",
    ):
        _open_candidate_system(database, state, graph)
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
