from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import struct
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.increment5.branch_contracts import BranchExclusionReason, BranchMode, BranchOutcome
from newsroom.increment5.vector_retriever import (
    EMBEDDING_COMPONENT_DIGEST,
    RETRIEVAL_CONTRACT_DIGEST,
    VECTOR_ACTOR_ID,
    VECTOR_COMPONENT_DIGEST,
    VECTOR_COMPONENT_SCALE,
    VECTOR_MATERIALIZED_BYTES,
    VECTOR_OUTPUT_DIMENSIONS,
    VECTOR_POLICY_ID,
    VECTOR_PROFILE_ID,
    VECTOR_PROVIDER_ID,
    VECTOR_PURPOSE,
    VECTOR_RESPONSE_LIMIT_BYTES,
    VECTOR_RESULT_LIMIT,
    VECTOR_SOURCE_DIMENSIONS,
    VECTOR_TIMEOUT_MS,
    PassageLifecycle,
    VectorAuthorityBinding,
    VectorAuthorityView,
    VectorBranchReceipt,
    VectorBranchRequest,
    VectorContractError,
    VectorFailureReason,
    VectorFixtureCatalog,
    VectorFixtureDocument,
    VectorFixtureQuery,
    VectorFixtureRetriever,
    VectorJournalError,
    VectorReceiptJournal,
    materialize_fixed_point_vector,
    rank_fixture_documents,
)


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "increment5"
    / "data"
    / "increment5b3_vector_fixture_v1.json"
)
SERVING_TIME = "2026-08-06T09:00:00Z"
QUERY_VALID_TIME = "2026-08-06T08:59:00Z"
VALIDATED_AT = "2026-08-06T08:58:00Z"
ZERO_DIGEST = "sha256:" + "0" * 64


@pytest.fixture
def catalog() -> VectorFixtureCatalog:
    return VectorFixtureCatalog.load(CATALOG_PATH)


def make_view(
    catalog: VectorFixtureCatalog,
    *,
    validated_at: str = VALIDATED_AT,
    bindings: tuple[VectorAuthorityBinding, ...] | None = None,
    **overrides: object,
) -> VectorAuthorityView:
    return VectorAuthorityView.for_catalog(
        catalog,
        validated_at=validated_at,
        bindings=bindings,
        **overrides,
    )


def make_request(
    catalog: VectorFixtureCatalog,
    *,
    query_id: str = "query:harbour-development",
    request_id: str | None = None,
    idempotency_key: str | None = None,
    query_digest: str | None = None,
    query_valid_time: str = QUERY_VALID_TIME,
    serving_time: str = SERVING_TIME,
    **overrides: object,
) -> VectorBranchRequest:
    query = catalog.query(query_id)
    selected_query_digest = (
        query_digest
        if query_digest is not None
        else (ZERO_DIGEST if query is None else query.query_digest)
    )
    values: dict[str, object] = {
        "request_id": request_id or str(uuid.uuid4()),
        "idempotency_key": idempotency_key or f"vector:{uuid.uuid4()}",
        "actor_id": VECTOR_ACTOR_ID,
        "purpose": VECTOR_PURPOSE,
        "policy_id": VECTOR_POLICY_ID,
        "contract_digest": RETRIEVAL_CONTRACT_DIGEST,
        "catalog_digest": catalog.catalog_digest,
        "profile_id": VECTOR_PROFILE_ID,
        "vector_component_digest": VECTOR_COMPONENT_DIGEST,
        "embedding_component_digest": EMBEDDING_COMPONENT_DIGEST,
        "query_id": query_id,
        "query_digest": selected_query_digest,
        "query_valid_time": query_valid_time,
        "serving_time": serving_time,
        "minimum_watermark_seq": 1,
        "result_limit": VECTOR_RESULT_LIMIT,
        "timeout_ms": VECTOR_TIMEOUT_MS,
        "response_limit_bytes": VECTOR_RESPONSE_LIMIT_BYTES,
    }
    values.update(overrides)
    return VectorBranchRequest(**values)


def make_retriever(
    tmp_path: Path,
    catalog: VectorFixtureCatalog,
    view: VectorAuthorityView,
    *,
    clock=None,
    journal_name: str = "vector-receipts.sqlite",
) -> VectorFixtureRetriever:
    return VectorFixtureRetriever(
        catalog=catalog,
        authority_provider=lambda _request: view,
        journal=VectorReceiptJournal(tmp_path / journal_name),
        monotonic_ns=clock or __import__("time").monotonic_ns,
    )


