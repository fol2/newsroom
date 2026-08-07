from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Iterable

import pytest

from newsroom.increment5.branch_contracts import BranchMode, BranchOutcome
from newsroom.increment5.admitted_graph_retriever import (
    ALLOWED_NODE_LABELS,
    ALLOWED_PREDICATES,
    GRAPH_ACTOR_ID,
    GRAPH_MAX_DEPTH,
    GRAPH_MAX_FANOUT,
    GRAPH_POLICY_ID,
    GRAPH_PROFILE_ID,
    GRAPH_PURPOSE,
    GRAPH_QUERY_COMPONENT_DIGEST,
    GRAPH_RELATION_CONTRACT_DIGEST,
    GRAPH_RESPONSE_LIMIT_BYTES,
    GRAPH_RESULT_LIMIT,
    GRAPH_TEMPORAL_WINDOW_SECONDS,
    GRAPH_TIMEOUT_MS,
    RETRIEVAL_CONTRACT_DIGEST,
    AdmittedGraphAuthorityView,
    AdmittedGraphContractError,
    AdmittedGraphExclusion,
    AdmittedGraphJournalError,
    AdmittedGraphPortError,
    AdmittedGraphPortTimeout,
    AdmittedGraphReceipt,
    AdmittedGraphReceiptJournal,
    AdmittedGraphRequest,
    AdmittedGraphRetriever,
    GraphDirection,
    GraphExclusionReason,
    GraphFailureReason,
    GraphLifecycle,
    GraphNodeAuthority,
    GraphProjectionEdge,
    GraphProjectionNode,
    GraphRelationAuthority,
    canonical_node_digest,
)


QUERY_VALID_TIME = "2026-08-06T08:59:00Z"
SERVING_TIME = "2026-08-06T09:00:00Z"
VALIDATED_AT = "2026-08-06T08:58:00Z"
VALID_FROM = "2020-01-01T00:00:00Z"
VALID_TO = "2035-01-01T00:00:00Z"
OBSERVED_AT = "2026-08-01T00:00:00Z"
OLD_OBSERVED_AT = "2026-06-01T00:00:00Z"
ZERO_DIGEST = "sha256:" + "0" * 64


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_node(
    canonical_id: str,
    label: str,
    *,
    lifecycle: GraphLifecycle = GraphLifecycle.ACTIVE,
    rights_current: bool = True,
) -> GraphNodeAuthority:
    return GraphNodeAuthority(
        canonical_id=canonical_id,
        identity_digest=canonical_node_digest(canonical_id),
        labels=(label,),
        dependency_root_id=f"dependency:{canonical_id}",
        source_revision_id=f"revision:{canonical_id}",
        lifecycle=lifecycle,
        rights_current=rights_current,
        rights_digest=digest(f"rights:{canonical_id}"),
        provenance_digest=digest(f"provenance:{canonical_id}"),
    )


def make_relation(
    relation_id: str,
    source_id: str,
    target_id: str,
    predicate: str,
    *,
    trust_scope: str = "ADMITTED",
    lifecycle: GraphLifecycle = GraphLifecycle.ACTIVE,
    rights_current: bool = True,
    valid_from: str = VALID_FROM,
    valid_to: str = VALID_TO,
    observed_at: str = OBSERVED_AT,
) -> GraphRelationAuthority:
    return GraphRelationAuthority(
        relation_id=relation_id,
        source_id=source_id,
        target_id=target_id,
        predicate=predicate,
        trust_scope=trust_scope,
        valid_from=valid_from,
        valid_to=valid_to,
        observed_at=observed_at,
        lifecycle=lifecycle,
        rights_current=rights_current,
        rights_digest=digest(f"rights:{relation_id}"),
        provenance_digest=digest(f"provenance:{relation_id}"),
        decision_digest=digest(f"decision:{relation_id}"),
    )


def base_nodes() -> tuple[GraphNodeAuthority, ...]:
    return (
        make_node("source:root", "Source"),
        make_node("revision:one", "Revision"),
        make_node("entity:one", "CanonicalEntity"),
        make_node("candidate:one", "Candidate"),
        make_node("process:one", "FormalProcess"),
        make_node("lead:held", "Lead", lifecycle=GraphLifecycle.HELD),
        make_node("signal:rights-blocked", "Signal", rights_current=False),
        make_node("hypothesis:tombstoned", "Hypothesis", lifecycle=GraphLifecycle.TOMBSTONED),
        make_node("lead:unadmitted", "Lead"),
        make_node("signal:old", "Signal"),
    )


