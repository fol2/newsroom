from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority import digest_canonical
from newsroom.integrated import (
    IntegratedContractError,
    IntegratedStateError,
)

from .test_integrated_c1_contracts import context


def test_exact_index_entries_must_match_their_graph_nodes_exactly() -> None:
    current = context()
    changed = (
        replace(
            current.exact_index[0],
            first_ledger_seq=current.exact_index[0].first_ledger_seq + 1,
        ),
        *current.exact_index[1:],
    )
    with pytest.raises(
        IntegratedContractError,
        match="exact index.*graph node|graph node.*exact index",
    ):
        replace(current, exact_index=changed)


def test_context_cannot_claim_graph_evidence_beyond_its_watermark() -> None:
    current = context()
    with pytest.raises(
        IntegratedStateError,
        match="watermark",
    ):
        replace(
            current,
            relations=(
                replace(
                    current.relations[0],
                    ledger_seq=current.metadata.contiguous_ledger_seq + 1,
                ),
            ),
        )


def test_context_hydrated_blob_must_be_the_canonical_manifest() -> None:
    current = context()
    with pytest.raises(
        IntegratedStateError,
        match="hydrated.*manifest|manifest.*hydrated",
    ):
        replace(
            current,
            hydrated_blob_digest=digest_canonical(
                {"different": "governed-object"}
            ),
        )