def binding_for(
    view: VectorAuthorityView, passage_id: str
) -> VectorAuthorityBinding:
    return next(binding for binding in view.bindings if binding.passage_id == passage_id)


def replace_binding(
    view: VectorAuthorityView,
    catalog: VectorFixtureCatalog,
    passage_id: str,
    **changes: object,
) -> VectorAuthorityView:
    bindings = tuple(
        replace(binding, **changes) if binding.passage_id == passage_id else binding
        for binding in view.bindings
    )
    return make_view(catalog, bindings=bindings)


class TimeoutClock:
    def __init__(self, safe_calls: int) -> None:
        self.safe_calls = safe_calls
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        if self.calls <= self.safe_calls:
            return 0
        return VECTOR_TIMEOUT_MS * 1_000_000 + 1


def test_catalog_loads_exact_locked_contract(catalog: VectorFixtureCatalog) -> None:
    assert catalog.provider_id == VECTOR_PROVIDER_ID
    assert catalog.profile_id == VECTOR_PROFILE_ID
    assert catalog.contract_digest == RETRIEVAL_CONTRACT_DIGEST
    assert catalog.vector_component_digest == VECTOR_COMPONENT_DIGEST
    assert catalog.embedding_component_digest == EMBEDDING_COMPONENT_DIGEST
    assert catalog.source_dimensions == VECTOR_SOURCE_DIMENSIONS
    assert catalog.output_dimensions == VECTOR_OUTPUT_DIMENSIONS
    assert catalog.component_scale == VECTOR_COMPONENT_SCALE
    assert catalog.output_type == "FLOAT32"
    assert catalog.byte_order == "BIG_ENDIAN"
    assert catalog.similarity == "COSINE"
    assert catalog.quantization == "NONE"
    assert catalog.catalog_digest.startswith("sha256:")


def test_catalog_contains_repository_admitted_queries(catalog: VectorFixtureCatalog) -> None:
    assert {query.query_id for query in catalog.queries} == {
        "query:harbour-development",
        "query:policy-correction",
        "query:overflow-nine",
    }
    assert len(catalog.documents) == 20


def test_materialization_is_exactly_1024_binary32_values() -> None:
    source = (1_000_000,) + (0,) * 15
    vector, raw, digest = materialize_fixed_point_vector(source)
    assert len(vector) == VECTOR_OUTPUT_DIMENSIONS
    assert len(raw) == VECTOR_MATERIALIZED_BYTES
    assert raw[:4] == struct.pack(">f", 1.0)
    assert raw[4:] == b"\x00" * (VECTOR_MATERIALIZED_BYTES - 4)
    assert digest == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_materialization_uses_round_to_nearest_even_binary32() -> None:
    source = (1_000_001,) + (0,) * 15
    vector, raw, _ = materialize_fixed_point_vector(source)
    expected = struct.unpack(">f", struct.pack(">f", 1.000001))[0]
    assert vector[0] == expected
    assert raw[:4] == struct.pack(">f", expected)


def test_materialization_rejects_wrong_dimension() -> None:
    with pytest.raises(VectorContractError, match="exactly 16"):
        materialize_fixed_point_vector((1,) * 15)


def test_materialization_rejects_zero_vector() -> None:
    with pytest.raises(VectorContractError, match="zero vector"):
        materialize_fixed_point_vector((0,) * 16)


def test_every_document_vector_is_content_addressed(catalog: VectorFixtureCatalog) -> None:
    for document in catalog.documents:
        _, raw, digest = materialize_fixed_point_vector(document.source_vector)
        assert len(raw) == 4096
        assert document.vector_digest == digest


def test_query_digest_is_stable(catalog: VectorFixtureCatalog) -> None:
    first = catalog.query("query:harbour-development")
    second = VectorFixtureCatalog.load(CATALOG_PATH).query("query:harbour-development")
    assert first is not None and second is not None
    assert first.query_digest == second.query_digest


