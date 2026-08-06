from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from increment5c1_test_support import *  # noqa: F403,F401


def test_no_named_tool_authorization_can_claim_execution_or_authority() -> None:
    receipt = authorize(call_for())
    value = receipt.canonical_value()
    assert "results" not in value
    assert "retrieval_context" not in value
    assert "candidate" not in value
    assert "authority_created" not in value
    assert value["external_calls"] == 0
    assert value["provider_spend_micros"] == 0

@pytest.mark.parametrize("tool", list(ToolIdentity))
def test_every_call_scope_is_exact_and_resource_bound(tool: ToolIdentity) -> None:
    call = call_for(tool)
    assert call.requested_scopes == tuple(sorted(call.request.scope_tokens()))
    scopes = set(call.requested_scopes)
    if tool is ToolIdentity.EXACT_AUTHORITY_LOOKUP:
        assert "lookup-kind:SOURCE_NATIVE_ID" in scopes
        assert "authority:source-registry" in scopes
    elif tool is ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
        assert "fixture:fixture-query-001" in scopes
    elif tool is ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
        assert "root:canonical:root" in scopes
    elif tool is ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP:
        assert f"collision:{DIGEST_C}" in scopes
        assert {"authority:authority:a", "authority:authority:b"}.issubset(scopes)
    elif tool is ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP:
        assert "source:source-1" in scopes
        assert "revision:revision-2" in scopes

def test_call_rejects_extra_scope_even_when_all_required_scopes_are_present() -> None:
    request = exact_request()
    with pytest.raises(NamedToolContractError, match="exact request-derived scope"):
        call_for(
            request=request,
            scopes=request.scope_tokens() + ("tool:admitted-graph",),
        )

@pytest.mark.parametrize(
    "field,value",
    [
        ("result_limit", 8.0),
        ("byte_budget", 262144.0),
        ("timeout_ms", 5000.0),
        ("result_limit", True),
    ],
)
def test_direct_request_construction_rejects_non_integer_bounds(
    field: str, value: object
) -> None:
    arguments = {
        "lookup_kind": ExactLookupKind.SOURCE_NATIVE_ID,
        "lookup_value": "native-123",
        "authority_scope_id": "source-registry",
        field: value,
    }
    with pytest.raises(NamedToolContractError, match="integer"):
        ExactAuthorityToolRequest(**arguments)  # type: ignore[arg-type]

def test_non_mapping_and_semantically_noncanonical_payloads_are_malformed() -> None:
    authorizer = NamedToolAuthorizer([])
    non_mapping = authorizer.authorize_payload(
        ["not", "a", "call"],
        completed_at=ts(6, 13),
    )
    assert non_mapping.outcome is ToolAuthorizationOutcome.MALFORMED
    assert non_mapping.call_digest is None

    payload = call_for().canonical_value()
    payload["requested_scopes"] = list(reversed(payload["requested_scopes"]))
    noncanonical = authorizer.authorize_payload(payload, completed_at=ts(6, 13))
    assert noncanonical.outcome is ToolAuthorizationOutcome.MALFORMED
    assert noncanonical.call_digest is None

def test_receipt_rejects_semantically_inconsistent_outcome_and_reason() -> None:
    receipt = authorize(call_for())
    with pytest.raises(NamedToolContractError, match="semantically inconsistent"):
        replace(
            receipt,
            outcome=ToolAuthorizationOutcome.STALE,
            reason=ToolAuthorizationReason.SCOPE_NOT_GRANTED,
            matched_grant_id=None,
            matched_grant_digest=None,
        )

