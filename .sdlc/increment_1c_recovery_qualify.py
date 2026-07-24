from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old[:120]}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    store_path = "newsroom/authority/_integrated_store.py"
    replace_exact(
        store_path,
        '''        if (
            not versions
            or int(versions[0]["version_number"]) != 1''',
        '''        if (
            len(versions) != 1
            or int(versions[0]["version_number"]) != 1''',
    )
    replace_exact(
        store_path,
        '''        version = conn.execute(
            "SELECT candidate_id,fixture_id,route,retrieval_context_id,"
            "manifest_digest FROM story_candidate_versions "
            "WHERE candidate_version_id=?",
            (str(row["candidate_version_id"]),),
        ).fetchone()
        context = conn.execute(
            "SELECT context_digest FROM integrated_retrieval_contexts "
            "WHERE context_id=?",
            (str(row["retrieval_context_id"]),),
        ).fetchone()
        if (
            candidate is None
            or version is None
            or context is None
            or str(candidate["semantic_collision_digest"])
            != str(row["semantic_collision_digest"])
            or str(version["candidate_id"]) != str(row["candidate_id"])
            or str(version["fixture_id"]) != str(row["fixture_id"])
            or str(version["route"]) != str(row["route"])
            or str(version["retrieval_context_id"])
            != str(row["retrieval_context_id"])
            or str(version["manifest_digest"])
            != str(row["manifest_digest"])
            or str(context["context_digest"])
            != str(row["retrieval_context_digest"])
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision cross-record identity is inconsistent"
            )''',
        '''        version = conn.execute(
            "SELECT candidate_id,fixture_id,signal_id,lead_id,"
            "hypothesis_version_id,route,retrieval_context_id,"
            "manifest_digest FROM story_candidate_versions "
            "WHERE candidate_version_id=?",
            (str(row["candidate_version_id"]),),
        ).fetchone()
        context = conn.execute(
            "SELECT fixture_id,fixture_event_id,context_digest,manifest_digest "
            "FROM integrated_retrieval_contexts WHERE context_id=?",
            (str(row["retrieval_context_id"]),),
        ).fetchone()
        outcome = CandidateAdmissionOutcome(str(row["outcome"]))
        expected_collision = (
            None
            if version is None or context is None
            else digest_canonical(
                {
                    "contract": _COLLISION_CONTRACT,
                    "fixture_id": str(context["fixture_id"]),
                    "fixture_event_id": str(context["fixture_event_id"]),
                    "signal_id": str(version["signal_id"]),
                    "lead_id": str(version["lead_id"]),
                    "hypothesis_version_id": str(
                        version["hypothesis_version_id"]
                    ),
                    "route": str(version["route"]),
                    "manifest_digest": str(context["manifest_digest"]),
                }
            )
        )
        if (
            candidate is None
            or version is None
            or context is None
            or str(candidate["semantic_collision_digest"])
            != str(row["semantic_collision_digest"])
            or str(version["candidate_id"]) != str(row["candidate_id"])
            or str(version["fixture_id"]) != str(row["fixture_id"])
            or str(version["route"]) != str(row["route"])
            or str(version["manifest_digest"])
            != str(row["manifest_digest"])
            or str(context["fixture_id"]) != str(row["fixture_id"])
            or str(context["manifest_digest"])
            != str(row["manifest_digest"])
            or str(context["context_digest"])
            != str(row["retrieval_context_digest"])
            or expected_collision != str(row["semantic_collision_digest"])
            or (
                outcome is CandidateAdmissionOutcome.ADMITTED
                and str(version["retrieval_context_id"])
                != str(row["retrieval_context_id"])
            )
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision cross-record identity is inconsistent"
            )''',
    )
    replace_exact(
        store_path,
        '''            "payload_digest,object_admission_id,trust_scope,security_scope,"
            "retention_scope FROM ledger_events WHERE event_id=?",''',
        '''            "payload_digest,object_admission_id,trust_scope,security_scope,"
            "retention_scope,recorded_at FROM ledger_events WHERE event_id=?",''',
    )
    replace_exact(
        store_path,
        '''            or str(event["retention_scope"]) != "authority.audit"
        ):''',
        '''            or str(event["retention_scope"]) != "authority.audit"
            or str(event["recorded_at"]) != str(row["recorded_at"])
        ):''',
    )

    test_path = Path("newsroom/tests/test_integrated_c1_recovery_integrity.py")
    if test_path.exists():
        raise SystemExit(f"qualifier test path already exists: {test_path}")
    test_path.write_text(
        '''from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    UtcTimestamp,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.integrated import (
    CandidateAdmissionOutcome,
    IntegratedRetrievalContextId,
    StoryCandidateVersionId,
)

from .integrated_c1_helpers import (
    SECOND_PROPOSAL_ID,
    candidate_request,
    proof,
)
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{name}"')
    return sql


def test_recovery_equivalent_context_dedup_reopens_exactly(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    recovered_context = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
    )
    system = _open_candidate_system(database, state, graph)
    try:
        admitted = system.candidates.admit(
            candidate_request(graph.context),
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        deduplicated = system.candidates.admit(
            candidate_request(
                recovered_context,
                proposal_id=SECOND_PROPOSAL_ID,
                key="integrated-recovery-context-deduplicate",
            ),
            context=recovered_context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert admitted.outcome is CandidateAdmissionOutcome.ADMITTED
        assert deduplicated.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert deduplicated.candidate_id == admitted.candidate_id
        assert deduplicated.candidate_version_id == admitted.candidate_version_id
        assert deduplicated.retrieval_context_id == recovered_context.context_id
    finally:
        system.close()

    reopened = _open_candidate_system(database, state, graph)
    try:
        assert reopened.candidates.context(
            recovered_context.context_id,
            proof=proof(),
        ) == recovered_context
    finally:
        reopened.close()


def test_schema_v5_rejects_candidate_version_without_creation_authority(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
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

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM story_candidate_versions"
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        new_version_id = StoryCandidateVersionId.new()
        value["candidate_version_id"] = str(new_version_id)
        value["version_number"] = 2
        canonical = canonical_json_bytes(value)
        conn.execute(
            "INSERT INTO story_candidate_versions("
            "candidate_version_id,candidate_id,version_number,fixture_id,"
            "signal_id,lead_id,hypothesis_version_id,route,"
            "hypothesis_trust_scope,retrieval_context_id,manifest_digest,"
            "canonical_bytes,canonical_digest,recorded_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(new_version_id),
                str(row["candidate_id"]),
                2,
                str(row["fixture_id"]),
                str(row["signal_id"]),
                str(row["lead_id"]),
                str(row["hypothesis_version_id"]),
                str(row["route"]),
                str(row["hypothesis_trust_scope"]),
                str(row["retrieval_context_id"]),
                str(row["manifest_digest"]),
                canonical,
                digest_bytes(canonical),
                str(row["recorded_at"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="one exact ADMITTED immutable version",
    ):
        _open_candidate_system(database, state, graph)


def test_decision_time_must_equal_authority_event_time(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
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

    rewritten_time = UtcTimestamp.parse(
        "2030-01-01T00:00:00.000000Z"
    ).to_text()
    conn = sqlite3.connect(database)
    try:
        triggers = tuple(
            _disable_trigger(conn, name)
            for name in (
                "immutable_story_candidate_update",
                "immutable_story_candidate_version_update",
                "immutable_candidate_admission_decision_update",
            )
        )
        conn.execute(
            "UPDATE story_candidates SET created_at=?",
            (rewritten_time,),
        )
        conn.execute(
            "UPDATE story_candidate_versions SET recorded_at=?",
            (rewritten_time,),
        )
        conn.execute(
            "UPDATE candidate_admission_decisions SET recorded_at=?",
            (rewritten_time,),
        )
        for trigger in triggers:
            conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="exact authority event|recorded_at",
    ):
        _open_candidate_system(database, state, graph)
''',
        encoding="utf-8",
    )

    service_path = "newsroom/tests/test_integrated_c1_neo4j_service.py"
    replace_exact(
        service_path,
        '''        assert deduplicated.candidate_id == initial.candidate.candidate_id
        assert recovered_context.metadata.generation_id == recovery_generation

        rights, hydration, admissions = _policy_registries()''',
        '''        assert deduplicated.candidate_id == initial.candidate.candidate_id
        assert recovered_context.metadata.generation_id == recovery_generation
        assert controller.retained_context(
            recovered_context.context_id,
            proof=proof(),
        ) == recovered_context

        rights, hydration, admissions = _policy_registries()''',
    )


if __name__ == "__main__":
    main()
