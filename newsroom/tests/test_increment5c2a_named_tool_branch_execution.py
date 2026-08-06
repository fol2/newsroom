from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from newsroom.increment5.named_tool_authorization import (
    NamedToolAuthorizationGrant,
    NamedToolAuthorizationJournal,
    NamedToolAuthorizationReceipt,
    NamedToolAuthorizer,
    NamedToolGateOutcome,
    NamedToolGrantRegistry,
)
from newsroom.increment5.named_tool_branch_execution import (
    BRANCH_TOOL_MODES,
    AttributedBranchResult,
    BranchComponentIdentity,
    BranchReceiptAttribution,
    NamedBranchMode,
    NamedBranchOutcome,
    NamedBranchPortRegistry,
    NamedToolBranchExecutionError,
    NamedToolBranchExecutor,
    NamedToolExecutionJournal,
    NamedToolExecutionOutcome,
    NamedToolExecutionReason,
    NamedToolExecutionReceipt,
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
    FixedPointVectorRetrievalToolRequest,
    FullTextRetrievalToolRequest,
    NamedToolContractError,
    NamedToolEnvelope,
    NamedToolId,
    NamedToolLanguage,
    NamedToolPurpose,
    SourceRevisionImpactLookupToolRequest,
    ToolScope,
)


PRINCIPAL_DIGEST = "sha256:" + hashlib.sha256(b"principal:triage").hexdigest()
POLICY_DIGEST = "sha256:" + hashlib.sha256(b"policy:named-tools").hexdigest()
GENERATION_ID = "retrieval-generation-v1"
GENERATION_DIGEST = "sha256:" + hashlib.sha256(b"generation:v1").hexdigest()
VALID_FROM = "2026-08-01T00:00:00Z"
VALID_TO = "2026-09-01T00:00:00Z"
QUERY_VALID_TIME = "2026-08-06T08:59:00Z"
SERVING_TIME = "2026-08-06T09:00:00Z"


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def envelope(
    *,
    tool_id: NamedToolId,
    purpose: NamedToolPurpose,
    scope: ToolScope,
    grant_id: str,
    idempotency_key: str | None = None,
    result_limit: int = NAMED_TOOL_RESULT_LIMIT,
    response_limit_bytes: int = NAMED_TOOL_RESPONSE_LIMIT_BYTES,
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
        "result_limit": result_limit,
        "timeout_ms": NAMED_TOOL_TIMEOUT_LIMIT_MS,
        "response_limit_bytes": response_limit_bytes,
    }
    values.update(overrides)
    return NamedToolEnvelope(**values)


def exact_request(
    *,
    idempotency_key: str | None = None,
    grant_id: str = "grant:exact",
    **envelope_overrides: object,
) -> ExactAuthorityLookupToolRequest:
    lookup = "source-native-001"
    return ExactAuthorityLookupToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(
                lookup_kind=(ExactLookupKind.SOURCE_NATIVE_ID.value,)
            ),
            grant_id=grant_id,
            idempotency_key=idempotency_key,
            **envelope_overrides,
        ),
        lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
        lookup_value=lookup,
        lookup_value_digest=digest_text(lookup),
    )


def fulltext_request(
    query_text: str = "harbour correction 港口更正",
    *,
    idempotency_key: str | None = None,
    grant_id: str = "grant:fulltext",
    **envelope_overrides: object,
) -> FullTextRetrievalToolRequest:
    languages = (
        NamedToolLanguage.EN_GB,
        NamedToolLanguage.MIXED,
        NamedToolLanguage.ZH_HANT_HK,
    )
    source_ids = ("source:legislature", "source:registry")
    return FullTextRetrievalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(
                language=tuple(item.value for item in languages),
                source_id=source_ids,
            ),
            grant_id=grant_id,
            idempotency_key=idempotency_key,
            **envelope_overrides,
        ),
        query_text=query_text,
        query_text_digest=digest_text(query_text),
        languages=languages,
        source_ids=source_ids,
    )


def vector_request(
    *,
    idempotency_key: str | None = None,
    grant_id: str = "grant:vector",
    **envelope_overrides: object,
) -> FixedPointVectorRetrievalToolRequest:
    query_id = "query:harbour-development"
    return FixedPointVectorRetrievalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(fixture_query=(query_id,)),
            grant_id=grant_id,
            idempotency_key=idempotency_key,
            **envelope_overrides,
        ),
        fixture_query_id=query_id,
        fixture_query_digest=digest_text("fixture-query"),
    )


