from __future__ import annotations

import hashlib
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.increment5.named_tool_authority_execution import (
    NamedAuthorityExecutionJournal,
    NamedAuthorityPortRegistry,
    NamedToolAuthorityExecutor,
)
from newsroom.increment5.named_tool_authorization import (
    NamedToolAuthorizationGrant,
    NamedToolAuthorizationJournal,
    NamedToolAuthorizer,
    NamedToolGrantRegistry,
)
from newsroom.increment5.named_tool_branch_execution import (
    NamedBranchPortRegistry,
    NamedToolBranchExecutor,
    NamedToolExecutionJournal,
)
from newsroom.increment5.named_tool_contracts import NamedToolId
from newsroom.increment5.named_tool_dispatch import (
    NAMED_TOOL_DISPATCH_CONTRACT_DIGEST,
    NAMED_TOOL_ROUTES,
    NamedToolDispatchError,
    NamedToolDispatchJournal,
    NamedToolDispatchOutcome,
    NamedToolDispatchReason,
    NamedToolDispatchReceipt,
    NamedToolDispatchRegistry,
    NamedToolDispatcher,
    NamedToolExecutionRoute,
)
from newsroom.tests import (
    test_increment5c2_named_tool_authority_execution as authority_helpers,
)
from newsroom.tests import (
    test_increment5c2_named_tool_branch_adapters as branch_helpers,
)


class CountingBranchPort:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.port_id = delegate.port_id
        self.tool_id = delegate.tool_id
        self.branch_mode = delegate.branch_mode
        self.calls: list[object] = []

    def execute(self, request: object):
        self.calls.append(request)
        return self.delegate.execute(request)


class CountingAuthorityPort:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.port_id = delegate.port_id
        self.tool_id = delegate.tool_id
        self.authority_mode = delegate.authority_mode
        self.calls: list[object] = []

    def execute(self, request: object):
        self.calls.append(request)
        return self.delegate.execute(request)


def authorize(tmp_path: Path, request: object, *, name: str):
    envelope = request.envelope
    grant = NamedToolAuthorizationGrant.create(
        grant_id=envelope.authorization_grant_id,
        actor_id=envelope.actor_id,
        authenticated_principal_digest=envelope.authenticated_principal_digest,
        tool_id=envelope.tool_id,
        purposes=(envelope.purpose,),
        scope=envelope.requested_scope,
        valid_from="2020-01-01T00:00:00Z",
        valid_to="2050-01-01T00:00:00Z",
        policy_id=envelope.policy_id,
        policy_digest=envelope.policy_digest,
        contract_digest=envelope.contract_digest,
        profile_id=envelope.profile_id,
        generation_id=envelope.generation_id,
    )
    return NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant,)),
        journal=NamedToolAuthorizationJournal(tmp_path / f"auth-{name}.sqlite"),
    ).authorize(request)


def denied_authorization(tmp_path: Path, request: object, *, name: str):
    unrelated = branch_helpers.exact_request(lookup_value=f"unrelated-{name}")
    grant = NamedToolAuthorizationGrant.create(
        grant_id=f"grant:unrelated:{name}",
        actor_id=unrelated.envelope.actor_id,
        authenticated_principal_digest=(
            unrelated.envelope.authenticated_principal_digest
        ),
        tool_id=unrelated.envelope.tool_id,
        purposes=(unrelated.envelope.purpose,),
        scope=unrelated.envelope.requested_scope,
        valid_from="2020-01-01T00:00:00Z",
        valid_to="2050-01-01T00:00:00Z",
        policy_id=unrelated.envelope.policy_id,
        policy_digest=unrelated.envelope.policy_digest,
        contract_digest=unrelated.envelope.contract_digest,
        profile_id=unrelated.envelope.profile_id,
        generation_id=unrelated.envelope.generation_id,
    )
    return NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant,)),
        journal=NamedToolAuthorizationJournal(tmp_path / f"denied-{name}.sqlite"),
    ).authorize(request)