def base_relations() -> tuple[GraphRelationAuthority, ...]:
    return (
        make_relation(
            "relation:root-revision",
            "source:root",
            "revision:one",
            "DEVELOPMENT_OF",
        ),
        make_relation(
            "relation:root-entity",
            "entity:one",
            "source:root",
            "SAME_PROCESS_AS",
        ),
        make_relation(
            "relation:revision-candidate",
            "revision:one",
            "candidate:one",
            "ABOUT_EVENT",
        ),
        make_relation(
            "relation:entity-process",
            "entity:one",
            "process:one",
            "SUPPORTS",
        ),
        make_relation(
            "relation:root-held",
            "source:root",
            "lead:held",
            "SUPPORTS",
        ),
        make_relation(
            "relation:root-rights",
            "source:root",
            "signal:rights-blocked",
            "CORRECTS",
        ),
        make_relation(
            "relation:root-tombstone",
            "source:root",
            "hypothesis:tombstoned",
            "DISPUTES",
        ),
        make_relation(
            "relation:root-unadmitted",
            "source:root",
            "lead:unadmitted",
            "SUPPORTS",
            trust_scope="PROPOSED",
        ),
        make_relation(
            "relation:root-old",
            "source:root",
            "signal:old",
            "ABOUT_EVENT",
            observed_at=OLD_OBSERVED_AT,
        ),
    )


def make_view(
    *,
    nodes: tuple[GraphNodeAuthority, ...] | None = None,
    relations: tuple[GraphRelationAuthority, ...] | None = None,
    **overrides: object,
) -> AdmittedGraphAuthorityView:
    values: dict[str, object] = {
        "generation_id": "graph-generation-v1",
        "validated_at": VALIDATED_AT,
        "nodes": base_nodes() if nodes is None else nodes,
        "relations": base_relations() if relations is None else relations,
        "watermark_seq": 10,
    }
    values.update(overrides)
    return AdmittedGraphAuthorityView.build(**values)


def make_request(
    *,
    root_id: str = "source:root",
    request_id: str | None = None,
    idempotency_key: str | None = None,
    **overrides: object,
) -> AdmittedGraphRequest:
    values: dict[str, object] = {
        "request_id": request_id or str(uuid.uuid4()),
        "idempotency_key": idempotency_key or f"graph:{uuid.uuid4()}",
        "actor_id": GRAPH_ACTOR_ID,
        "purpose": GRAPH_PURPOSE,
        "policy_id": GRAPH_POLICY_ID,
        "contract_digest": RETRIEVAL_CONTRACT_DIGEST,
        "profile_id": GRAPH_PROFILE_ID,
        "graph_component_digest": GRAPH_QUERY_COMPONENT_DIGEST,
        "relation_contract_digest": GRAPH_RELATION_CONTRACT_DIGEST,
        "root_id": root_id,
        "root_identity_digest": canonical_node_digest(root_id),
        "query_valid_time": QUERY_VALID_TIME,
        "serving_time": SERVING_TIME,
        "minimum_watermark_seq": 10,
        "maximum_depth": GRAPH_MAX_DEPTH,
        "maximum_fanout": GRAPH_MAX_FANOUT,
        "temporal_window_seconds": GRAPH_TEMPORAL_WINDOW_SECONDS,
        "result_limit": GRAPH_RESULT_LIMIT,
        "timeout_ms": GRAPH_TIMEOUT_MS,
        "response_limit_bytes": GRAPH_RESPONSE_LIMIT_BYTES,
    }
    values.update(overrides)
    return AdmittedGraphRequest(**values)


def projection_node(node: GraphNodeAuthority, generation_id: str) -> GraphProjectionNode:
    return GraphProjectionNode(
        generation_id=generation_id,
        canonical_id=node.canonical_id,
        identity_digest=node.identity_digest,
        labels=node.labels,
    )


def projection_edge(
    relation: GraphRelationAuthority,
    node_by_id: dict[str, GraphNodeAuthority],
    generation_id: str,
    frontier_id: str,
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        generation_id=generation_id,
        frontier_id=frontier_id,
        relation_id=relation.relation_id,
        source_id=relation.source_id,
        target_id=relation.target_id,
        predicate=relation.predicate,
        source_labels=node_by_id[relation.source_id].labels,
        target_labels=node_by_id[relation.target_id].labels,
        valid_from=relation.valid_from,
        valid_to=relation.valid_to,
        observed_at=relation.observed_at,
    )


class FakeGraphPort:
    def __init__(
        self,
        view: AdmittedGraphAuthorityView,
        *,
        root: GraphProjectionNode | None | object = ...,
        root_error: Exception | None = None,
        expand_error: Exception | None = None,
        generation_override: str | None = None,
        extra_edges: tuple[GraphProjectionEdge, ...] = (),
        drop_relations: tuple[str, ...] = (),
        edge_mutator=None,
    ) -> None:
        self.view = view
        self.root = root
        self.root_error = root_error
        self.expand_error = expand_error
        self.generation_override = generation_override
        self.extra_edges = extra_edges
        self.drop_relations = set(drop_relations)
        self.edge_mutator = edge_mutator
        self.root_calls: list[tuple[str, str, int]] = []
        self.expand_calls: list[tuple[str, tuple[str, ...], str, str, int]] = []

    def read_root(
        self,
        *,
        generation_id: str,
        canonical_id: str,
        timeout_ms: int,
    ) -> GraphProjectionNode | None:
        self.root_calls.append((generation_id, canonical_id, timeout_ms))
        if self.root_error is not None:
            raise self.root_error
        if self.root is None:
            return None
        if self.root is not ...:
            assert isinstance(self.root, GraphProjectionNode)
            return self.root
        node = next(
            (item for item in self.view.nodes if item.canonical_id == canonical_id),
            None,
        )
        if node is None:
            return None
        return projection_node(node, self.generation_override or generation_id)

    def expand_frontier(
        self,
        *,
        generation_id: str,
        frontier_ids: tuple[str, ...],
        query_valid_time: str,
        temporal_lower_bound: str,
        timeout_ms: int,
    ) -> tuple[GraphProjectionEdge, ...]:
        self.expand_calls.append(
            (
                generation_id,
                frontier_ids,
                query_valid_time,
                temporal_lower_bound,
                timeout_ms,
            )
        )
        if self.expand_error is not None:
            raise self.expand_error
        node_by_id = {node.canonical_id: node for node in self.view.nodes}
        result: list[GraphProjectionEdge] = []
        for frontier_id in frontier_ids:
            for relation in self.view.relations:
                if relation.relation_id in self.drop_relations:
                    continue
                if frontier_id not in {relation.source_id, relation.target_id}:
                    continue
                edge = projection_edge(
                    relation,
                    node_by_id,
                    self.generation_override or generation_id,
                    frontier_id,
                )
                if self.edge_mutator is not None:
                    edge = self.edge_mutator(edge)
                result.append(edge)
        result.extend(self.extra_edges)
        return tuple(result)