def graph_request(
    *,
    idempotency_key: str | None = None,
    grant_id: str = "grant:graph",
    **envelope_overrides: object,
) -> AdmittedGraphTraversalToolRequest:
    root = "source:root"
    return AdmittedGraphTraversalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(root_id=(root,)),
            grant_id=grant_id,
            idempotency_key=idempotency_key,
            **envelope_overrides,
        ),
        root_id=root,
        root_identity_digest=digest_text(f"canonical-node:{root}"),
        maximum_depth=2,
        maximum_fanout=32,
        temporal_window_seconds=2_678_400,
    )


def impact_request() -> SourceRevisionImpactLookupToolRequest:
    source = "source:registry"
    revision = "revision:registry:042"
    return SourceRevisionImpactLookupToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP,
            purpose=NamedToolPurpose.SOURCE_IMPACT,
            scope=ToolScope.from_dimensions(
                revision_id=(revision,),
                source_id=(source,),
            ),
            grant_id="grant:impact",
        ),
        source_id=source,
        revision_id=revision,
        window_start="2026-07-07T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
        lineage_depth=2,
        include_superseded=False,
    )


def grant_for(request) -> NamedToolAuthorizationGrant:
    return NamedToolAuthorizationGrant.create(
        grant_id=request.envelope.authorization_grant_id,
        actor_id=request.envelope.actor_id,
        authenticated_principal_digest=(
            request.envelope.authenticated_principal_digest
        ),
        tool_id=request.envelope.tool_id,
        purposes=(request.envelope.purpose,),
        scope=request.envelope.requested_scope,
        valid_from=VALID_FROM,
        valid_to=VALID_TO,
        policy_id=request.envelope.policy_id,
        policy_digest=request.envelope.policy_digest,
        contract_digest=request.envelope.contract_digest,
        profile_id=request.envelope.profile_id,
        generation_id=request.envelope.generation_id,
    )


def authorization(
    tmp_path: Path,
    request,
    *,
    journal_name: str | None = None,
) -> NamedToolAuthorizationReceipt:
    grant = grant_for(request)
    gate = NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant,)),
        journal=NamedToolAuthorizationJournal(
            tmp_path / (journal_name or f"auth-{request.envelope.tool_id.value}.sqlite")
        ),
    )
    return gate.authorize(request)


def denied_authorization(tmp_path: Path, request) -> NamedToolAuthorizationReceipt:
    unrelated = fulltext_request(grant_id="grant:unrelated")
    gate = NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant_for(unrelated),)),
        journal=NamedToolAuthorizationJournal(tmp_path / "denied-auth.sqlite"),
    )
    return gate.authorize(request)


