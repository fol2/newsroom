from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from newsroom.increment5.named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_DATE_WINDOW_SECONDS,
    NAMED_TOOL_GRAPH_DEPTH_LIMIT,
    NAMED_TOOL_GRAPH_FANOUT_LIMIT,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_QUERY_TEXT_LIMIT_BYTES,
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    NAMED_TOOL_RESULT_LIMIT,
    NAMED_TOOL_TIMEOUT_LIMIT_MS,
    AdmittedGraphTraversalToolRequest,
    CollisionHydrationLookupToolRequest,
    ExactAuthorityLookupToolRequest,
    ExactLookupKind,
    FixedPointVectorRetrievalToolRequest,
    FullTextRetrievalToolRequest,
    NamedToolContractError,
    NamedToolEnvelope,
    NamedToolId,
    NamedToolLanguage,
    NamedToolPurpose,
    PERMITTED_PURPOSES,
    SourceRevisionImpactLookupToolRequest,
    ToolScope,
    ToolScopeClaim,
    decode_named_tool_json,
    decode_named_tool_request,
)


PRINCIPAL_DIGEST = "sha256:" + hashlib.sha256(b"principal:triage").hexdigest()
POLICY_DIGEST = "sha256:" + hashlib.sha256(b"policy:named-tools").hexdigest()
FIXTURE_QUERY_DIGEST = "sha256:" + hashlib.sha256(b"fixture-query").hexdigest()
COLLISION_DIGEST = "sha256:" + hashlib.sha256(b"collision-key").hexdigest()
QUERY_VALID_TIME = "2026-08-06T08:59:00Z"
SERVING_TIME = "2026-08-06T09:00:00Z"
GENERATION_ID = "retrieval-generation-v1"


def digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def envelope(
    tool_id: NamedToolId,
    purpose: NamedToolPurpose,
    scope: ToolScope,
    *,
    grant_id: str | None = None,
    **overrides: object,
) -> NamedToolEnvelope:
    values: dict[str, object] = {
        "request_id": str(uuid.uuid4()),
        "idempotency_key": f"tool:{uuid.uuid4()}",
        "tool_id": tool_id,
        "actor_id": "triage_worker",
        "authenticated_principal_digest": PRINCIPAL_DIGEST,
        "authorization_grant_id": grant_id or f"grant:{tool_id.value.lower()}",
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


def exact_request(**envelope_overrides: object) -> ExactAuthorityLookupToolRequest:
    value = "source-native-001"
    return ExactAuthorityLookupToolRequest(
        envelope=envelope(
            NamedToolId.EXACT_AUTHORITY_LOOKUP,
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            ToolScope.from_dimensions(
                lookup_kind=(ExactLookupKind.SOURCE_NATIVE_ID.value,)
            ),
            **envelope_overrides,
        ),
        lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
        lookup_value=value,
        lookup_value_digest=digest_text(value),
    )


def fulltext_request(
    query_text: str = "harbour policy correction 港口政策更正",
    **envelope_overrides: object,
) -> FullTextRetrievalToolRequest:
    languages = (
        NamedToolLanguage.EN_GB,
        NamedToolLanguage.MIXED,
        NamedToolLanguage.ZH_HANT_HK,
    )
    sources = ("source:legislature", "source:registry")
    return FullTextRetrievalToolRequest(
        envelope=envelope(
            NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            ToolScope.from_dimensions(
                language=tuple(item.value for item in languages),
                source_id=sources,
            ),
            **envelope_overrides,
        ),
        query_text=query_text,
        query_text_digest=digest_text(query_text),
        languages=languages,
        source_ids=sources,
    )


def vector_request(**envelope_overrides: object) -> FixedPointVectorRetrievalToolRequest:
    query_id = "query:harbour-development"
    return FixedPointVectorRetrievalToolRequest(
        envelope=envelope(
            NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            ToolScope.from_dimensions(fixture_query=(query_id,)),
            **envelope_overrides,
        ),
        fixture_query_id=query_id,
        fixture_query_digest=FIXTURE_QUERY_DIGEST,
    )


def graph_request(**envelope_overrides: object) -> AdmittedGraphTraversalToolRequest:
    root_id = "source:root"
    return AdmittedGraphTraversalToolRequest(
        envelope=envelope(
            NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            ToolScope.from_dimensions(root_id=(root_id,)),
            **envelope_overrides,
        ),
        root_id=root_id,
        root_identity_digest=digest_text(f"canonical-node:{root_id}"),
        maximum_depth=NAMED_TOOL_GRAPH_DEPTH_LIMIT,
        maximum_fanout=NAMED_TOOL_GRAPH_FANOUT_LIMIT,
        temporal_window_seconds=NAMED_TOOL_DATE_WINDOW_SECONDS,
    )


def collision_request(**envelope_overrides: object) -> CollisionHydrationLookupToolRequest:
    objects = ("object:001", "object:002")
    passages = ("passage:001",)
    namespace = "candidate-development"
    return CollisionHydrationLookupToolRequest(
        envelope=envelope(
            NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
            NamedToolPurpose.COLLISION_CHECK,
            ToolScope.from_dimensions(
                authority_object_id=objects,
                collision_namespace=(namespace,),
                passage_id=passages,
            ),
            **envelope_overrides,
        ),
        collision_namespace=namespace,
        collision_key_digest=COLLISION_DIGEST,
        authority_object_ids=objects,
        passage_ids=passages,
        require_current_collision=True,
    )


def impact_request(**envelope_overrides: object) -> SourceRevisionImpactLookupToolRequest:
    source_id = "source:registry"
    revision_id = "revision:registry:042"
    return SourceRevisionImpactLookupToolRequest(
        envelope=envelope(
            NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP,
            NamedToolPurpose.SOURCE_IMPACT,
            ToolScope.from_dimensions(
                revision_id=(revision_id,),
                source_id=(source_id,),
            ),
            **envelope_overrides,
        ),
        source_id=source_id,
        revision_id=revision_id,
        window_start="2026-07-07T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
        lineage_depth=2,
        include_superseded=False,
    )


def mapping_for(request) -> dict[str, object]:
    return {
        "schema_version": request.SCHEMA_VERSION,
        "envelope": request.envelope.canonical_value(),
        **request.payload_value(),
    }


def test_tool_inventory_is_closed_and_exact() -> None:
    assert tuple(NamedToolId) == (
        NamedToolId.EXACT_AUTHORITY_LOOKUP,
        NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
        NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
        NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
        NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP,
    )
    assert set(PERMITTED_PURPOSES) == set(NamedToolId)


def test_contract_digest_binds_inventory_purposes_and_bounds() -> None:
    assert NAMED_TOOL_CONTRACT_DIGEST.startswith("sha256:")
    assert len(NAMED_TOOL_CONTRACT_DIGEST) == 71
    assert NAMED_TOOL_RESULT_LIMIT == 8
    assert NAMED_TOOL_TIMEOUT_LIMIT_MS == 5_000
    assert NAMED_TOOL_RESPONSE_LIMIT_BYTES == 262_144
    assert NAMED_TOOL_GRAPH_DEPTH_LIMIT == 2
    assert NAMED_TOOL_GRAPH_FANOUT_LIMIT == 32
    assert NAMED_TOOL_DATE_WINDOW_SECONDS == 2_678_400


def test_scope_is_canonical_content_addressed_and_subset_checked() -> None:
    grant = ToolScope.from_dimensions(
        language=("EN_GB", "MIXED", "ZH_HANT_HK"),
        source_id=("source:a", "source:b"),
    )
    requested = ToolScope.from_dimensions(
        language=("EN_GB", "MIXED"),
        source_id=("source:a",),
    )
    outside = ToolScope.from_dimensions(
        language=("EN_GB",),
        source_id=("source:c",),
    )
    assert grant.contains(requested)
    assert not grant.contains(outside)
    assert grant.scope_digest.startswith("sha256:")
    assert ToolScope.from_mapping(grant.canonical_value()) == grant


def test_scope_rejects_unsorted_duplicate_or_empty_claims() -> None:
    with pytest.raises(NamedToolContractError, match="sorted and unique"):
        ToolScopeClaim(dimension="source_id", values=("source:b", "source:a"))
    with pytest.raises(NamedToolContractError, match="sorted by unique dimension"):
        ToolScope(
            claims=(
                ToolScopeClaim("z", ("a",)),
                ToolScopeClaim("a", ("b",)),
            )
        )
    with pytest.raises(NamedToolContractError, match="at least one"):
        ToolScope(claims=())


def test_envelope_rejects_wrong_purpose_time_or_bounds() -> None:
    scope = ToolScope.from_dimensions(root_id=("source:root",))
    with pytest.raises(NamedToolContractError, match="purpose is not permitted"):
        envelope(
            NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
            NamedToolPurpose.SOURCE_IMPACT,
            scope,
        )
    with pytest.raises(NamedToolContractError, match="cannot be after"):
        envelope(
            NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            scope,
            query_valid_time="2026-08-06T09:00:01Z",
        )
    for field, value in (
        ("result_limit", 9),
        ("timeout_ms", 5_001),
        ("response_limit_bytes", 262_145),
    ):
        with pytest.raises(NamedToolContractError, match=field):
            envelope(
                NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
                NamedToolPurpose.TRIAGE_PRIOR_MATCH,
                scope,
                **{field: value},
            )


def test_all_six_request_schemas_round_trip_through_strict_decoder() -> None:
    requests = (
        exact_request(),
        fulltext_request(),
        vector_request(),
        graph_request(),
        collision_request(),
        impact_request(),
    )
    decoded = tuple(decode_named_tool_request(mapping_for(item)) for item in requests)
    assert decoded == requests
    assert len({item.request_digest for item in requests}) == 6
    for item in requests:
        raw = json.dumps(
            mapping_for(item),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert decode_named_tool_json(raw) == item


def test_unknown_or_extra_fields_fail_closed() -> None:
    request = mapping_for(graph_request())
    request["cypher"] = "MATCH (n) DETACH DELETE n"
    with pytest.raises(NamedToolContractError, match="extra"):
        decode_named_tool_request(request)

    nested = mapping_for(fulltext_request())
    assert isinstance(nested["envelope"], dict)
    nested["envelope"]["raw_lucene"] = "field:*"
    with pytest.raises(NamedToolContractError, match="extra"):
        decode_named_tool_request(nested)


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(NamedToolContractError, match="duplicate JSON key"):
        decode_named_tool_json(
            b'{"schema_version":"a","schema_version":"b"}'
        )


def test_unaccepted_schema_and_oversized_raw_request_fail_closed() -> None:
    with pytest.raises(NamedToolContractError, match="schema"):
        decode_named_tool_request({"schema_version": "unknown"})
    with pytest.raises(NamedToolContractError, match="exceed"):
        decode_named_tool_json(b"{" + b" " * NAMED_TOOL_RESPONSE_LIMIT_BYTES + b"}")


def test_exact_lookup_binds_value_bytes_and_scope() -> None:
    request = exact_request()
    assert request.lookup_value_digest == digest_text(request.lookup_value)
    with pytest.raises(NamedToolContractError, match="digest"):
        replace(request, lookup_value_digest="sha256:" + "0" * 64)
    with pytest.raises(NamedToolContractError, match="scope"):
        replace(
            request,
            envelope=replace(
                request.envelope,
                requested_scope=ToolScope.from_dimensions(
                    lookup_kind=(ExactLookupKind.AUTHORITY_ALIAS.value,)
                ),
            ),
        )


def test_fulltext_query_is_bounded_data_and_cannot_select_another_tool() -> None:
    injected = (
        'title:(*) OR CALL db.index.fulltext.queryNodes("other", "*") '
        'MATCH (n) DETACH DELETE n'
    )
    request = fulltext_request(injected)
    assert request.envelope.tool_id is NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL
    assert request.query_text == injected
    assert request.query_text_digest == digest_text(injected)
    assert set(request.envelope.canonical_value()).isdisjoint(
        {"index", "lucene", "cypher", "write", "destination"}
    )


def test_fulltext_rejects_digest_language_source_and_text_boundaries() -> None:
    request = fulltext_request()
    with pytest.raises(NamedToolContractError, match="digest"):
        replace(request, query_text_digest="sha256:" + "0" * 64)
    with pytest.raises(NamedToolContractError, match="sorted"):
        replace(
            request,
            languages=(NamedToolLanguage.ZH_HANT_HK, NamedToolLanguage.EN_GB),
        )
    with pytest.raises(NamedToolContractError, match="sorted and unique"):
        replace(request, source_ids=("source:z", "source:a"))
    too_long = "x" * (NAMED_TOOL_QUERY_TEXT_LIMIT_BYTES + 1)
    with pytest.raises(NamedToolContractError, match="bounded canonical text"):
        fulltext_request(too_long)


def test_vector_request_has_no_arbitrary_vector_or_model_surface() -> None:
    request = vector_request()
    assert set(mapping_for(request)).isdisjoint(
        {"vector", "embedding", "model", "provider", "credential"}
    )
    mapping = mapping_for(request)
    mapping["vector"] = [1.0, 2.0]
    with pytest.raises(NamedToolContractError, match="extra"):
        decode_named_tool_request(mapping)


def test_graph_request_binds_root_and_rejects_broader_shape() -> None:
    request = graph_request()
    assert request.root_identity_digest == digest_text(
        f"canonical-node:{request.root_id}"
    )
    with pytest.raises(NamedToolContractError, match="root digest"):
        replace(request, root_identity_digest="sha256:" + "0" * 64)
    with pytest.raises(NamedToolContractError, match="maximum_depth"):
        replace(request, maximum_depth=3)
    mapping = mapping_for(request)
    mapping["predicates"] = ["ANYTHING"]
    with pytest.raises(NamedToolContractError, match="extra"):
        decode_named_tool_request(mapping)


def test_collision_request_requires_current_relational_collision_and_named_authority() -> None:
    request = collision_request()
    assert request.require_current_collision is True
    with pytest.raises(NamedToolContractError, match="must require current"):
        replace(request, require_current_collision=False)
    with pytest.raises(NamedToolContractError, match="must name"):
        CollisionHydrationLookupToolRequest(
            envelope=envelope(
                NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
                NamedToolPurpose.COLLISION_CHECK,
                ToolScope.from_dimensions(
                    collision_namespace=("candidate-development",)
                ),
            ),
            collision_namespace="candidate-development",
            collision_key_digest=COLLISION_DIGEST,
            authority_object_ids=(),
            passage_ids=(),
            require_current_collision=True,
        )


def test_impact_request_enforces_date_and_lineage_bounds() -> None:
    request = impact_request()
    with pytest.raises(NamedToolContractError, match="exceeds"):
        replace(request, window_start="2026-06-01T00:00:00Z")
    with pytest.raises(NamedToolContractError, match="lineage_depth"):
        replace(request, lineage_depth=3)
    with pytest.raises(NamedToolContractError, match="increasing"):
        replace(request, window_start=request.window_end)


def test_typed_scope_cannot_be_widened_by_payload_or_query_content() -> None:
    request = fulltext_request("source_id=source:other; result_limit=999")
    assert request.envelope.result_limit == NAMED_TOOL_RESULT_LIMIT
    assert request.envelope.timeout_ms == NAMED_TOOL_TIMEOUT_LIMIT_MS
    assert request.envelope.requested_scope.as_mapping()["source_id"] == frozenset(
        {"source:legislature", "source:registry"}
    )
    with pytest.raises(NamedToolContractError, match="scope"):
        replace(
            request,
            source_ids=("source:legislature", "source:other", "source:registry"),
        )


def test_request_digest_binds_envelope_and_payload() -> None:
    request = graph_request()
    changed_time = replace(
        request,
        envelope=replace(
            request.envelope,
            query_valid_time="2026-08-06T08:58:59Z",
        ),
    )
    changed_root = graph_request()
    assert request.request_digest != changed_time.request_digest
    assert request.request_digest != changed_root.request_digest


def test_contract_module_is_branch_neutral_and_network_free() -> None:
    import newsroom.increment5.named_tool_contracts as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "exact_retriever",
        "fulltext_retriever",
        "vector_retriever",
        "admitted_graph_retriever",
        "neo4j",
        "requests",
        "httpx",
        "socket",
        "provider",
    )
    assert not any(item in source for item in forbidden)
