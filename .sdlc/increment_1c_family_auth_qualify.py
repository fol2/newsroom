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
        '''        self._projection_read_policy.require_principal(
            grant.authentication.principal_id
        )
        self._projection_boundary._authorize_read(
            family_id=context.metadata.family_id,
            operation="integrated-candidate-context-reconcile",''',
        '''        self._projection_read_policy.require_principal(
            grant.authentication.principal_id
        )
        family_ids = tuple(
            sorted(self._projection_read_policy.allowed_family_ids)
        )
        if len(family_ids) != 1:
            raise IntegratedStateError(
                "Candidate admission requires one exact family policy"
            )
        family_id = family_ids[0]
        if context.metadata.family_id != family_id:
            raise IntegratedStateError(
                "Candidate context belongs to another projection family"
            )
        self._projection_boundary._authorize_read(
            family_id=family_id,
            operation="integrated-candidate-context-reconcile",''',
    )
    replace_exact(
        system,
        '''        metadata = self._store.projection_active_generation_metadata(
            context.metadata.family_id
        )''',
        '''        metadata = self._store.projection_active_generation_metadata(
            family_id
        )''',
    )

    test_path = Path(
        "newsroom/tests/test_integrated_c1_candidate_family_authorization.py"
    )
    if test_path.exists():
        raise SystemExit(f"qualifier test path already exists: {test_path}")
    test_path.write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