def raw_branch_bytes(tool_id: NamedToolId, marker: str = "receipt") -> bytes:
    return json.dumps(
        {"marker": marker, "tool_id": tool_id.value},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def branch_result(
    request,
    *,
    outcome: NamedBranchOutcome = NamedBranchOutcome.COMPLETE,
    result_count: int = 1,
    reason: str | None = None,
    no_match: bool = False,
    raw: bytes | None = None,
    tool_id: NamedToolId | None = None,
    mode: NamedBranchMode | None = None,
    tool_request_digest: str | None = None,
    generation_id: str | None = GENERATION_ID,
    generation_digest: str | None = GENERATION_DIGEST,
    query_valid_time: str = QUERY_VALID_TIME,
    serving_time: str = SERVING_TIME,
) -> AttributedBranchResult:
    selected_tool = tool_id or request.envelope.tool_id
    selected_mode = mode or BRANCH_TOOL_MODES[selected_tool]
    selected_raw = raw or raw_branch_bytes(selected_tool)
    if outcome is NamedBranchOutcome.COMPLETE and result_count == 0:
        reason = "NO_MATCH"
        no_match = True
    if outcome is not NamedBranchOutcome.COMPLETE and reason is None:
        reason = "BRANCH_NON_COMPLETE"
    attribution = BranchReceiptAttribution(
        tool_request_digest=tool_request_digest or request.request_digest,
        tool_id=selected_tool,
        branch_mode=selected_mode,
        branch_schema_version="newsroom.increment5.branch-receipt.v1",
        branch_request_digest=digest_text(
            f"branch-request:{selected_tool.value}:{request.request_digest}"
        ),
        branch_receipt_digest=digest_bytes(selected_raw),
        branch_profile_id=f"profile:{selected_mode.value.lower()}",
        branch_generation_id=generation_id,
        branch_generation_digest=generation_digest,
        component_identities=(
            BranchComponentIdentity(
                name="branch_component",
                digest=digest_text(f"component:{selected_mode.value}"),
            ),
            BranchComponentIdentity(
                name="retrieval_contract",
                digest=digest_text("retrieval-contract"),
            ),
        ),
        query_valid_time=query_valid_time,
        serving_time=serving_time,
        outcome=outcome,
        reason=reason,
        result_count=result_count,
        no_match=no_match,
        branch_receipt_bytes=len(selected_raw),
    )
    return AttributedBranchResult(
        attribution=attribution,
        branch_receipt_bytes=selected_raw,
    )


class FakePort:
    def __init__(
        self,
        *,
        port_id: str,
        tool_id: NamedToolId,
        branch_mode: NamedBranchMode,
        producer: Callable[[object], object] | None = None,
    ) -> None:
        self.port_id = port_id
        self.tool_id = tool_id
        self.branch_mode = branch_mode
        self.producer = producer or (lambda request: branch_result(request))
        self.calls: list[object] = []

    def execute(self, request):
        self.calls.append(request)
        return self.producer(request)


def ports(
    *,
    override: dict[NamedToolId, FakePort] | None = None,
) -> tuple[FakePort, ...]:
    selected = {
        tool_id: FakePort(
            port_id=f"port:{mode.value.lower()}",
            tool_id=tool_id,
            branch_mode=mode,
        )
        for tool_id, mode in BRANCH_TOOL_MODES.items()
    }
    if override:
        selected.update(override)
    return tuple(selected[tool_id] for tool_id in BRANCH_TOOL_MODES)


def executor(
    tmp_path: Path,
    *,
    selected_ports: tuple[FakePort, ...] | None = None,
    journal_name: str = "execution.sqlite",
) -> tuple[NamedToolBranchExecutor, tuple[FakePort, ...]]:
    chosen = selected_ports or ports()
    return (
        NamedToolBranchExecutor(
            registry=NamedBranchPortRegistry(chosen),
            journal=NamedToolExecutionJournal(tmp_path / journal_name),
        ),
        chosen,
    )


def port_for(chosen: tuple[FakePort, ...], tool_id: NamedToolId) -> FakePort:
    return next(port for port in chosen if port.tool_id is tool_id)


def test_branch_tool_mode_inventory_is_closed_and_exact() -> None:
    assert BRANCH_TOOL_MODES == {
        NamedToolId.EXACT_AUTHORITY_LOOKUP: NamedBranchMode.EXACT,
        NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: NamedBranchMode.FULL_TEXT,
        NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: NamedBranchMode.VECTOR,
        NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: NamedBranchMode.ADMITTED_GRAPH,
    }


def test_registry_requires_exactly_one_matching_port_per_tool() -> None:
    good = ports()
    registry = NamedBranchPortRegistry(good)
    assert registry.registry_digest.startswith("sha256:")
    with pytest.raises(NamedToolBranchExecutionError, match="exactly four"):
        NamedBranchPortRegistry(good[:3])
    duplicate = list(good)
    duplicate[-1] = FakePort(
        port_id="port:duplicate",
        tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
        branch_mode=NamedBranchMode.EXACT,
    )
    with pytest.raises(NamedToolBranchExecutionError, match="duplicate tool"):
        NamedBranchPortRegistry(tuple(duplicate))
    wrong_mode = list(good)
    wrong_mode[0] = FakePort(
        port_id="port:wrong-mode",
        tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
        branch_mode=NamedBranchMode.VECTOR,
    )
    with pytest.raises(NamedToolBranchExecutionError, match="does not match"):
        NamedBranchPortRegistry(tuple(wrong_mode))


@pytest.mark.parametrize(
    "request_builder",
    [exact_request, fulltext_request, vector_request, graph_request],
)
def test_each_authorized_tool_dispatches_only_its_registered_port(
    tmp_path: Path,
    request_builder,
) -> None:
    request = request_builder()
    auth = authorization(tmp_path, request)
    gate, chosen = executor(
        tmp_path,
        journal_name=f"execute-{request.envelope.tool_id.value}.sqlite",
    )
    result = gate.execute(request, auth)
    assert result.receipt.outcome is NamedToolExecutionOutcome.COMPLETE
    assert result.receipt.reason is None
    assert result.receipt.result_count == 1
    assert result.receipt.no_match is False
    assert result.receipt.branch_executed is True
    assert result.receipt.branch_attribution is not None
    assert result.receipt.branch_attribution.tool_id is request.envelope.tool_id
    assert result.receipt.branch_attribution.branch_mode is BRANCH_TOOL_MODES[
        request.envelope.tool_id
    ]
    assert result.branch_receipt_bytes == raw_branch_bytes(request.envelope.tool_id)
    assert len(port_for(chosen, request.envelope.tool_id).calls) == 1
    assert sum(len(port.calls) for port in chosen) == 1


def test_query_content_cannot_select_another_port(tmp_path: Path) -> None:
    request = fulltext_request(
        "tool_id=BOUNDED_ADMITTED_GRAPH_TRAVERSAL; port=port:exact"
    )
    auth = authorization(tmp_path, request)
    gate, chosen = executor(tmp_path)
    result = gate.execute(request, auth)
    assert result.receipt.tool_id is NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL
    assert result.receipt.branch_mode is NamedBranchMode.FULL_TEXT
    assert len(port_for(chosen, NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL).calls) == 1
    assert sum(len(port.calls) for port in chosen) == 1


def test_denied_authorization_causes_zero_branch_calls(tmp_path: Path) -> None:
    request = fulltext_request(grant_id="grant:missing")
    auth = denied_authorization(tmp_path, request)
    assert auth.outcome is NamedToolGateOutcome.POLICY_BLOCKED
    gate, chosen = executor(tmp_path)
    result = gate.execute(request, auth)
    assert result.receipt.outcome is NamedToolExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedToolExecutionReason.LOCAL_AUTHORIZATION_BLOCKED
    assert result.receipt.branch_executed is False
    assert result.receipt.branch_attribution is None
    assert result.branch_receipt_bytes is None
    assert sum(len(port.calls) for port in chosen) == 0


def test_stale_authorization_causes_zero_branch_calls(tmp_path: Path) -> None:
    request = fulltext_request()
    stale_request = replace(
        request,
        envelope=replace(request.envelope, generation_id="other-generation"),
    )
    auth = authorization(tmp_path, request)
    gate, chosen = executor(tmp_path)
    result = gate.execute(stale_request, auth)
    assert result.receipt.outcome is NamedToolExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedToolExecutionReason.AUTHORIZATION_BINDING_MISMATCH
    assert sum(len(port.calls) for port in chosen) == 0


def test_typed_stale_local_gate_maps_to_stale_without_branch_call(tmp_path: Path) -> None:
    request = fulltext_request()
    grant = replace(grant_for(request), generation_id="other-generation")
    # Rebuild the content-addressed grant after changing generation.
    grant = NamedToolAuthorizationGrant.create(
        grant_id=grant.grant_id,
        actor_id=grant.actor_id,
        authenticated_principal_digest=grant.authenticated_principal_digest,
        tool_id=grant.tool_id,
        purposes=grant.purposes,
        scope=grant.scope,
        valid_from=grant.valid_from,
        valid_to=grant.valid_to,
        policy_id=grant.policy_id,
        policy_digest=grant.policy_digest,
        contract_digest=grant.contract_digest,
        profile_id=grant.profile_id,
        generation_id="other-generation",
    )
    local = NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant,)),
        journal=NamedToolAuthorizationJournal(tmp_path / "stale-local.sqlite"),
    ).authorize(request)
    assert local.outcome is NamedToolGateOutcome.STALE
    gate, chosen = executor(tmp_path, journal_name="stale-execution.sqlite")
    result = gate.execute(request, local)
    assert result.receipt.outcome is NamedToolExecutionOutcome.STALE
    assert result.receipt.reason is NamedToolExecutionReason.LOCAL_AUTHORIZATION_BLOCKED
    assert sum(len(port.calls) for port in chosen) == 0


