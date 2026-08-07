from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.increment5.named_tool_authorization import (
    NamedToolAuthorizationError,
    NamedToolAuthorizationGrant,
    NamedToolAuthorizationJournal,
    NamedToolAuthorizationReceipt,
    NamedToolAuthorizer,
    NamedToolGateOutcome,
    NamedToolGateReason,
    NamedToolGrantRegistry,
)
from newsroom.increment5.named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    NAMED_TOOL_RESULT_LIMIT,
    NAMED_TOOL_TIMEOUT_LIMIT_MS,
    AdmittedGraphTraversalToolRequest,
    ExactAuthorityLookupToolRequest,
    ExactLookupKind,
    FullTextRetrievalToolRequest,
    NamedToolContractError,
    NamedToolEnvelope,
    NamedToolId,
    NamedToolLanguage,
    NamedToolPurpose,
    ToolScope,
)


PRINCIPAL_DIGEST = "sha256:" + hashlib.sha256(b"principal:triage").hexdigest()
OTHER_PRINCIPAL_DIGEST = "sha256:" + hashlib.sha256(b"principal:other").hexdigest()
POLICY_DIGEST = "sha256:" + hashlib.sha256(b"policy:named-tools").hexdigest()
OTHER_POLICY_DIGEST = "sha256:" + hashlib.sha256(b"policy:other").hexdigest()
GENERATION_ID = "retrieval-generation-v1"
VALID_FROM = "2026-08-01T00:00:00Z"
VALID_TO = "2026-09-01T00:00:00Z"
QUERY_VALID_TIME = "2026-08-06T08:59:00Z"
SERVING_TIME = "2026-08-06T09:00:00Z"
ZERO_DIGEST = "sha256:" + "0" * 64


def digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def envelope(
    *,
    tool_id: NamedToolId,
    purpose: NamedToolPurpose,
    scope: ToolScope,
    grant_id: str,
    idempotency_key: str | None = None,
    **overrides: object,
) -> NamedToolEnvelope:
    values: dict[str, object] = {
        "request_id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key or f"tool:{uuid.uuid4()}",
        "tool_id": tool_id,
        "actor_id": "triage_worker",
        "authenticated_principal_digest": PRINCIPAL_DIGEST,
        "authorization_grant_id": grant_id,
        "purpose": purpose,
        "policy_id": NAMED_TOOL_POLICY_ID,
        "policy_digest": POLICY_DIGEST,
        "contract_digest": NAMED_TOOL_CONTRACT_DIGEST,
        "profile_id": NAMED_TOOL_PROFILE_ID,
        "generation_id": GENERATION_ID,
        "query_valid_time": QUERY_VALID_TIME,
        "serving_time": SERVING_TIME,
        "requested_scope": scope,
        "result_limit": NAMED_TOOL_RESULT_LIMIT,
        "timeout_ms": NAMED_TOOL_TIMEOUT_LIMIT_MS,
        "response_limit_bytes": NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    }
    values.update(overrides)
    return NamedToolEnvelope(**values)


def fulltext_request(
    query_text: str = "harbour correction 港口更正",
    *,
    grant_id: str = "grant:fulltext",
    idempotency_key: str | None = None,
    **envelope_overrides: object,
) -> FullTextRetrievalToolRequest:
    languages = (
        NamedToolLanguage.EN_GB,
        NamedToolLanguage.MIXED,
        NamedToolLanguage.ZH_HANT_HK,
    )
    source_ids = ("source:legislature", "source:registry")
    scope = ToolScope.from_dimensions(
        language=tuple(item.value for item in languages),
        source_id=source_ids,
    )
    return FullTextRetrievalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=scope,
            grant_id=grant_id,
            idempotency_key=idempotency_key,
            **envelope_overrides,
        ),
        query_text=query_text,
        query_text_digest=digest_text(query_text),
        languages=languages,
        source_ids=source_ids,
    )


