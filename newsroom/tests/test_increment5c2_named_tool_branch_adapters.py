from __future__ import annotations

import hashlib
import inspect
import uuid
from pathlib import Path

import pytest

from newsroom.increment5.admitted_graph_retriever import (
    GRAPH_MAX_DEPTH,
    GRAPH_MAX_FANOUT,
    GRAPH_TEMPORAL_WINDOW_SECONDS,
    AdmittedGraphReceipt,
)
from newsroom.increment5.branch_receipts import ExactBranchReceipt
from newsroom.increment5.fulltext_receipts import FullTextBranchReceipt
from newsroom.increment5.named_tool_authorization import (
    NamedToolAuthorizationGrant,
    NamedToolAuthorizationJournal,
    NamedToolAuthorizer,
    NamedToolGrantRegistry,
)
from newsroom.increment5.named_tool_branch_adapters import (
    NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST,
    AdmittedGraphNamedToolAdapterConfig,
    AdmittedGraphNamedToolPort,
    ExactNamedToolAdapterConfig,
    ExactNamedToolPort,
    FullTextNamedToolAdapterConfig,
    FullTextNamedToolPort,
    VectorNamedToolAdapterConfig,
    VectorNamedToolPort,
)
from newsroom.increment5.named_tool_branch_execution import (
    NamedBranchPortRegistry,
    NamedToolBranchExecutor,
    NamedToolExecutionJournal,
    NamedToolExecutionOutcome,
    NamedToolExecutionReason,
)
from newsroom.increment5.named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    AdmittedGraphTraversalToolRequest,
    ExactAuthorityLookupToolRequest,
    ExactLookupKind,
    FixedPointVectorRetrievalToolRequest,
    FullTextRetrievalToolRequest,
    NamedToolEnvelope,
    NamedToolId,
    NamedToolLanguage,
    NamedToolPurpose,
    ToolScope,
)
from newsroom.increment5.vector_retriever import (
    VectorAuthorityView,
    VectorBranchReceipt,
    VectorFixtureCatalog,
    VectorFixtureRetriever,
    VectorReceiptJournal,
)
from newsroom.tests import increment5b1_helpers as exact_helpers
from newsroom.tests import increment5b2_helpers as fulltext_helpers
from newsroom.tests import test_increment5b4_admitted_graph_retriever as graph_helpers


PRINCIPAL_DIGEST = "sha256:" + hashlib.sha256(b"principal:5c2-adapter-test").hexdigest()
POLICY_DIGEST = "sha256:" + hashlib.sha256(b"policy:5c2-adapter-test").hexdigest()
CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "increment5"
    / "data"
    / "increment5b3_vector_fixture_v1.json"
)


def digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def envelope(
    *,
    tool_id: NamedToolId,
    purpose: NamedToolPurpose,
    scope: ToolScope,
    generation_id: str,
    query_valid_time: str,
    serving_time: str,
    grant_id: str,
    timeout_ms: int = 5_000,
) -> NamedToolEnvelope:
    return NamedToolEnvelope(
        request_id=str(uuid.uuid4()),
        idempotency_key=f"adapter:{uuid.uuid4()}",
        tool_id=tool_id,
        actor_id="triage_worker",
        authenticated_principal_digest=PRINCIPAL_DIGEST,
        authorization_grant_id=grant_id,
        purpose=purpose,
        policy_id=NAMED_TOOL_POLICY_ID,
        policy_digest=POLICY_DIGEST,
        contract_digest=NAMED_TOOL_CONTRACT_DIGEST,
        profile_id=NAMED_TOOL_PROFILE_ID,
        generation_id=generation_id,
        query_valid_time=query_valid_time,
        serving_time=serving_time,
        requested_scope=scope,
        result_limit=8,
        timeout_ms=timeout_ms,
        response_limit_bytes=262_144,
    )


