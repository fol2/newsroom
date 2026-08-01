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
    "newsroom/authority/_increment4_projection_store.py",
    '''from newsroom.projection.models import ProjectionStateError
from newsroom.relations.editorial_types import (
''',
    '''from newsroom.projection.models import ProjectionStateError
from newsroom.relations.editorial_models import (
    CanonicalEntityRelationEndpoint,
)
from newsroom.relations.editorial_types import (
''',
)

replace_once(
    "newsroom/authority/_increment4_projection_store.py",
    '''                entity_states.append(
                    Increment4EntityProjectionState(
                        entity=entity,
                        version=version,
                        preferred=preferred,
                        aliases=aliases,
                        projection_event=projection_event,
                    )
                )

            relation_states: list[Increment4RelationProjectionState] = []
''',
    '''                entity_states.append(
                    Increment4EntityProjectionState(
                        entity=entity,
                        version=version,
                        preferred=preferred,
                        aliases=aliases,
                        projection_event=projection_event,
                    )
                )

            # Current derivative authority must be dependency-closed. A merge or
            # split predecessor cannot remain when its preferred target was
            # excluded by current rights. Remove dangling states to a fixed point
            # so longer preferred-identity chains fail closed as one unit.
            entity_state_by_id = {
                str(item.entity.entity_id): item for item in entity_states
            }
            while True:
                retained_entity_ids = set(entity_state_by_id)
                dangling_entity_ids = tuple(
                    sorted(
                        entity_id
                        for entity_id, item in entity_state_by_id.items()
                        if str(item.preferred.preferred_entity_id)
                        not in retained_entity_ids
                    )
                )
                if not dangling_entity_ids:
                    break
                for entity_id in dangling_entity_ids:
                    del entity_state_by_id[entity_id]
            entity_states = [
                entity_state_by_id[entity_id]
                for entity_id in sorted(entity_state_by_id)
            ]
            current_entity_version_ids = {
                str(item.version.entity_version_id) for item in entity_states
            }

            relation_states: list[Increment4RelationProjectionState] = []
''',
)