def exact_request(
    *,
    grant_id: str = "grant:exact",
    **envelope_overrides: object,
) -> ExactAuthorityLookupToolRequest:
    lookup = "source-native-001"
    scope = ToolScope.from_dimensions(
        lookup_kind=(ExactLookupKind.SOURCE_NATIVE_ID.value,)
    )
    return ExactAuthorityLookupToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=scope,
            grant_id=grant_id,
            **envelope_overrides,
        ),
        lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
        lookup_value=lookup,
        lookup_value_digest=digest_text(lookup),
    )


def graph_request(
    *,
    grant_id: str = "grant:graph",
    **envelope_overrides: object,
) -> AdmittedGraphTraversalToolRequest:
    root = "source:root"
    scope = ToolScope.from_dimensions(root_id=(root,))
    return AdmittedGraphTraversalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=scope,
            grant_id=grant_id,
            **envelope_overrides,
        ),
        root_id=root,
        root_identity_digest=digest_text(f"canonical-node:{root}"),
        maximum_depth=2,
        maximum_fanout=32,
        temporal_window_seconds=2_678_400,
    )


def grant_for(
    request,
    *,
    grant_id: str | None = None,
    actor_id: str | None = None,
    principal_digest: str | None = None,
    tool_id: NamedToolId | None = None,
    purposes: tuple[NamedToolPurpose, ...] | None = None,
    scope: ToolScope | None = None,
    valid_from: str = VALID_FROM,
    valid_to: str = VALID_TO,
    policy_id: str | None = None,
    policy_digest: str | None = None,
    contract_digest: str | None = None,
    profile_id: str | None = None,
    generation_id: str | None = None,
) -> NamedToolAuthorizationGrant:
    envelope_value = request.envelope
    return NamedToolAuthorizationGrant.create(
        grant_id=grant_id or envelope_value.authorization_grant_id,
        actor_id=actor_id or envelope_value.actor_id,
        authenticated_principal_digest=(
            principal_digest or envelope_value.authenticated_principal_digest
        ),
        tool_id=tool_id or envelope_value.tool_id,
        purposes=purposes or (envelope_value.purpose,),
        scope=scope or envelope_value.requested_scope,
        valid_from=valid_from,
        valid_to=valid_to,
        policy_id=policy_id or envelope_value.policy_id,
        policy_digest=policy_digest or envelope_value.policy_digest,
        contract_digest=contract_digest or envelope_value.contract_digest,
        profile_id=profile_id or envelope_value.profile_id,
        generation_id=generation_id or envelope_value.generation_id,
    )


def authorizer(
    tmp_path: Path,
    request,
    *,
    grant: NamedToolAuthorizationGrant | None = None,
    journal_name: str = "tool-authorization.sqlite",
) -> NamedToolAuthorizer:
    selected_grant = grant or grant_for(request)
    return NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((selected_grant,)),
        journal=NamedToolAuthorizationJournal(tmp_path / journal_name),
    )


def test_grant_is_content_addressed_and_canonical() -> None:
    request = fulltext_request()
    grant = grant_for(request)
    assert grant.grant_digest.startswith("sha256:")
    assert grant.contract_digest == NAMED_TOOL_CONTRACT_DIGEST
    assert grant.tool_id is request.envelope.tool_id
    assert grant.scope.contains(request.envelope.requested_scope)
    with pytest.raises(NamedToolContractError, match="grant digest"):
        replace(grant, grant_digest=ZERO_DIGEST)


def test_registry_digest_is_order_independent_and_rejects_duplicates() -> None:
    first_request = fulltext_request()
    second_request = exact_request()
    first = grant_for(first_request)
    second = grant_for(second_request)
    assert NamedToolGrantRegistry((first, second)).registry_digest == (
        NamedToolGrantRegistry((second, first)).registry_digest
    )
    with pytest.raises(NamedToolContractError, match="unique"):
        NamedToolGrantRegistry((first, first))
    with pytest.raises(NamedToolContractError, match="must not be empty"):
        NamedToolGrantRegistry(())