def test_port_failure_is_explicit_unavailable_without_branch_receipt(tmp_path: Path) -> None:
    request = graph_request()
    failing = FakePort(
        port_id="port:graph-failing",
        tool_id=NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
        branch_mode=NamedBranchMode.ADMITTED_GRAPH,
        producer=lambda _request: (_ for _ in ()).throw(RuntimeError("down")),
    )
    gate, chosen = executor(
        tmp_path,
        selected_ports=ports(
            override={NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: failing}
        ),
    )
    result = gate.execute(request, authorization(tmp_path, request))
    assert result.receipt.outcome is NamedToolExecutionOutcome.UNAVAILABLE
    assert result.receipt.reason is NamedToolExecutionReason.BRANCH_PORT_UNAVAILABLE
    assert result.receipt.branch_executed is False
    assert result.branch_receipt_bytes is None
    assert len(failing.calls) == 1


def test_non_attributed_port_result_is_invalid_not_complete(tmp_path: Path) -> None:
    request = exact_request()
    invalid = FakePort(
        port_id="port:invalid",
        tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
        branch_mode=NamedBranchMode.EXACT,
        producer=lambda _request: {"outcome": "COMPLETE"},
    )
    gate, _ = executor(
        tmp_path,
        selected_ports=ports(
            override={NamedToolId.EXACT_AUTHORITY_LOOKUP: invalid}
        ),
    )
    result = gate.execute(request, authorization(tmp_path, request))
    assert result.receipt.outcome is NamedToolExecutionOutcome.UNAVAILABLE
    assert result.receipt.reason is NamedToolExecutionReason.BRANCH_RECEIPT_INVALID
    assert result.receipt.branch_executed is False


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda request: branch_result(
            request,
            tool_request_digest=digest_text("other-tool-request"),
        ),
        lambda request: branch_result(
            request,
            tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
            mode=NamedBranchMode.EXACT,
        ),
        lambda request: branch_result(
            request,
            generation_id="other-generation",
            generation_digest=digest_text("other-generation"),
        ),
        lambda request: branch_result(
            request,
            query_valid_time="2026-08-06T08:58:59Z",
        ),
        lambda request: branch_result(
            request,
            serving_time="2026-08-06T09:00:01Z",
        ),
    ],
)
def test_mismatched_branch_attribution_fails_closed(
    tmp_path: Path,
    result_factory,
) -> None:
    request = fulltext_request()
    invalid = FakePort(
        port_id="port:mismatched",
        tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
        branch_mode=NamedBranchMode.FULL_TEXT,
        producer=result_factory,
    )
    gate, _ = executor(
        tmp_path,
        selected_ports=ports(
            override={NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: invalid}
        ),
        journal_name=f"mismatch-{uuid.uuid4()}.sqlite",
    )
    result = gate.execute(request, authorization(tmp_path, request, journal_name=f"auth-{uuid.uuid4()}.sqlite"))
    assert result.receipt.outcome is NamedToolExecutionOutcome.UNAVAILABLE
    assert result.receipt.reason is NamedToolExecutionReason.BRANCH_RECEIPT_INVALID
    assert result.receipt.branch_attribution is None
    assert result.branch_receipt_bytes is None


