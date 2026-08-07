from __future__ import annotations

import inspect
import json
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import pytest

import newsroom.increment5.hybrid_composer as hybrid_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5.admitted_graph_retriever import (
    GRAPH_TEMPORAL_WINDOW_SECONDS,
    AdmittedGraphReceipt,
    GraphFailureReason,
)
from newsroom.increment5.branch_receipts import ExactBranchReceipt
from newsroom.increment5.fulltext_receipts import FullTextBranchReceipt
from newsroom.increment5.hybrid_composer import (
    HYBRID_COMPOSER_CONTRACT_DIGEST,
    HybridComposer,
    HybridCompositionError,
    HybridCompositionInput,
    HybridCompositionJournal,
    HybridCompositionOutcome,
    HybridCompositionPurpose,
    HybridCompositionReason,
    HybridCompositionReceipt,
    HybridCompositionRequest,
    HybridManifestState,
    HybridMode,
    HybridPrecedence,
)
from newsroom.increment5.named_tool_branch_execution import (
    NamedBranchOutcome,
    NamedToolExecutionOutcome,
    NamedToolExecutionReason,
    NamedToolExecutionReceipt,
)
from newsroom.increment5.named_tool_contracts import NamedToolId
from newsroom.increment5.named_tool_dispatch import (
    NamedToolDispatchOutcome,
    NamedToolDispatchReason,
)
from newsroom.increment5.vector_retriever import (
    VectorBranchReceipt,
    VectorFailureReason,
)
from newsroom.tests.test_increment5c2_named_tool_dispatch import (
    authorize,
    denied_authorization,
    system,
)

QUERY_VALID_TIME = "2042-03-12T12:00:00Z"
SERVING_TIME = "2042-03-12T12:00:00Z"
BRANCH_TOOLS = (
    NamedToolId.EXACT_AUTHORITY_LOOKUP,
    NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
    NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
    NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
)


def _digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def _graph_receipt_id(receipt: AdmittedGraphReceipt) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "|".join(
                (
                    receipt.request_digest,
                    receipt.outcome.value,
                    "NONE" if receipt.reason is None else receipt.reason.value,
                    receipt.generation_digest or "NO_GENERATION",
                )
            ),
        )
    )


def _retime_receipt(
    receipt: ExactBranchReceipt
    | FullTextBranchReceipt
    | VectorBranchReceipt
    | AdmittedGraphReceipt,
):
    if isinstance(receipt, VectorBranchReceipt):
        return replace(
            receipt,
            query_valid_time=QUERY_VALID_TIME,
            serving_time=SERVING_TIME,
        )
    if isinstance(receipt, AdmittedGraphReceipt):
        lower = (
            datetime(2042, 3, 12, 12, tzinfo=UTC)
            - timedelta(seconds=GRAPH_TEMPORAL_WINDOW_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return replace(
            receipt,
            query_valid_time=QUERY_VALID_TIME,
            serving_time=SERVING_TIME,
            temporal_lower_bound=lower,
        )
    return receipt


def _parse_receipt(tool_id: NamedToolId, raw: bytes):
    if tool_id is NamedToolId.EXACT_AUTHORITY_LOOKUP:
        return ExactBranchReceipt.from_canonical_bytes(raw)
    if tool_id is NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL:
        return FullTextBranchReceipt.from_canonical_bytes(raw)
    if tool_id is NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
        return VectorBranchReceipt.from_canonical_bytes(raw)
    if tool_id is NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
        return AdmittedGraphReceipt.from_canonical_bytes(raw)
    raise AssertionError(tool_id)


def _with_first_root(receipt, root_id: str):
    first, *remaining = receipt.hits
    return replace(
        receipt,
        hits=(replace(first, dependency_root_id=root_id), *remaining),
    )


def _without_hits(receipt):
    if isinstance(receipt, ExactBranchReceipt):
        return replace(receipt, hits=(), reason_code="NO_MATCH", exclusions=())
    if isinstance(receipt, FullTextBranchReceipt):
        return replace(receipt, hits=(), reason_code="NO_MATCH", exclusions=())
    if isinstance(receipt, VectorBranchReceipt):
        return replace(
            receipt,
            hits=(),
            exclusions=(),
            reason=VectorFailureReason.NO_MATCH,
        )
    if isinstance(receipt, AdmittedGraphReceipt):
        receipt_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        receipt.request_digest,
                        receipt.outcome.value,
                        GraphFailureReason.NO_MATCH.value,
                        receipt.generation_digest or "NO_GENERATION",
                    )
                ),
            )
        )
        return replace(
            receipt,
            receipt_id=receipt_id,
            hits=(),
            exclusions=(),
            reason=GraphFailureReason.NO_MATCH,
        )
    raise AssertionError(type(receipt))