def exact_request(
    *,
    lookup_kind: ExactLookupKind = ExactLookupKind.SOURCE_NATIVE_ID,
    lookup_value: str = "native-42",
    timeout_ms: int = 5_000,
) -> ExactAuthorityLookupToolRequest:
    return ExactAuthorityLookupToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.EXACT_AUTHORITY_LOOKUP,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(lookup_kind=(lookup_kind.value,)),
            generation_id="retrieval-generation-v1",
            query_valid_time="2042-03-12T12:00:00Z",
            serving_time="2042-03-12T12:00:00Z",
            grant_id="grant:adapter-exact",
            timeout_ms=timeout_ms,
        ),
        lookup_kind=lookup_kind,
        lookup_value=lookup_value,
        lookup_value_digest=digest_text(lookup_value),
    )


def fulltext_request(
    *,
    generation_id: str,
    source_ids: tuple[str, ...] = ("source-en",),
    timeout_ms: int = 5_000,
) -> FullTextRetrievalToolRequest:
    languages = (NamedToolLanguage.EN_GB,)
    dimensions: dict[str, tuple[str, ...]] = {
        "language": tuple(item.value for item in languages)
    }
    if source_ids:
        dimensions["source_id"] = source_ids
    query = "Synthetic Authority deadline 27 March 2042"
    return FullTextRetrievalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(**dimensions),
            generation_id=generation_id,
            query_valid_time="2042-03-12T12:00:00Z",
            serving_time="2042-03-12T12:00:00Z",
            grant_id="grant:adapter-fulltext",
            timeout_ms=timeout_ms,
        ),
        query_text=query,
        query_text_digest=digest_text(query),
        languages=languages,
        source_ids=source_ids,
    )


def vector_request(
    catalog: VectorFixtureCatalog,
    *,
    generation_id: str,
) -> FixedPointVectorRetrievalToolRequest:
    query = catalog.query("query:harbour-development")
    assert query is not None
    return FixedPointVectorRetrievalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(
                fixture_query=(query.query_id,)
            ),
            generation_id=generation_id,
            query_valid_time="2026-08-06T08:59:00Z",
            serving_time="2026-08-06T09:00:00Z",
            grant_id="grant:adapter-vector",
        ),
        fixture_query_id=query.query_id,
        fixture_query_digest=query.query_digest,
    )


def graph_request(
    *,
    generation_id: str,
    maximum_depth: int = GRAPH_MAX_DEPTH,
) -> AdmittedGraphTraversalToolRequest:
    root_id = "source:root"
    return AdmittedGraphTraversalToolRequest(
        envelope=envelope(
            tool_id=NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
            purpose=NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope=ToolScope.from_dimensions(root_id=(root_id,)),
            generation_id=generation_id,
            query_valid_time="2026-08-06T08:59:00Z",
            serving_time="2026-08-06T09:00:00Z",
            grant_id="grant:adapter-graph",
        ),
        root_id=root_id,
        root_identity_digest=digest_text(f"canonical-node:{root_id}"),
        maximum_depth=maximum_depth,
        maximum_fanout=GRAPH_MAX_FANOUT,
        temporal_window_seconds=GRAPH_TEMPORAL_WINDOW_SECONDS,
    )


def authorization(tmp_path: Path, request, *, name: str):
    grant = NamedToolAuthorizationGrant.create(
        grant_id=request.envelope.authorization_grant_id,
        actor_id=request.envelope.actor_id,
        authenticated_principal_digest=(
            request.envelope.authenticated_principal_digest
        ),
        tool_id=request.envelope.tool_id,
        purposes=(request.envelope.purpose,),
        scope=request.envelope.requested_scope,
        valid_from="2020-01-01T00:00:00Z",
        valid_to="2050-01-01T00:00:00Z",
        policy_id=request.envelope.policy_id,
        policy_digest=request.envelope.policy_digest,
        contract_digest=request.envelope.contract_digest,
        profile_id=request.envelope.profile_id,
        generation_id=request.envelope.generation_id,
    )
    return NamedToolAuthorizer(
        registry=NamedToolGrantRegistry((grant,)),
        journal=NamedToolAuthorizationJournal(tmp_path / f"auth-{name}.sqlite"),
    ).authorize(request)