def make_retriever(
    tmp_path: Path,
    view: AdmittedGraphAuthorityView,
    port: FakeGraphPort | None = None,
    *,
    journal_name: str = "graph-receipts.sqlite",
    clock=None,
    provider=None,
) -> tuple[AdmittedGraphRetriever, FakeGraphPort]:
    selected_port = port or FakeGraphPort(view)
    retriever = AdmittedGraphRetriever(
        authority_provider=provider or (lambda _request: view),
        graph_port=selected_port,
        journal=AdmittedGraphReceiptJournal(tmp_path / journal_name),
        monotonic_ns=clock or (lambda: 0),
    )
    return retriever, selected_port


class TimeoutClock:
    def __init__(self, safe_calls: int) -> None:
        self.safe_calls = safe_calls
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        if self.calls <= self.safe_calls:
            return 0
        return GRAPH_TIMEOUT_MS * 1_000_000 + 1


def test_contract_allow_lists_and_bounds_are_exact() -> None:
    assert ALLOWED_PREDICATES == (
        "ABOUT_EVENT",
        "CORRECTS",
        "DEVELOPMENT_OF",
        "DISPUTES",
        "SAME_EVENT_AS",
        "SAME_PROCESS_AS",
        "SUPERSEDES",
        "SUPPORTS",
    )
    assert set(ALLOWED_NODE_LABELS) == {
        "Candidate",
        "CanonicalEntity",
        "FormalProcess",
        "Hypothesis",
        "Lead",
        "Revision",
        "Signal",
        "Source",
    }
    assert GRAPH_MAX_DEPTH == 2
    assert GRAPH_MAX_FANOUT == 32
    assert GRAPH_TEMPORAL_WINDOW_SECONDS == 2_678_400
    assert GRAPH_RESULT_LIMIT == 8
    assert GRAPH_TIMEOUT_MS == 5_000
    assert GRAPH_RESPONSE_LIMIT_BYTES == 262_144


