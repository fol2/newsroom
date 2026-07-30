from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority.object_policy import merge_authority_registries
from newsroom.entities import (
    EntityAliasKind,
    EntityContractError,
    EntityResolutionDecisionAction,
    EntityResolutionDependencyId,
    EntityResolutionProposalVersionId,
    EntityResolutionState,
    EntitySemanticCollision,
    EntityStaleDecision,
    EntityStateError,
)
from newsroom.entities.policy import merge_entity_authority_registries

from .authority_a2b_helpers import open_object_system
from .entity_4b_helpers import (
    DEPENDENCY_ID,
    EN_ALIAS_ID,
    EN_MENTION_ID,
    ENTITY_ID,
    ENTITY_VERSION_ID,
    decision_request,
    dependency_request,
    mention_request,
    new_entity_proposal_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof
from .source_3a_helpers import SOURCE_NOW, proof


def _id(suffix: int) -> EntityResolutionDependencyId:
    return EntityResolutionDependencyId.parse(
        f"00000000-0000-4000-8000-{suffix:012d}"
    )


def _seed_proposal(system, state):
    system.entities.admit_mention(
        mention_request(
            state.en_source,
            mention_id=EN_MENTION_ID,
            language="en-GB",
            key="dependency-mention-en-v1",
        ),
        proof=extraction_proof(),
    )
    return system.entities.propose_resolution(
        new_entity_proposal_request(
            state, key="dependency-resolution-proposal-v1"
        ),
        proof=extraction_proof(),
    )


def test_material_dependency_blocks_until_resolution_is_accepted_and_replays(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_proposal(system, state)
        request = dependency_request(state, proposal)
        dependency = system.entities.bind_resolution_dependency(
            request, proof=extraction_proof()
        )
        replay = system.entities.bind_resolution_dependency(
            request, proof=extraction_proof()
        )
        guard = system.entities.dependent_admission_guard(
            state.relation_source.proposal_id, proof=extraction_proof()
        )
        assert replay.replayed is True
        assert replay.canonical_digest == dependency.canonical_digest
        assert system.entities.dependency(
            DEPENDENCY_ID, proof=extraction_proof()
        ).canonical_digest == dependency.canonical_digest
        assert guard.dependencies[0].state is EntityResolutionState.PROPOSED
        assert guard.materially_unresolved is True
        with pytest.raises(EntityContractError, match="blocks dependent admission"):
            guard.require_resolved()

        hold = system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.HOLD,
                key="dependency-resolution-hold-v1",
            ),
            proof=extraction_proof(),
        )
        held = system.entities.dependent_admission_guard(
            state.relation_source.proposal_id, proof=extraction_proof()
        )
        assert held.dependencies[0].state is EntityResolutionState.HELD
        assert held.materially_unresolved is True

        system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                expected_decision_version=1,
                previous=hold.decision_id,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="dependency-resolution-accept-v2",
            ),
            proof=extraction_proof(),
        )
        accepted = system.entities.dependent_admission_guard(
            state.relation_source.proposal_id, proof=extraction_proof()
        )
        assert accepted.dependencies[0].state is EntityResolutionState.ACCEPTED
        assert accepted.materially_unresolved is False
        accepted.require_resolved()



def test_material_dependency_rejection_remains_blocking(tmp_path: Path) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_proposal(system, state)
        system.entities.bind_resolution_dependency(
            dependency_request(state, proposal), proof=extraction_proof()
        )
        system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.REJECT,
                key="dependency-resolution-reject-v1",
            ),
            proof=extraction_proof(),
        )
        guard = system.entities.dependent_admission_guard(
            state.relation_source.proposal_id, proof=extraction_proof()
        )
        assert guard.dependencies[0].state is EntityResolutionState.REJECTED
        assert guard.materially_unresolved is True
        with pytest.raises(EntityContractError, match="blocks dependent admission"):
            guard.require_resolved()

def test_nonmaterial_dependency_is_traceable_but_does_not_block(tmp_path: Path) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_proposal(system, state)
        system.entities.bind_resolution_dependency(
            dependency_request(
                state,
                proposal,
                dependency_id=_id(4242),
                material=False,
                key="dependency-nonmaterial-v1",
            ),
            proof=extraction_proof(),
        )
        guard = system.entities.dependent_admission_guard(
            state.relation_source.proposal_id, proof=extraction_proof()
        )
        assert guard.dependencies[0].state is EntityResolutionState.PROPOSED
        assert guard.dependencies[0].material is False
        assert guard.materially_unresolved is False
        guard.require_resolved()


def test_dependency_rejects_nonrelation_stale_and_duplicate_semantics(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_proposal(system, state)
        request = dependency_request(state, proposal)
        with pytest.raises(EntityStateError, match="RELATION"):
            system.entities.bind_resolution_dependency(
                replace(
                    request,
                    dependency_id=_id(4243),
                    dependent_proposal_id=state.en_source.proposal_id,
                    expected_dependent_proposal_digest=(
                        state.en_source.canonical_digest
                    ),
                    idempotency_key="dependency-nonrelation-v1",
                ),
                proof=extraction_proof(),
            )
        with pytest.raises(EntityStaleDecision, match="digest"):
            system.entities.bind_resolution_dependency(
                replace(
                    request,
                    dependency_id=_id(4244),
                    expected_dependent_proposal_digest="sha256:" + "0" * 64,
                    idempotency_key="dependency-stale-relation-v1",
                ),
                proof=extraction_proof(),
            )
        with pytest.raises(EntityStaleDecision, match="current proposal"):
            system.entities.bind_resolution_dependency(
                replace(
                    request,
                    dependency_id=_id(4246),
                    expected_resolution_proposal_version_id=(
                        EntityResolutionProposalVersionId.parse(
                            "00000000-0000-4000-8000-000000004246"
                        )
                    ),
                    idempotency_key="dependency-stale-resolution-version-v1",
                ),
                proof=extraction_proof(),
            )
        with pytest.raises(EntityStaleDecision, match="current proposal"):
            system.entities.bind_resolution_dependency(
                replace(
                    request,
                    dependency_id=_id(4247),
                    expected_resolution_proposal_digest="sha256:" + "0" * 64,
                    idempotency_key="dependency-stale-resolution-digest-v1",
                ),
                proof=extraction_proof(),
            )
        system.entities.bind_resolution_dependency(
            request, proof=extraction_proof()
        )
        with pytest.raises(EntitySemanticCollision, match="equivalent"):
            system.entities.bind_resolution_dependency(
                replace(
                    request,
                    dependency_id=_id(4245),
                    idempotency_key="dependency-duplicate-semantics-v1",
                ),
                proof=extraction_proof(),
            )


def test_dependency_guard_revalidates_complete_extraction_run_rights(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_proposal(system, state)
        system.entities.bind_resolution_dependency(
            dependency_request(state, proposal), proof=extraction_proof()
        )

    commands, schemas = merge_entity_authority_registries(
        command_registry=state.extraction.commands,
        payload_schemas=state.extraction.schemas,
    )
    commands, schemas = merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )
    with open_object_system(
        state.extraction.database,
        object_root=state.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.extraction.input_binding.passages[0].admission_id,
            reason_code="DEPENDENCY_INPUT_REVOKED",
            idempotency_key="dependency-input-revoked-v1",
            proof=proof(),
        )

    with open_entity_system(state) as reopened:
        with pytest.raises(PermissionError):
            reopened.entities.dependency(
                DEPENDENCY_ID, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            reopened.entities.dependent_admission_guard(
                state.relation_source.proposal_id, proof=extraction_proof()
            )