def real_ports(tmp_path: Path):
    _authority, _journal, exact_retriever = exact_helpers._system(tmp_path)
    snapshot = fulltext_helpers.snapshot()
    driver, _factory, fulltext_retriever = fulltext_helpers.system(tmp_path)

    catalog = VectorFixtureCatalog.load(CATALOG_PATH)
    vector_view = VectorAuthorityView.for_catalog(
        catalog,
        validated_at="2026-08-06T08:58:00Z",
    )
    vector_retriever = VectorFixtureRetriever(
        catalog=catalog,
        authority_provider=lambda _request: vector_view,
        journal=VectorReceiptJournal(tmp_path / "vector-adapter-receipts.sqlite"),
        monotonic_ns=lambda: 0,
    )

    graph_view = graph_helpers.make_view()
    graph_retriever, graph_port = graph_helpers.make_retriever(
        tmp_path,
        graph_view,
        journal_name="graph-adapter-receipts.sqlite",
    )

    ports = (
        ExactNamedToolPort(
            retriever=exact_retriever,
            config=ExactNamedToolAdapterConfig(
                source_authority_scope_id="source-a",
                minimum_ledger_seq=3,
            ),
        ),
        FullTextNamedToolPort(
            retriever=fulltext_retriever,
            config=FullTextNamedToolAdapterConfig(
                expected_generation_id=str(snapshot.generation_id),
                expected_generation_identity_digest=(
                    snapshot.generation_identity_digest
                ),
                expected_rights_manifest_digest=snapshot.rights_manifest_digest,
                minimum_watermark=snapshot.contiguous_ledger_seq,
            ),
        ),
        VectorNamedToolPort(
            retriever=vector_retriever,
            config=VectorNamedToolAdapterConfig(minimum_watermark_seq=1),
        ),
        AdmittedGraphNamedToolPort(
            retriever=graph_retriever,
            config=AdmittedGraphNamedToolAdapterConfig(
                minimum_watermark_seq=10
            ),
        ),
    )
    return ports, driver, graph_port, catalog, vector_view, graph_view, snapshot


def test_adapter_contract_is_closed_and_content_addressed() -> None:
    assert NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST.startswith("sha256:")
    assert len(NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST) == 71


def test_all_four_real_retrievers_execute_through_one_closed_registry(tmp_path: Path) -> None:
    ports, driver, _graph_port, catalog, vector_view, graph_view, snapshot = real_ports(
        tmp_path
    )
    requests = (
        exact_request(),
        fulltext_request(generation_id=str(snapshot.generation_id)),
        vector_request(catalog, generation_id=vector_view.generation_id),
        graph_request(generation_id=graph_view.generation_id),
    )
    executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(ports),
        journal=NamedToolExecutionJournal(tmp_path / "named-adapter-execution.sqlite"),
    )
    parsers = (
        ExactBranchReceipt.from_canonical_bytes,
        FullTextBranchReceipt.from_canonical_bytes,
        VectorBranchReceipt.from_canonical_bytes,
        AdmittedGraphReceipt.from_canonical_bytes,
    )
    for index, (request, parser) in enumerate(zip(requests, parsers, strict=True)):
        result = executor.execute(
            request,
            authorization(tmp_path, request, name=f"complete-{index}"),
        )
        assert result.receipt.outcome is NamedToolExecutionOutcome.COMPLETE
        assert result.receipt.branch_attribution is not None
        assert result.receipt.branch_attribution.tool_id is request.envelope.tool_id
        assert result.receipt.branch_attribution.tool_request_digest == request.request_digest
        assert result.receipt.branch_attribution.branch_request_digest != request.request_digest
        assert result.receipt.branch_attribution.independently_attributable is True
        names = {
            item.name
            for item in result.receipt.branch_attribution.component_identities
        }
        assert {"adapter_config", "adapter_contract", "branch_contract", "named_tool_contract"}.issubset(names)
        assert result.branch_receipt_bytes is not None
        parser(result.branch_receipt_bytes)
    query_reads = [item for item in driver.read_requests if item.lucene_expression]
    assert len(query_reads) == 1
    assert query_reads[0].source_ids == ("source-en",)