def test_relation_contract_digest_is_stable() -> None:
    payload = json.dumps(
        {
            "allowed_node_labels": list(ALLOWED_NODE_LABELS),
            "allowed_predicates": list(ALLOWED_PREDICATES),
            "direction": "BOTH",
            "maximum_depth": 2,
            "maximum_fanout": 32,
            "temporal_window_seconds": 2_678_400,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert GRAPH_RELATION_CONTRACT_DIGEST == "sha256:" + hashlib.sha256(payload).hexdigest()


def test_request_has_no_raw_graph_query_surface() -> None:
    request = make_request()
    keys = set(request.canonical_value())
    forbidden = {"cypher", "query", "labels", "predicates", "direction", "order", "properties"}
    assert keys.isdisjoint(forbidden)
    assert request.root_identity_digest == canonical_node_digest(request.root_id)


def test_request_rejects_injection_and_variable_bounds() -> None:
    with pytest.raises(AdmittedGraphContractError, match="bounded canonical text"):
        make_request(root_id=" source:root")
    with pytest.raises(AdmittedGraphContractError, match="maximum_depth"):
        make_request(maximum_depth=3)
    with pytest.raises(AdmittedGraphContractError, match="maximum_fanout"):
        make_request(maximum_fanout=33)
    with pytest.raises(AdmittedGraphContractError, match="result_limit"):
        make_request(result_limit=9)
    with pytest.raises(AdmittedGraphContractError, match="timeout_ms"):
        make_request(timeout_ms=4_999)


def test_request_binds_root_query_valid_and_serving_time() -> None:
    first = make_request(idempotency_key="graph:binding")
    changed = make_request(
        idempotency_key="graph:binding",
        query_valid_time="2026-08-06T08:58:59Z",
    )
    assert first.request_digest != changed.request_digest
    with pytest.raises(AdmittedGraphContractError, match="cannot be after"):
        make_request(
            query_valid_time="2026-08-06T09:00:01Z",
            serving_time=SERVING_TIME,
        )


def test_authority_generation_digest_binds_nodes_relations_and_rights() -> None:
    view = make_view()
    nodes = tuple(
        replace(node, rights_current=False) if node.canonical_id == "revision:one" else node
        for node in view.nodes
    )
    changed = make_view(nodes=nodes, relations=view.relations)
    assert changed.generation_digest != view.generation_digest
    with pytest.raises(AdmittedGraphContractError, match="generation digest"):
        replace(view, generation_digest=ZERO_DIGEST)


def test_complete_two_phase_traversal_is_independently_attributable(tmp_path: Path) -> None:
    view = make_view()
    retriever, port = make_retriever(tmp_path, view)
    request = make_request()
    receipt = retriever.retrieve(request)
    assert receipt.mode is BranchMode.ADMITTED_GRAPH
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason is None
    assert receipt.request_digest == request.request_digest
    assert receipt.generation_digest == view.generation_digest
    assert receipt.graph_component_digest == GRAPH_QUERY_COMPONENT_DIGEST
    assert receipt.relation_contract_digest == GRAPH_RELATION_CONTRACT_DIGEST
    assert receipt.rights_manifest_digest == view.rights_manifest_digest
    assert [hit.canonical_id for hit in receipt.hits] == [
        "revision:one",
        "entity:one",
        "candidate:one",
        "process:one",
    ]
    assert [len(hit.path) for hit in receipt.hits] == [1, 1, 2, 2]
    assert receipt.graph_port_read_count == 3
    assert len(port.root_calls) == 1
    assert len(port.expand_calls) == 2


def test_incoming_and_outgoing_direction_are_retained(tmp_path: Path) -> None:
    view = make_view()
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    hit_by_id = {hit.canonical_id: hit for hit in receipt.hits}
    assert hit_by_id["revision:one"].path[0].direction is GraphDirection.OUTGOING
    assert hit_by_id["entity:one"].path[0].direction is GraphDirection.INCOMING


def test_complete_receipt_reports_zero_calls_spend_and_authority(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    assert receipt.external_call_count == 0
    assert receipt.provider_call_count == 0
    assert receipt.model_call_count == 0
    assert receipt.embedding_call_count == 0
    assert receipt.provider_spend_micros == 0
    assert receipt.read_only is True
    assert receipt.authority_effect == "NONE"
    assert receipt.production_activation_authorized is False


def test_receipt_canonical_round_trip_and_size(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    assert AdmittedGraphReceipt.from_canonical_bytes(receipt.canonical_bytes) == receipt
    assert len(receipt.canonical_bytes) <= GRAPH_RESPONSE_LIMIT_BYTES


def test_current_rights_lifecycle_trust_and_temporal_exclusions(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    by_subject = {(item.subject_id, item.reason) for item in receipt.exclusions}
    assert ("lead:held", GraphExclusionReason.LIFECYCLE_NOT_ACTIVE) in by_subject
    assert ("signal:rights-blocked", GraphExclusionReason.RIGHTS_NOT_CURRENT) in by_subject
    assert ("hypothesis:tombstoned", GraphExclusionReason.TOMBSTONED) in by_subject
    assert ("lead:unadmitted", GraphExclusionReason.TRUST_NOT_ADMITTED) in by_subject
    assert ("signal:old", GraphExclusionReason.OUTSIDE_TEMPORAL_WINDOW) in by_subject
    hit_ids = {hit.canonical_id for hit in receipt.hits}
    assert hit_ids.isdisjoint({subject for subject, _reason in by_subject})


def test_tombstone_cannot_resurrect_from_projection(tmp_path: Path) -> None:
    view = make_view()
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    assert all(hit.canonical_id != "hypothesis:tombstoned" for hit in receipt.hits)
    assert any(
        item.subject_id == "hypothesis:tombstoned"
        and item.reason is GraphExclusionReason.TOMBSTONED
        for item in receipt.exclusions
    )


def test_cycle_and_root_repeat_are_rejected(tmp_path: Path) -> None:
    nodes = base_nodes() + (make_node("signal:cycle", "Signal"),)
    relations = base_relations() + (
        make_relation(
            "relation:root-cycle",
            "source:root",
            "signal:cycle",
            "ABOUT_EVENT",
        ),
        make_relation(
            "relation:cycle-revision",
            "signal:cycle",
            "revision:one",
            "SUPPORTS",
        ),
    )
    view = make_view(nodes=nodes, relations=relations)
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    assert any(
        item.reason in {GraphExclusionReason.ROOT_REPEATED, GraphExclusionReason.CYCLE_REJECTED}
        for item in receipt.exclusions
    )
    assert all(len(hit.path) <= 2 for hit in receipt.hits)


def test_duplicate_endpoint_keeps_deterministic_best_path(tmp_path: Path) -> None:
    relations = base_relations() + (
        make_relation(
            "relation:entity-candidate",
            "entity:one",
            "candidate:one",
            "ABOUT_EVENT",
        ),
    )
    view = make_view(relations=relations)
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    candidate_hits = [hit for hit in receipt.hits if hit.canonical_id == "candidate:one"]
    assert len(candidate_hits) == 1
    assert any(
        item.subject_id == "candidate:one"
        and item.reason is GraphExclusionReason.DUPLICATE_PATH
        for item in receipt.exclusions
    )


def test_ninth_distinct_result_is_explicit_overflow(tmp_path: Path) -> None:
    extra_nodes = tuple(make_node(f"signal:overflow:{index:02d}", "Signal") for index in range(9))
    extra_relations = tuple(
        make_relation(
            f"relation:overflow:{index:02d}",
            "source:root",
            node.canonical_id,
            "ABOUT_EVENT",
        )
        for index, node in enumerate(extra_nodes)
    )
    view = make_view(
        nodes=(make_node("source:root", "Source"),) + extra_nodes,
        relations=extra_relations,
    )
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is GraphFailureReason.RESULT_LIMIT_EXCEEDED
    assert not receipt.hits


def test_thirty_third_edge_on_one_frontier_is_fanout_failure(tmp_path: Path) -> None:
    extra_nodes = tuple(make_node(f"signal:fanout:{index:02d}", "Signal") for index in range(33))
    extra_relations = tuple(
        make_relation(
            f"relation:fanout:{index:02d}",
            "source:root",
            node.canonical_id,
            "ABOUT_EVENT",
        )
        for index, node in enumerate(extra_nodes)
    )
    view = make_view(
        nodes=(make_node("source:root", "Source"),) + extra_nodes,
        relations=extra_relations,
    )
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is GraphFailureReason.FANOUT_EXCEEDED
    assert not receipt.hits


@pytest.mark.parametrize(
    ("view", "outcome", "reason"),
    [
        (make_view(active=False), BranchOutcome.STALE, GraphFailureReason.GENERATION_INACTIVE),
        (
            make_view(complete=False),
            BranchOutcome.INCOMPLETE,
            GraphFailureReason.GENERATION_INCOMPLETE,
        ),
        (
            make_view(profile_id="other-profile"),
            BranchOutcome.STALE,
            GraphFailureReason.PROFILE_MISMATCH,
        ),
        (
            make_view(graph_component_digest=ZERO_DIGEST),
            BranchOutcome.STALE,
            GraphFailureReason.GRAPH_COMPONENT_MISMATCH,
        ),
        (
            make_view(relation_contract_digest=ZERO_DIGEST),
            BranchOutcome.STALE,
            GraphFailureReason.RELATION_CONTRACT_MISMATCH,
        ),
        (
            make_view(watermark_seq=9),
            BranchOutcome.STALE,
            GraphFailureReason.WATERMARK_BEHIND,
        ),
        (
            make_view(open_gap_count=1),
            BranchOutcome.INCOMPLETE,
            GraphFailureReason.REQUIRED_GAP_OPEN,
        ),
        (
            make_view(dead_letter_count=1),
            BranchOutcome.INCOMPLETE,
            GraphFailureReason.DEAD_LETTER_PRESENT,
        ),
        (
            make_view(validated_at="2026-08-01T00:00:00Z", maximum_age_seconds=60),
            BranchOutcome.STALE,
            GraphFailureReason.AUTHORITY_VIEW_STALE,
        ),
    ],
)
def test_generation_and_projection_health_fail_truthfully(
    tmp_path: Path,
    view: AdmittedGraphAuthorityView,
    outcome: BranchOutcome,
    reason: GraphFailureReason,
) -> None:
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    assert receipt.outcome is outcome
    assert receipt.reason is reason
    assert receipt.reason is not GraphFailureReason.NO_MATCH


def test_request_contract_profile_and_component_drift_are_policy_blocked(tmp_path: Path) -> None:
    cases = (
        ({"contract_digest": ZERO_DIGEST}, GraphFailureReason.CONTRACT_MISMATCH),
        ({"profile_id": "other-profile"}, GraphFailureReason.PROFILE_MISMATCH),
        ({"graph_component_digest": ZERO_DIGEST}, GraphFailureReason.GRAPH_COMPONENT_MISMATCH),
        ({"relation_contract_digest": ZERO_DIGEST}, GraphFailureReason.RELATION_CONTRACT_MISMATCH),
    )
    view = make_view()
    for index, (override, reason) in enumerate(cases):
        receipt = make_retriever(
            tmp_path,
            view,
            journal_name=f"policy-{index}.sqlite",
        )[0].retrieve(make_request(**override))
        assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
        assert receipt.reason is reason


def test_unknown_or_non_active_root_is_policy_blocked(tmp_path: Path) -> None:
    view = make_view()
    unknown = make_retriever(tmp_path, view, journal_name="unknown.sqlite")[0].retrieve(
        make_request(root_id="source:unknown")
    )
    assert unknown.outcome is BranchOutcome.POLICY_BLOCKED
    assert unknown.reason is GraphFailureReason.ROOT_NOT_ACCEPTED

    nodes = tuple(
        replace(node, lifecycle=GraphLifecycle.HELD)
        if node.canonical_id == "source:root"
        else node
        for node in view.nodes
    )
    held_view = make_view(nodes=nodes, relations=view.relations)
    held = make_retriever(tmp_path, held_view, journal_name="held-root.sqlite")[0].retrieve(
        make_request()
    )
    assert held.outcome is BranchOutcome.POLICY_BLOCKED
    assert held.reason is GraphFailureReason.ROOT_NOT_ACCEPTED


def test_root_projection_missing_and_generation_mismatch_are_explicit(tmp_path: Path) -> None:
    view = make_view()
    missing_port = FakeGraphPort(view, root=None)
    missing = make_retriever(tmp_path, view, missing_port, journal_name="missing-root.sqlite")[0].retrieve(
        make_request()
    )
    assert missing.outcome is BranchOutcome.INCOMPLETE
    assert missing.reason is GraphFailureReason.ROOT_PROJECTION_MISSING

    mismatch_port = FakeGraphPort(view, generation_override="other-generation")
    mismatch = make_retriever(
        tmp_path,
        view,
        mismatch_port,
        journal_name="generation-mismatch.sqlite",
    )[0].retrieve(make_request())
    assert mismatch.outcome is BranchOutcome.UNAVAILABLE
    assert mismatch.reason is GraphFailureReason.PROJECTION_GENERATION_MISMATCH


def test_root_projection_identity_or_label_mismatch_is_integrity_failure(tmp_path: Path) -> None:
    view = make_view()
    wrong_root = GraphProjectionNode(
        generation_id=view.generation_id,
        canonical_id="source:root",
        identity_digest=ZERO_DIGEST,
        labels=("Source",),
    )
    receipt = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, root=wrong_root),
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is GraphFailureReason.AUTHORITY_BINDING_INTEGRITY


def test_projection_scope_escape_is_unavailable(tmp_path: Path) -> None:
    view = make_view()
    extra = projection_edge(
        view.relations[0],
        {node.canonical_id: node for node in view.nodes},
        view.generation_id,
        "source:not-requested",
    )
    receipt = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, extra_edges=(extra,)),
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is GraphFailureReason.PROJECTION_SCOPE_ESCAPE


def test_projection_record_not_incident_to_frontier_is_malformed(tmp_path: Path) -> None:
    view = make_view()

    def mutate(edge: GraphProjectionEdge) -> GraphProjectionEdge:
        if edge.relation_id == "relation:root-revision":
            return replace(edge, source_id="candidate:one", target_id="process:one")
        return edge

    receipt = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, edge_mutator=mutate),
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is GraphFailureReason.PROJECTION_RECORD_MALFORMED


def test_projection_authority_binding_mismatch_is_unavailable(tmp_path: Path) -> None:
    view = make_view()

    def mutate(edge: GraphProjectionEdge) -> GraphProjectionEdge:
        if edge.relation_id == "relation:root-revision":
            return replace(edge, observed_at="2026-08-02T00:00:00Z")
        return edge

    receipt = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, edge_mutator=mutate),
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason is GraphFailureReason.AUTHORITY_BINDING_INTEGRITY


def test_missing_relation_authority_is_incomplete(tmp_path: Path) -> None:
    view = make_view()
    fake_relation = make_relation(
        "relation:projection-only",
        "source:root",
        "revision:one",
        "SUPPORTS",
    )
    extra = projection_edge(
        fake_relation,
        {node.canonical_id: node for node in view.nodes},
        view.generation_id,
        "source:root",
    )
    receipt = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, extra_edges=(extra,)),
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is GraphFailureReason.RELATION_AUTHORITY_MISSING


