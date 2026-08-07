from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority.migrations import apply_pending_migrations
from newsroom.increment5.named_tool_authority_adapters import (
    COLLISION_NAMESPACE,
    CollisionHydrationNamedToolPort,
    NamedAuthorityAdapterConfig,
    SourceRevisionImpactNamedToolPort,
)
from newsroom.increment5.named_tool_authority_execution import (
    AUTHORITY_TOOL_MODES,
    NamedAuthorityExecutionJournal,
    NamedAuthorityExecutionOutcome,
    NamedAuthorityExecutionReason,
    NamedAuthorityExecutionReceipt,
    NamedAuthorityMode,
    NamedAuthorityPortRegistry,
    NamedToolAuthorityExecutionError,
    NamedToolAuthorityExecutor,
)
from newsroom.increment5.named_tool_authorization import (
    NamedToolAuthorizationGrant,
    NamedToolAuthorizationJournal,
    NamedToolAuthorizer,
    NamedToolGateOutcome,
    NamedToolGrantRegistry,
)
from newsroom.increment5.named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    CollisionHydrationLookupToolRequest,
    NamedToolEnvelope,
    NamedToolId,
    NamedToolPurpose,
    SourceRevisionImpactLookupToolRequest,
    ToolScope,
)


SERVING = "2026-08-06T09:00:00Z"
QUERY_VALID = "2026-08-06T08:59:00Z"
VALID_FROM = "2026-01-01T00:00:00Z"
VALID_UNTIL = "2027-01-01T00:00:00Z"
POLICY_DIGEST = "sha256:" + hashlib.sha256(b"named-policy").hexdigest()
PRINCIPAL_DIGEST = "sha256:" + hashlib.sha256(b"triage-principal").hexdigest()
COLLISION_DIGEST = "sha256:" + hashlib.sha256(b"collision").hexdigest()


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def envelope(
    *,
    tool_id: NamedToolId,
    purpose: NamedToolPurpose,
    scope: ToolScope,
    grant_id: str,
    idempotency_key: str | None = None,
    result_limit: int = 8,
    response_limit_bytes: int = 262_144,
    **overrides: object,
) -> NamedToolEnvelope:
    values: dict[str, object] = {
        "request_id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key or f"authority:{uuid.uuid4()}",
        "tool_id": tool_id,
        "actor_id": "triage_worker",
        "authenticated_principal_digest": PRINCIPAL_DIGEST,
        "authorization_grant_id": grant_id,
        "purpose": purpose,
        "policy_id": NAMED_TOOL_POLICY_ID,
        "policy_digest": POLICY_DIGEST,
        "contract_digest": NAMED_TOOL_CONTRACT_DIGEST,
        "profile_id": NAMED_TOOL_PROFILE_ID,
        "generation_id": "retrieval-generation-v1",
        "query_valid_time": QUERY_VALID,
        "serving_time": SERVING,
        "requested_scope": scope,
        "result_limit": result_limit,
        "timeout_ms": 5_000,
        "response_limit_bytes": response_limit_bytes,
    }
    values.update(overrides)
    return NamedToolEnvelope(**values)


def collision_request(
    *,
    object_ids: tuple[str, ...] = ("object:001",),
    passage_ids: tuple[str, ...] = ("passage:001",),
    idempotency_key: str | None = None,
    result_limit: int = 8,
    **overrides: object,
) -> CollisionHydrationLookupToolRequest:
    dimensions: dict[str, tuple[str, ...]] = {
        "collision_namespace": (COLLISION_NAMESPACE,)
    }
    if object_ids:
        dimensions["authority_object_id"] = object_ids
    if passage_ids:
        dimensions["passage_id"] = passage_ids
    return CollisionHydrationLookupToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
            purpose=NamedToolPurpose.COLLISION_CHECK,
            scope=ToolScope.from_dimensions(**dimensions),
            grant_id="grant:collision",
            idempotency_key=idempotency_key,
            result_limit=result_limit,
            **overrides,
        ),
        collision_namespace=COLLISION_NAMESPACE,
        collision_key_digest=COLLISION_DIGEST,
        authority_object_ids=object_ids,
        passage_ids=passage_ids,
        require_current_collision=True,
    )


