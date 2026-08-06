from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from increment5c1_test_support import *  # noqa: F403,F401


def test_grant_decoder_rejects_unknown_fields_and_non_boolean_enabled() -> None:
    call = call_for()
    value = dict(grant_for(call).canonical_value)
    value["extra"] = "no"
    with pytest.raises(NamedToolContractError, match="keys differ"):
        ToolAuthorizationGrant.from_mapping(value)

    value = dict(grant_for(call).canonical_value)
    value["enabled"] = 1
    with pytest.raises(NamedToolContractError, match="enabled"):
        ToolAuthorizationGrant.from_mapping(value)

def test_journal_replays_byte_identical_first_writer_and_does_not_reproduce(tmp_path: Path) -> None:
    call = call_for()
    receipt = authorize(call)
    journal = NamedToolAuthorizationJournal(tmp_path / "authorizations.sqlite")
    produced = 0

    def producer() -> ToolAuthorizationReceipt:
        nonlocal produced
        produced += 1
        return receipt

    first = journal.execute(call, producer)
    second = journal.execute(call, producer)
    assert first.replayed is False
    assert second.replayed is True
    assert second.receipt.canonical_bytes == first.receipt.canonical_bytes
    assert produced == 1

def test_journal_rejects_semantic_idempotency_conflict(tmp_path: Path) -> None:
    call = call_for()
    journal = NamedToolAuthorizationJournal(tmp_path / "authorizations.sqlite")
    journal.execute(call, lambda: authorize(call))
    conflicting = replace(
        call,
        request_id=str(uuid.uuid4()),
        request=ExactAuthorityToolRequest(
            lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
            lookup_value="different-native-id",
            authority_scope_id="source-registry",
        ),
    )
    with pytest.raises(NamedToolIdempotencyConflict):
        journal.execute(conflicting, lambda: authorize(conflicting))

def test_journal_detects_retained_byte_tampering(tmp_path: Path) -> None:
    call = call_for()
    path = tmp_path / "authorizations.sqlite"
    journal = NamedToolAuthorizationJournal(path)
    journal.execute(call, lambda: authorize(call))
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP TRIGGER immutable_named_tool_authorization_update")
        connection.execute(
            "UPDATE increment5_named_tool_authorizations SET receipt_bytes=?",
            (b"{}",),
        )
        connection.commit()
    with pytest.raises(NamedToolJournalError, match="digest"):
        journal.execute(call, lambda: authorize(call))

def test_journal_rows_cannot_be_updated_or_deleted(tmp_path: Path) -> None:
    call = call_for()
    path = tmp_path / "authorizations.sqlite"
    journal = NamedToolAuthorizationJournal(path)
    journal.execute(call, lambda: authorize(call))
    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE increment5_named_tool_authorizations SET recorded_at=recorded_at"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute("DELETE FROM increment5_named_tool_authorizations")

def test_modules_import_no_network_provider_or_retriever_client() -> None:
    paths = sorted((ROOT / "newsroom" / "increment5").glob("*named_tool*.py"))
    assert {path.name for path in paths} == {
        "_named_tool_common.py",
        "named_tool_authorization.py",
        "named_tool_authorizer.py",
        "named_tool_call.py",
        "named_tool_contract_identity.py",
        "named_tool_contracts.py",
        "named_tool_grants.py",
        "named_tool_journal.py",
        "named_tool_receipts.py",
        "named_tool_request_types.py",
        "named_tool_requests.py",
    }
    imported: set[str] = set()
    imported_modules: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported.update(
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported_modules.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
    assert imported.isdisjoint(
        {
            "httpx",
            "requests",
            "socket",
            "subprocess",
            "neo4j",
            "openai",
            "anthropic",
            "boto3",
        }
    )
    assert all(
        retriever not in module
        for module in imported_modules
        for retriever in (
            "exact_retriever",
            "fulltext_retriever",
            "vector_retriever",
            "admitted_graph_retriever",
        )
    )