def stale_authorization(tmp_path: Path, request: object, *, name: str):
    envelope = request.envelope
    grant = NamedToolAuthorizationGrant.create(
        grant_id=envelope.authorization_grant_id,
        actor_id=envelope.actor_id,
        authenticated_principal_digest=envelope.authenticated_principal_digest,
        tool_id=envelope.tool_id,
        purposes=(envelope.purpose,),
        scope=envelope.requested_scope,
        valid_from="2020-01-01T00:00:00Z",
        valid_to="2050-01-01T00:00:00Z",
        policy_id=envelope.policy_id,
        policy_digest=envelope.policy_digest,
        contract_digest=envelope.contract_digest,
        profile_id=envelope.profile_id,
        generation_id="other-generation",
    )
    return NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant,)),
        journal=NamedToolAuthorizationJournal(tmp_path / f"stale-{name}.sqlite"),
    ).authorize(request)


def system(tmp_path: Path, *, dispatch_name: str = "dispatch.sqlite"):
    branch_ports, driver, graph_port, catalog, vector_view, graph_view, snapshot = (
        branch_helpers.real_ports(tmp_path)
    )
    counted_branches = tuple(CountingBranchPort(item) for item in branch_ports)
    branch_executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(counted_branches),
        journal=NamedToolExecutionJournal(tmp_path / "branch-execution.sqlite"),
    )

    authority_path = authority_helpers.authority_database(tmp_path)
    counted_authorities = tuple(
        CountingAuthorityPort(item)
        for item in authority_helpers.ports(authority_path)
    )
    authority_executor = NamedToolAuthorityExecutor(
        registry=NamedAuthorityPortRegistry(counted_authorities),
        journal=NamedAuthorityExecutionJournal(
            tmp_path / "authority-execution.sqlite"
        ),
    )
    registry = NamedToolDispatchRegistry(
        branch_executor=branch_executor,
        authority_executor=authority_executor,
    )
    dispatcher = NamedToolDispatcher(
        registry=registry,
        journal=NamedToolDispatchJournal(tmp_path / dispatch_name),
    )
    requests = (
        branch_helpers.exact_request(),
        branch_helpers.fulltext_request(
            generation_id=str(snapshot.generation_id)
        ),
        branch_helpers.vector_request(
            catalog,
            generation_id=vector_view.generation_id,
        ),
        branch_helpers.graph_request(generation_id=graph_view.generation_id),
        authority_helpers.collision_request(),
        authority_helpers.impact_request(),
    )
    return (
        dispatcher,
        registry,
        counted_branches,
        counted_authorities,
        requests,
        driver,
        graph_port,
    )


def total_calls(
    branches: tuple[CountingBranchPort, ...],
    authorities: tuple[CountingAuthorityPort, ...],
) -> int:
    return sum(len(item.calls) for item in branches) + sum(
        len(item.calls) for item in authorities
    )


def with_idempotency(request: object, key: str):
    return replace(
        request,
        envelope=replace(request.envelope, idempotency_key=key),
    )


def test_route_inventory_and_contract_are_closed_and_exact() -> None:
    assert NAMED_TOOL_ROUTES == {
        NamedToolId.EXACT_AUTHORITY_LOOKUP: NamedToolExecutionRoute.BRANCH,
        NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: NamedToolExecutionRoute.BRANCH,
        NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: (
            NamedToolExecutionRoute.BRANCH
        ),
        NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: (
            NamedToolExecutionRoute.BRANCH
        ),
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP: (
            NamedToolExecutionRoute.AUTHORITY
        ),
        NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP: (
            NamedToolExecutionRoute.AUTHORITY
        ),
    }
    assert NAMED_TOOL_DISPATCH_CONTRACT_DIGEST.startswith("sha256:")
    assert len(NAMED_TOOL_DISPATCH_CONTRACT_DIGEST) == 71


