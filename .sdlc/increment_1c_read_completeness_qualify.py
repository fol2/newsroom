from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old[:120]}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    system = "newsroom/authority/_integrated_system.py"
    replace_exact(
        system,
        '''        canonical_ids = tuple(item.canonical_id for item in context.nodes)
        actual = self._adapter.read(
            generation_id=str(context.metadata.generation_id),
            canonical_ids=canonical_ids,
            maximum_ledger_seq=context.metadata.contiguous_ledger_seq,
            limit=max(len(context.nodes), len(context.relations), 1),
        )''',
        '''        canonical_ids = expected_canonical_ids
        selected_ids = set(canonical_ids)
        relevant_relation_upper_bound = len(
            {
                relation.relation_key
                for batch in batches
                for relation in batch.relations
                if relation.source_canonical_id in selected_ids
                or relation.target_canonical_id in selected_ids
            }
        )
        read_limit = self._projection_read_policy.max_results
        if (
            len(canonical_ids) >= read_limit
            or relevant_relation_upper_bound >= read_limit
        ):
            raise IntegratedStateError(
                "integrated fixture graph exceeds the bounded read policy"
            )
        actual = self._adapter.read(
            generation_id=str(context.metadata.generation_id),
            canonical_ids=canonical_ids,
            maximum_ledger_seq=context.metadata.contiguous_ledger_seq,
            limit=read_limit,
        )''',
    )

    test_path = Path("newsroom/tests/test_integrated_c1_read_completeness.py")
    if test_path.exists():
        raise SystemExit(f"qualifier test path already exists: {test_path}")
    test_path.write_text(
        '''from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.integrated import IntegratedRetrievalContextId
from newsroom.projection.neo4j import Neo4jIdentityConflict

from .integrated_c1_helpers import candidate_request, proof
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def test_caller_cannot_truncate_fixture_relations_with_a_smaller_read_limit(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    assert len(graph.context.relations) > len(graph.context.nodes)
    retained_relations = graph.context.relations[: len(graph.context.nodes)]
    assert len(retained_relations) < len(graph.context.relations)
    assert any(
        relation.source_event_id == str(graph.context.fixture_event_id)
        and relation.object_admission_id == str(graph.context.admission_id)
        for relation in retained_relations
    )
    truncated = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        relations=retained_relations,
    )

    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            Neo4jIdentityConflict,
            match="current Neo4j read differs",
        ):
            system.candidates.admit(
                candidate_request(
                    truncated,
                    key="integrated-truncated-relations",
                ),
                context=truncated,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