def impact_request(
    *,
    revision_id: str | None = None,
    include_superseded: bool = False,
    lineage_depth: int = 2,
    result_limit: int = 8,
    idempotency_key: str | None = None,
    **overrides: object,
) -> SourceRevisionImpactLookupToolRequest:
    source_id = "source:registry"
    dimensions: dict[str, tuple[str, ...]] = {"source_id": (source_id,)}
    if revision_id is not None:
        dimensions["revision_id"] = (revision_id,)
    return SourceRevisionImpactLookupToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP,
            purpose=NamedToolPurpose.SOURCE_IMPACT,
            scope=ToolScope.from_dimensions(**dimensions),
            grant_id="grant:impact",
            idempotency_key=idempotency_key,
            result_limit=result_limit,
            **overrides,
        ),
        source_id=source_id,
        revision_id=revision_id,
        window_start="2026-07-07T00:00:00Z",
        window_end="2026-08-07T00:00:00Z",
        lineage_depth=lineage_depth,
        include_superseded=include_superseded,
    )


def grant_for(request) -> NamedToolAuthorizationGrant:
    return NamedToolAuthorizationGrant.create(
        grant_id=request.envelope.authorization_grant_id,
        actor_id=request.envelope.actor_id,
        authenticated_principal_digest=request.envelope.authenticated_principal_digest,
        tool_id=request.envelope.tool_id,
        purposes=(request.envelope.purpose,),
        scope=request.envelope.requested_scope,
        valid_from="2026-08-01T00:00:00Z",
        valid_to="2026-09-01T00:00:00Z",
        policy_id=request.envelope.policy_id,
        policy_digest=request.envelope.policy_digest,
        contract_digest=request.envelope.contract_digest,
        profile_id=request.envelope.profile_id,
        generation_id=request.envelope.generation_id,
    )