def _branch_input(
    result,
    *,
    transform=lambda value: value,
    preserve_attributed_request_digest: bool = True,
) -> HybridCompositionInput:
    tool_id = result.receipt.tool_id
    raw = result.upstream_raw_receipt_bytes
    assert raw is not None
    parsed = _retime_receipt(_parse_receipt(tool_id, raw))
    parsed = transform(parsed)
    raw = parsed.canonical_bytes

    execution = NamedToolExecutionReceipt.from_canonical_bytes(
        result.upstream_execution_receipt_bytes
    )
    attribution = execution.branch_attribution
    assert attribution is not None
    result_count = len(parsed.hits)
    no_match = parsed.outcome.value == "COMPLETE" and result_count == 0
    branch_reason = "NO_MATCH" if no_match else None
    attribution = replace(
        attribution,
        branch_request_digest=(
            attribution.branch_request_digest
            if preserve_attributed_request_digest
            else parsed.request_digest
        ),
        branch_receipt_digest=digest_bytes(raw),
        query_valid_time=QUERY_VALID_TIME,
        serving_time=SERVING_TIME,
        outcome=NamedBranchOutcome(parsed.outcome.value),
        reason=branch_reason,
        result_count=result_count,
        no_match=no_match,
        branch_receipt_bytes=len(raw),
    )
    execution = replace(
        execution,
        branch_attribution=attribution,
        outcome=NamedToolExecutionOutcome(parsed.outcome.value),
        reason=NamedToolExecutionReason.NO_MATCH if no_match else None,
        result_count=result_count,
        no_match=no_match,
    )
    execution_bytes = execution.canonical_bytes
    raw_digest = digest_bytes(raw)
    upstream = replace(
        result.receipt.upstream,
        execution_receipt_digest=execution.receipt_digest,
        attribution_digest=digest_bytes(
            canonical_json_bytes(attribution.canonical_value())
        ),
        upstream_request_digest=attribution.branch_request_digest,
        upstream_receipt_digest=raw_digest,
        outcome=NamedToolDispatchOutcome(parsed.outcome.value),
        reason=branch_reason,
        raw_receipt_bytes=len(raw),
        raw_receipt_digest=raw_digest,
    )
    dispatch = replace(
        result.receipt,
        upstream=upstream,
        outcome=NamedToolDispatchOutcome(parsed.outcome.value),
        reason=NamedToolDispatchReason.NO_MATCH if no_match else None,
        result_count=result_count,
        no_match=no_match,
    )
    return HybridCompositionInput(
        dispatch_receipt=dispatch,
        execution_receipt_bytes=execution_bytes,
        raw_upstream_receipt_bytes=raw,
    )


@pytest.fixture
def branch_inputs(tmp_path: Path) -> tuple[HybridCompositionInput, ...]:
    dispatcher, _registry, _branches, _authorities, requests, _driver, _graph = system(
        tmp_path
    )
    results = tuple(
        dispatcher.execute(
            request,
            authorize(tmp_path, request, name=f"hybrid-{index}"),
        )
        for index, request in enumerate(requests[:4])
    )
    return tuple(_branch_input(result) for result in results)


def _request(
    inputs: tuple[HybridCompositionInput, ...],
    *,
    key: str = "hybrid:complete",
    purpose: HybridCompositionPurpose = HybridCompositionPurpose.TRIAGE_PRIOR_MATCH,
    request_id: str = "00000000-0000-0000-0000-000000005d10",
) -> HybridCompositionRequest:
    return HybridCompositionRequest(
        request_id=request_id,
        idempotency_key=key,
        purpose=purpose,
        query_valid_time=QUERY_VALID_TIME,
        serving_time=SERVING_TIME,
        inputs=inputs,
    )


def test_contract_is_content_addressed_and_fixed() -> None:
    assert HYBRID_COMPOSER_CONTRACT_DIGEST.startswith("sha256:")
    assert len(HYBRID_COMPOSER_CONTRACT_DIGEST) == 71
    request = _request(())
    assert request.reciprocal_rank_k == 60
    assert request.candidate_limit == 12
    assert request.response_limit_bytes == 262_144
    assert request.required_tools == BRANCH_TOOLS
    with pytest.raises(HybridCompositionError, match="fixed at 60"):
        replace(request, reciprocal_rank_k=61)