def test_exact_authorization_retains_no_branch_or_authority_execution(tmp_path: Path) -> None:
    request = fulltext_request()
    receipt = authorizer(tmp_path, request).authorize(request)
    assert receipt.outcome is NamedToolGateOutcome.AUTHORIZED
    assert receipt.reason is None
    assert receipt.local_tool_call_authorized is True
    assert receipt.request_digest == request.request_digest
    assert receipt.envelope_digest == request.envelope.envelope_digest
    assert receipt.grant_id == request.envelope.authorization_grant_id
    assert receipt.grant_digest == grant_for(request).grant_digest
    assert receipt.tool_id is request.envelope.tool_id
    assert receipt.purpose is request.envelope.purpose
    assert receipt.requested_scope_digest == request.envelope.requested_scope.scope_digest
    assert receipt.branch_executed is False
    assert receipt.authority_read_executed is False
    assert receipt.authority_effect == "NONE"
    assert receipt.qualification_authority_granted is False
    assert receipt.production_activation_authorized is False


def test_authorization_receipt_has_zero_external_execution_and_spend(tmp_path: Path) -> None:
    receipt = authorizer(tmp_path, exact_request()).authorize(exact_request())
    assert receipt.external_call_count == 0
    assert receipt.provider_call_count == 0
    assert receipt.model_call_count == 0
    assert receipt.embedding_call_count == 0
    assert receipt.provider_spend_micros == 0


def test_receipt_canonical_round_trip(tmp_path: Path) -> None:
    request = graph_request()
    receipt = authorizer(tmp_path, request).authorize(request)
    assert NamedToolAuthorizationReceipt.from_canonical_bytes(
        receipt.canonical_bytes
    ) == receipt
    assert receipt.receipt_digest.startswith("sha256:")


def test_unknown_grant_is_policy_blocked(tmp_path: Path) -> None:
    request = fulltext_request(grant_id="grant:missing")
    unrelated = grant_for(
        fulltext_request(grant_id="grant:other"),
        grant_id="grant:other",
    )
    gate = NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((unrelated,)),
        journal=NamedToolAuthorizationJournal(tmp_path / "unknown.sqlite"),
    )
    receipt = gate.authorize(request)
    assert receipt.outcome is NamedToolGateOutcome.POLICY_BLOCKED
    assert receipt.reason is NamedToolGateReason.GRANT_UNKNOWN
    assert receipt.grant_digest is None
    assert receipt.local_tool_call_authorized is False