def test_missing_node_authority_is_incomplete(tmp_path: Path) -> None:
    view = make_view()
    ghost = GraphProjectionEdge(
        generation_id=view.generation_id,
        frontier_id="source:root",
        relation_id="relation:ghost",
        source_id="source:root",
        target_id="signal:ghost",
        predicate="ABOUT_EVENT",
        source_labels=("Source",),
        target_labels=("Signal",),
        valid_from=VALID_FROM,
        valid_to=VALID_TO,
        observed_at=OBSERVED_AT,
    )
    receipt = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, extra_edges=(ghost,)),
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is GraphFailureReason.NODE_AUTHORITY_MISSING


def test_port_unavailability_and_timeout_are_not_no_match(tmp_path: Path) -> None:
    view = make_view()
    unavailable = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, expand_error=AdmittedGraphPortError("down")),
        journal_name="port-down.sqlite",
    )[0].retrieve(make_request())
    assert unavailable.outcome is BranchOutcome.UNAVAILABLE
    assert unavailable.reason is GraphFailureReason.PROJECTION_UNAVAILABLE

    timeout = make_retriever(
        tmp_path,
        view,
        FakeGraphPort(view, root_error=AdmittedGraphPortTimeout("timeout")),
        journal_name="port-timeout.sqlite",
    )[0].retrieve(make_request())
    assert timeout.outcome is BranchOutcome.INCOMPLETE
    assert timeout.reason is GraphFailureReason.QUERY_TIMEOUT
    assert timeout.elapsed_ms == GRAPH_TIMEOUT_MS


