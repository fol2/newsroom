from __future__ import annotations

import inspect
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority._discovery_store import (
    _create_discovery_governing_producer_read_port,
)
from newsroom.authority._event_hypothesis_lineage_system import (
    _create_event_hypothesis_lineage_read_port,
)
from newsroom.authority.auth import StaticAuthorizer
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.story_candidate_migrations import STORY_CANDIDATE_MIGRATION_NAME
from newsroom.discovery import NewsLeadId
from newsroom.increment6.candidates import (
    CandidateAdmissionRequest,
    CandidateContractError,
    CandidateGoverningState,
    CandidateGoverningStateStatus,
    StoryCandidateAuthority,
    build_candidate_governing_manifest,
    candidate_command_definition,
    evaluate_candidate_admission,
    open_story_candidate_authority,
)
from newsroom.increment6.collision import (
    CandidateUseCollisionBinding,
    CandidateUseOperation,
    CurrentCollisionAuthoritySnapshot,
    CurrentCollisionEffectEnforcer,
    CurrentCollisionEligibilityRequest,
    CurrentCollisionReceiptEvidence,
    TrustedCurrentCollisionAuthorityBoundary,
)
from newsroom.increment6.dispositions import ProposalDispositionStore
from newsroom.increment6.lineage import lineage_command_definition
from newsroom.increment6.outcomes import CanonicalOutcome
from newsroom.increment6.relationships import (
    open_event_hypothesis_relationship_authority,
    relationship_command_definition,
)
from newsroom.tests import test_increment6d3_lineage as d3
from newsroom.tests import test_increment6d3_lineage_store as d3store
from newsroom.tests.graphiti_adapter_4d_migration_helpers import (
    drop_empty_v23_lineage_schema,
)
from newsroom.tests.test_increment5c2_named_tool_authority_execution import (
    COLLISION_DIGEST,
    QUERY_VALID,
    SERVING,
    authority_database,
    authorize,
    collision_request,
    executor,
)
from newsroom.tests.test_increment6e1_collision import (
    _enforcer,
    _occupied_evidence,
    _trusted_context,
)


def test_authority_api_consumes_the_exact_candidate_admission_contract() -> None:
    signature = inspect.signature(StoryCandidateAuthority.admit)
    assert "admission_bytes" in signature.parameters
    assert "request" not in signature.parameters
    assert "hypothesis_version_id" not in signature.parameters
    assert "relationship_assessment_digest" not in signature.parameters
    assert "disposition_ids" not in signature.parameters
    assert "collision_request" in signature.parameters
    assert "comparator_collision_request" in signature.parameters


def test_v24_allocates_only_exact_candidate_tables(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "authority.sqlite3", isolation_level=None)
    migrations.apply_pending_migrations(
        connection, applied_at="2042-01-01T00:00:00.000000Z"
    )
    assert connection.execute("PRAGMA user_version").fetchone() == (migrations.SCHEMA_VERSION,)
    assert connection.execute(
        "SELECT name FROM authority_migrations WHERE version=24"
    ).fetchone() == (STORY_CANDIDATE_MIGRATION_NAME,)
    retained_v5 = {"story_candidates", "story_candidate_versions"}
    assert {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'story_candidate_%'"
        )
    } - retained_v5 == {
        "story_candidate_heads",
        "story_candidate_admission_receipts_v2",
        "story_candidate_collision_bindings",
    }