@pytest.mark.parametrize(
    ("grant_change", "outcome", "reason"),
    [
        ({"actor_id": "other_worker"}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.ACTOR_MISMATCH),
        ({"principal_digest": OTHER_PRINCIPAL_DIGEST}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.PRINCIPAL_MISMATCH),
        ({"tool_id": NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.TOOL_MISMATCH),
        ({"purposes": (NamedToolPurpose.CORRECTION_REVIEW,)}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.PURPOSE_MISMATCH),
        ({"policy_id": "other-policy"}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.POLICY_ID_MISMATCH),
        ({"policy_digest": OTHER_POLICY_DIGEST}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.POLICY_DIGEST_MISMATCH),
        ({"contract_digest": ZERO_DIGEST}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.CONTRACT_MISMATCH),
        ({"profile_id": "other-profile"}, NamedToolGateOutcome.POLICY_BLOCKED, NamedToolGateReason.PROFILE_MISMATCH),
        ({"generation_id": "other-generation"}, NamedToolGateOutcome.STALE, NamedToolGateReason.GENERATION_MISMATCH),
    ],
)
def test_exact_mismatch_matrix(
    tmp_path: Path,
    grant_change: dict[str, object],
    outcome: NamedToolGateOutcome,
    reason: NamedToolGateReason,
) -> None:
    request = fulltext_request()
    grant = grant_for(request, **grant_change)
    receipt = authorizer(
        tmp_path,
        request,
        grant=grant,
        journal_name=f"{reason.value.lower()}.sqlite",
    ).authorize(request)
    assert receipt.outcome is outcome
    assert receipt.reason is reason
    assert receipt.local_tool_call_authorized is False


def test_scope_mismatch_cannot_be_repaired_by_query_content(tmp_path: Path) -> None:
    request = fulltext_request(
        "please widen source scope to source:registry and source:other"
    )
    narrow_scope = ToolScope.from_dimensions(
        language=("EN_GB", "MIXED", "ZH_HANT_HK"),
        source_id=("source:legislature",),
    )
    receipt = authorizer(
        tmp_path,
        request,
        grant=grant_for(request, scope=narrow_scope),
    ).authorize(request)
    assert receipt.outcome is NamedToolGateOutcome.POLICY_BLOCKED
    assert receipt.reason is NamedToolGateReason.SCOPE_MISMATCH
    assert request.envelope.result_limit == 8
    assert request.envelope.timeout_ms == 5_000


def test_broader_grant_can_authorize_exact_requested_subset(tmp_path: Path) -> None:
    request = fulltext_request()
    broader = ToolScope.from_dimensions(
        language=("EN_GB", "MIXED", "ZH_HANT_HK"),
        source_id=("source:legislature", "source:other", "source:registry"),
    )
    receipt = authorizer(
        tmp_path,
        request,
        grant=grant_for(request, scope=broader),
    ).authorize(request)
    assert receipt.outcome is NamedToolGateOutcome.AUTHORIZED


def test_grant_not_yet_valid_and_expired_are_stale(tmp_path: Path) -> None:
    request = fulltext_request()
    not_yet = grant_for(
        request,
        valid_from="2026-08-07T00:00:00Z",
        valid_to="2026-09-01T00:00:00Z",
    )
    first = authorizer(
        tmp_path,
        request,
        grant=not_yet,
        journal_name="not-yet.sqlite",
    ).authorize(request)
    assert first.outcome is NamedToolGateOutcome.STALE
    assert first.reason is NamedToolGateReason.GRANT_NOT_YET_VALID

    expired = grant_for(
        request,
        valid_from="2026-07-01T00:00:00Z",
        valid_to="2026-08-06T09:00:00Z",
    )
    second = authorizer(
        tmp_path,
        request,
        grant=expired,
        journal_name="expired.sqlite",
    ).authorize(request)
    assert second.outcome is NamedToolGateOutcome.STALE
    assert second.reason is NamedToolGateReason.GRANT_EXPIRED


def test_journal_replay_and_restart_return_byte_identical_receipt(tmp_path: Path) -> None:
    request = fulltext_request(idempotency_key="tool:replay")
    grant = grant_for(request)
    first = authorizer(tmp_path, request, grant=grant).authorize(request)
    replay = authorizer(tmp_path, request, grant=grant).authorize(request)
    assert replay.canonical_bytes == first.canonical_bytes
    assert replay.receipt_digest == first.receipt_digest


def test_same_request_is_deterministic_across_fresh_journals(tmp_path: Path) -> None:
    request = graph_request()
    grant = grant_for(request)
    first = authorizer(
        tmp_path,
        request,
        grant=grant,
        journal_name="first.sqlite",
    ).authorize(request)
    second = authorizer(
        tmp_path,
        request,
        grant=grant,
        journal_name="second.sqlite",
    ).authorize(request)
    assert first.decision_id == second.decision_id
    assert first.canonical_bytes == second.canonical_bytes


def test_journal_rejects_semantic_idempotency_conflict(tmp_path: Path) -> None:
    key = "tool:conflict"
    first_request = fulltext_request("first query", idempotency_key=key)
    second_request = fulltext_request("second query", idempotency_key=key)
    grant = grant_for(first_request)
    gate = authorizer(tmp_path, first_request, grant=grant)
    gate.authorize(first_request)
    with pytest.raises(NamedToolAuthorizationError, match="semantic conflict"):
        gate.authorize(second_request)


def test_journal_detects_retained_receipt_tamper(tmp_path: Path) -> None:
    request = fulltext_request(idempotency_key="tool:tamper")
    gate = authorizer(tmp_path, request)
    gate.authorize(request)
    path = tmp_path / "tool-authorization.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE increment5_named_tool_authorization_receipts SET receipt_bytes = ? WHERE idempotency_key = ?",
            (b"{}", request.envelope.idempotency_key),
        )
    with pytest.raises(NamedToolAuthorizationError, match="digest mismatch"):
        gate.authorize(request)


def test_concurrent_same_request_retains_one_decision(tmp_path: Path) -> None:
    request = fulltext_request(idempotency_key="tool:concurrent")
    gate = authorizer(tmp_path, request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _item: gate.authorize(request), range(16)))
    assert len({receipt.receipt_digest for receipt in receipts}) == 1
    with sqlite3.connect(tmp_path / "tool-authorization.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_named_tool_authorization_receipts"
        ).fetchone()[0] == 1