def test_cumulative_timeout_before_port_is_explicit(tmp_path: Path) -> None:
    view = make_view()
    port = FakeGraphPort(view)
    retriever, _ = make_retriever(
        tmp_path,
        view,
        port,
        clock=TimeoutClock(safe_calls=1),
    )
    receipt = retriever.retrieve(make_request())
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason is GraphFailureReason.QUERY_TIMEOUT
    assert receipt.elapsed_ms == GRAPH_TIMEOUT_MS
    assert port.root_calls == []


def test_no_match_only_after_complete_authority_and_projection_checks(tmp_path: Path) -> None:
    root = make_node("source:root", "Source")
    view = make_view(nodes=(root,), relations=())
    receipt = make_retriever(tmp_path, view)[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason is GraphFailureReason.NO_MATCH
    assert not receipt.hits

    blocked = make_view(nodes=(root,), relations=(), open_gap_count=1)
    blocked_receipt = make_retriever(
        tmp_path,
        blocked,
        journal_name="no-match-blocked.sqlite",
    )[0].retrieve(make_request())
    assert blocked_receipt.outcome is BranchOutcome.INCOMPLETE
    assert blocked_receipt.reason is GraphFailureReason.REQUIRED_GAP_OPEN


def test_journal_replay_and_restart_are_byte_identical(tmp_path: Path) -> None:
    view = make_view()
    request = make_request(idempotency_key="graph:replay")
    first = make_retriever(tmp_path, view)[0].retrieve(request)
    replay = make_retriever(tmp_path, view)[0].retrieve(request)
    assert replay.canonical_bytes == first.canonical_bytes
    assert replay.receipt_digest == first.receipt_digest


def test_journal_semantic_conflict_and_tamper_fail_closed(tmp_path: Path) -> None:
    view = make_view()
    key = "graph:conflict"
    retriever, _ = make_retriever(tmp_path, view)
    first = make_request(idempotency_key=key)
    retriever.retrieve(first)
    with pytest.raises(AdmittedGraphJournalError, match="semantic conflict"):
        retriever.retrieve(make_request(root_id="revision:one", idempotency_key=key))

    path = tmp_path / "graph-receipts.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE increment5_admitted_graph_receipts SET receipt_bytes = ? WHERE idempotency_key = ?",
            (b"{}", key),
        )
    with pytest.raises(AdmittedGraphJournalError, match="digest mismatch"):
        retriever.retrieve(first)