def test_all_six_real_tools_execute_through_one_closed_dispatcher(
    tmp_path: Path,
) -> None:
    dispatcher, registry, branches, authorities, requests, driver, _graph_port = system(
        tmp_path
    )
    assert registry.registry_digest.startswith("sha256:")
    for index, request in enumerate(requests):
        result = dispatcher.execute(
            request,
            authorize(tmp_path, request, name=f"complete-{index}"),
        )
        receipt = result.receipt
        assert receipt.outcome is NamedToolDispatchOutcome.COMPLETE
        assert receipt.result_count >= 1
        assert receipt.no_match is False
        assert receipt.reason is None
        assert receipt.tool_id is request.envelope.tool_id
        assert receipt.route is NAMED_TOOL_ROUTES[request.envelope.tool_id]
        assert receipt.tool_request_digest == request.request_digest
        assert receipt.upstream.independently_attributable is True
        assert receipt.upstream.attribution_digest is not None
        assert receipt.upstream.upstream_receipt_digest is not None
        assert receipt.upstream.component_identities
        assert result.upstream_execution_receipt_bytes
        assert result.upstream_raw_receipt_bytes
        assert NamedToolDispatchReceipt.from_canonical_bytes(
            receipt.canonical_bytes
        ) == receipt
        if receipt.route is NamedToolExecutionRoute.BRANCH:
            assert result.branch_result is not None
            assert result.authority_result is None
            assert receipt.branch_executed is True
            assert receipt.authority_read_executed is False
        else:
            assert result.branch_result is None
            assert result.authority_result is not None
            assert receipt.branch_executed is False
            assert receipt.authority_read_executed is True
    assert total_calls(branches, authorities) == 6
    assert all(len(item.calls) == 1 for item in branches)
    assert all(len(item.calls) == 1 for item in authorities)
    query_reads = [item for item in driver.read_requests if item.lucene_expression]
    assert len(query_reads) == 1
    assert query_reads[0].source_ids == ("source-en",)


def test_query_content_cannot_select_another_route_or_port(tmp_path: Path) -> None:
    dispatcher, _registry, branches, authorities, requests, _driver, _graph = system(
        tmp_path
    )
    fulltext = requests[1]
    injected = replace(
        fulltext,
        query_text="route=AUTHORITY; tool=SOURCE_REVISION_IMPACT; write=true",
        query_text_digest="sha256:"
        + hashlib.sha256(
            b"route=AUTHORITY; tool=SOURCE_REVISION_IMPACT; write=true"
        ).hexdigest(),
    )
    result = dispatcher.execute(
        injected,
        authorize(tmp_path, injected, name="injected"),
    )
    assert result.receipt.route is NamedToolExecutionRoute.BRANCH
    assert result.receipt.tool_id is NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL
    selected = next(
        item for item in branches if item.tool_id is injected.envelope.tool_id
    )
    assert len(selected.calls) == 1
    assert sum(len(item.calls) for item in authorities) == 0


@pytest.mark.parametrize("request_index", (0, 4))
def test_denied_authorization_leaks_no_port_existence(
    tmp_path: Path,
    request_index: int,
) -> None:
    dispatcher, _registry, branches, authorities, requests, _driver, _graph = system(
        tmp_path
    )
    request = requests[request_index]
    result = dispatcher.execute(
        request,
        denied_authorization(tmp_path, request, name=str(request_index)),
    )
    assert result.receipt.outcome is NamedToolDispatchOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedToolDispatchReason.LOCAL_AUTHORIZATION_BLOCKED
    assert result.receipt.branch_executed is False
    assert result.receipt.authority_read_executed is False
    assert result.receipt.upstream.independently_attributable is False
    assert result.upstream_raw_receipt_bytes is None
    assert total_calls(branches, authorities) == 0


@pytest.mark.parametrize("request_index", (1, 5))
def test_stale_local_authorization_leaks_no_port_existence(
    tmp_path: Path,
    request_index: int,
) -> None:
    dispatcher, _registry, branches, authorities, requests, _driver, _graph = system(
        tmp_path
    )
    request = requests[request_index]
    result = dispatcher.execute(
        request,
        stale_authorization(tmp_path, request, name=str(request_index)),
    )
    assert result.receipt.outcome is NamedToolDispatchOutcome.STALE
    assert result.receipt.reason is NamedToolDispatchReason.LOCAL_AUTHORIZATION_BLOCKED
    assert result.receipt.upstream.independently_attributable is False
    assert total_calls(branches, authorities) == 0


def test_authorization_binding_mismatch_is_blocked_before_port(tmp_path: Path) -> None:
    dispatcher, _registry, branches, authorities, requests, _driver, _graph = system(
        tmp_path
    )
    first = requests[0]
    second = branch_helpers.exact_request(lookup_value="different-native-id")
    result = dispatcher.execute(
        second,
        authorize(tmp_path, first, name="wrong-request"),
    )
    assert result.receipt.outcome is NamedToolDispatchOutcome.POLICY_BLOCKED
    assert result.receipt.reason is (
        NamedToolDispatchReason.AUTHORIZATION_BINDING_MISMATCH
    )
    assert total_calls(branches, authorities) == 0