@pytest.mark.parametrize(
    "failure", ("missing_trigger", "predecessor", "nonempty", "history", "version")
)
def test_v24_downgrade_preflight_is_non_mutating(tmp_path: Path, failure: str) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    migrations.apply_pending_migrations(
        connection, applied_at="2042-01-01T00:00:00.000000Z"
    )
    before = (
        connection.execute("PRAGMA user_version").fetchone(),
        tuple(connection.iterdump()),
    )
    if failure == "missing_trigger":
        connection.execute("DROP TRIGGER candidate_head_insert_guard")
    elif failure == "predecessor":
        connection.execute("DROP TRIGGER event_hypothesis_lineage_head_insert_guard")
    elif failure == "nonempty":
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO story_candidate_admission_receipts_v2(admission_digest,request_id,request_digest,actor_identity_digest,idempotency_key,authority_aggregate_id,authority_event_id,committed_admission_decision_id,admission_bytes,candidate_id,candidate_bytes,version_id,version_ordinal,version_bytes,version_digest,manifest_material_digest,semantic_scope_digest,hypothesis_version_id,relationship_assessment_digest,disposition_ids_bytes,collision_request_bytes,collision_request_digest,collision_decision_bytes,collision_decision_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "1" * 64,
                "11111111-1111-4111-8111-111111111111",
                "sha256:" + "2" * 64,
                "sha256:" + "3" * 64,
                "x",
                "22222222-2222-4222-8222-222222222222",
                "33333333-3333-4333-8333-333333333333",
                "66666666-6666-4666-8666-666666666666",
                b"x",
                "22222222-2222-4222-8222-222222222222",
                b"x",
                "55555555-5555-4555-8555-555555555555",
                1,
                b"x",
                "sha256:" + "9" * 64,
                "sha256:" + "4" * 64,
                "sha256:" + "5" * 64,
                "44444444-4444-4444-8444-444444444444",
                "sha256:" + "6" * 64,
                b"[]",
                b"{}",
                "sha256:" + "7" * 64,
                b"{}",
                "sha256:" + "8" * 64,
                "x",
            ),
        )
    elif failure == "history":
        connection.execute("DROP TRIGGER immutable_authority_migrations_update")
        connection.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=24",
            ("sha256:" + "f" * 64,),
        )
    else:
        connection.execute("PRAGMA user_version=29")
    damaged = (
        connection.execute("PRAGMA user_version").fetchone(),
        tuple(connection.iterdump()),
    )
    with pytest.raises(sqlite3.DatabaseError):
        drop_empty_v23_lineage_schema(connection)
    assert (
        connection.execute("PRAGMA user_version").fetchone(),
        tuple(connection.iterdump()),
    ) == damaged
    assert damaged != before