replace_once(
    "newsroom/authority/_increment4_projection_store.py",
    '''                except (PermissionError, EditorialRelationStaleDecision):
                    # Rights-invalid or endpoint-stale assertions remain immutable
                    # history but cannot participate in the current graph snapshot.
                    continue
                projection_row = conn.execute(
''',
    '''                except (PermissionError, EditorialRelationStaleDecision):
                    # Rights-invalid or endpoint-stale assertions remain immutable
                    # history but cannot participate in the current graph snapshot.
                    continue
                assertion = current.assertion
                if isinstance(
                    assertion.subject,
                    CanonicalEntityRelationEndpoint,
                ):
                    if not isinstance(
                        assertion.object,
                        CanonicalEntityRelationEndpoint,
                    ):
                        raise AuthorityPersistenceError(
                            "Increment 4 relation endpoint kinds differ"
                        )
                    if (
                        str(assertion.subject.entity_version_id)
                        not in current_entity_version_ids
                        or str(assertion.object.entity_version_id)
                        not in current_entity_version_ids
                    ):
                        # A relation can remain individually current while an
                        # endpoint was removed by preferred-identity closure.
                        # Preserve its immutable history but omit the derivative.
                        continue
                projection_row = conn.execute(
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''        return authoritative.through_ledger_seq, authoritative

    @staticmethod
    def _batch_by_sequence(
''',
    '''        return authoritative.through_ledger_seq, authoritative

    def _create_generation(
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
                    },
                ),
            ),
            proof,
        )

    def _retry_active_predecessor_cleanup(
        self,
        *,
        request: Increment4Neo4jBuildRequest,
        proof: AuthenticationProof,
    ) -> tuple[Any | None, int | None]:
        metadata = self._metadata_or_none(request.generation_id)
        if (
            metadata is None
            or metadata.generation.state is not ProjectionGenerationState.ACTIVE
        ):
            return None, None
        self._require_family(metadata)

        # Prove this is the exact immutable creation-command replay before any
        # graph cleanup. A changed request key or snapshot digest cannot attach to
        # an existing ACTIVE identity and trigger predecessor deletion.
        self._create_generation(
            request=request,
            snapshot_digest=request.snapshot.canonical_digest,
            proof=proof,
        )
        promotion = self._promotion_for_generation(request.generation_id)
        purged_prior = 0
        if (
            request.purge_retired_generation
            and promotion.prior_generation is not None
        ):
            # The target is already ACTIVE and the predecessor already RETIRED in
            # SQLite. Retry only that immutable retired namespace before the
            # current-source gate, because newer source authority must not strand
            # a failed post-promotion purge forever.
            purged_prior = self._adapter.cleanup_generation(
                str(promotion.prior_generation.generation_id)
            )
        return promotion, purged_prior

    @staticmethod
    def _batch_by_sequence(
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''        validation: Any,
        promotion: Any,
        state_digest: str,
    ) -> Increment4Neo4jBuildResult:
        purged_prior = 0
        if (
            request.purge_retired_generation
            and promotion.prior_generation is not None
        ):
            purged_prior = self._adapter.cleanup_generation(
                str(promotion.prior_generation.generation_id)
            )
''',
    '''        validation: Any,
        promotion: Any,
        state_digest: str,
        purged_prior: int | None = None,
    ) -> Increment4Neo4jBuildResult:
        if purged_prior is None:
            purged_prior = 0
            if (
                request.purge_retired_generation
                and promotion.prior_generation is not None
            ):
                purged_prior = self._adapter.cleanup_generation(
                    str(promotion.prior_generation.generation_id)
                )
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''            # Register the immutable family and authorize this operation before
            # authority reads. Generation and graph mutation wait until the caller
            # snapshot exactly matches current retained serving authority.
''',
    '''            # Register the immutable family and authorize this operation before
            # authority reads. New generation and serving-graph mutation wait for
            # the exact current snapshot. The sole pre-gate graph effect is an
            # exact-command retry of a retained ACTIVE promotion's failed cleanup
            # against its immutable RETIRED predecessor namespace.
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''                },
                proof=proof,
            )
            source_watermark, authoritative_snapshot = (
                self._require_source_snapshot(request)
            )
''',
    '''                },
                proof=proof,
            )
            active_promotion, pre_purged_prior = (
                self._retry_active_predecessor_cleanup(
                    request=request,
                    proof=proof,
                )
            )
            source_watermark, authoritative_snapshot = (
                self._require_source_snapshot(request)
            )
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''            # Always replay the exact immutable creation command. A different
            # request key or semantic payload cannot attach to an existing
            # generation identity and masquerade as a completed-command retry.
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
                            "snapshot_digest": authoritative_snapshot.canonical_digest,
                        },
                    ),
                ),
                proof,
            )
''',
    '''            # New and unfinished generations replay the exact immutable
            # creation command only after the source gate. ACTIVE generations
            # already replayed it before their bounded predecessor cleanup.
            if active_promotion is None:
                self._create_generation(
                    request=request,
                    snapshot_digest=authoritative_snapshot.canonical_digest,
                    proof=proof,
                )
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''                promotion = self._promotion_for_generation(request.generation_id)
                # The serving generation remains reconciliation-only. A retained
''',
    '''                promotion = (
                    active_promotion
                    if active_promotion is not None
                    else self._promotion_for_generation(request.generation_id)
                )
                # The serving generation remains reconciliation-only. A retained
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''                    promotion=promotion,
                    state_digest=state_digest,
                )
                # Authority commands do not share the graph operation lock. Re-read
''',
    '''                    promotion=promotion,
                    state_digest=state_digest,
                    purged_prior=pre_purged_prior,
                )
                # Authority commands do not share the graph operation lock. Re-read
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''        serving_before_retry = {
            key: value
            for key, value in adapter.deliveries.items()
            if key[0] == str(GENERATION_2)
        }
        apply_before_retry = adapter.apply_count
        reconcile_before_retry = adapter.reconcile_count

        second = system.increment4.build_and_promote(
            replacement_request,
            proof=extraction_proof(),
        )

    assert first.generation.state is ProjectionGenerationState.ACTIVE
    assert second.generation.state is ProjectionGenerationState.ACTIVE
    assert second.prior_generation is not None
    assert second.prior_generation.generation_id == GENERATION_1
    assert second.prior_generation.state is ProjectionGenerationState.RETIRED
    assert second.deleted_target_graph_record_count == 0
    assert second.purged_retired_graph_record_count == first.projected_batch_count
    assert adapter.apply_count == apply_before_retry
    assert adapter.reconcile_count == reconcile_before_retry + 1
    assert not any(key[0] == str(GENERATION_1) for key in adapter.deliveries)
    assert {
        key: value
        for key, value in adapter.deliveries.items()
        if key[0] == str(GENERATION_2)
    } == serving_before_retry
''',
    '''        serving_before_retry = {
            key: value
            for key, value in adapter.deliveries.items()
            if key[0] == str(GENERATION_2)
        }
        apply_before_retry = adapter.apply_count
        cleanup_before_retry = adapter.cleanup_count
        reconcile_before_retry = adapter.reconcile_count
        system.commands.execute(
            authority_command(
                key="increment4-retired-cleanup-source-advance-v1",
                aggregate_id=AggregateId.parse(
                    "00000000-0000-4000-8000-000000005100"
                ),
            ),
            proof=extraction_proof(),
        )

        with pytest.raises(
            ProjectionStateError,
            match="differs from exact retained admitted authority",
        ):
            system.increment4.build_and_promote(
                replacement_request,
                proof=extraction_proof(),
            )
        first_after = system.increment4.generation_status(
            GENERATION_1, proof=extraction_proof()
        )
        second_after = system.increment4.generation_status(
            GENERATION_2, proof=extraction_proof()
        )

    assert first.generation.state is ProjectionGenerationState.ACTIVE
    assert first_after.generation.state is ProjectionGenerationState.RETIRED
    assert second_after.generation.state is ProjectionGenerationState.ACTIVE
    assert second_after.source_watermark_ledger_seq > snapshot.through_ledger_seq
    assert adapter.apply_count == apply_before_retry
    assert adapter.cleanup_count == cleanup_before_retry + 1
    assert adapter.reconcile_count == reconcile_before_retry
    assert not any(key[0] == str(GENERATION_1) for key in adapter.deliveries)
    assert {
        key: value
        for key, value in adapter.deliveries.items()
        if key[0] == str(GENERATION_2)
    } == serving_before_retry
''',
)

