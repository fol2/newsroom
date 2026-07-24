from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import StaticAuthorizer, digest_canonical
from newsroom.authority._integrated_system import _open_candidate_with_adapter
from newsroom.integrated import (
    IntegratedRetrievalContextId,
    IntegratedStateError,
)

from .integrated_c1_helpers import (
    authenticator,
    candidate_request,
    event_policy,
    manifest,
    proof,
    scopes,
)
from .projection_b1_helpers import projection_contracts, projection_read_policy
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)
from .test_integrated_c1_contracts import context as contract_context


def _query_digest(context, nodes) -> str:
    return digest_canonical(
        {
            "contract": "newsroom-integrated-query-v1",
            "family_id": context.metadata.family_id,
            "generation_id": str(context.metadata.generation_id),
            "canonical_ids": [node.canonical_id for node in nodes],
            "query_valid_time": context.metadata.query_valid_time.to_text(),
            "authority_watermark": context.metadata.contiguous_ledger_seq,
        }
    )


def test_query_digest_is_server_recomputable() -> None:
    current = contract_context()
    with pytest.raises(IntegratedStateError, match="query digest"):
        replace(
            current,
            query_digest=digest_canonical({"caller": "asserted"}),
        )


def test_negative_execution_evidence_is_exact() -> None:
    current = contract_context()
    with pytest.raises(IntegratedStateError, match="negative execution evidence"):
        replace(current, known_omissions=())


def test_retrieval_version_must_match_fixture_manifest(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    changed = replace(
        graph.context,
        retrieval_version="integrated_retrieval_v2",
    )
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(IntegratedStateError, match="version.*manifest"):
            system.candidates.admit(
                candidate_request(
                    changed,
                    key="integrated-retrieval-version-mismatch",
                ),
                context=changed,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()


def test_partial_fixture_graph_context_cannot_commit_candidate(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    relation = next(
        item
        for item in graph.context.relations
        if item.source_event_id == str(graph.context.fixture_event_id)
        and item.object_admission_id == str(graph.context.admission_id)
    )
    retained_ids = {
        relation.source_canonical_id,
        relation.target_canonical_id,
    }
    nodes = tuple(
        node
        for node in graph.context.nodes
        if node.canonical_id in retained_ids
    )
    exact_index = tuple(
        entry
        for entry in graph.context.exact_index
        if entry.canonical_id in retained_ids
    )
    partial = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        nodes=nodes,
        relations=(relation,),
        exact_index=exact_index,
        query_digest=_query_digest(graph.context, nodes),
    )
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            IntegratedStateError,
            match="complete fixture structural mapping",
        ):
            system.candidates.admit(
                candidate_request(
                    partial,
                    key="integrated-partial-context",
                ),
                context=partial,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()


def test_retained_context_authorizes_before_identity_lookup(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    denied_scopes = frozenset(
        scope for scope in scopes() if scope != "authority.projection.read"
    )
    system = _open_candidate_with_adapter(
        path=database,
        registry=state.commands,
        payload_schemas=state.schemas,
        contracts=projection_contracts(),
        authenticator=authenticator(),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={"principal.alpha": denied_scopes},
        ),
        event_read_policy=event_policy(),
        projection_read_policy=projection_read_policy(),
        adapter=graph.adapter,
        clock=lambda: graph.context.recorded_at,
    )
    try:
        failures = []
        for context_id in (
            graph.context.context_id,
            IntegratedRetrievalContextId.new(),
        ):
            with pytest.raises(PermissionError) as exc_info:
                system.candidates.context(context_id, proof=proof())
            failures.append((type(exc_info.value), str(exc_info.value)))
        assert failures[0] == failures[1]
    finally:
        system.close()