def test_complete_no_match_is_truthful_and_retains_branch_receipt(tmp_path: Path) -> None:
    request = exact_request()
    no_match = FakePort(
        port_id="port:exact-no-match",
        tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
        branch_mode=NamedBranchMode.EXACT,
        producer=lambda item: branch_result(item, result_count=0),
    )
    gate, _ = executor(
        tmp_path,
        selected_ports=ports(
            override={NamedToolId.EXACT_AUTHORITY_LOOKUP: no_match}
        ),
    )
    result = gate.execute(request, authorization(tmp_path, request))
    assert result.receipt.outcome is NamedToolExecutionOutcome.COMPLETE
    assert result.receipt.reason is NamedToolExecutionReason.NO_MATCH
    assert result.receipt.no_match is True
    assert result.receipt.result_count == 0
    assert result.receipt.branch_attribution is not None
    assert result.receipt.branch_attribution.reason == "NO_MATCH"
    assert result.branch_receipt_bytes is not None


@pytest.mark.parametrize(
    ("branch_outcome", "tool_outcome"),
    [
        (NamedBranchOutcome.INCOMPLETE, NamedToolExecutionOutcome.INCOMPLETE),
        (NamedBranchOutcome.POLICY_BLOCKED, NamedToolExecutionOutcome.POLICY_BLOCKED),
        (NamedBranchOutcome.STALE, NamedToolExecutionOutcome.STALE),
        (NamedBranchOutcome.UNAVAILABLE, NamedToolExecutionOutcome.UNAVAILABLE),
    ],
)
def test_non_complete_branch_outcomes_remain_explicit(
    tmp_path: Path,
    branch_outcome: NamedBranchOutcome,
    tool_outcome: NamedToolExecutionOutcome,
) -> None:
    request = vector_request()
    selected = FakePort(
        port_id=f"port:vector-{branch_outcome.value.lower()}",
        tool_id=NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
        branch_mode=NamedBranchMode.VECTOR,
        producer=lambda item: branch_result(
            item,
            outcome=branch_outcome,
            result_count=0,
            reason=f"VECTOR_{branch_outcome.value}",
        ),
    )
    gate, _ = executor(
        tmp_path,
        selected_ports=ports(
            override={
                NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: selected
            }
        ),
        journal_name=f"outcome-{branch_outcome.value}.sqlite",
    )
    result = gate.execute(
        request,
        authorization(tmp_path, request, journal_name=f"auth-outcome-{branch_outcome.value}.sqlite"),
    )
    assert result.receipt.outcome is tool_outcome
    assert result.receipt.reason is NamedToolExecutionReason.BRANCH_NON_COMPLETE
    assert result.receipt.result_count == 0
    assert result.receipt.no_match is False
    assert result.receipt.branch_attribution is not None
    assert result.receipt.branch_attribution.reason == f"VECTOR_{branch_outcome.value}"