def test_complete_composition_is_exact_first_and_input_order_independent(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    first = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "first.sqlite")
    ).execute(_request(branch_inputs, key="hybrid:first"))
    second = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "second.sqlite")
    ).execute(
        _request(tuple(reversed(branch_inputs)), key="hybrid:first")
    )
    assert first == second
    assert first.outcome is HybridCompositionOutcome.COMPLETE
    assert first.reason is None
    assert first.no_match is False
    assert first.candidates
    assert first.candidates[0].precedence is HybridPrecedence.EXACT_FIRST
    assert first.candidates[0].dependency_root_id == "item-a"
    assert first.candidates[0].score.fraction == Fraction(1, 61)
    assert first.raw_scores_compared is False
    assert first.fusion_is_authority is False
    assert first.external_call_count == 0
    assert first.provider_spend_micros == 0
    assert first.authority_effect == "NONE"
    assert HybridCompositionReceipt.from_canonical_bytes(first.canonical_bytes) == first


def test_authoritative_dependency_root_dedup_retains_all_origins(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    root_id = "authority:shared-root"
    changed = tuple(
        _branch_input(
            type("Result", (), {
                "receipt": item.dispatch_receipt,
                "upstream_execution_receipt_bytes": item.execution_receipt_bytes,
                "upstream_raw_receipt_bytes": item.raw_upstream_receipt_bytes,
            })(),
            transform=lambda receipt, root_id=root_id: _with_first_root(receipt, root_id),
        )
        for item in branch_inputs
    )
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "dedup.sqlite")
    ).execute(_request(changed, key="hybrid:dedup"))
    shared = next(item for item in receipt.candidates if item.dependency_root_id == root_id)
    assert shared.precedence is HybridPrecedence.EXACT_FIRST
    assert shared.contributing_modes == tuple(HybridMode)
    assert shared.score.fraction == Fraction(4, 61)
    assert len(shared.origins) == 4
    assert all(item.used_for_score for item in shared.origins)
    assert {item.upstream_receipt_digest for item in shared.origins} == {
        digest_bytes(item.raw_upstream_receipt_bytes)
        for item in changed
    }


def test_missing_mandatory_branch_is_incomplete_not_no_match(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "missing.sqlite")
    ).execute(_request(branch_inputs[:-1], key="hybrid:missing"))
    assert receipt.outcome is HybridCompositionOutcome.INCOMPLETE
    assert receipt.reason is HybridCompositionReason.MISSING_MANDATORY_TOOL
    assert receipt.no_match is False
    assert receipt.candidates == ()
    graph = next(
        item
        for item in receipt.manifest
        if item.tool_id is NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL
    )
    assert graph.state is HybridManifestState.MISSING
    assert graph.blocking is True


def test_purpose_specific_authority_evidence_is_mandatory(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "collision.sqlite")
    ).execute(
        _request(
            branch_inputs,
            key="hybrid:collision",
            purpose=HybridCompositionPurpose.COLLISION_REVIEW,
        )
    )
    assert receipt.outcome is HybridCompositionOutcome.INCOMPLETE
    assert receipt.reason is HybridCompositionReason.MISSING_MANDATORY_TOOL
    collision = next(
        item
        for item in receipt.manifest
        if item.tool_id
        is NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP
    )
    assert collision.mandatory is True
    assert collision.state is HybridManifestState.MISSING


def test_no_match_requires_all_four_complete_zero_result_receipts(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    empty = tuple(
        _branch_input(
            type("Result", (), {
                "receipt": item.dispatch_receipt,
                "upstream_execution_receipt_bytes": item.execution_receipt_bytes,
                "upstream_raw_receipt_bytes": item.raw_upstream_receipt_bytes,
            })(),
            transform=_without_hits,
        )
        for item in branch_inputs
    )
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "no-match.sqlite")
    ).execute(_request(empty, key="hybrid:no-match"))
    assert receipt.outcome is HybridCompositionOutcome.COMPLETE
    assert receipt.reason is HybridCompositionReason.NO_MATCH
    assert receipt.no_match is True
    assert receipt.candidates == ()
    assert all(
        item.state is HybridManifestState.COMPLETE_NO_MATCH
        for item in receipt.manifest[:4]
    )


