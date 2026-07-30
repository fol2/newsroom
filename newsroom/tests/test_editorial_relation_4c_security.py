from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from newsroom.authority._editorial_relation_boundary import _EditorialRelationBoundary
from newsroom.authority.editorial_relation_system import GovernedEditorialRelations
from newsroom.relations import EditorialRelationDecisionAction

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    RELATION_PROPOSAL_ID,
    open_relation_system,
    relation_authorizer,
    relation_decision_request,
    relation_proposal_request,
    relation_read_policy,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_authenticator, extraction_proof
from .source_3a_helpers import SOURCE_NOW


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _seed_admitted_relation(tmp_path: Path):
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        decision = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="relation-security-accept-v1",
            ),
            proof=extraction_proof(),
        )
        assertion = system.relations.assertion(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        )
        events = system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=100,
            proof=extraction_proof(),
        )
    return state, proposal, decision, assertion, events


def test_public_relation_facade_exposes_only_bounded_typed_operations() -> None:
    public = {
        name
        for name, value in inspect.getmembers(
            GovernedEditorialRelations, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert public == {
        "assertion",
        "current",
        "current_relations",
        "decide",
        "decision",
        "projection_events_after",
        "proposal",
        "proposal_version",
        "propose",
    }
    forbidden = {
        "connection",
        "cypher",
        "graph",
        "graphiti",
        "model",
        "publish",
        "rebuild",
        "session",
        "write_relation",
    }
    assert not public & forbidden
    assert not hasattr(GovernedEditorialRelations, "connection")
    assert not hasattr(GovernedEditorialRelations, "store")


def test_relation_modules_have_no_graphiti_model_network_or_graph_runtime_imports() -> None:
    files = sorted((_REPOSITORY_ROOT / "newsroom/relations").glob("editorial*.py"))
    files += sorted(
        (_REPOSITORY_ROOT / "newsroom/authority").glob("*editorial_relation*.py")
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


def test_relation_read_boundary_rejects_forged_authorization_provenance() -> None:
    delegate = relation_authorizer()

    class ForgedAuthorizer:
        def authorize(self, context, request, *, now):
            decision = delegate.authorize(context, request, now=now)
            return dataclasses.replace(
                decision,
                authorization_request_digest="sha256:" + "0" * 64,
            )

    boundary = _EditorialRelationBoundary(
        store=None,  # type: ignore[arg-type]
        command_service=None,  # type: ignore[arg-type]
        authenticator=extraction_authenticator(),
        authorizer=ForgedAuthorizer(),
        read_policy=relation_read_policy(),
        clock=lambda: SOURCE_NOW,
    )
    with pytest.raises(PermissionError, match="authorization provenance differs"):
        boundary.proposal(RELATION_PROPOSAL_ID, extraction_proof())


def test_proposal_admitted_and_projection_read_scopes_are_independent(
    tmp_path: Path,
) -> None:
    state, proposal, decision, assertion, events = _seed_admitted_relation(tmp_path)

    with open_relation_system(
        state, scopes=frozenset({"authority.relation.read_proposals"})
    ) as proposal_only:
        assert proposal_only.relations.proposal(
            proposal.proposal_id, proof=extraction_proof()
        ).proposal_id == proposal.proposal_id
        assert proposal_only.relations.decision(
            proposal.proposal_id, proof=extraction_proof()
        ).decision_id == decision.decision_id
        with pytest.raises(PermissionError):
            proposal_only.relations.assertion(
                assertion.assertion_id, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            proposal_only.relations.projection_events_after(
                after_ledger_seq=0,
                limit=100,
                proof=extraction_proof(),
            )

    with open_relation_system(
        state, scopes=frozenset({"authority.relation.read_admitted"})
    ) as admitted_only:
        assert admitted_only.relations.assertion(
            assertion.assertion_id, proof=extraction_proof()
        ).assertion_id == assertion.assertion_id
        assert admitted_only.relations.current(
            assertion.assertion_id, proof=extraction_proof()
        ).assertion.assertion_id == assertion.assertion_id
        assert admitted_only.relations.current_relations(
            limit=100, proof=extraction_proof()
        )[0].assertion.assertion_id == assertion.assertion_id
        with pytest.raises(PermissionError):
            admitted_only.relations.proposal(
                proposal.proposal_id, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            admitted_only.relations.projection_events_after(
                after_ledger_seq=0,
                limit=100,
                proof=extraction_proof(),
            )

    with open_relation_system(
        state, scopes=frozenset({"authority.relation.read_projection"})
    ) as projection_only:
        assert projection_only.relations.projection_events_after(
            after_ledger_seq=0,
            limit=100,
            proof=extraction_proof(),
        ) == events
        with pytest.raises(PermissionError):
            projection_only.relations.proposal(
                proposal.proposal_id, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            projection_only.relations.assertion(
                assertion.assertion_id, proof=extraction_proof()
            )


def test_relation_read_limits_are_enforced_before_store_access(tmp_path: Path) -> None:
    state, _proposal, _decision, _assertion, _events = _seed_admitted_relation(
        tmp_path
    )
    limit = relation_read_policy().max_results + 1
    with open_relation_system(state) as system:
        with pytest.raises(PermissionError, match="limit"):
            system.relations.current_relations(
                limit=limit, proof=extraction_proof()
            )
        with pytest.raises(PermissionError, match="limit"):
            system.relations.projection_events_after(
                after_ledger_seq=0,
                limit=limit,
                proof=extraction_proof(),
            )


def test_relation_safe_representations_exclude_retained_statement(tmp_path: Path) -> None:
    state, proposal, _decision, assertion, _events = _seed_admitted_relation(
        tmp_path
    )
    source_expression = "The two admitted entities participate in the same governed process."
    assert source_expression not in repr(relation_proposal_request(state))
    assert source_expression not in repr(proposal)
    assert source_expression not in repr(assertion)