def test_concurrent_same_request_retains_one_receipt(tmp_path: Path) -> None:
    view = make_view()
    request = make_request(idempotency_key="graph:concurrent")
    retriever, _ = make_retriever(tmp_path, view)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _item: retriever.retrieve(request), range(16)))
    assert len({receipt.receipt_digest for receipt in receipts}) == 1
    with sqlite3.connect(tmp_path / "graph-receipts.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_admitted_graph_receipts"
        ).fetchone()[0] == 1


def test_graph_production_occurs_outside_sqlite_write_reservation(tmp_path: Path) -> None:
    view = make_view()
    journal = AdmittedGraphReceiptJournal(tmp_path / "nested.sqlite")
    nested_request = make_request(
        root_id="revision:one",
        idempotency_key="graph:nested",
    )
    outer_request = make_request(idempotency_key="graph:outer")
    port = FakeGraphPort(view)
    state = {"nested": False}
    retriever: AdmittedGraphRetriever

    def provider(request: AdmittedGraphRequest) -> AdmittedGraphAuthorityView:
        if request.idempotency_key == "graph:outer" and not state["nested"]:
            state["nested"] = True
            nested = retriever.retrieve(nested_request)
            assert nested.outcome is BranchOutcome.COMPLETE
        return view

    retriever = AdmittedGraphRetriever(
        authority_provider=provider,
        graph_port=port,
        journal=journal,
        monotonic_ns=lambda: 0,
    )
    assert retriever.retrieve(outer_request).outcome is BranchOutcome.COMPLETE
    with sqlite3.connect(tmp_path / "nested.sqlite") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM increment5_admitted_graph_receipts"
        ).fetchone()[0] == 2


def test_journal_schema_has_no_authority_or_write_surface(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite"
    AdmittedGraphReceiptJournal(path)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(increment5_admitted_graph_receipts)"
            )
        }
    assert columns == {
        "idempotency_key",
        "request_digest",
        "receipt_bytes",
        "receipt_digest",
    }