def test_complete_no_match_is_the_only_no_match_path(tmp_path: Path) -> None:
    dispatcher, _registry, _branches, _authorities, _requests, _driver, _graph = system(
        tmp_path
    )
    request = branch_helpers.exact_request(lookup_value="does-not-exist")
    result = dispatcher.execute(
        request,
        authorize(tmp_path, request, name="no-match"),
    )
    assert result.receipt.outcome is NamedToolDispatchOutcome.COMPLETE
    assert result.receipt.reason is NamedToolDispatchReason.NO_MATCH
    assert result.receipt.result_count == 0
    assert result.receipt.no_match is True
    assert result.receipt.upstream.reason == "NO_MATCH"


def test_low_payload_bound_does_not_invalidate_internal_dispatch_receipt(
    tmp_path: Path,
) -> None:
    dispatcher, _registry, _branches, _authorities, requests, _driver, _graph = system(
        tmp_path
    )
    request = replace(
        requests[0],
        envelope=replace(requests[0].envelope, response_limit_bytes=1_024),
    )
    result = dispatcher.execute(
        request,
        authorize(tmp_path, request, name="low-bound"),
    )
    assert result.receipt.outcome is NamedToolDispatchOutcome.INCOMPLETE
    assert result.receipt.reason is NamedToolDispatchReason.RESPONSE_LIMIT_EXCEEDED
    assert result.receipt.response_limit_bytes == 1_024
    assert len(result.receipt.canonical_bytes) > 1_024
    assert result.upstream_raw_receipt_bytes is not None


def test_dispatch_journal_restart_replays_exact_child_and_raw_bytes(
    tmp_path: Path,
) -> None:
    dispatcher, registry, branches, authorities, requests, _driver, _graph = system(
        tmp_path,
        dispatch_name="replay.sqlite",
    )
    request = with_idempotency(requests[4], "dispatch:replay")
    authorization = authorize(tmp_path, request, name="replay")
    first = dispatcher.execute(request, authorization)
    restarted = NamedToolDispatcher(
        registry=registry,
        journal=NamedToolDispatchJournal(tmp_path / "replay.sqlite"),
    )
    replay = restarted.execute(request, authorization)
    assert replay.receipt.canonical_bytes == first.receipt.canonical_bytes
    assert replay.receipt.receipt_digest == first.receipt.receipt_digest
    assert (
        replay.upstream_execution_receipt_bytes
        == first.upstream_execution_receipt_bytes
    )
    assert replay.upstream_raw_receipt_bytes == first.upstream_raw_receipt_bytes
    assert total_calls(branches, authorities) == 1


def test_dispatch_journal_rejects_semantic_idempotency_conflict(tmp_path: Path) -> None:
    dispatcher, _registry, _branches, _authorities, _requests, _driver, _graph = system(
        tmp_path,
        dispatch_name="conflict.sqlite",
    )
    key = "dispatch:conflict"
    first = with_idempotency(
        branch_helpers.exact_request(lookup_value="native-42"), key
    )
    second = with_idempotency(
        branch_helpers.exact_request(lookup_value="different-native"), key
    )
    dispatcher.execute(first, authorize(tmp_path, first, name="conflict-first"))
    with pytest.raises(NamedToolDispatchError, match="semantic conflict"):
        dispatcher.execute(
            second,
            authorize(tmp_path, second, name="conflict-second"),
        )


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("receipt_bytes", b"{}", "dispatch receipt digest mismatch"),
        (
            "upstream_execution_receipt_bytes",
            b"{}",
            "upstream execution receipt digest mismatch",
        ),
        (
            "upstream_raw_receipt_bytes",
            b"tampered",
            "upstream raw receipt digest mismatch",
        ),
    ),
)
def test_dispatch_journal_detects_all_retained_byte_tamper(
    tmp_path: Path,
    column: str,
    value: bytes,
    message: str,
) -> None:
    journal_name = f"tamper-{column}.sqlite"
    dispatcher, registry, _branches, _authorities, requests, _driver, _graph = system(
        tmp_path,
        dispatch_name=journal_name,
    )
    request = with_idempotency(requests[4], f"dispatch:{column}")
    authorization = authorize(tmp_path, request, name=column)
    dispatcher.execute(request, authorization)
    with sqlite3.connect(tmp_path / journal_name) as connection:
        connection.execute(
            (
                "UPDATE increment5_named_tool_dispatch_receipts "
                f"SET {column} = ? WHERE idempotency_key = ?"
            ),
            (value, request.envelope.idempotency_key),
        )
    restarted = NamedToolDispatcher(
        registry=registry,
        journal=NamedToolDispatchJournal(tmp_path / journal_name),
    )
    with pytest.raises(NamedToolDispatchError, match=message):
        restarted.execute(request, authorization)


