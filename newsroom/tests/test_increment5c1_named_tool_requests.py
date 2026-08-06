from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from increment5c1_test_support import *  # noqa: F403,F401


def test_closed_inventory_has_exactly_six_tools_and_six_purposes() -> None:
    assert [item.value for item in ToolIdentity] == [
        "EXACT_AUTHORITY_LOOKUP",
        "BOUNDED_FULL_TEXT_RETRIEVAL",
        "BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL",
        "BOUNDED_ADMITTED_GRAPH_TRAVERSAL",
        "COLLISION_AUTHORITY_HYDRATION_LOOKUP",
        "SOURCE_REVISION_IMPACT_LOOKUP",
    ]
    assert len(ToolPurpose) == 6
    assert NAMED_TOOL_CONTRACT_DIGEST.startswith("sha256:")

@pytest.mark.parametrize("tool", list(ToolIdentity))
def test_every_named_tool_round_trips_through_its_strict_schema(tool: ToolIdentity) -> None:
    call = call_for(tool)
    decoded = NamedToolCall.from_mapping(call.canonical_value())
    assert decoded == call
    assert decoded.call_digest == call.call_digest

@pytest.mark.parametrize("locale", ["en-GB", "zh-Hant-HK", "mixed"])
def test_approved_locales_are_bounded(locale: str) -> None:
    request = FullTextToolRequest(
        normalized_query="bounded multilingual request",
        locale=locale,
        window_start=ts(1),
        window_end=ts(2),
    )
    assert request.locale == locale

@pytest.mark.parametrize("locale", ["en-US", "zh-CN", "", "mixed "])
def test_unapproved_locales_fail_closed(locale: str) -> None:
    with pytest.raises(NamedToolContractError, match="locale"):
        FullTextToolRequest(
            normalized_query="bounded request",
            locale=locale,
            window_start=ts(1),
            window_end=ts(2),
        )

def test_exact_scope_is_mandatory_for_source_native_lookup() -> None:
    with pytest.raises(NamedToolContractError, match="requires an authority scope"):
        ExactAuthorityToolRequest(
            lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
            lookup_value="native-123",
            authority_scope_id=None,
        )

def test_unscoped_exact_kind_cannot_smuggle_scope() -> None:
    with pytest.raises(NamedToolContractError, match="cannot carry"):
        ExactAuthorityToolRequest(
            lookup_kind=ExactLookupKind.CANONICAL_ENTITY_ID,
            lookup_value="entity-123",
            authority_scope_id="source-registry",
        )

@pytest.mark.parametrize(
    "query",
    [
        "title:secret",
        "alpha && beta",
        "alpha*",
        "(alpha OR beta)",
        "MATCH x DELETE x",
        "CREATE node",
    ],
)
def test_raw_lucene_cypher_and_write_like_text_is_rejected(query: str) -> None:
    with pytest.raises(NamedToolContractError, match="query|write"):
        FullTextToolRequest(
            normalized_query=query,
            locale="en-GB",
            window_start=ts(1),
            window_end=ts(2),
        )

@pytest.mark.parametrize(
    "replacement, message",
    [
        ({"result_limit": 9}, "result limit"),
        ({"byte_budget": NAMED_TOOL_BYTE_BUDGET + 1}, "byte budget"),
        ({"timeout_ms": NAMED_TOOL_TIMEOUT_MS + 1}, "timeout"),
    ],
)
def test_common_bounds_cannot_be_widened(replacement: dict[str, int], message: str) -> None:
    with pytest.raises(NamedToolContractError, match=message):
        ExactAuthorityToolRequest(
            lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
            lookup_value="native-123",
            authority_scope_id="source-registry",
            **replacement,
        )