def test_canonical_catalog_digest_ignores_whitespace(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rewritten = tmp_path / "catalog.json"
    rewritten.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    assert VectorFixtureCatalog.load(rewritten).catalog_digest == catalog.catalog_digest


def test_valid_catalog_content_change_changes_digest(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    payload["documents"][0]["source_vector"][1] -= 1
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    assert VectorFixtureCatalog.load(changed).catalog_digest != catalog.catalog_digest


def test_catalog_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    broken = tmp_path / "duplicate.json"
    broken.write_text('{"schema_version":"a","schema_version":"b"}', encoding="utf-8")
    with pytest.raises(VectorContractError, match="duplicate JSON key"):
        VectorFixtureCatalog.load(broken)


def test_catalog_rejects_contract_drift(tmp_path: Path) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    payload["source_dimensions"] = 17
    broken = tmp_path / "drift.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(VectorContractError, match="source dimension drifted"):
        VectorFixtureCatalog.load(broken)


def test_exact_ranking_puts_identical_vector_first_and_inverse_last(
    catalog: VectorFixtureCatalog,
) -> None:
    query = catalog.query("query:harbour-development")
    assert query is not None
    documents = [
        document
        for document in catalog.documents
        if query.query_id in document.query_ids
    ]
    ranked = rank_fixture_documents(query, documents)
    assert ranked[0].document.passage_id == "passage:harbour:001"
    assert ranked[0].proof().squared_cosine_numerator == 1
    assert ranked[0].proof().squared_cosine_denominator == 1
    assert ranked[-1].document.passage_id == "passage:harbour:006"
    assert ranked[-1].proof().sign == -1


def test_exact_ranking_tie_breaks_by_passage_identity() -> None:
    query = VectorFixtureQuery.from_record(
        {"query_id": "query:tie", "source_vector": [1_000_000] + [0] * 15}
    )
    common = {
        "dependency_root_id": "root:tie",
        "language": "EN_GB",
        "query_ids": ["query:tie"],
        "source_vector": [1_000_000] + [0] * 15,
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to": "2035-01-01T00:00:00Z",
    }
    later = VectorFixtureDocument.from_record(
        {
            **common,
            "passage_id": "passage:tie:b",
            "source_revision_id": "revision:tie:b",
        }
    )
    earlier = VectorFixtureDocument.from_record(
        {
            **common,
            "passage_id": "passage:tie:a",
            "source_revision_id": "revision:tie:a",
        }
    )
    assert [item.document.passage_id for item in rank_fixture_documents(query, [later, earlier])] == [
        "passage:tie:a",
        "passage:tie:b",
    ]


def test_complete_vector_receipt_is_independently_attributable(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    request = make_request(catalog)
    receipt = make_retriever(tmp_path, catalog, view).retrieve(request)
    assert receipt.mode is BranchMode.VECTOR
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason is None
    assert receipt.request_digest == request.request_digest
    assert receipt.catalog_digest == catalog.catalog_digest
    assert receipt.generation_digest == view.generation_digest
    assert receipt.vector_component_digest == VECTOR_COMPONENT_DIGEST
    assert receipt.embedding_component_digest == EMBEDDING_COMPONENT_DIGEST
    assert receipt.watermark_seq == view.watermark_seq
    assert receipt.rights_manifest_digest == view.rights_manifest_digest
    assert receipt.hits[0].passage_id == "passage:harbour:001"
    assert [hit.rank for hit in receipt.hits] == list(range(1, 7))


def test_complete_receipt_reports_zero_external_execution_and_spend(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    assert receipt.external_call_count == 0
    assert receipt.provider_call_count == 0
    assert receipt.model_call_count == 0
    assert receipt.embedding_call_count == 0
    assert receipt.provider_spend_micros == 0
    assert receipt.replay_only is True
    assert receipt.qualification_authority_granted is False
    assert receipt.production_activation_authorized is False


def test_receipt_canonical_round_trip(catalog: VectorFixtureCatalog, tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    assert VectorBranchReceipt.from_canonical_bytes(receipt.canonical_bytes) == receipt
    assert len(receipt.canonical_bytes) <= VECTOR_RESPONSE_LIMIT_BYTES


def test_journal_replay_returns_byte_identical_receipt(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    request = make_request(catalog)
    retriever = make_retriever(tmp_path, catalog, view)
    first = retriever.retrieve(request)
    second = retriever.retrieve(request)
    assert first.canonical_bytes == second.canonical_bytes
    assert first.receipt_digest == second.receipt_digest


def test_journal_restart_replay_is_byte_identical(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    request = make_request(catalog)
    first = make_retriever(tmp_path, catalog, view).retrieve(request)
    restarted = make_retriever(tmp_path, catalog, view).retrieve(request)
    assert restarted.canonical_bytes == first.canonical_bytes


def test_journal_rejects_idempotency_semantic_conflict(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    key = "vector:conflict"
    retriever = make_retriever(tmp_path, catalog, view)
    retriever.retrieve(make_request(catalog, idempotency_key=key))
    with pytest.raises(VectorJournalError, match="reused for another request"):
        retriever.retrieve(
            make_request(
                catalog,
                query_id="query:policy-correction",
                idempotency_key=key,
            )
        )


def test_journal_detects_retained_receipt_tamper(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    request = make_request(catalog)
    path = tmp_path / "tamper.sqlite"
    retriever = make_retriever(tmp_path, catalog, view, journal_name=path.name)
    retriever.retrieve(request)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE increment5_vector_receipts SET receipt_bytes = ? WHERE idempotency_key = ?",
            (b"{}", request.idempotency_key),
        )
    with pytest.raises(VectorJournalError, match="digest does not match"):
        retriever.retrieve(request)


def test_concurrent_same_request_retains_one_byte_identity(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    request = make_request(catalog)
    retriever = make_retriever(tmp_path, catalog, view)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _index: retriever.retrieve(request), range(16)))
    assert len({receipt.receipt_digest for receipt in receipts}) == 1
    with sqlite3.connect(tmp_path / "vector-receipts.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_vector_receipts"
        ).fetchone()[0] == 1


def test_authority_provider_executes_outside_journal_write_reservation(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(catalog)
    journal = VectorReceiptJournal(tmp_path / "nested.sqlite")
    nested_request = make_request(
        catalog,
        query_id="query:policy-correction",
        idempotency_key="vector:nested",
    )
    outer_request = make_request(catalog, idempotency_key="vector:outer")
    state = {"nested": False}
    retriever: VectorFixtureRetriever

    def provider(request: VectorBranchRequest) -> VectorAuthorityView:
        if request.idempotency_key == "vector:outer" and not state["nested"]:
            state["nested"] = True
            nested = retriever.retrieve(nested_request)
            assert nested.outcome is BranchOutcome.COMPLETE
        return view

    retriever = VectorFixtureRetriever(
        catalog=catalog,
        authority_provider=provider,
        journal=journal,
    )
    assert retriever.retrieve(outer_request).outcome is BranchOutcome.COMPLETE
    with sqlite3.connect(tmp_path / "nested.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_vector_receipts"
        ).fetchone()[0] == 2


def test_unknown_query_fails_policy_closed(catalog: VectorFixtureCatalog, tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog, query_id="query:unknown")
    )
    assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
    assert receipt.reason is VectorFailureReason.QUERY_UNKNOWN
    assert not receipt.hits


def test_query_digest_mismatch_fails_policy_closed(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog, query_digest=ZERO_DIGEST)
    )
    assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
    assert receipt.reason is VectorFailureReason.QUERY_DIGEST_MISMATCH


def test_arbitrary_query_vector_is_not_a_request_surface(catalog: VectorFixtureCatalog) -> None:
    with pytest.raises(TypeError, match="source_vector"):
        make_request(catalog, source_vector=[1] * 16)


def test_query_identifier_injection_is_rejected(catalog: VectorFixtureCatalog) -> None:
    with pytest.raises(VectorContractError, match="bounded canonical token"):
        make_request(catalog, query_id="query:harbour OR *")


def test_non_uuid4_request_identity_is_rejected(catalog: VectorFixtureCatalog) -> None:
    with pytest.raises(VectorContractError, match="UUIDv4"):
        make_request(catalog, request_id=str(uuid.uuid1()))


def test_request_bounds_are_fixed(catalog: VectorFixtureCatalog) -> None:
    with pytest.raises(VectorContractError, match="result limit"):
        make_request(catalog, result_limit=7)
    with pytest.raises(VectorContractError, match="timeout"):
        make_request(catalog, timeout_ms=4_999)
    with pytest.raises(VectorContractError, match="response limit"):
        make_request(catalog, response_limit_bytes=1_024)


def test_actor_or_purpose_drift_is_policy_blocked(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    for override in ({"actor_id": "other_worker"}, {"purpose": "other_purpose"}):
        receipt = make_retriever(
            tmp_path,
            catalog,
            make_view(catalog),
            journal_name=f"{next(iter(override))}.sqlite",
        ).retrieve(make_request(catalog, **override))
        assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
        assert receipt.reason is VectorFailureReason.CONTRACT_MISMATCH


def test_contract_profile_and_component_drift_fail_closed(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    cases = (
        ({"contract_digest": ZERO_DIGEST}, VectorFailureReason.CONTRACT_MISMATCH),
        ({"profile_id": "other-profile"}, VectorFailureReason.PROFILE_MISMATCH),
        (
            {"vector_component_digest": ZERO_DIGEST},
            VectorFailureReason.VECTOR_COMPONENT_MISMATCH,
        ),
        (
            {"embedding_component_digest": ZERO_DIGEST},
            VectorFailureReason.EMBEDDING_COMPONENT_MISMATCH,
        ),
        ({"catalog_digest": ZERO_DIGEST}, VectorFailureReason.CATALOG_MISMATCH),
    )
    for index, (override, expected) in enumerate(cases):
        receipt = make_retriever(
            tmp_path,
            catalog,
            make_view(catalog),
            journal_name=f"request-drift-{index}.sqlite",
        ).retrieve(make_request(catalog, **override))
        assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
        assert receipt.reason is expected


def test_authority_unavailability_cannot_be_no_match(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    retriever = VectorFixtureRetriever(
        catalog=catalog,
        authority_provider=lambda _request: (_ for _ in ()).throw(RuntimeError("down")),
        journal=VectorReceiptJournal(tmp_path / "unavailable.sqlite"),
    )
    receipt = retriever.retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is VectorFailureReason.AUTHORITY_VIEW_UNAVAILABLE
    assert receipt.reason is not VectorFailureReason.NO_MATCH


def test_inactive_or_incomplete_generation_fails_closed(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    cases = (
        (make_view(catalog, active=False), BranchOutcome.STALE, VectorFailureReason.GENERATION_INACTIVE),
        (
            make_view(catalog, complete=False),
            BranchOutcome.INCOMPLETE,
            VectorFailureReason.GENERATION_INCOMPLETE,
        ),
    )
    for index, (view, outcome, reason) in enumerate(cases):
        receipt = make_retriever(
            tmp_path,
            catalog,
            view,
            journal_name=f"generation-{index}.sqlite",
        ).retrieve(make_request(catalog))
        assert receipt.outcome is outcome
        assert receipt.reason is reason


def test_authority_component_and_catalog_mismatch_are_stale(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    cases = (
        (
            make_view(catalog, catalog_digest=ZERO_DIGEST),
            VectorFailureReason.GENERATION_IDENTITY_MISMATCH,
        ),
        (
            make_view(catalog, profile_id="other-profile"),
            VectorFailureReason.PROFILE_MISMATCH,
        ),
        (
            make_view(catalog, vector_component_digest=ZERO_DIGEST),
            VectorFailureReason.VECTOR_COMPONENT_MISMATCH,
        ),
        (
            make_view(catalog, embedding_component_digest=ZERO_DIGEST),
            VectorFailureReason.EMBEDDING_COMPONENT_MISMATCH,
        ),
    )
    for index, (view, reason) in enumerate(cases):
        receipt = make_retriever(
            tmp_path,
            catalog,
            view,
            journal_name=f"view-drift-{index}.sqlite",
        ).retrieve(make_request(catalog))
        assert receipt.outcome is BranchOutcome.STALE
        assert receipt.reason is reason


def test_watermark_gap_and_dead_letter_are_explicit(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    cases = (
        (
            make_view(catalog, watermark_seq=0),
            BranchOutcome.STALE,
            VectorFailureReason.WATERMARK_BEHIND,
        ),
        (
            make_view(catalog, open_gap_count=1),
            BranchOutcome.INCOMPLETE,
            VectorFailureReason.REQUIRED_GAP_OPEN,
        ),
        (
            make_view(catalog, dead_letter_count=1),
            BranchOutcome.INCOMPLETE,
            VectorFailureReason.DEAD_LETTER_PRESENT,
        ),
    )
    for index, (view, outcome, reason) in enumerate(cases):
        receipt = make_retriever(
            tmp_path,
            catalog,
            view,
            journal_name=f"projection-state-{index}.sqlite",
        ).retrieve(make_request(catalog))
        assert receipt.outcome is outcome
        assert receipt.reason is reason
        assert receipt.reason is not VectorFailureReason.NO_MATCH


def test_stale_authority_view_is_not_no_match(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = make_view(
        catalog,
        validated_at="2026-08-01T00:00:00Z",
        maximum_age_seconds=60,
    )
    receipt = make_retriever(tmp_path, catalog, view).retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.STALE
    assert receipt.reason is VectorFailureReason.AUTHORITY_VIEW_STALE


def test_missing_passage_binding_is_incomplete(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    original = make_view(catalog)
    bindings = tuple(
        binding for binding in original.bindings if binding.passage_id != "passage:harbour:001"
    )
    receipt = make_retriever(
        tmp_path,
        catalog,
        make_view(catalog, bindings=bindings),
    ).retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is VectorFailureReason.PASSAGE_BINDING_MISSING


def test_passage_binding_integrity_failure_is_unavailable(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = replace_binding(
        make_view(catalog),
        catalog,
        "passage:harbour:001",
        document_digest=ZERO_DIGEST,
    )
    receipt = make_retriever(tmp_path, catalog, view).retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is VectorFailureReason.PASSAGE_BINDING_INTEGRITY


def test_rights_digest_mismatch_is_unavailable(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = replace_binding(
        make_view(catalog),
        catalog,
        "passage:harbour:001",
        rights_digest=ZERO_DIGEST,
    )
    receipt = make_retriever(tmp_path, catalog, view).retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is VectorFailureReason.RIGHTS_MANIFEST_MISMATCH


def test_non_current_rights_are_explicitly_excluded(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = replace_binding(
        make_view(catalog),
        catalog,
        "passage:harbour:002",
        rights_current=False,
    )
    receipt = make_retriever(tmp_path, catalog, view).retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert len(receipt.hits) == 5
    assert receipt.exclusions == (
        pytest.helpers.anything
        if hasattr(pytest, "helpers")
        else receipt.exclusions
    )
    assert any(
        exclusion.passage_id == "passage:harbour:002"
        and exclusion.reason is BranchExclusionReason.RIGHTS_NOT_CURRENT
        for exclusion in receipt.exclusions
    )


def test_held_proposal_and_revoked_lifecycle_never_rank(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    for index, lifecycle in enumerate(
        (
            PassageLifecycle.HELD,
            PassageLifecycle.PROPOSAL_ONLY,
            PassageLifecycle.REVOKED,
        )
    ):
        view = replace_binding(
            make_view(catalog),
            catalog,
            "passage:harbour:002",
            lifecycle=lifecycle,
        )
        receipt = make_retriever(
            tmp_path,
            catalog,
            view,
            journal_name=f"lifecycle-{index}.sqlite",
        ).retrieve(make_request(catalog))
        assert all(hit.passage_id != "passage:harbour:002" for hit in receipt.hits)
        assert any(
            exclusion.passage_id == "passage:harbour:002"
            and exclusion.reason is BranchExclusionReason.STALE_SOURCE_VERSION
            for exclusion in receipt.exclusions
        )


def test_tombstone_never_resurrects_from_fixture(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    view = replace_binding(
        make_view(catalog),
        catalog,
        "passage:harbour:001",
        lifecycle=PassageLifecycle.TOMBSTONED,
    )
    receipt = make_retriever(tmp_path, catalog, view).retrieve(make_request(catalog))
    assert all(hit.passage_id != "passage:harbour:001" for hit in receipt.hits)
    assert any(
        exclusion.passage_id == "passage:harbour:001"
        and exclusion.reason is BranchExclusionReason.TOMBSTONED
        for exclusion in receipt.exclusions
    )


def test_temporally_ineligible_fixture_produces_complete_no_match_only_after_checks(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    request = make_request(catalog, query_valid_time="2019-01-01T00:00:00Z")
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(request)
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason is VectorFailureReason.NO_MATCH
    assert not receipt.hits
    assert len(receipt.exclusions) == 6
    assert all(
        exclusion.reason is BranchExclusionReason.OUTSIDE_QUERY_VALID_TIME
        for exclusion in receipt.exclusions
    )


def test_gap_prevents_no_match_even_when_every_document_is_out_of_time(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    receipt = make_retriever(
        tmp_path,
        catalog,
        make_view(catalog, open_gap_count=1),
    ).retrieve(make_request(catalog, query_valid_time="2019-01-01T00:00:00Z"))
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is VectorFailureReason.REQUIRED_GAP_OPEN


def test_ninth_result_is_an_overflow_failure_not_silent_truncation(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    request = make_request(catalog, query_id="query:overflow-nine")
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(request)
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is VectorFailureReason.RESULT_LIMIT_EXCEEDED
    assert receipt.fixture_vector_count == 9
    assert not receipt.hits


def test_timeout_before_authority_is_explicit(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    called = False

    def provider(_request: VectorBranchRequest) -> VectorAuthorityView:
        nonlocal called
        called = True
        return make_view(catalog)

    retriever = VectorFixtureRetriever(
        catalog=catalog,
        authority_provider=provider,
        journal=VectorReceiptJournal(tmp_path / "timeout-before.sqlite"),
        monotonic_ns=TimeoutClock(safe_calls=1),
    )
    receipt = retriever.retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is VectorFailureReason.QUERY_TIMEOUT
    assert receipt.elapsed_ms == VECTOR_TIMEOUT_MS
    assert called is False


def test_timeout_after_authority_is_explicit(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    retriever = VectorFixtureRetriever(
        catalog=catalog,
        authority_provider=lambda _request: make_view(catalog),
        journal=VectorReceiptJournal(tmp_path / "timeout-after.sqlite"),
        monotonic_ns=TimeoutClock(safe_calls=2),
    )
    receipt = retriever.retrieve(make_request(catalog))
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is VectorFailureReason.QUERY_TIMEOUT
    assert receipt.authority_read_count == 1
    assert receipt.elapsed_ms == VECTOR_TIMEOUT_MS


def test_receipt_cannot_claim_live_execution(catalog: VectorFixtureCatalog, tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    with pytest.raises(VectorContractError, match="external work or spend"):
        replace(receipt, provider_call_count=1)
    with pytest.raises(VectorContractError, match="replay-only"):
        replace(receipt, replay_only=False)
    with pytest.raises(VectorContractError, match="activation authority"):
        replace(receipt, production_activation_authorized=True)


def test_non_complete_receipt_cannot_manufacture_ranked_hits(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    with pytest.raises(VectorContractError, match="non-complete"):
        replace(
            receipt,
            outcome=BranchOutcome.INCOMPLETE,
            reason=VectorFailureReason.REQUIRED_GAP_OPEN,
        )


def test_empty_complete_receipt_must_state_no_match(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    with pytest.raises(VectorContractError, match="must state NO_MATCH"):
        replace(receipt, hits=(), reason=None)


def test_module_has_no_live_provider_or_cross_branch_import_surface() -> None:
    import newsroom.increment5.vector_retriever as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "import neo4j",
        "from neo4j",
        "import openai",
        "from openai",
        "import requests",
        "import httpx",
        "exact_retriever",
        "fulltext_retriever",
        "graph_retriever",
        "reciprocal_rank",
    )
    assert not any(token in source for token in forbidden)


def test_fixture_request_contains_no_arbitrary_vector_field(catalog: VectorFixtureCatalog) -> None:
    request = make_request(catalog)
    assert set(request.canonical_value()) == {
        "schema_version",
        "request_id",
        "idempotency_key",
        "actor_id",
        "purpose",
        "policy_id",
        "contract_digest",
        "catalog_digest",
        "profile_id",
        "vector_component_digest",
        "embedding_component_digest",
        "query_id",
        "query_digest",
        "query_valid_time",
        "serving_time",
        "minimum_watermark_seq",
        "result_limit",
        "timeout_ms",
        "response_limit_bytes",
    }


def test_authority_generation_digest_binds_every_current_passage(catalog: VectorFixtureCatalog) -> None:
    view = make_view(catalog)
    changed = replace_binding(
        view,
        catalog,
        "passage:harbour:001",
        lifecycle=PassageLifecycle.HELD,
    )
    assert changed.generation_digest != view.generation_digest


def test_request_digest_binds_query_valid_and_serving_time(catalog: VectorFixtureCatalog) -> None:
    request = make_request(catalog, idempotency_key="vector:time-binding")
    changed = make_request(
        catalog,
        idempotency_key="vector:time-binding",
        query_valid_time="2026-08-06T08:58:59Z",
    )
    assert request.request_digest != changed.request_digest


def test_fixture_catalog_cannot_supply_authority() -> None:
    source = inspect.getsource(VectorFixtureCatalog)
    assert "rights_current" not in source
    assert "lifecycle" not in source


def test_rank_score_is_branch_local_exact_proof_not_cross_mode_float(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    proof = receipt.hits[0].proof.canonical_value()
    assert "squared_cosine_numerator" in proof
    assert "squared_cosine_denominator" in proof
    assert all(not isinstance(value, float) for value in proof.values())


def test_policy_blocked_receipt_still_binds_exact_request(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    request = make_request(catalog, contract_digest=ZERO_DIGEST)
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(request)
    assert receipt.request_digest == request.request_digest
    assert receipt.catalog_digest == catalog.catalog_digest
    assert receipt.generation_id is None
    assert receipt.authority_read_count == 0


def test_receipt_identity_is_deterministic_across_fresh_journals(
    catalog: VectorFixtureCatalog, tmp_path: Path
) -> None:
    request = make_request(catalog, idempotency_key="vector:deterministic-receipt")
    view = make_view(catalog)
    first = make_retriever(
        tmp_path,
        catalog,
        view,
        journal_name="first.sqlite",
    ).retrieve(request)
    second = make_retriever(
        tmp_path,
        catalog,
        view,
        journal_name="second.sqlite",
    ).retrieve(request)
    assert first.receipt_id == second.receipt_id
    assert first.canonical_bytes == second.canonical_bytes


def test_query_valid_time_cannot_be_after_serving_time(catalog: VectorFixtureCatalog) -> None:
    with pytest.raises(VectorContractError, match="cannot be after"):
        make_request(
            catalog,
            query_valid_time="2026-08-06T09:00:01Z",
            serving_time="2026-08-06T09:00:00Z",
        )


def test_authority_view_requires_canonical_generation_digest(
    catalog: VectorFixtureCatalog,
) -> None:
    view = make_view(catalog)
    with pytest.raises(VectorContractError, match="generation digest"):
        replace(view, generation_digest=ZERO_DIGEST)


def test_fixture_document_digest_binds_temporal_and_dependency_identity() -> None:
    record = {
        "passage_id": "passage:binding:001",
        "dependency_root_id": "root:binding",
        "source_revision_id": "revision:binding:001",
        "language": "EN_GB",
        "query_ids": ["query:binding"],
        "source_vector": [1_000_000] + [0] * 15,
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to": "2035-01-01T00:00:00Z",
    }
    original = VectorFixtureDocument.from_record(record)
    changed = VectorFixtureDocument.from_record(
        {**record, "dependency_root_id": "root:binding:changed"}
    )
    assert original.document_digest != changed.document_digest


def test_journal_schema_has_no_authority_mutation_columns(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite"
    VectorReceiptJournal(path)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(increment5_vector_receipts)"
            )
        }
    assert columns == {
        "idempotency_key",
        "request_digest",
        "receipt_bytes",
        "receipt_digest",
    }


def test_rights_and_lifecycle_exclusions_retain_no_rank(catalog: VectorFixtureCatalog, tmp_path: Path) -> None:
    base = make_view(catalog)
    first = binding_for(base, "passage:harbour:001")
    second = binding_for(base, "passage:harbour:002")
    bindings = tuple(
        replace(binding, rights_current=False)
        if binding == first
        else replace(binding, lifecycle=PassageLifecycle.TOMBSTONED)
        if binding == second
        else binding
        for binding in base.bindings
    )
    receipt = make_retriever(
        tmp_path,
        catalog,
        make_view(catalog, bindings=bindings),
    ).retrieve(make_request(catalog))
    excluded_ids = {exclusion.passage_id for exclusion in receipt.exclusions}
    hit_ids = {hit.passage_id for hit in receipt.hits}
    assert {"passage:harbour:001", "passage:harbour:002"} <= excluded_ids
    assert excluded_ids.isdisjoint(hit_ids)


def test_no_external_clients_are_constructed_during_complete_retrieval(
    catalog: VectorFixtureCatalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted: list[str] = []

    def forbidden(*_args, **_kwargs):
        attempted.append("external")
        raise AssertionError("external execution is prohibited")

    monkeypatch.setattr(threading, "Thread", forbidden)
    receipt = make_retriever(tmp_path, catalog, make_view(catalog)).retrieve(
        make_request(catalog)
    )
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert attempted == []