def test_raw_receipt_semantic_mismatch_is_typed_incomplete(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    exact = branch_inputs[0]
    fake = type("Result", (), {
        "receipt": exact.dispatch_receipt,
        "upstream_execution_receipt_bytes": exact.execution_receipt_bytes,
        "upstream_raw_receipt_bytes": exact.raw_upstream_receipt_bytes,
    })()
    invalid = _branch_input(
        fake,
        transform=lambda receipt: replace(
            receipt,
            request_digest=_digest_text("different-branch-request"),
        ),
        preserve_attributed_request_digest=True,
    )
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "invalid.sqlite")
    ).execute(
        _request(
            (invalid, *branch_inputs[1:]),
            key="hybrid:invalid",
        )
    )
    assert receipt.outcome is HybridCompositionOutcome.INCOMPLETE
    assert receipt.reason is HybridCompositionReason.RECEIPT_INVALID
    assert receipt.no_match is False
    assert receipt.candidates == ()


def test_journal_restart_replays_exact_bytes_and_rejects_conflict(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    path = tmp_path / "journal.sqlite"
    request = _request(branch_inputs, key="hybrid:restart")
    first = HybridComposer(journal=HybridCompositionJournal(path)).execute(request)
    second = HybridComposer(journal=HybridCompositionJournal(path)).execute(request)
    assert second.canonical_bytes == first.canonical_bytes
    conflict = replace(
        request,
        request_id="00000000-0000-0000-0000-000000005d11",
    )
    with pytest.raises(HybridCompositionError, match="another request"):
        HybridComposer(journal=HybridCompositionJournal(path)).execute(conflict)


def test_journal_detects_retained_receipt_tamper(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    path = tmp_path / "tamper.sqlite"
    request = _request(branch_inputs, key="hybrid:tamper")
    HybridComposer(journal=HybridCompositionJournal(path)).execute(request)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE increment5d1_hybrid_receipts SET receipt_bytes=?",
            (b"{}",),
        )
    with pytest.raises(HybridCompositionError, match="digest is corrupt"):
        HybridComposer(journal=HybridCompositionJournal(path)).execute(request)


def test_receipt_rejects_duplicate_keys_and_scalar_type_confusion(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "decode.sqlite")
    ).execute(_request(branch_inputs, key="hybrid:decode"))
    raw = receipt.canonical_bytes
    duplicate = raw.replace(
        b'{"authority_effect":"NONE",',
        b'{"authority_effect":"NONE","authority_effect":"NONE",',
        1,
    )
    with pytest.raises(HybridCompositionError, match="duplicate keys"):
        HybridCompositionReceipt.from_canonical_bytes(duplicate)
    value = json.loads(raw)
    value["no_match"] = 0
    confused = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    with pytest.raises(HybridCompositionError, match="flags must be boolean"):
        HybridCompositionReceipt.from_canonical_bytes(confused)


def test_result_bound_retains_twelve_and_records_exclusions() -> None:
    origins = tuple(
        hybrid_module.HybridOrigin(
            mode=HybridMode.FULL_TEXT,
            tool_id=NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
            rank=(index % 8) + 1,
            result_id=f"result:{index:02d}",
            dependency_root_id=f"root:{index:02d}",
            source_identity=f"source:{index:02d}",
            passage_id=f"passage:{index:02d}",
            trust_scope="OBSERVED",
            provenance_digest=_digest_text(f"provenance:{index}"),
            branch_hit_digest=_digest_text(f"hit:{index}"),
            dispatch_receipt_digest=_digest_text("dispatch"),
            upstream_receipt_digest=_digest_text("upstream"),
            exact_match_signal=None,
            path=(),
            used_for_score=False,
        )
        for index in range(13)
    )
    candidates, exclusions = hybrid_module._fuse(origins)
    assert len(candidates) == 12
    assert len(exclusions) == 1
    assert exclusions[0].would_be_rank == 13
    assert {item.dependency_root_id for item in candidates}.isdisjoint(
        {item.dependency_root_id for item in exclusions}
    )


def test_module_has_no_backend_query_provider_or_effect_surface() -> None:
    source = inspect.getsource(hybrid_module).lower()
    forbidden = (
        "requests.",
        "httpx",
        "socket",
        "run_cypher",
        "raw_lucene",
        "execute_sql",
        "create_candidate",
        "admit_relation",
        "publish_story",
        "activate_production",
        "provider_client",
        "model_client",
    )
    assert not any(item in source for item in forbidden)
    assert "reciprocal_rank_k: int = _rrf_k" in source
    assert "raw_scores_compared: bool = false" in source
    assert "authority_effect: str = \"none\"" in source