def test_exact_revision_name_maps_to_fixed_source_revision_branch(tmp_path: Path) -> None:
    ports, *_rest = real_ports(tmp_path)
    request = exact_request(
        lookup_kind=ExactLookupKind.REVISION_ID,
        lookup_value="revision-a",
    )
    executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(ports),
        journal=NamedToolExecutionJournal(tmp_path / "revision-execution.sqlite"),
    )
    result = executor.execute(
        request,
        authorization(tmp_path, request, name="revision"),
    )
    assert result.receipt.outcome is NamedToolExecutionOutcome.COMPLETE
    assert result.receipt.result_count == 1
    assert result.branch_receipt_bytes is not None
    upstream = ExactBranchReceipt.from_canonical_bytes(result.branch_receipt_bytes)
    assert upstream.hits[0].authority_id == "revision-a"


def test_narrow_timeout_is_policy_blocked_before_authority_read(tmp_path: Path) -> None:
    ports, driver, *_rest = real_ports(tmp_path)
    request = fulltext_request(
        generation_id=str(fulltext_helpers.GENERATION_ID),
        timeout_ms=4_000,
    )
    executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(ports),
        journal=NamedToolExecutionJournal(tmp_path / "timeout-execution.sqlite"),
    )
    result = executor.execute(
        request,
        authorization(tmp_path, request, name="timeout"),
    )
    assert result.receipt.outcome is NamedToolExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedToolExecutionReason.ADAPTER_POLICY_BLOCKED
    assert result.receipt.branch_executed is False
    assert result.branch_receipt_bytes is None
    assert driver.read_requests == []


def test_narrow_graph_shape_is_policy_blocked_before_graph_access(tmp_path: Path) -> None:
    ports, _driver, graph_port, _catalog, _vector_view, graph_view, _snapshot = real_ports(
        tmp_path
    )
    request = graph_request(generation_id=graph_view.generation_id, maximum_depth=1)
    executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(ports),
        journal=NamedToolExecutionJournal(tmp_path / "narrow-graph.sqlite"),
    )
    result = executor.execute(
        request,
        authorization(tmp_path, request, name="narrow-graph"),
    )
    assert result.receipt.outcome is NamedToolExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedToolExecutionReason.ADAPTER_POLICY_BLOCKED
    assert graph_port.root_calls == []
    assert graph_port.expand_calls == []


def test_fulltext_generation_outside_fixed_config_is_blocked_without_query(tmp_path: Path) -> None:
    ports, driver, *_rest = real_ports(tmp_path)
    request = fulltext_request(generation_id="other-generation")
    executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(ports),
        journal=NamedToolExecutionJournal(tmp_path / "fulltext-generation.sqlite"),
    )
    result = executor.execute(
        request,
        authorization(tmp_path, request, name="fulltext-generation"),
    )
    assert result.receipt.outcome is NamedToolExecutionOutcome.POLICY_BLOCKED
    assert result.receipt.reason is NamedToolExecutionReason.ADAPTER_POLICY_BLOCKED
    assert driver.read_requests == []


def test_vector_generation_mismatch_is_stale_with_upstream_receipt(tmp_path: Path) -> None:
    ports, _driver, _graph_port, catalog, _vector_view, _graph_view, _snapshot = real_ports(
        tmp_path
    )
    request = vector_request(catalog, generation_id="other-generation")
    executor = NamedToolBranchExecutor(
        registry=NamedBranchPortRegistry(ports),
        journal=NamedToolExecutionJournal(tmp_path / "vector-generation.sqlite"),
    )
    result = executor.execute(
        request,
        authorization(tmp_path, request, name="vector-generation"),
    )
    assert result.receipt.outcome is NamedToolExecutionOutcome.STALE
    assert result.receipt.reason is NamedToolExecutionReason.BRANCH_GENERATION_MISMATCH
    assert result.receipt.result_count == 0
    assert result.receipt.branch_attribution is not None
    assert result.branch_receipt_bytes is not None
    upstream = VectorBranchReceipt.from_canonical_bytes(result.branch_receipt_bytes)
    assert upstream.generation_id == "vector-fixture-generation-v1"


def test_adapter_module_has_no_generic_query_or_write_surface() -> None:
    import newsroom.increment5.named_tool_branch_adapters as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "run_cypher",
        "raw_lucene",
        "execute_sql",
        "backend_selector",
        "requests.",
        "httpx",
        "socket",
        "create_candidate",
        "admit_relation",
        "publish",
        "activate_production",
    )
    assert not any(item in source for item in forbidden)