replace_once(
    "newsroom/tests/test_increment4e_stale_relation_rebuild.py",
    '''import pytest

from newsroom.entities import (
''',
    '''import pytest

import newsroom.authority._increment4_projection_store as projection_store_module
from newsroom.entities import (
''',
)

replace_once(
    "newsroom/tests/test_increment4e_stale_relation_rebuild.py",
    '''from .increment4e_helpers import (
    _entity_state,
    _ledger_events,
''',
    '''from .increment4e_helpers import (
    _ledger_events,
''',
)

replace_once(
    "newsroom/tests/test_increment4e_stale_relation_rebuild.py",
    '''def test_increment4_rebuild_omits_relation_stale_after_entity_merge(
    tmp_path: Path,
) -> None:
    state, _initial_snapshot = admitted_increment4_fixture(tmp_path)
''',
    '''def test_increment4_rebuild_omits_relation_stale_after_entity_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, initial_snapshot = admitted_increment4_fixture(tmp_path)
    retained_current = next(
        item.current
        for item in initial_snapshot.relations
        if item.current.assertion.assertion_id == RELATION_ASSERTION_ID
    )
''',
)

replace_once(
    "newsroom/tests/test_increment4e_stale_relation_rebuild.py",
    '''        merged_versions = {
            item.entity_id: item.merged_entity_version_id
            for item in merged.predecessors
        }
        current_entities = (
            _entity_state(entities, ENTITY_ID, merged_versions[ENTITY_ID]),
            _entity_state(
                entities,
                ZH_ENTITY_ID,
                merged_versions[ZH_ENTITY_ID],
            ),
            _entity_state(
                entities,
                successor_entity_id,
                successor_version_id,
            ),
        )
''',
    '''        for predecessor_id in (ENTITY_ID, ZH_ENTITY_ID):
            preferred = entities.entities.preferred(
                predecessor_id,
                proof=extraction_proof(),
            )
            assert preferred.preferred_entity_id == successor_entity_id
''',
)

replace_once(
    "newsroom/tests/test_increment4e_stale_relation_rebuild.py",
    '''    events = _ledger_events(state.entity.extraction.database)
    snapshot = sorted_snapshot(
        entities=current_entities,
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    adapter = MemoryNeo4jAdapter()
''',
    '''    events = _ledger_events(state.entity.extraction.database)
    snapshot = sorted_snapshot(
        entities=(),
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    store_type = projection_store_module._Increment4ProjectionAuthorityStore
    original_entity = store_type.entity
    original_editorial_current = store_type.editorial_current

    def entity(self, entity_id):
        if entity_id == successor_entity_id:
            raise PermissionError("fixed merge-successor rights denial")
        return original_entity(self, entity_id)

    def editorial_current(self, assertion_id):
        if assertion_id == RELATION_ASSERTION_ID:
            return retained_current
        return original_editorial_current(self, assertion_id)

    monkeypatch.setattr(store_type, "entity", entity)
    monkeypatch.setattr(store_type, "editorial_current", editorial_current)

    adapter = MemoryNeo4jAdapter()
''',
)

replace_once(
    "newsroom/tests/test_increment4e_stale_relation_rebuild.py",
    '''    assert rebuilt.generation.state is ProjectionGenerationState.ACTIVE
    assert not any(
        node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
''',
    '''    assert rebuilt.generation.state is ProjectionGenerationState.ACTIVE
    assert not any(
        node.identity_source == "CANONICAL_ENTITY_ID"
        for (generation, _ledger_seq), batch in adapter.deliveries.items()
        if generation == str(GENERATION_ID)
        for node in batch.nodes
    )
    assert not any(
        node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
''',
)