def test_operations_and_traceability_preserve_the_5d_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    operations = (
        root / "docs/operations/increment-5d1-hybrid-composer.md"
    ).read_text(encoding="utf-8")
    traceability = (
        root / "docs/traceability/increment-5d1-hybrid-composer.md"
    ).read_text(encoding="utf-8")
    for identity in (
        "EXACT_AUTHORITY_LOOKUP",
        "BOUNDED_FULL_TEXT_RETRIEVAL",
        "BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL",
        "BOUNDED_ADMITTED_GRAPH_TRAVERSAL",
        "CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP",
        "BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP",
    ):
        assert f"`{identity}`" in operations
    assert "fixed RRF `k=60`" in operations
    assert "`GRAG-035`" in traceability
    assert "`TRI-022`" in traceability
    assert "does not complete either row" in traceability
    assert "5D2/#331" in operations
    assert "Increment 6/#146" in traceability
    assert "Increment 8/#148" in traceability
    assert "production activation" in operations.lower()



def _synthetic_origin(
    *,
    mode: HybridMode,
    rank: int,
    root: str,
    suffix: str,
) -> hybrid_module.HybridOrigin:
    tool_by_mode = {
        HybridMode.EXACT: NamedToolId.EXACT_AUTHORITY_LOOKUP,
        HybridMode.FULL_TEXT: NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
        HybridMode.VECTOR: NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
        HybridMode.ADMITTED_GRAPH: NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
    }
    path = ()
    if mode is HybridMode.ADMITTED_GRAPH:
        path = (
            hybrid_module.HybridPathHop(
                relation_id=f"relation:{suffix}",
                predicate="DEVELOPMENT_OF",
                source_id="root:synthetic",
                target_id=f"result:{suffix}",
                direction="OUTGOING",
                relation_decision_digest=_digest_text(f"decision:{suffix}"),
                relation_provenance_digest=_digest_text(f"relation-prov:{suffix}"),
            ),
        )
    return hybrid_module.HybridOrigin(
        mode=mode,
        tool_id=tool_by_mode[mode],
        rank=rank,
        result_id=f"result:{suffix}",
        dependency_root_id=root,
        source_identity=f"source:{suffix}",
        passage_id=(
            None
            if mode in {HybridMode.EXACT, HybridMode.ADMITTED_GRAPH}
            else f"passage:{suffix}"
        ),
        trust_scope="ADMITTED" if mode is HybridMode.ADMITTED_GRAPH else "OBSERVED",
        provenance_digest=_digest_text(f"provenance:{suffix}"),
        branch_hit_digest=_digest_text(f"hit:{suffix}"),
        dispatch_receipt_digest=_digest_text(f"dispatch:{mode.value}"),
        upstream_receipt_digest=_digest_text(f"upstream:{mode.value}"),
        exact_match_signal="SOURCE_NATIVE_ID_EQUAL" if mode is HybridMode.EXACT else None,
        path=path,
        used_for_score=False,
    )


def test_exact_precedence_beats_a_larger_approximate_rrf_score() -> None:
    origins = (
        _synthetic_origin(
            mode=HybridMode.EXACT, rank=8, root="root:exact", suffix="exact"
        ),
        _synthetic_origin(
            mode=HybridMode.FULL_TEXT,
            rank=1,
            root="root:approx",
            suffix="full",
        ),
        _synthetic_origin(
            mode=HybridMode.VECTOR, rank=1, root="root:approx", suffix="vector"
        ),
        _synthetic_origin(
            mode=HybridMode.ADMITTED_GRAPH,
            rank=1,
            root="root:approx",
            suffix="graph",
        ),
    )
    candidates, _exclusions = hybrid_module._fuse(origins)
    assert candidates[0].dependency_root_id == "root:exact"
    assert candidates[0].score.fraction == Fraction(1, 68)
    assert candidates[1].score.fraction == Fraction(3, 61)
    assert candidates[0].score.fraction < candidates[1].score.fraction


def test_only_best_hit_per_mode_scores_but_every_origin_is_retained() -> None:
    root = "root:one-mode-duplicates"
    origins = (
        _synthetic_origin(mode=HybridMode.FULL_TEXT, rank=1, root=root, suffix="full-1"),
        _synthetic_origin(mode=HybridMode.FULL_TEXT, rank=2, root=root, suffix="full-2"),
        _synthetic_origin(mode=HybridMode.VECTOR, rank=1, root=root, suffix="vector-1"),
    )
    candidates, _ = hybrid_module._fuse(origins)
    candidate = candidates[0]
    assert len(candidate.origins) == 3
    assert candidate.score.fraction == Fraction(2, 61)
    selected = [item for item in candidate.origins if item.used_for_score]
    assert [(item.mode, item.rank) for item in selected] == [
        (HybridMode.FULL_TEXT, 1),
        (HybridMode.VECTOR, 1),
    ]