def test_journal_schema_contains_no_branch_authority_or_content_columns(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite"
    NamedToolAuthorizationJournal(path)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(increment5_named_tool_authorization_receipts)"
            )
        }
    assert columns == {
        "idempotency_key",
        "request_digest",
        "receipt_bytes",
        "receipt_digest",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("local_tool_call_authorized", 1),
        ("branch_executed", 0),
        ("authority_read_executed", 0.0),
        ("qualification_authority_granted", 0),
        ("production_activation_authorized", None),
    ),
)
def test_receipt_rejects_type_confused_boolean_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    request = exact_request()
    receipt = authorizer(tmp_path, request).authorize(request)
    with pytest.raises(NamedToolContractError, match=f"{field} must be boolean"):
        replace(receipt, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("external_call_count", False),
        ("provider_call_count", 0.0),
        ("model_call_count", None),
        ("embedding_call_count", "0"),
        ("provider_spend_micros", False),
    ),
)
def test_receipt_rejects_type_confused_integer_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    request = exact_request()
    receipt = authorizer(tmp_path, request).authorize(request)
    with pytest.raises(NamedToolContractError, match=f"{field} must be an integer"):
        replace(receipt, **{field: value})


def test_journal_rejects_canonical_type_confusion_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    request = fulltext_request(idempotency_key="tool:type-confusion")
    gate = authorizer(tmp_path, request)
    gate.authorize(request)
    path = tmp_path / "tool-authorization.sqlite"
    with sqlite3.connect(path) as connection:
        raw = bytes(
            connection.execute(
                "SELECT receipt_bytes FROM increment5_named_tool_authorization_receipts "
                "WHERE idempotency_key = ?",
                (request.envelope.idempotency_key,),
            ).fetchone()[0]
        )
        payload = json.loads(raw.decode("utf-8"))
        payload["branch_executed"] = 0
        tampered = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        connection.execute(
            "UPDATE increment5_named_tool_authorization_receipts "
            "SET receipt_bytes = ?, receipt_digest = ? WHERE idempotency_key = ?",
            (
                tampered,
                "sha256:" + hashlib.sha256(tampered).hexdigest(),
                request.envelope.idempotency_key,
            ),
        )
    with pytest.raises(NamedToolAuthorizationError, match="malformed"):
        gate.authorize(request)


def test_receipt_rejects_branch_execution_external_work_and_authority_claims(tmp_path: Path) -> None:
    request = exact_request()
    receipt = authorizer(tmp_path, request).authorize(request)
    with pytest.raises(NamedToolContractError, match="branch or authority execution"):
        replace(receipt, branch_executed=True)
    with pytest.raises(NamedToolContractError, match="external work or spend"):
        replace(receipt, provider_call_count=1)
    with pytest.raises(NamedToolContractError, match="authority effect"):
        replace(receipt, authority_effect="CANDIDATE_ADMISSION")
    with pytest.raises(NamedToolContractError, match="activation authority"):
        replace(receipt, production_activation_authorized=True)


def test_blocked_receipt_cannot_claim_local_authorization(tmp_path: Path) -> None:
    request = fulltext_request(grant_id="grant:missing")
    unrelated_request = fulltext_request(grant_id="grant:other")
    gate = NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant_for(unrelated_request),)),
        journal=NamedToolAuthorizationJournal(tmp_path / "blocked.sqlite"),
    )
    receipt = gate.authorize(request)
    with pytest.raises(NamedToolContractError, match="blocked/stale"):
        replace(receipt, local_tool_call_authorized=True)


def test_authorization_module_is_branch_neutral_and_has_no_operational_claim() -> None:
    import newsroom.increment5.named_tool_authorization as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "exact_retriever",
        "fulltext_retriever",
        "vector_retriever",
        "admitted_graph_retriever",
        "neo4j",
        "execute_branch",
        "hydrate_object",
        "create_candidate",
        "admit_relation",
        "dops-026",
        "dops-067",
    )
    assert not any(item in source for item in forbidden)