def test_real_new_candidate_admission_commits_and_exact_replay_skips_providers(
    tmp_path: Path,
) -> None:
    seed, args, _ = d3store._seed(tmp_path)
    version = seed[2]
    assessment, evidence = d3._decision(
        version, (), CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH
    )
    scopes = {
        relationship_command_definition().required_scope,
        lineage_command_definition().required_scope,
        candidate_command_definition().required_scope,
    }
    args["authorizer"] = StaticAuthorizer(
        policy_version="candidate-test-v1",
        grants_by_principal={"editor": frozenset(scopes), "other": frozenset(scopes)},
    )
    relationship = open_event_hypothesis_relationship_authority(**args)
    try:
        relationship.retain(
            assessment.canonical_bytes,
            tuple(item.canonical_bytes for item in evidence),
            proof=seed[0][3],
        )
    finally:
        relationship.close()

    binding = CandidateUseCollisionBinding(
        version.hypothesis_id,
        version.version_id,
        version.canonical_digest,
        CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        None,
        "candidate-development",
        COLLISION_DIGEST,
        "retrieval-generation-v2",
        QUERY_VALID,
        SERVING,
        42,
    )
    named = collision_request(
        idempotency_key=binding.idempotency_key, generation_id=binding.generation_id
    )
    collision_root = tmp_path / "collision"
    collision_root.mkdir()
    collision_db = authority_database(collision_root)
    with sqlite3.connect(collision_db) as connection:
        connection.execute("DELETE FROM development_candidates_v2")
    result = executor(collision_root, collision_db).execute(
        named, authorize(collision_root, named)
    )
    collision_request_value = CurrentCollisionEligibilityRequest(
        binding, named.request_digest
    )
    collision_evidence = CurrentCollisionReceiptEvidence(
        named, result.receipt.canonical_bytes, result.authority_receipt_bytes
    )
    context = _trusted_context(collision_evidence)
    snapshot = CurrentCollisionAuthoritySnapshot(collision_evidence, context)
    calls = []
    enforcer = CurrentCollisionEffectEnforcer(
        current_authority_provider=lambda request: calls.append(request) or snapshot,
        trusted_boundary=TrustedCurrentCollisionAuthorityBoundary(
            context.authority_scope_id,
            context.authority_profile_id,
            context.adapter_config_digest,
            context.port_registry_digest,
            context.port_id,
        ),
    )

    connection = sqlite3.connect(args["database"], isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    lineage = _create_event_hypothesis_lineage_read_port(
        connection,
        retrieval_authority=args["retrieval_authority"],
        authenticator=args["authenticator"],
        command_registry=args["command_registry"],
        payload_schemas=args["payload_schemas"],
        clock=args["clock"],
    )
    store = ProposalDispositionStore(
        connection, args["retrieval_authority"], args["authenticator"]
    )
    connection.execute("BEGIN IMMEDIATE")
    try:
        discovery_port = _create_discovery_governing_producer_read_port(connection)
        lineage_snapshot = lineage.require_current_producers_in_transaction(
            version.version_id, proof=seed[0][3]
        )
        retained_relationship = lineage.require_retained_relationship_in_transaction(
            assessment.canonical_digest
        )
        disposition_ids = tuple(
            sorted(item.disposition_id for item in version.source_bindings)
        )
        dispositions = tuple(
            store.require_current_in_transaction(item, proof=seed[0][3])
            for item in disposition_ids
        )
        lead_ids = tuple(
            sorted(
                {NewsLeadId.parse(item.decision_lead_id) for item in dispositions},
                key=str,
            )
        )
        discovery = discovery_port.require_current_governing_producers(lead_ids)
        from newsroom.increment6.collision import decide_current_collision_eligibility

        decision = decide_current_collision_eligibility(
            request=collision_request_value,
            evidence=collision_evidence,
            trusted_context=context,
        )
        manifest = build_candidate_governing_manifest(
            hypothesis_version=version,
            lineage_receipts=lineage_snapshot.receipts,
            lineage_initial_heads=lineage_snapshot.initial_heads,
            lineage_versions=lineage_snapshot.versions,
            lineage_relationship_proofs=lineage_snapshot.relationship_proofs,
            dispositions=dispositions,
            leads=tuple(x[0] for x in discovery),
            signals=tuple(x[1] for x in discovery),
            gates=tuple(x[2] for x in discovery),
            relationship=retained_relationship,
            collision=decision,
        )
    finally:
        connection.rollback()
        connection.close()
    authentication = args["authenticator"].authenticate(seed[0][3], now=args["clock"]())
    actor = digest_bytes(
        canonical_json_bytes(
            {
                "principal_id": authentication.principal_id,
                "credential_binding_digest": authentication.credential_binding_digest,
            }
        )
    )
    request = CandidateAdmissionRequest(
        str(uuid.uuid4()),
        actor,
        "candidate:e2e",
        None,
        None,
        0,
        manifest.semantic_scope_digest,
        collision_request_value.request_digest,
        manifest.governing_state_binding.canonical_digest,
        None,
    )
    admission = evaluate_candidate_admission(
        request=request,
        manifest=manifest,
        collision=decision,
        current_version=None,
        governing_state=CandidateGoverningState(
            CandidateGoverningStateStatus.COMPLETE, manifest.governing_state_binding
        ),
    )
    authority = open_story_candidate_authority(**args, collision_enforcer=enforcer)
    try:
        committed = authority.admit(
            admission.canonical_bytes,
            collision_request=collision_request_value,
            proof=seed[0][3],
        )
        assert committed.ordinal == 1
        assert len(calls) == 2
        calls.clear()
        replay = authority.admit(
            admission.canonical_bytes,
            collision_request=collision_request_value,
            proof=seed[0][3],
        )
        assert replay == committed and calls == []
        divergent = replace(
            admission,
            request=replace(
                admission.request, idempotency_key="candidate:e2e:divergent"
            ),
        )
        with pytest.raises(CandidateContractError, match="replay diverges"):
            authority.admit(
                divergent.canonical_bytes,
                collision_request=collision_request_value,
                proof=seed[0][3],
            )
        assert calls == []
    finally:
        authority.close()
    reopened = open_story_candidate_authority(**args, collision_enforcer=enforcer)
    try:
        assert reopened.load_version(committed.version_id) == committed
    finally:
        reopened.close()
    with sqlite3.connect(args["database"]) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='candidate_head_update_guard'"
        ).fetchone()[0]
        original = connection.execute(
            "SELECT updated_at FROM story_candidate_heads"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER candidate_head_update_guard")
        connection.execute(
            "UPDATE story_candidate_heads SET updated_at='2044-01-01T00:00:00Z'"
        )
        connection.execute(trigger)
    with pytest.raises(CandidateContractError):
        open_story_candidate_authority(**args, collision_enforcer=enforcer)
    with sqlite3.connect(args["database"]) as connection:
        connection.execute("DROP TRIGGER candidate_head_update_guard")
        connection.execute("UPDATE story_candidate_heads SET updated_at=?", (original,))
        connection.execute(trigger)
    with sqlite3.connect(args["database"]) as connection:
        connection.execute("DROP TRIGGER immutable_candidate_receipt")
        connection.execute(
            "UPDATE story_candidate_admission_receipts_v2 SET admission_bytes=?",
            (b"{}",),
        )
    with pytest.raises(CandidateContractError):
        open_story_candidate_authority(**args, collision_enforcer=enforcer)


class _CandidateOpeningSignal(BaseException):
    pass


class _CandidateClosingSignal(BaseException):
    pass


def _candidate_open_arguments(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "candidate-open"
    root.mkdir()
    _, args, _ = d3store._seed(root)
    scopes = {
        relationship_command_definition().required_scope,
        lineage_command_definition().required_scope,
        candidate_command_definition().required_scope,
    }
    args["authorizer"] = StaticAuthorizer(
        policy_version="candidate-open-v1",
        grants_by_principal={
            "editor": frozenset(scopes),
            "other": frozenset(scopes),
        },
    )
    collision_root = tmp_path / "candidate-collision"
    collision_root.mkdir()
    _, evidence = _occupied_evidence(collision_root)
    return {
        **args,
        "collision_enforcer": _enforcer(evidence),
        "busy_timeout_ms": 5_000,
    }


def test_second_public_candidate_writer_fails_until_first_closes(
    tmp_path: Path,
) -> None:
    arguments = _candidate_open_arguments(tmp_path)
    first = open_story_candidate_authority(**arguments)
    try:
        with pytest.raises(CandidateContractError, match="open failed"):
            open_story_candidate_authority(**arguments)
    finally:
        first.close()
    reopened = open_story_candidate_authority(**arguments)
    reopened.close()


@pytest.mark.parametrize("failure", ("lineage-port", "command-service"))
@pytest.mark.parametrize("error_type", (RuntimeError, _CandidateOpeningSignal))
def test_candidate_open_failure_preserves_signal_releases_lock_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    error_type: type[BaseException],
) -> None:
    from newsroom.authority import story_candidate_system as private

    arguments = _candidate_open_arguments(tmp_path)
    error = error_type("candidate opening failed")
    closed: list[object] = []
    original_close = private._CandidateStore.close

    def close_then_fail(store) -> None:
        closed.append(store)
        original_close(store)
        raise _CandidateClosingSignal("candidate closing failed")

    with monkeypatch.context() as scoped:
        scoped.setattr(private._CandidateStore, "close", close_then_fail)
        target = (
            "_create_event_hypothesis_lineage_read_port"
            if failure == "lineage-port"
            else "CommandService"
        )
        scoped.setattr(
            private,
            target,
            lambda *args, **kwargs: (_ for _ in ()).throw(error),
        )
        with pytest.raises(error_type) as caught:
            private.open_story_candidate_authority_system(**arguments)
        assert caught.value is error
        assert len(closed) == 1

    corrected = private.open_story_candidate_authority_system(**arguments)
    corrected.close()


def test_candidate_system_rejects_forged_facade_and_releases_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newsroom.authority import story_candidate_system as private

    arguments = _candidate_open_arguments(tmp_path)
    with monkeypatch.context() as scoped:
        scoped.setattr(
            private, "_compose_story_candidate_authority", lambda _: object()
        )
        with pytest.raises(CandidateContractError, match="facade differs"):
            private.open_story_candidate_authority_system(**arguments)

    corrected = private.open_story_candidate_authority_system(**arguments)
    corrected.close()
