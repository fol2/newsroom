from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact patch anchor, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''    def _create_generation(
        self,
        *,
        request: Increment4Neo4jBuildRequest,
        snapshot_digest: str,
        proof: AuthenticationProof,
    ) -> None:
        self._projection_boundary.create_generation(
            ProjectionGenerationCreateRequest(
                generation_id=request.generation_id,
                family_id=INCREMENT4_ADMITTED_FAMILY_ID,
                reason_code=request.reason_code,
                idempotency_key=self._operation_key(
                    request.idempotency_key,
                    "create",
                    {
                        "generation_id": str(request.generation_id),
                        "snapshot_digest": snapshot_digest,
                        "purge_retired_generation": (
                            request.purge_retired_generation
                        ),
                    },
                ),
            ),
            proof,
        )
''',
    '''    def _create_generation(
        self,
        *,
        request: Increment4Neo4jBuildRequest,
        snapshot_digest: str,
        proof: AuthenticationProof,
        legacy_identity: bool = False,
    ) -> None:
        creation_value: dict[str, object] = {
            "generation_id": str(request.generation_id),
            "snapshot_digest": snapshot_digest,
        }
        if not legacy_identity:
            creation_value["purge_retired_generation"] = (
                request.purge_retired_generation
            )
        self._projection_boundary.create_generation(
            ProjectionGenerationCreateRequest(
                generation_id=request.generation_id,
                family_id=INCREMENT4_ADMITTED_FAMILY_ID,
                reason_code=request.reason_code,
                idempotency_key=self._operation_key(
                    request.idempotency_key,
                    "create",
                    creation_value,
                ),
            ),
            proof,
        )
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''        try:
            self._create_generation(
                request=request,
                snapshot_digest=request.snapshot.canonical_digest,
                proof=proof,
            )
        except ExpectedVersionConflict:
            raise ProjectionStateError(
                "Increment 4 ACTIVE retry differs from immutable build intent"
            ) from None
        promotion = self._promotion_for_generation(request.generation_id)
''',
    '''        try:
            self._create_generation(
                request=request,
                snapshot_digest=request.snapshot.canonical_digest,
                proof=proof,
            )
        except ExpectedVersionConflict:
            if not request.purge_retired_generation:
                raise ProjectionStateError(
                    "Increment 4 ACTIVE retry differs from immutable build intent"
                ) from None
            try:
                # Parent-release creation identities predate the explicit purge
                # bit. Retired graph state is derivative and that release's
                # rights-safe/default contract is therefore migrated one-way to
                # purge=True. A false request never receives this fallback.
                self._create_generation(
                    request=request,
                    snapshot_digest=request.snapshot.canonical_digest,
                    proof=proof,
                    legacy_identity=True,
                )
            except ExpectedVersionConflict:
                raise ProjectionStateError(
                    "Increment 4 ACTIVE retry differs from immutable build intent"
                ) from None
        promotion = self._promotion_for_generation(request.generation_id)
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''import pytest

from newsroom.authority import AggregateId
''',
    '''import pytest

import newsroom.authority._increment4_neo4j_boundary as increment4_boundary_module
from newsroom.authority import AggregateId
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = MemoryNeo4jAdapter()

    with open_increment4_neo4j_system(state, adapter) as system:
        result = system.increment4.build_and_promote(
            _request(GENERATION_1, snapshot, key="increment4-build-v1"),
            proof=extraction_proof(),
        )
''',
    '''    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = MemoryNeo4jAdapter()
    request = _request(GENERATION_1, snapshot, key="increment4-build-v1")

    with open_increment4_neo4j_system(state, adapter) as system:
        result = system.increment4.build_and_promote(
            request,
            proof=extraction_proof(),
        )
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''        response = system.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )

    assert result.generation.state is ProjectionGenerationState.ACTIVE
''',
    '''        response = system.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )
        apply_before_changed_retry = adapter.apply_count
        cleanup_before_changed_retry = adapter.cleanup_count
        reconcile_before_changed_retry = adapter.reconcile_count
        with pytest.raises(
            ProjectionStateError,
            match="immutable build intent",
        ):
            system.increment4.build_and_promote(
                replace(request, purge_retired_generation=False),
                proof=extraction_proof(),
            )
        assert adapter.apply_count == apply_before_changed_retry
        assert adapter.cleanup_count == cleanup_before_changed_retry
        assert adapter.reconcile_count == reconcile_before_changed_retry

    assert result.generation.state is ProjectionGenerationState.ACTIVE
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''def test_increment4_replacement_retires_and_purges_prior_generation(
    tmp_path: Path,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = _FailRetiredCleanupOnceAdapter()
''',
    '''def test_increment4_replacement_retires_and_purges_prior_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = _FailRetiredCleanupOnceAdapter()
    boundary_type = increment4_boundary_module._Increment4Neo4jBoundary
    current_create_generation = boundary_type._create_generation

    def create_legacy_generation(
        self,
        *,
        request,
        snapshot_digest,
        proof,
        legacy_identity=False,
    ):
        return current_create_generation(
            self,
            request=request,
            snapshot_digest=snapshot_digest,
            proof=proof,
            legacy_identity=True,
        )

    # Seed the exact parent-release identity before exercising post-upgrade
    # ACTIVE replay and pending predecessor cleanup.
    monkeypatch.setattr(
        boundary_type,
        "_create_generation",
        create_legacy_generation,
    )
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''        with pytest.raises(
            Neo4jWriteError,
            match="retired-generation cleanup failure",
        ):
            system.increment4.build_and_promote(
                replacement_request,
                proof=extraction_proof(),
            )
        first_status = system.increment4.generation_status(
''',
    '''        with pytest.raises(
            Neo4jWriteError,
            match="retired-generation cleanup failure",
        ):
            system.increment4.build_and_promote(
                replacement_request,
                proof=extraction_proof(),
            )
        monkeypatch.setattr(
            boundary_type,
            "_create_generation",
            current_create_generation,
        )
        first_status = system.increment4.generation_status(
''',
)

replace_once(
    "docs/operations/increment-4e-bilingual-actual-neo4j-proof.md",
    '''- whether a retired predecessor generation may be physically purged.

The controller performs:
''',
    '''- whether a retired predecessor generation may be physically purged.

Creation identity is versioned. Current builds bind the purge bit into the
immutable generation-creation key. A parent-release ACTIVE generation may carry
the earlier key that omitted this bit. That legacy identity is accepted only for
`purge_retired_generation=True`: retired Neo4j state is derivative, the historical
default is purge, and the compatibility rule therefore migrates ambiguous legacy
intent one-way to the rights-safe default. A false request never receives the
legacy fallback and cannot suppress a pending cleanup.

The controller performs:
''',
)