def test_graph_shape_is_fixed_and_caller_cannot_choose_predicates_or_indexes() -> None:
    with pytest.raises(NamedToolContractError, match="depth"):
        AdmittedGraphToolRequest(root_id="canonical:root", depth=3)
    with pytest.raises(NamedToolContractError, match="fan-out"):
        AdmittedGraphToolRequest(root_id="canonical:root", fan_out=64)
    payload = call_for(ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL).canonical_value()
    payload["request"] = dict(payload["request"], predicate="SUPPORTS")
    receipt = NamedToolAuthorizer([]).authorize_payload(payload, completed_at=ts(6, 13))
    assert receipt.outcome is ToolAuthorizationOutcome.MALFORMED
    assert receipt.tool is None

def test_arbitrary_vector_and_index_fields_are_rejected_before_authorization() -> None:
    payload = call_for(
        ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL
    ).canonical_value()
    payload["request"] = dict(
        payload["request"],
        vector=[0.1, 0.2],
        index="caller-index",
    )
    receipt = NamedToolAuthorizer([]).authorize_payload(payload, completed_at=ts(6, 13))
    assert receipt.outcome is ToolAuthorizationOutcome.MALFORMED
    assert receipt.reason is ToolAuthorizationReason.MALFORMED_REQUEST

def test_unknown_common_or_nested_fields_are_rejected() -> None:
    call = call_for()
    payload = call.canonical_value()
    payload["model_instruction"] = "use another tool"
    malformed = NamedToolAuthorizer([]).authorize_payload(payload, completed_at=ts(6, 13))
    assert malformed.outcome is ToolAuthorizationOutcome.MALFORMED

    payload = call.canonical_value()
    payload["authentication"] = dict(payload["authentication"], credential="secret")
    malformed = NamedToolAuthorizer([]).authorize_payload(payload, completed_at=ts(6, 13))
    assert malformed.outcome is ToolAuthorizationOutcome.MALFORMED

def test_request_content_cannot_select_another_tool_or_change_response_schema() -> None:
    payload = call_for(ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL).canonical_value()
    payload["request"] = dict(
        payload["request"],
        tool="BOUNDED_ADMITTED_GRAPH_TRAVERSAL",
        response_schema="unbounded",
    )
    receipt = NamedToolAuthorizer([]).authorize_payload(payload, completed_at=ts(6, 13))
    assert receipt.outcome is ToolAuthorizationOutcome.MALFORMED

def test_call_rejects_tool_purpose_and_request_schema_mismatch() -> None:
    call = call_for()
    with pytest.raises(NamedToolContractError, match="purpose"):
        replace(call, purpose=ToolPurpose.RETRIEVE_TEXT_CONTEXT)
    with pytest.raises(NamedToolContractError, match="request schema"):
        replace(
            call,
            request=request_for(ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL),
        )

def test_call_requires_every_request_derived_scope() -> None:
    with pytest.raises(NamedToolContractError, match="exact request-derived scope"):
        call_for(scopes=("tool:exact-authority",))

def test_date_windows_are_bounded_and_cannot_extend_after_query_valid_time() -> None:
    with pytest.raises(NamedToolContractError, match="31 days"):
        SourceRevisionImpactToolRequest(
            source_id="source-1",
            revision_id=None,
            window_start=ts(1),
            window_end=CanonicalUtc(ts(1).value + timedelta(days=32)),
        )
    request = FullTextToolRequest(
        normalized_query="future window",
        locale="en-GB",
        window_start=ts(5),
        window_end=ts(7),
    )
    with pytest.raises(NamedToolContractError, match="query-valid"):
        call_for(ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL, request=request)

def test_collision_hydration_requires_governed_bytes_and_bounded_unique_ids() -> None:
    with pytest.raises(NamedToolContractError, match="governed bytes"):
        CollisionHydrationToolRequest(
            semantic_collision_digest=DIGEST_C,
            authority_ids=("authority:a",),
            include_retained_bytes=False,
        )
    with pytest.raises(NamedToolContractError, match="duplicates"):
        CollisionHydrationToolRequest(
            semantic_collision_digest=DIGEST_C,
            authority_ids=("authority:a", "authority:a"),
        )

