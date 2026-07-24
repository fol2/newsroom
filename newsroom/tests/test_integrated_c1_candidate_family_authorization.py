from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import digest_canonical
from newsroom.integrated import IntegratedStateError

from .integrated_c1_helpers import candidate_request, proof
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def test_candidate_context_family_is_rejected_before_authority_lookup(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    family_id = "unregistered.family"
    metadata = replace(graph.context.metadata, family_id=family_id)
    changed = replace(
        graph.context,
        metadata=metadata,
        query_digest=digest_canonical(
            {
                "contract": "newsroom-integrated-query-v1",
                "family_id": family_id,
                "generation_id": str(metadata.generation_id),
                "canonical_ids": [
                    node.canonical_id for node in graph.context.nodes
                ],
                "query_valid_time": metadata.query_valid_time.to_text(),
                "authority_watermark": metadata.contiguous_ledger_seq,
            }
        ),
    )

    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            IntegratedStateError,
            match="another projection family",
        ):
            system.candidates.admit(
                candidate_request(
                    changed,
                    key="integrated-candidate-other-family",
                ),
                context=changed,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()