def test_requested_result_limit_is_enforced_without_silent_truncation(tmp_path: Path) -> None:
    request = fulltext_request(result_limit=2)
    selected = FakePort(
        port_id="port:fulltext-overflow",
        tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
        branch_mode=NamedBranchMode.FULL_TEXT,
        producer=lambda item: branch_result(item, result_count=3),
    )
    gate, _ = executor(
        tmp_path,
        selected_ports=ports(
            override={NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: selected}
        ),
    )
    result = gate.execute(request, authorization(tmp_path, request))
    assert result.receipt.outcome is NamedToolExecutionOutcome.INCOMPLETE
    assert result.receipt.reason is NamedToolExecutionReason.RESULT_LIMIT_EXCEEDED
    assert result.receipt.result_count == 0
    assert result.receipt.no_match is False
    assert result.receipt.branch_attribution is not None
    assert result.receipt.branch_attribution.result_count == 3
    assert result.branch_receipt_bytes is not None


def test_requested_payload_byte_limit_is_enforced_without_losing_audit_bytes(tmp_path: Path) -> None:
    request = graph_request(response_limit_bytes=1_024)
    raw = b"{" + b"x" * 1_500 + b"}"
    selected = FakePort(
        port_id="port:graph-large",
        tool_id=NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
        branch_mode=NamedBranchMode.ADMITTED_GRAPH,
        producer=lambda item: branch_result(item, raw=raw),
    )
    gate, _ = executor(
        tmp_path,
        selected_ports=ports(
            override={NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: selected}
        ),
    )
    result = gate.execute(request, authorization(tmp_path, request))
    assert result.receipt.outcome is NamedToolExecutionOutcome.INCOMPLETE
    assert result.receipt.reason is NamedToolExecutionReason.RESPONSE_LIMIT_EXCEEDED
    assert result.receipt.result_count == 0
    assert result.receipt.branch_attribution is not None
    assert result.receipt.branch_attribution.branch_receipt_bytes == len(raw)
    assert result.branch_receipt_bytes == raw
    assert raw not in result.receipt.canonical_bytes


def test_absolute_branch_receipt_byte_limit_fails_before_journal() -> None:
    request = graph_request()
    raw = b"x" * (NAMED_TOOL_RESPONSE_LIMIT_BYTES + 1)
    with pytest.raises(NamedToolContractError, match="global response bound"):
        branch_result(request, raw=raw)


