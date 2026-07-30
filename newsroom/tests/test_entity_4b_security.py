from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from newsroom.authority._entity_boundary import _EntityBoundary
from newsroom.authority.entity_system import GovernedEntityRecords
from newsroom.entities import EntityResolutionState

from .entity_4b_helpers import (
    EN_MENTION_ID,
    dependency_request,
    entity_authorizer,
    entity_read_policy,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import (
    extraction_authenticator,
    extraction_proof,
)
from .source_3a_helpers import SOURCE_NOW
from .test_entity_4b_lineage import (
    ENTITY_A_ID,
    _seed_two_entities,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_public_entity_facade_exposes_only_bounded_typed_operations() -> None:
    public = {
        name
        for name, value in inspect.getmembers(
            GovernedEntityRecords, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert public == {
        "admission_guard",
        "admit_mention",
        "aliases",
        "bind_resolution_dependency",
        "decide_resolution",
        "decision",
        "dependency",
        "dependent_admission_guard",
        "entity",
        "entity_version",
        "mention",
        "merge_decision",
        "merge_entities",
        "preferred",
        "projection_events_after",
        "proposal",
        "proposal_version",
        "propose_resolution",
        "reversal_decision",
        "reverse_lineage",
        "split_decision",
        "split_entity",
    }
    forbidden = {
        "connection",
        "cypher",
        "graph",
        "graphiti",
        "model",
        "publish",
        "rebuild_preferred_projection",
        "session",
        "write_relation",
    }
    assert not public & forbidden
    assert not hasattr(GovernedEntityRecords, "connection")
    assert not hasattr(GovernedEntityRecords, "store")


def test_entity_modules_have_no_graphiti_model_network_or_graph_runtime_imports() -> None:
    files = sorted((_REPOSITORY_ROOT / "newsroom/entities").glob("*.py"))
    files += sorted(
        (_REPOSITORY_ROOT / "newsroom/authority").glob("*entity*.py")
    )
    forbidden_roots = {
        "anthropic",
        "cohere",
        "graphiti",
        "google.generativeai",
        "httpx",
        "neo4j",
        "openai",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not {
        name
        for name in imported
        if any(name == root or name.startswith(root + ".") for root in forbidden_roots)
    }


def test_entity_read_boundary_rejects_forged_authorization_provenance() -> None:
    delegate = entity_authorizer()

    class ForgedAuthorizer:
        def authorize(self, context, request, *, now):
            decision = delegate.authorize(context, request, now=now)
            return dataclasses.replace(
                decision,
                authorization_request_digest="sha256:" + "0" * 64,
            )

    boundary = _EntityBoundary(
        store=None,  # type: ignore[arg-type]
        command_service=None,  # type: ignore[arg-type]
        authenticator=extraction_authenticator(),
        authorizer=ForgedAuthorizer(),
        read_policy=entity_read_policy(),
        clock=lambda: SOURCE_NOW,
    )
    with pytest.raises(PermissionError, match="authorization provenance differs"):
        boundary.mention(EN_MENTION_ID, extraction_proof())


def test_proposal_admitted_and_projection_read_scopes_are_independent(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal_a, _proposal_b = _seed_two_entities(system, state)
        dependency = system.entities.bind_resolution_dependency(
            dependency_request(state, proposal_a), proof=extraction_proof()
        )
        projection = system.entities.projection_events_after(
            0, limit=100, proof=extraction_proof()
        )
        assert projection

    proposal_scope = frozenset({"authority.entity.read_proposals"})
    with open_entity_system(state, scopes=proposal_scope) as proposal_only:
        assert proposal_only.entities.mention(
            EN_MENTION_ID, proof=extraction_proof()
        ).mention_id == EN_MENTION_ID
        assert proposal_only.entities.proposal(
            proposal_a.proposal_id, proof=extraction_proof()
        ).proposal_id == proposal_a.proposal_id
        assert proposal_only.entities.dependency(
            dependency.dependency_id, proof=extraction_proof()
        ).dependency_id == dependency.dependency_id
        with pytest.raises(PermissionError):
            proposal_only.entities.entity(ENTITY_A_ID, proof=extraction_proof())
        with pytest.raises(PermissionError):
            proposal_only.entities.projection_events_after(
                0, limit=100, proof=extraction_proof()
            )

    admitted_scope = frozenset({"authority.entity.read_admitted"})
    with open_entity_system(state, scopes=admitted_scope) as admitted_only:
        assert admitted_only.entities.entity(
            ENTITY_A_ID, proof=extraction_proof()
        ).entity_id == ENTITY_A_ID
        guard = admitted_only.entities.dependent_admission_guard(
            state.relation_source.proposal_id, proof=extraction_proof()
        )
        assert guard.dependencies[0].state is EntityResolutionState.ACCEPTED
        with pytest.raises(PermissionError):
            admitted_only.entities.proposal(
                proposal_a.proposal_id, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            admitted_only.entities.preferred(
                ENTITY_A_ID, proof=extraction_proof()
            )

    projection_scope = frozenset({"authority.entity.read_projection"})
    with open_entity_system(state, scopes=projection_scope) as projection_only:
        assert projection_only.entities.preferred(
            ENTITY_A_ID, proof=extraction_proof()
        ).entity_id == ENTITY_A_ID
        assert projection_only.entities.projection_events_after(
            0, limit=100, proof=extraction_proof()
        ) == projection
        with pytest.raises(PermissionError):
            projection_only.entities.entity(
                ENTITY_A_ID, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            projection_only.entities.mention(
                EN_MENTION_ID, proof=extraction_proof()
            )


def test_entity_read_limits_are_enforced_before_store_access(tmp_path: Path) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        _seed_two_entities(system, state)
        with pytest.raises(PermissionError, match="limit"):
            system.entities.projection_events_after(
                0,
                limit=entity_read_policy().max_results + 1,
                proof=extraction_proof(),
            )
        with pytest.raises(PermissionError, match="limit"):
            system.entities.aliases(
                ENTITY_A_ID,
                limit=entity_read_policy().max_results + 1,
                proof=extraction_proof(),
            )