def test_dispatch_receipt_rejects_duplicate_keys(tmp_path: Path) -> None:
    dispatcher, _registry, _branches, _authorities, requests, _driver, _graph = system(
        tmp_path
    )
    request = requests[0]
    receipt = dispatcher.execute(
        request,
        authorize(tmp_path, request, name="duplicate"),
    ).receipt
    raw = receipt.canonical_bytes.replace(
        b'"authority_effect":"NONE"',
        b'"authority_effect":"NONE","authority_effect":"NONE"',
        1,
    )
    with pytest.raises(NamedToolDispatchError, match="duplicate keys"):
        NamedToolDispatchReceipt.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("no_match", 0, "dispatch no_match must be boolean"),
        ("branch_executed", 1, "branch_executed must be boolean"),
        ("authority_read_executed", 0, "authority_read_executed must be boolean"),
        (
            "external_call_count",
            False,
            "external_call_count must be a non-negative integer",
        ),
        (
            "qualification_authority_granted",
            0,
            "qualification_authority_granted must be boolean",
        ),
    ),
)
def test_dispatch_receipt_rejects_scalar_type_confusion(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    dispatcher, _registry, _branches, _authorities, requests, _driver, _graph = system(
        tmp_path
    )
    request = requests[0]
    receipt = dispatcher.execute(
        request,
        authorize(tmp_path, request, name=f"type-{field}"),
    ).receipt
    with pytest.raises(Exception, match=message):
        replace(receipt, **{field: value})


def test_concurrent_dispatch_retains_one_canonical_result(tmp_path: Path) -> None:
    dispatcher, _registry, _branches, _authorities, requests, _driver, _graph = system(
        tmp_path,
        dispatch_name="concurrent.sqlite",
    )
    request = with_idempotency(requests[2], "dispatch:concurrent")
    authorization = authorize(tmp_path, request, name="concurrent")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _item: dispatcher.execute(request, authorization),
                range(16),
            )
        )
    assert len({item.receipt.receipt_digest for item in results}) == 1
    assert len({item.upstream_execution_receipt_bytes for item in results}) == 1
    assert len({item.upstream_raw_receipt_bytes for item in results}) == 1
    with sqlite3.connect(tmp_path / "concurrent.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_named_tool_dispatch_receipts"
        ).fetchone()[0] == 1


def test_dispatch_journal_schema_is_exact_and_non_authoritative(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite"
    NamedToolDispatchJournal(path)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(increment5_named_tool_dispatch_receipts)"
            )
        }
    assert columns == {
        "idempotency_key",
        "dispatch_request_digest",
        "receipt_bytes",
        "receipt_digest",
        "upstream_execution_receipt_bytes",
        "upstream_execution_receipt_digest",
        "upstream_raw_receipt_bytes",
        "upstream_raw_receipt_digest",
    }


def test_dispatch_module_has_no_concrete_query_fusion_or_effect_surface() -> None:
    import newsroom.increment5.named_tool_dispatch as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "named_tool_branch_adapters",
        "named_tool_authority_adapters",
        "exact_retriever",
        "fulltext_retriever",
        "vector_retriever",
        "admitted_graph_retriever",
        "neo4j",
        "run_cypher",
        "reciprocal_rank",
        "hydrate_object",
        "create_candidate",
        "provider_client",
        "requests.",
        "httpx",
        "socket",
    )
    assert not any(item in source for item in forbidden)