def test_component_identities_must_be_bounded_sorted_and_unique() -> None:
    request = exact_request()
    raw = raw_branch_bytes(request.envelope.tool_id)
    base = branch_result(request).attribution
    with pytest.raises(NamedToolContractError, match="sorted and unique"):
        replace(
            base,
            component_identities=(
                BranchComponentIdentity("z", digest_text("z")),
                BranchComponentIdentity("a", digest_text("a")),
            ),
        )
    too_many = tuple(
        BranchComponentIdentity(f"component_{index:02d}", digest_text(str(index)))
        for index in range(17)
    )
    with pytest.raises(NamedToolContractError, match="at most 16"):
        replace(base, component_identities=too_many)


def test_branch_no_match_and_non_complete_semantics_fail_closed() -> None:
    request = exact_request()
    base = branch_result(request).attribution
    with pytest.raises(NamedToolContractError, match="NO_MATCH"):
        replace(base, result_count=0, no_match=False, reason=None)
    with pytest.raises(NamedToolContractError, match="non-complete"):
        replace(
            base,
            outcome=NamedBranchOutcome.INCOMPLETE,
            reason="INCOMPLETE",
            result_count=1,
        )


def test_execution_receipt_round_trip_and_raw_bytes_are_not_embedded(tmp_path: Path) -> None:
    request = fulltext_request()
    result = executor(tmp_path)[0].execute(request, authorization(tmp_path, request))
    decoded = NamedToolExecutionReceipt.from_canonical_bytes(
        result.receipt.canonical_bytes
    )
    assert decoded == result.receipt
    assert result.branch_receipt_bytes is not None
    assert result.branch_receipt_bytes not in result.receipt.canonical_bytes
    assert result.receipt.branch_attribution is not None
    assert result.receipt.branch_attribution.branch_receipt_digest == digest_bytes(
        result.branch_receipt_bytes
    )


def test_low_payload_limit_does_not_invalidate_internal_audit_receipt(tmp_path: Path) -> None:
    request = exact_request(response_limit_bytes=1_024)
    result = executor(tmp_path)[0].execute(request, authorization(tmp_path, request))
    assert result.receipt.outcome is NamedToolExecutionOutcome.COMPLETE
    assert len(result.receipt.canonical_bytes) > 1_024
    assert result.receipt.response_limit_bytes == 1_024


def test_journal_replay_and_restart_return_exact_receipt_and_branch_bytes(tmp_path: Path) -> None:
    request = fulltext_request(idempotency_key="tool:replay")
    auth = authorization(tmp_path, request)
    first = executor(tmp_path)[0].execute(request, auth)
    replay = executor(tmp_path)[0].execute(request, auth)
    assert replay.receipt.canonical_bytes == first.receipt.canonical_bytes
    assert replay.receipt.receipt_digest == first.receipt.receipt_digest
    assert replay.branch_receipt_bytes == first.branch_receipt_bytes


def test_execution_journal_semantic_conflict_fails_closed(tmp_path: Path) -> None:
    key = "tool:conflict"
    first_request = fulltext_request("first query", idempotency_key=key)
    second_request = fulltext_request("second query", idempotency_key=key)
    gate, _ = executor(tmp_path)
    gate.execute(first_request, authorization(tmp_path, first_request))
    with pytest.raises(NamedToolBranchExecutionError, match="semantic conflict"):
        gate.execute(second_request, authorization(tmp_path, second_request, journal_name="auth-second.sqlite"))


def test_execution_journal_detects_receipt_and_raw_branch_tamper(tmp_path: Path) -> None:
    request = fulltext_request(idempotency_key="tool:tamper")
    auth = authorization(tmp_path, request)
    gate, _ = executor(tmp_path)
    gate.execute(request, auth)
    path = tmp_path / "execution.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE increment5_named_tool_execution_receipts SET receipt_bytes = ? WHERE idempotency_key = ?",
            (b"{}", request.envelope.idempotency_key),
        )
    with pytest.raises(NamedToolBranchExecutionError, match="receipt digest mismatch"):
        gate.execute(request, auth)

    other_request = graph_request(idempotency_key="tool:branch-tamper")
    other_auth = authorization(tmp_path, other_request, journal_name="auth-branch-tamper.sqlite")
    other_gate, _ = executor(tmp_path, journal_name="branch-tamper.sqlite")
    other_gate.execute(other_request, other_auth)
    with sqlite3.connect(tmp_path / "branch-tamper.sqlite") as connection:
        connection.execute(
            "UPDATE increment5_named_tool_execution_receipts SET branch_receipt_bytes = ? WHERE idempotency_key = ?",
            (b"tampered", other_request.envelope.idempotency_key),
        )
    with pytest.raises(NamedToolBranchExecutionError, match="raw branch receipt digest mismatch"):
        other_gate.execute(other_request, other_auth)