def test_supplied_optional_block_is_degraded_but_required_block_is_policy_blocked(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    other = tmp_path / "optional"
    other.mkdir()
    dispatcher, _registry, _branches, _authorities, requests, _driver, _graph = system(other)
    collision = requests[4]
    blocked = dispatcher.execute(
        collision,
        denied_authorization(other, collision, name="optional-collision"),
    )
    blocked_input = HybridCompositionInput.from_dispatch_result(blocked)

    degraded = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "degraded.sqlite")
    ).execute(
        _request(
            (*branch_inputs, blocked_input),
            key="hybrid:degraded",
            purpose=HybridCompositionPurpose.TRIAGE_PRIOR_MATCH,
        )
    )
    assert degraded.outcome is HybridCompositionOutcome.DEGRADED
    assert degraded.reason is HybridCompositionReason.OPTIONAL_EVIDENCE_NON_COMPLETE
    assert degraded.candidates
    assert degraded.no_match is False
    assert degraded.known_omission_tools == (
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
    )

    required = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "required-block.sqlite")
    ).execute(
        _request(
            (*branch_inputs, blocked_input),
            key="hybrid:required-block",
            purpose=HybridCompositionPurpose.COLLISION_REVIEW,
        )
    )
    assert required.outcome is HybridCompositionOutcome.POLICY_BLOCKED
    assert required.reason is HybridCompositionReason.MANDATORY_TOOL_POLICY_BLOCKED
    assert required.candidates == ()


def test_blocked_receipt_outcome_must_match_manifest(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "blocked-map.sqlite")
    ).execute(_request(branch_inputs[:-1], key="hybrid:blocked-map"))
    value = json.loads(receipt.canonical_bytes)
    value["outcome"] = HybridCompositionOutcome.UNAVAILABLE.value
    value["reason"] = HybridCompositionReason.MANDATORY_TOOL_UNAVAILABLE.value
    tampered = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(HybridCompositionError, match="differs from the manifest"):
        HybridCompositionReceipt.from_canonical_bytes(tampered)


def test_composition_identity_binds_manifest_and_exclusions(
    tmp_path: Path,
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    receipt = HybridComposer(
        journal=HybridCompositionJournal(tmp_path / "identity.sqlite")
    ).execute(_request(branch_inputs, key="hybrid:identity"))
    value = json.loads(receipt.canonical_bytes)
    value["manifest"][0]["generation_id"] = "tampered-generation"
    value["manifest"][0]["generation_digest"] = _digest_text("tampered-generation")
    tampered = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(HybridCompositionError, match="identity differs"):
        HybridCompositionReceipt.from_canonical_bytes(tampered)


def test_local_response_limit_failure_is_a_valid_bounded_receipt(
    branch_inputs: tuple[HybridCompositionInput, ...],
) -> None:
    request = _request(branch_inputs, key="hybrid:local-failure")
    manifest = hybrid_module._manifest(request)
    receipt = hybrid_module._receipt(
        request=request,
        manifest=manifest,
        outcome=HybridCompositionOutcome.INCOMPLETE,
        reason=HybridCompositionReason.RESPONSE_LIMIT_EXCEEDED,
        candidates=(),
        exclusions=(),
        no_match=False,
    )
    assert receipt.outcome is HybridCompositionOutcome.INCOMPLETE
    assert receipt.reason is HybridCompositionReason.RESPONSE_LIMIT_EXCEEDED
    assert len(receipt.canonical_bytes) < 262_144


def test_journal_schema_is_minimal_and_non_authoritative(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite"
    HybridCompositionJournal(path)
    with sqlite3.connect(path) as connection:
        columns = tuple(
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(increment5d1_hybrid_receipts)"
            )
        )
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        )
    assert columns == (
        "idempotency_key",
        "request_digest",
        "receipt_digest",
        "receipt_bytes",
    )
    assert tables == ("increment5d1_hybrid_receipts",)
    assert not any(
        token in " ".join(columns)
        for token in ("candidate", "hypothesis", "publication", "authority_decision")
    )
