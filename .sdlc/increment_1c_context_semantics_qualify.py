from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old[:120]}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    models = "newsroom/integrated/models.py"
    replace_exact(
        models,
        '''        if (
            self.metadata.authoritative_system
            != "sqlite-ledger-and-governed-objects"
            or self.metadata.graph_role
            != "non-authoritative-rebuildable-context"
        ):
            raise IntegratedStateError(
                "integrated context must return to non-graph authority"
            )
        if not isinstance(self.nodes, tuple) or not self.nodes:''',
        '''        if (
            self.metadata.authoritative_system
            != "sqlite-ledger-and-governed-objects"
            or self.metadata.graph_role
            != "non-authoritative-rebuildable-context"
        ):
            raise IntegratedStateError(
                "integrated context must return to non-graph authority"
            )
        if (
            self.metadata.query_valid_time.value
            > self.metadata.serving_time.value
        ):
            raise IntegratedStateError(
                "integrated query-valid time exceeds serving time"
            )
        if not isinstance(self.nodes, tuple) or not self.nodes:''',
    )
    replace_exact(
        models,
        '''        if any(
            relation.source_canonical_id not in known_node_ids
            or relation.target_canonical_id not in known_node_ids
            for relation in self.relations
        ):
            raise IntegratedContractError(
                "integrated graph relation endpoint is absent from returned nodes"
            )
        if not isinstance(self.exact_index, tuple) or not self.exact_index:''',
        '''        if any(
            relation.source_canonical_id not in known_node_ids
            or relation.target_canonical_id not in known_node_ids
            for relation in self.relations
        ):
            raise IntegratedContractError(
                "integrated graph relation endpoint is absent from returned nodes"
            )
        if any(
            relation.recorded_at.value
            > self.metadata.query_valid_time.value
            for relation in self.relations
        ):
            raise IntegratedStateError(
                "integrated graph relation postdates query-valid time"
            )
        if not isinstance(self.exact_index, tuple) or not self.exact_index:''',
    )
    replace_exact(
        models,
        '''        if self.hydrated_blob_digest != self.manifest_digest:
            raise IntegratedStateError(
                "integrated hydrated blob must equal the canonical manifest"
            )
        if not isinstance(''',
        '''        if self.hydrated_blob_digest != self.manifest_digest:
            raise IntegratedStateError(
                "integrated hydrated blob must equal the canonical manifest"
            )
        expected_query_digest = digest_canonical(
            {
                "contract": "newsroom-integrated-query-v1",
                "family_id": self.metadata.family_id,
                "generation_id": str(self.metadata.generation_id),
                "canonical_ids": list(node_ids),
                "query_valid_time": (
                    self.metadata.query_valid_time.to_text()
                ),
                "authority_watermark": (
                    self.metadata.contiguous_ledger_seq
                ),
            }
        )
        if self.query_digest != expected_query_digest:
            raise IntegratedStateError(
                "integrated query digest differs from exact graph request"
            )
        if not isinstance(''',
    )
    replace_exact(
        models,
        '''        object.__setattr__(
            self,
            "known_omissions",
            _require_text_tuple(
                self.known_omissions,
                field="known_omissions",
                allow_empty=True,
            ),
        )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise IntegratedContractError("retrieval context time must be typed")''',
        '''        object.__setattr__(
            self,
            "known_omissions",
            _require_text_tuple(
                self.known_omissions,
                field="known_omissions",
                allow_empty=True,
            ),
        )
        expected_omissions = (
            "No vector, full-text, Graphiti, model, embedding or "
            "live-source retrieval was executed.",
        )
        if self.known_omissions != expected_omissions:
            raise IntegratedStateError(
                "integrated context must retain exact negative execution evidence"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise IntegratedContractError("retrieval context time must be typed")
        if self.metadata.serving_time.value > self.recorded_at.value:
            raise IntegratedStateError(
                "integrated context cannot be recorded before serving time"
            )''',
    )

    store = "newsroom/authority/_integrated_store.py"
    replace_exact(
        store,
        '''            "SELECT fixture_id,fixture_event_id,admission_id,context_digest,"
            "manifest_digest FROM integrated_retrieval_contexts "''',
        '''            "SELECT fixture_id,fixture_event_id,admission_id,context_digest,"
            "manifest_digest,retrieval_version FROM integrated_retrieval_contexts "''',
    )
    replace_exact(
        store,
        '''            or manifest.get("hypothesis_trust_scope") != "PROPOSED"
            or value.get("hypothesis_trust_scope") != "PROPOSED"
        ):''',
        '''            or manifest.get("hypothesis_trust_scope") != "PROPOSED"
            or manifest.get("retrieval_version")
            != str(context["retrieval_version"])
            or value.get("hypothesis_trust_scope") != "PROPOSED"
        ):''',
    )
    replace_exact(
        store,
        '''        if manifest.manifest_digest != context.manifest_digest:
            raise IntegratedStateError(
                "retrieval context belongs to another fixture manifest"
            )
        if context.hydrated_blob_digest != manifest.manifest_digest:''',
        '''        if manifest.manifest_digest != context.manifest_digest:
            raise IntegratedStateError(
                "retrieval context belongs to another fixture manifest"
            )
        if context.retrieval_version != manifest.retrieval_version:
            raise IntegratedStateError(
                "retrieval context version differs from fixture manifest"
            )
        if context.hydrated_blob_digest != manifest.manifest_digest:''',
    )

    system = "newsroom/authority/_integrated_system.py"
    replace_exact(
        system,
        '''    def context(
        self,
        context_id: IntegratedRetrievalContextId,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("retrieval context identity must be typed")
        authenticated = self._projection_boundary._authenticate_read(proof)
        context = self._store.retrieval_context(context_id)
        self._projection_boundary._authorize_read(
            family_id=context.metadata.family_id,
            operation="integrated-retained-context-read",
            semantic_value={
                "context_id": str(context.context_id),
                "context_digest": context.context_digest,
                "generation_id": str(context.metadata.generation_id),
                "authority_watermark": (
                    context.metadata.contiguous_ledger_seq
                ),
            },
            authenticated=authenticated,
        )
        return context''',
        '''    def context(
        self,
        context_id: IntegratedRetrievalContextId,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("retrieval context identity must be typed")
        family_ids = tuple(
            sorted(self._projection_read_policy.allowed_family_ids)
        )
        if len(family_ids) != 1:
            raise IntegratedStateError(
                "retained context reads require one exact family policy"
            )
        family_id = family_ids[0]
        authenticated = self._projection_boundary._authenticate_read(proof)
        self._projection_boundary._authorize_read(
            family_id=family_id,
            operation="integrated-retained-context-read",
            semantic_value={"context_id": str(context_id)},
            authenticated=authenticated,
        )
        context = self._store.retrieval_context(context_id)
        if context.metadata.family_id != family_id:
            raise IntegratedStateError(
                "retained context belongs to another projection family"
            )
        return context''',
    )
    replace_exact(
        system,
        '''        batches = self._expected_batches(
            context.metadata.generation_id,
            context.metadata.contiguous_ledger_seq,
        )
        state_digest = self._adapter.reconcile_generation(''',
        '''        batches = self._expected_batches(
            context.metadata.generation_id,
            context.metadata.contiguous_ledger_seq,
        )
        fixture_batches = tuple(
            batch
            for batch in batches
            if batch.source_event_id == str(context.fixture_event_id)
        )
        if len(fixture_batches) != 1:
            raise IntegratedStateError(
                "retrieval context lacks one exact fixture structural batch"
            )
        expected_canonical_ids = tuple(
            sorted(node.canonical_id for node in fixture_batches[0].nodes)
        )
        retained_canonical_ids = tuple(
            node.canonical_id for node in context.nodes
        )
        if retained_canonical_ids != expected_canonical_ids:
            raise IntegratedStateError(
                "retrieval context must cover the complete fixture structural mapping"
            )
        state_digest = self._adapter.reconcile_generation(''',
    )

    helpers = "newsroom/tests/integrated_c1_helpers.py"
    replace_exact(
        helpers,
        '''        query_digest=digest_canonical(
            {"canonical_ids": list(canonical_ids)}
        ),
        known_omissions=(
            "No vector, full-text, model or live-source retrieval was executed.",
        ),''',
        '''        query_digest=digest_canonical(
            {
                "contract": "newsroom-integrated-query-v1",
                "family_id": response.metadata.family_id,
                "generation_id": str(response.metadata.generation_id),
                "canonical_ids": list(canonical_ids),
                "query_valid_time": (
                    response.metadata.query_valid_time.to_text()
                ),
                "authority_watermark": (
                    response.metadata.contiguous_ledger_seq
                ),
            }
        ),
        known_omissions=(
            "No vector, full-text, Graphiti, model, embedding or "
            "live-source retrieval was executed.",
        ),''',
    )

    contracts = "newsroom/tests/test_integrated_c1_contracts.py"
    replace_exact(
        contracts,
        '''QUERY_DIGEST = digest_canonical({"canonical_ids": ["aggregate", "event"]})''',
        '''QUERY_DIGEST = digest_canonical(
    {
        "contract": "newsroom-integrated-query-v1",
        "family_id": "native-structural",
        "generation_id": str(GENERATION_ID),
        "canonical_ids": [
            "npid:v1:authority-aggregate:fixture",
            "npid:v1:ledger-event:fixture",
        ],
        "query_valid_time": NOW.to_text(),
        "authority_watermark": 1,
    }
)''',
    )
    replace_exact(
        contracts,
        '''        known_omissions=(
            "No vector, full-text, model or live-source retrieval was executed.",
        ),''',
        '''        known_omissions=(
            "No vector, full-text, Graphiti, model, embedding or "
            "live-source retrieval was executed.",
        ),''',
    )

    history = "newsroom/tests/test_integrated_c1_context_history.py"
    replace_exact(
        history,
        '''        query_digest=digest_canonical(
            {"canonical_ids": list(canonical_ids)}
        ),''',
        '''        query_digest=digest_canonical(
            {
                "contract": "newsroom-integrated-query-v1",
                "family_id": response.metadata.family_id,
                "generation_id": str(response.metadata.generation_id),
                "canonical_ids": list(canonical_ids),
                "query_valid_time": (
                    response.metadata.query_valid_time.to_text()
                ),
                "authority_watermark": (
                    response.metadata.contiguous_ledger_seq
                ),
            }
        ),''',
    )

    temporal = "newsroom/tests/test_integrated_c1_temporal_integrity.py"
    replace_exact(
        temporal,
        '''    future = replace(
        graph.context,
        metadata=replace(
            graph.context.metadata,
            serving_time=type(FIXED_NOW)(
                FIXED_NOW.value + timedelta(minutes=1)
            ),
        ),
    )''',
        '''    future_time = type(FIXED_NOW)(
        FIXED_NOW.value + timedelta(minutes=1)
    )
    future = replace(
        graph.context,
        metadata=replace(
            graph.context.metadata,
            serving_time=future_time,
        ),
        recorded_at=future_time,
    )''',
    )

    test_path = Path("newsroom/tests/test_integrated_c1_context_semantics.py")
    if test_path.exists():
        raise SystemExit(f"qualifier test path already exists: {test_path}")
    test_path.write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