def test_receipt_rejects_provider_work_or_authority_claims(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    with pytest.raises(AdmittedGraphContractError, match="provider work or spend"):
        replace(receipt, provider_call_count=1)
    with pytest.raises(AdmittedGraphContractError, match="authority effect"):
        replace(receipt, authority_effect="RELATION_ADMISSION")
    with pytest.raises(AdmittedGraphContractError, match="production activation"):
        replace(receipt, production_activation_authorized=True)


def test_non_complete_receipt_cannot_retain_paths(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    with pytest.raises(AdmittedGraphContractError, match="non-complete"):
        replace(
            receipt,
            outcome=BranchOutcome.INCOMPLETE,
            reason=GraphFailureReason.REQUIRED_GAP_OPEN,
        )


def test_retriever_imports_no_driver_and_calls_no_other_branch() -> None:
    import newsroom.increment5.admitted_graph_retriever as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "import neo4j",
        "from neo4j",
        "exact_retriever",
        "fulltext_retriever",
        "vector_retriever",
        "reciprocal_rank",
        "candidate_store",
    )
    assert not any(token in source for token in forbidden)


def test_port_protocol_exposes_only_fixed_root_and_frontier_operations() -> None:
    from newsroom.increment5.admitted_graph_retriever import AdmittedGraphReadPort

    names = {
        name
        for name, value in vars(AdmittedGraphReadPort).items()
        if callable(value) and not name.startswith("_")
    }
    assert names == {"read_root", "expand_frontier"}


def test_future_observed_relation_cannot_leak_into_historical_query(tmp_path: Path) -> None:
    root = make_node("source:root", "Source")
    future = make_node("signal:future", "Signal")
    relation = make_relation(
        "relation:future-observation",
        root.canonical_id,
        future.canonical_id,
        "ABOUT_EVENT",
        observed_at="2026-08-07T00:00:00Z",
    )
    view = make_view(nodes=(root, future), relations=(relation,))
    receipt = make_retriever(
        tmp_path,
        view,
        journal_name="future-observation.sqlite",
    )[0].retrieve(make_request())
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason is GraphFailureReason.NO_MATCH
    assert not receipt.hits
    assert any(
        item.subject_id == future.canonical_id
        and item.relation_id == relation.relation_id
        and item.reason is GraphExclusionReason.OUTSIDE_QUERY_VALID_TIME
        for item in receipt.exclusions
    )


def test_receipt_rejects_contradictory_attribution_and_identity(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    with pytest.raises(AdmittedGraphContractError, match="metadata without a read"):
        replace(receipt, authority_read_count=0)
    with pytest.raises(AdmittedGraphContractError, match="identity does not match evidence"):
        replace(receipt, receipt_id=str(uuid.uuid4()))
    with pytest.raises(AdmittedGraphContractError, match="root identity"):
        replace(receipt, root_identity_digest=ZERO_DIGEST)
    with pytest.raises(AdmittedGraphContractError, match="temporal lower bound"):
        replace(receipt, temporal_lower_bound="2026-07-06T08:58:59Z")
    with pytest.raises(AdmittedGraphContractError, match="requires a reason"):
        replace(receipt, outcome=BranchOutcome.INCOMPLETE, reason=None, hits=())


def test_receipt_rejects_disconnected_or_repeated_paths(tmp_path: Path) -> None:
    receipt = make_retriever(tmp_path, make_view())[0].retrieve(make_request())
    first = receipt.hits[0]
    disconnected_hop = replace(first.path[0], source_id="source:not-root")
    disconnected = replace(first, path=(disconnected_hop,))
    with pytest.raises(AdmittedGraphContractError, match="root-contiguous"):
        replace(receipt, hits=(disconnected,) + receipt.hits[1:])
    repeated = replace(first, path=first.path + first.path)
    with pytest.raises(AdmittedGraphContractError, match="repeats a relation"):
        replace(receipt, hits=(repeated,) + receipt.hits[1:])


def test_oversized_failure_diagnostics_compact_and_replay_byte_identically(
    tmp_path: Path,
) -> None:
    view = make_view()
    request = make_request(idempotency_key="graph:compact-response")
    retriever, _ = make_retriever(
        tmp_path,
        view,
        journal_name="compact-producer.sqlite",
    )
    exclusions = tuple(
        AdmittedGraphExclusion(
  subject_id=f"subject:{index:04d}:" + "s" * 390,
  reason=GraphExclusionReason.DUPLICATE_PATH,
  relation_id=f"relation:{index:04d}:" + "r" * 390,
        )
        for index in range(400)
    )
    oversized = retriever._receipt(
        request,
        outcome=BranchOutcome.UNAVAILABLE,
        reason=GraphFailureReason.PROJECTION_UNAVAILABLE,
        lower_bound="2026-07-06T08:59:00Z",
        elapsed_ms=10,
        view=view,
        exclusions=exclusions,
        port_reads=3,
        projection_edges=(GRAPH_MAX_FANOUT + 1) * (GRAPH_MAX_FANOUT + 1),
    )
    assert len(oversized.canonical_bytes) > GRAPH_RESPONSE_LIMIT_BYTES

    compact = retriever._failure(
        request,
        GraphFailureReason.PROJECTION_UNAVAILABLE,
        BranchOutcome.UNAVAILABLE,
        "2026-07-06T08:59:00Z",
        10,
        view=view,
        exclusions=exclusions,
        port_reads=3,
        projection_edges=(GRAPH_MAX_FANOUT + 1) * (GRAPH_MAX_FANOUT + 1),
    )
    assert compact.outcome is BranchOutcome.INCOMPLETE
    assert compact.reason is GraphFailureReason.RESPONSE_LIMIT_EXCEEDED
    assert compact.exclusions == ()
    assert compact.authority_read_count == 1
    assert compact.graph_port_read_count == 3
    assert compact.projection_edge_count == 1_089
    assert len(compact.canonical_bytes) <= GRAPH_RESPONSE_LIMIT_BYTES

    journal = AdmittedGraphReceiptJournal(tmp_path / "compact-replay.sqlite")
    first = journal.execute(request, lambda: compact)
    second = journal.execute(
        request,
        lambda: (_ for _ in ()).throw(AssertionError("producer must not rerun")),
    )
    assert second.canonical_bytes == first.canonical_bytes
    assert second.receipt_digest == first.receipt_digest