def test_concurrent_same_request_retains_one_canonical_result(tmp_path: Path) -> None:
    request = vector_request(idempotency_key="tool:concurrent")
    auth = authorization(tmp_path, request)
    gate, chosen = executor(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _item: gate.execute(request, auth), range(16)))
    assert len({item.receipt.receipt_digest for item in results}) == 1
    assert len({item.branch_receipt_bytes for item in results}) == 1
    with sqlite3.connect(tmp_path / "execution.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_named_tool_execution_receipts"
        ).fetchone()[0] == 1
    assert len(port_for(chosen, request.envelope.tool_id).calls) >= 1


def test_branch_execution_occurs_outside_sqlite_write_reservation(tmp_path: Path) -> None:
    outer_request = fulltext_request(idempotency_key="tool:outer")
    nested_request = exact_request(idempotency_key="tool:nested")
    outer_auth = authorization(tmp_path, outer_request, journal_name="auth-outer.sqlite")
    nested_auth = authorization(tmp_path, nested_request, journal_name="auth-nested.sqlite")
    state = {"nested": False}
    gate: NamedToolBranchExecutor

    def outer_producer(request):
        if not state["nested"]:
            state["nested"] = True
            nested = gate.execute(nested_request, nested_auth)
            assert nested.receipt.outcome is NamedToolExecutionOutcome.COMPLETE
        return branch_result(request)

    chosen = ports(
        override={
            NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: FakePort(
                port_id="port:outer-nested",
                tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
                branch_mode=NamedBranchMode.FULL_TEXT,
                producer=outer_producer,
            )
        }
    )
    gate, _ = executor(tmp_path, selected_ports=chosen, journal_name="nested.sqlite")
    assert gate.execute(outer_request, outer_auth).receipt.outcome is NamedToolExecutionOutcome.COMPLETE
    with sqlite3.connect(tmp_path / "nested.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_named_tool_execution_receipts"
        ).fetchone()[0] == 2


def test_journal_schema_is_audit_only_and_retains_raw_branch_bytes_separately(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite"
    NamedToolExecutionJournal(path)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(increment5_named_tool_execution_receipts)"
            )
        }
    assert columns == {
        "idempotency_key",
        "execution_request_digest",
        "receipt_bytes",
        "receipt_digest",
        "branch_receipt_bytes",
        "branch_receipt_digest",
    }


def test_unsupported_collision_or_impact_tool_is_rejected_before_dispatch(tmp_path: Path) -> None:
    request = impact_request()
    auth = authorization(tmp_path, request)
    gate, chosen = executor(tmp_path)
    with pytest.raises(NamedToolBranchExecutionError, match="not supported"):
        gate.execute(request, auth)
    assert sum(len(port.calls) for port in chosen) == 0


def test_execution_receipt_rejects_authority_or_activation_claims(tmp_path: Path) -> None:
    request = exact_request()
    result = executor(tmp_path)[0].execute(request, authorization(tmp_path, request))
    with pytest.raises(NamedToolContractError, match="authority effect"):
        replace(result.receipt, authority_effect="CANDIDATE_ADMISSION")
    with pytest.raises(NamedToolContractError, match="activation authority"):
        replace(result.receipt, production_activation_authorized=True)


def test_kernel_imports_no_concrete_branch_fusion_hydration_or_network_client() -> None:
    import newsroom.increment5.named_tool_branch_execution as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "exact_retriever",
        "fulltext_retriever",
        "vector_retriever",
        "admitted_graph_retriever",
        "neo4j",
        "reciprocal_rank",
        "fusion",
        "hydrate_object",
        "collision_store",
        "requests",
        "httpx",
        "socket",
    )
    assert not any(item in source for item in forbidden)