def authorize(tmp_path: Path, request, *, name: str = "auth.sqlite"):
    return NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant_for(request),)),
        journal=NamedToolAuthorizationJournal(tmp_path / name),
    ).authorize(request)


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE ledger_events(ledger_seq INTEGER PRIMARY KEY);
        CREATE TABLE development_candidates_v2(
            candidate_id TEXT PRIMARY KEY,
            semantic_collision_digest TEXT NOT NULL UNIQUE
        );
        CREATE TABLE object_admissions(
            admission_id TEXT PRIMARY KEY,rights_decision_id TEXT NOT NULL,
            blob_digest TEXT NOT NULL,object_class TEXT NOT NULL,
            allowed_use TEXT NOT NULL,security_scope TEXT NOT NULL,
            retention_scope TEXT NOT NULL,valid_from TEXT NOT NULL,
            valid_until TEXT,definition_digest TEXT NOT NULL,created_at TEXT NOT NULL
        );
        CREATE TABLE object_admission_heads(
            admission_id TEXT PRIMARY KEY,current_version INTEGER NOT NULL
        );
        CREATE TABLE object_admission_versions(
            admission_id TEXT NOT NULL,lifecycle_version INTEGER NOT NULL,
            state TEXT NOT NULL,reason_code TEXT NOT NULL,recorded_at TEXT NOT NULL,
            PRIMARY KEY(admission_id,lifecycle_version)
        );
        CREATE TABLE blob_identities(
            blob_digest TEXT PRIMARY KEY,size_bytes INTEGER NOT NULL
        );
        CREATE TABLE blob_lifecycle_heads(
            blob_digest TEXT PRIMARY KEY,current_version INTEGER NOT NULL
        );
        CREATE TABLE blob_lifecycle_versions(
            blob_digest TEXT NOT NULL,lifecycle_version INTEGER NOT NULL,
            state TEXT NOT NULL,integrity_state TEXT NOT NULL,recorded_at TEXT NOT NULL,
            PRIMARY KEY(blob_digest,lifecycle_version)
        );
        CREATE TABLE object_rights_decisions(
            rights_decision_id TEXT PRIMARY KEY,blob_digest TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,object_class TEXT NOT NULL,
            allowed_use TEXT NOT NULL,security_scope TEXT NOT NULL,
            retention_scope TEXT NOT NULL,allowed INTEGER NOT NULL,
            reason_code TEXT NOT NULL,decided_at TEXT NOT NULL,
            valid_from TEXT NOT NULL,valid_until TEXT,canonical_digest TEXT NOT NULL
        );
        CREATE TABLE object_access_decisions(
            access_decision_id TEXT PRIMARY KEY,
            hydration_policy_contract_digest TEXT NOT NULL,
            principal_id TEXT NOT NULL,authority_domain TEXT NOT NULL,
            purpose TEXT NOT NULL,admission_id TEXT NOT NULL,
            object_class TEXT NOT NULL,allowed_use TEXT NOT NULL,
            security_scope TEXT NOT NULL,retention_scope TEXT NOT NULL,
            byte_offset INTEGER NOT NULL,allowed_bytes INTEGER NOT NULL
        );
        CREATE TABLE extraction_run_passages(
            run_id TEXT NOT NULL,passage_id TEXT NOT NULL,admission_id TEXT NOT NULL,
            access_decision_id TEXT NOT NULL,
            hydration_policy_contract_digest TEXT NOT NULL,
            principal_id TEXT NOT NULL,authority_domain TEXT NOT NULL,
            purpose TEXT NOT NULL,object_class TEXT NOT NULL,
            allowed_use TEXT NOT NULL,security_scope TEXT NOT NULL,
            retention_scope TEXT NOT NULL,byte_offset INTEGER NOT NULL,
            byte_length INTEGER NOT NULL,blob_digest TEXT NOT NULL,
            text_digest TEXT NOT NULL,language TEXT NOT NULL,
            canonical_digest TEXT NOT NULL,PRIMARY KEY(run_id,passage_id)
        );
        CREATE TABLE source_definitions(
            definition_id TEXT PRIMARY KEY,name TEXT NOT NULL,
            editorial_purpose TEXT NOT NULL,canonical_digest TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE TABLE source_items(
            item_id TEXT PRIMARY KEY,definition_id TEXT NOT NULL,
            identity_digest TEXT NOT NULL
        );
        CREATE TABLE source_revisions(
            revision_id TEXT PRIMARY KEY,item_id TEXT NOT NULL,
            definition_id TEXT NOT NULL,definition_version_id TEXT NOT NULL,
            prior_revision_id TEXT,source_native_revision_token TEXT,
            permitted_state_digest TEXT NOT NULL,revision_identity_digest TEXT NOT NULL,
            observed_at TEXT NOT NULL,recorded_at TEXT NOT NULL
        );
        CREATE TABLE discovery_representations(
            representation_id TEXT PRIMARY KEY,revision_id TEXT NOT NULL,
            definition_id TEXT NOT NULL,definition_version_id TEXT NOT NULL,
            adapter_version TEXT NOT NULL,parser_version TEXT NOT NULL,
            normalizer_version TEXT NOT NULL,extraction_scope_version TEXT NOT NULL,
            permitted_fields_digest TEXT NOT NULL,representation_digest TEXT NOT NULL,
            producer_slot_digest TEXT NOT NULL,
            representation_identity_digest TEXT NOT NULL,
            produced_at TEXT NOT NULL,recorded_at TEXT NOT NULL,
            canonical_digest TEXT NOT NULL
        );
        CREATE TABLE discovery_occurrences(
            occurrence_id TEXT PRIMARY KEY,check_outcome_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,representation_id TEXT,
            definition_id TEXT NOT NULL,definition_version_id TEXT NOT NULL,
            occurrence_kind TEXT NOT NULL,observed_at TEXT NOT NULL,
            receipt_digest TEXT NOT NULL,semantic_digest TEXT NOT NULL,
            recorded_at TEXT NOT NULL,canonical_digest TEXT NOT NULL
        );
        """
    )
    connection.execute("INSERT INTO ledger_events VALUES(42)")


def seed_object(
    connection: sqlite3.Connection,
    *,
    admission_id: str = "object:001",
    passage_id: str | None = "passage:001",
    run_id: str = "run:001",
    allowed: int = 1,
    admission_state: str = "ACTIVE",
    blob_state: str = "ACTIVE",
    integrity_state: str = "VERIFIED",
    valid_until: str | None = VALID_UNTIL,
    rights_object_class: str = "EXTRACTION_PASSAGE",
) -> None:
    blob_digest = digest(f"blob:{admission_id}")
    rights_id = f"rights:{admission_id}"
    connection.execute(
        "INSERT INTO object_admissions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            admission_id,
            rights_id,
            blob_digest,
            "EXTRACTION_PASSAGE",
            "RETRIEVAL",
            "editorial",
            "retained",
            VALID_FROM,
            valid_until,
            digest("definition"),
            VALID_FROM,
        ),
    )
    connection.execute("INSERT INTO object_admission_heads VALUES(?,1)", (admission_id,))
    connection.execute(
        "INSERT INTO object_admission_versions VALUES(?,1,?,?,?)",
        (admission_id, admission_state, "OK", VALID_FROM),
    )
    connection.execute("INSERT INTO blob_identities VALUES(?,100)", (blob_digest,))
    connection.execute("INSERT INTO blob_lifecycle_heads VALUES(?,1)", (blob_digest,))
    connection.execute(
        "INSERT INTO blob_lifecycle_versions VALUES(?,1,?,?,?)",
        (blob_digest, blob_state, integrity_state, VALID_FROM),
    )
    connection.execute(
        "INSERT INTO object_rights_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rights_id,
            blob_digest,
            100,
            rights_object_class,
            "RETRIEVAL",
            "editorial",
            "retained",
            allowed,
            "ALLOWED" if allowed else "DENIED",
            VALID_FROM,
            VALID_FROM,
            valid_until,
            digest(f"rights:{admission_id}"),
        ),
    )
    if passage_id is None:
        return
    access_id = f"access:{run_id}:{passage_id}"
    connection.execute(
        "INSERT INTO object_access_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            access_id,
            digest("hydration-policy"),
            "triage_worker",
            "editorial",
            "AUTHORITY_HYDRATION",
            admission_id,
            "EXTRACTION_PASSAGE",
            "RETRIEVAL",
            "editorial",
            "retained",
            0,
            100,
        ),
    )
    connection.execute(
        "INSERT INTO extraction_run_passages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            passage_id,
            admission_id,
            access_id,
            digest("hydration-policy"),
            "triage_worker",
            "editorial",
            "AUTHORITY_HYDRATION",
            "EXTRACTION_PASSAGE",
            "RETRIEVAL",
            "editorial",
            "retained",
            0,
            50,
            blob_digest,
            digest(f"text:{passage_id}"),
            "EN_GB",
            digest(f"passage:{run_id}:{passage_id}"),
        ),
    )


def seed_impact(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO source_definitions VALUES(?,?,?,?,?)",
        (
            "source:registry",
            "Registry",
            "source impact",
            digest("source-definition"),
            "2026-07-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO source_items VALUES(?,?,?)",
        ("item:001", "source:registry", digest("item")),
    )
    for revision_id, prior, observed in (
        ("revision:001", None, "2026-08-01T00:00:00Z"),
        ("revision:002", "revision:001", "2026-08-02T00:00:00Z"),
    ):
        connection.execute(
            "INSERT INTO source_revisions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                revision_id,
                "item:001",
                "source:registry",
                "version:001",
                prior,
                revision_id,
                digest(f"state:{revision_id}"),
                digest(f"revision:{revision_id}"),
                observed,
                observed,
            ),
        )
        representation_id = f"representation:{revision_id}"
        connection.execute(
            "INSERT INTO discovery_representations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                representation_id,
                revision_id,
                "source:registry",
                "version:001",
                "adapter-v1",
                "parser-v1",
                "normalizer-v1",
                "scope-v1",
                digest("fields"),
                digest(f"representation:{revision_id}"),
                digest("slot"),
                digest(f"representation-identity:{revision_id}"),
                observed,
                observed,
                digest(f"representation-canonical:{revision_id}"),
            ),
        )
        connection.execute(
            "INSERT INTO discovery_occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"occurrence:{revision_id}",
                f"check:{revision_id}",
                revision_id,
                representation_id,
                "source:registry",
                "version:001",
                "FIRST_OBSERVED",
                observed,
                digest(f"occurrence-receipt:{revision_id}"),
                digest(f"occurrence-semantic:{revision_id}"),
                observed,
                digest(f"occurrence-canonical:{revision_id}"),
            ),
        )


def authority_database(tmp_path: Path) -> Path:
    path = tmp_path / "authority.sqlite"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        seed_object(connection)
        seed_impact(connection)
        connection.execute(
            "INSERT INTO development_candidates_v2 VALUES(?,?)",
            ("candidate:001", COLLISION_DIGEST),
        )
    return path


def ports(path: Path, *, minimum_ledger_seq: int = 0):
    config = NamedAuthorityAdapterConfig(
        authority_scope_id="authority:fixture",
        minimum_ledger_seq=minimum_ledger_seq,
    )
    return (
        CollisionHydrationNamedToolPort(
            authority_database=path,
            config=config,
        ),
        SourceRevisionImpactNamedToolPort(
            authority_database=path,
            config=config,
        ),
    )


def executor(tmp_path: Path, path: Path, *, selected_ports=None):
    selected = selected_ports or ports(path)
    return NamedToolAuthorityExecutor(
        registry=NamedAuthorityPortRegistry(selected),
        journal=NamedAuthorityExecutionJournal(tmp_path / "execution.sqlite"),
    )


def raw_payload(result) -> dict[str, object]:
    assert result.authority_receipt_bytes is not None
    value = json.loads(result.authority_receipt_bytes)
    assert isinstance(value, dict)
    return value


def test_authority_tool_inventory_and_registry_are_closed() -> None:
    assert AUTHORITY_TOOL_MODES == {
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP: (
            NamedAuthorityMode.COLLISION_HYDRATION
        ),
        NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP: (
            NamedAuthorityMode.SOURCE_REVISION_IMPACT
        ),
    }
    with pytest.raises(NamedToolAuthorityExecutionError, match="exactly two"):
        NamedAuthorityPortRegistry(())


def test_authorization_precedes_authority_dispatch(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = collision_request()
    unrelated = impact_request()
    denied = NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant_for(unrelated),)),
        journal=NamedToolAuthorizationJournal(tmp_path / "denied.sqlite"),
    ).authorize(request)
    assert denied.outcome is NamedToolGateOutcome.POLICY_BLOCKED
    result = executor(tmp_path, path).execute(request, denied)
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedAuthorityExecutionReason.LOCAL_AUTHORIZATION_BLOCKED
    assert result.receipt.authority_read_executed is False
    assert result.authority_receipt_bytes is None


def test_collision_tool_returns_current_collision_and_metadata_not_bytes(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = collision_request()
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.COMPLETE
    assert result.receipt.result_count == 3
    payload = raw_payload(result)
    assert payload["collision_state"] == "OCCUPIED"
    assert payload["candidate_id"] == "candidate:001"
    assert payload["object_bytes_returned"] is False
    assert payload["objects"][0]["usable"] is True
    assert payload["passages"][0]["usable"] is True
    assert "canonical_bytes" not in json.dumps(payload)


def test_rights_or_lifecycle_block_is_explicit_policy_block(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        seed_object(connection, allowed=0)
    request = collision_request()
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedAuthorityExecutionReason.AUTHORITY_NON_COMPLETE
    payload = raw_payload(result)
    assert payload["reason"] == "RIGHTS_OR_LIFECYCLE_BLOCKED"
    assert payload["objects"][0]["block_reason"] == "RIGHTS_DENIED"


def test_rights_metadata_mismatch_fails_closed_as_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        seed_object(connection, rights_object_class="WRONG_CLASS")
    request = collision_request()
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.UNAVAILABLE
    assert raw_payload(result)["reason"] == "AUTHORITY_INTEGRITY_ERROR"


def test_missing_and_ambiguous_passage_are_incomplete_without_choice(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        seed_object(connection)
        seed_object(
            connection,
            admission_id="object:002",
            passage_id="passage:001",
            run_id="run:002",
        )
    request = collision_request(object_ids=("object:001",), passage_ids=("passage:001",))
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.INCOMPLETE
    payload = raw_payload(result)
    assert payload["ambiguous_passage_ids"] == ["passage:001"]
    assert payload["passages"] == []


def test_collision_result_bound_is_not_silently_truncated(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = collision_request(result_limit=2)
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.INCOMPLETE
    assert result.receipt.reason is NamedAuthorityExecutionReason.RESULT_LIMIT_EXCEEDED
    payload = raw_payload(result)
    assert len(payload["objects"]) == 1
    assert len(payload["passages"]) == 1
    assert payload["candidate_id"] == "candidate:001"


def test_stale_watermark_is_explicit_and_reads_no_rows(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    selected = ports(path, minimum_ledger_seq=43)
    request = impact_request()
    result = executor(tmp_path, path, selected_ports=selected).execute(
        request, authorize(tmp_path, request)
    )
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.STALE
    assert raw_payload(result)["reason"] == "AUTHORITY_WATERMARK_STALE"


def test_source_impact_excludes_superseded_by_default_and_binds_depth(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = impact_request()
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.COMPLETE
    payload = raw_payload(result)
    assert [item["revision_id"] for item in payload["revisions"]] == ["revision:002"]
    assert len(payload["representations"]) == 1
    assert len(payload["occurrences"]) == 1
    assert result.receipt.result_count == 3

    historical = impact_request(
        include_superseded=True,
        lineage_depth=1,
        idempotency_key="impact:historical",
    )
    historical_result = executor(
        tmp_path,
        path,
    ).execute(
        historical,
        authorize(tmp_path, historical, name="auth-historical.sqlite"),
    )
    historical_payload = raw_payload(historical_result)
    assert [item["revision_id"] for item in historical_payload["revisions"]] == [
        "revision:001",
        "revision:002",
    ]
    assert historical_payload["representations"] == []
    assert historical_payload["occurrences"] == []


def test_exact_superseded_revision_is_no_match_unless_history_requested(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    current_only = impact_request(revision_id="revision:001")
    result = executor(tmp_path, path).execute(
        current_only, authorize(tmp_path, current_only)
    )
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.COMPLETE
    assert result.receipt.reason is NamedAuthorityExecutionReason.NO_MATCH
    assert result.receipt.no_match is True

    historical = impact_request(
        revision_id="revision:001",
        include_superseded=True,
        lineage_depth=1,
        idempotency_key="impact:revision-history",
    )
    second = executor(tmp_path, path).execute(
        historical,
        authorize(tmp_path, historical, name="auth-revision-history.sqlite"),
    )
    assert second.receipt.result_count == 1
    assert raw_payload(second)["revisions"][0]["revision_id"] == "revision:001"


def test_impact_result_bound_retains_raw_audit_rows(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = impact_request(result_limit=1)
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.INCOMPLETE
    assert result.receipt.reason is NamedAuthorityExecutionReason.RESULT_LIMIT_EXCEEDED
    payload = raw_payload(result)
    assert len(payload["revisions"]) == 1
    assert len(payload["representations"]) == 1
    assert len(payload["occurrences"]) == 1


def test_malformed_authority_timestamp_is_integrity_failure(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE source_revisions SET observed_at='not-a-time' WHERE revision_id='revision:002'"
        )
    request = impact_request()
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.UNAVAILABLE
    assert raw_payload(result)["reason"] == "AUTHORITY_INTEGRITY_ERROR"


def test_missing_schema_is_unavailable_not_no_match(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    request = impact_request()
    result = executor(tmp_path, path).execute(request, authorize(tmp_path, request))
    assert result.receipt.outcome is NamedAuthorityExecutionOutcome.UNAVAILABLE
    assert result.receipt.no_match is False
    assert raw_payload(result)["reason"] == "AUTHORITY_SCHEMA_UNAVAILABLE"


def test_journal_replay_tamper_and_semantic_conflict(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = collision_request(idempotency_key="authority:replay")
    auth = authorize(tmp_path, request)
    gate = executor(tmp_path, path)
    first = gate.execute(request, auth)
    replay = gate.execute(request, auth)
    assert replay.receipt.canonical_bytes == first.receipt.canonical_bytes
    assert replay.authority_receipt_bytes == first.authority_receipt_bytes

    with sqlite3.connect(tmp_path / "execution.sqlite") as connection:
        connection.execute(
            "UPDATE increment5_named_tool_authority_receipts SET authority_receipt_bytes=? WHERE idempotency_key=?",
            (b"tampered", request.envelope.idempotency_key),
        )
    with pytest.raises(NamedToolAuthorityExecutionError, match="raw authority"):
        gate.execute(request, auth)

    other = collision_request(
        object_ids=("object:001",),
        passage_ids=(),
        idempotency_key="authority:replay",
    )
    with pytest.raises(NamedToolAuthorityExecutionError, match="semantic conflict"):
        gate.execute(other, authorize(tmp_path, other, name="auth-other.sqlite"))


def test_execution_receipt_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = authority_database(tmp_path)
    request = impact_request()
    receipt = executor(tmp_path, path).execute(
        request, authorize(tmp_path, request)
    ).receipt
    raw = receipt.canonical_bytes.replace(
        b'"authority_effect":"NONE"',
        b'"authority_effect":"NONE","authority_effect":"NONE"',
        1,
    )
    with pytest.raises(NamedToolAuthorityExecutionError, match="duplicate keys"):
        NamedAuthorityExecutionReceipt.from_canonical_bytes(raw)


def test_fixed_queries_compile_against_complete_authority_schema(tmp_path: Path) -> None:
    path = tmp_path / "complete.sqlite"
    with sqlite3.connect(path, isolation_level=None) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        apply_pending_migrations(connection, applied_at="2026-08-07T00:00:00Z")
    collision = collision_request()
    collision_result = CollisionHydrationNamedToolPort(
        authority_database=path,
        config=NamedAuthorityAdapterConfig("authority:complete"),
    ).execute(collision)
    assert collision_result.attribution.outcome is NamedAuthorityExecutionOutcome.INCOMPLETE or (
        collision_result.attribution.outcome.value == "INCOMPLETE"
    )
    impact = impact_request()
    impact_result = SourceRevisionImpactNamedToolPort(
        authority_database=path,
        config=NamedAuthorityAdapterConfig("authority:complete"),
    ).execute(impact)
    assert impact_result.attribution.outcome.value == "COMPLETE"
    assert impact_result.attribution.no_match is True


def test_authority_modules_expose_no_raw_query_or_write_surface() -> None:
    import newsroom.increment5.named_tool_authority_adapters as adapters
    import newsroom.increment5.named_tool_authority_execution as execution

    source = (inspect.getsource(adapters) + inspect.getsource(execution)).lower()
    forbidden = (
        "run_sql",
        "raw_sql",
        "execute_script",
        "create_candidate",
        "admit_relation",
        "hydrate_object_bytes",
        "requests.",
        "httpx",
        "socket",
        "provider_call(",
    )
    assert not any(item in source for item in forbidden)
    assert "?mode=ro" in source
    assert "pragma query_only=on" in source
    assert "pragma trusted_schema=off" in source