def test_receipt_decoder_rejects_noncanonical_scope_order() -> None:
    receipt = authorize(call_for())
    changed = json.loads(receipt.canonical_bytes)
    changed["requested_scopes"] = list(reversed(changed["requested_scopes"]))
    noncanonical = json.dumps(
        changed,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(NamedToolContractError, match="semantically canonical"):
        ToolAuthorizationReceipt.from_canonical_bytes(noncanonical)

def test_mixed_expired_and_future_grants_report_no_current_grant() -> None:
    call = call_for()
    expired = grant_for(
        call,
        grant_id="grant-expired",
        valid_from=ts(1),
        valid_to=ts(5),
    )
    future = grant_for(
        call,
        grant_id="grant-future",
        valid_from=ts(7),
        valid_to=ts(20),
    )
    receipt = authorize(call, [expired, future])
    assert receipt.outcome is ToolAuthorizationOutcome.STALE
    assert receipt.reason is ToolAuthorizationReason.NO_CURRENT_GRANT

def test_public_tool_purpose_mapping_is_immutable() -> None:
    with pytest.raises(TypeError):
        TOOL_PURPOSE_BY_IDENTITY[ToolIdentity.EXACT_AUTHORITY_LOOKUP] = (  # type: ignore[index]
            ToolPurpose.RETRIEVE_TEXT_CONTEXT
        )

def test_subclassed_request_and_grant_records_are_rejected() -> None:
    class DerivedExactRequest(ExactAuthorityToolRequest):
        pass

    derived = DerivedExactRequest(
        lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
        lookup_value="native-123",
        authority_scope_id="source-registry",
    )
    with pytest.raises(NamedToolContractError, match="request schema"):
        call_for(request=derived)

    call = call_for()

    class DerivedGrant(ToolAuthorizationGrant):
        pass

    base = grant_for(call)
    derived_grant = DerivedGrant(**{
        "grant_id": base.grant_id,
        "actor_id": base.actor_id,
        "tool": base.tool,
        "purpose": base.purpose,
        "scopes": base.scopes,
        "policy_id": base.policy_id,
        "policy_digest": base.policy_digest,
        "profile_id": base.profile_id,
        "valid_from": base.valid_from,
        "valid_to": base.valid_to,
        "enabled": base.enabled,
    })
    with pytest.raises(NamedToolContractError, match="exact typed records"):
        NamedToolAuthorizer([derived_grant])

def test_authorization_completion_cannot_precede_serving_time() -> None:
    call = call_for()
    with pytest.raises(NamedToolContractError, match="before the call serving time"):
        NamedToolAuthorizer([grant_for(call)]).authorize(
            call,
            completed_at=ts(5, 23),
        )

def test_journal_detects_recorded_at_and_row_identity_tampering(tmp_path: Path) -> None:
    call = call_for()
    path = tmp_path / "authorizations.sqlite"
    journal = NamedToolAuthorizationJournal(path)
    journal.execute(call, lambda: authorize(call))
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP TRIGGER immutable_named_tool_authorization_update")
        connection.execute(
            "UPDATE increment5_named_tool_authorizations SET recorded_at=?",
            ("2026-08-06T13:00:01Z",),
        )
        connection.commit()
    with pytest.raises(NamedToolJournalError, match="record time"):
        journal.execute(call, lambda: authorize(call))

def test_journal_concurrency_retains_one_first_writer_receipt(tmp_path: Path) -> None:
    call = call_for()
    path = tmp_path / "authorizations.sqlite"
    journal = NamedToolAuthorizationJournal(path)

    def execute_at(hour: int) -> bytes:
        receipt = NamedToolAuthorizer([grant_for(call)]).authorize(
            call,
            completed_at=ts(6, hour),
        )
        return journal.execute(call, lambda: receipt).receipt.canonical_bytes

    with ThreadPoolExecutor(max_workers=4) as executor:
        retained = list(executor.map(execute_at, [13, 14, 15, 16]))
    assert len(set(retained)) == 1

def test_journal_rejects_wrong_producer_record_type(tmp_path: Path) -> None:
    call = call_for()
    journal = NamedToolAuthorizationJournal(tmp_path / "authorizations.sqlite")
    with pytest.raises(NamedToolJournalError, match="another record type"):
        journal.execute(call, lambda: object())  # type: ignore[arg-type,return-value]

