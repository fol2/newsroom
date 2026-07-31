from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from newsroom.authority._graphiti_adapter_boundary import _GraphitiAdapterBoundary
from newsroom.authority.graphiti_adapter_system import GovernedGraphitiProposalAdapter
from newsroom.graphiti_adapter import GraphitiAdapterConfigurationId

from .extraction_4a_helpers import extraction_authenticator, extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    GRAPHITI_SCOPES,
    approval_from_authority,
    fake_attempt,
    graphiti_authorizer,
    graphiti_read_policy,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)
from .source_3a_helpers import SOURCE_NOW


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_public_graphiti_facade_exposes_only_typed_proposal_adapter_operations() -> None:
    public = {
        name
        for name, value in inspect.getmembers(
            GovernedGraphitiProposalAdapter, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert public == {
        "approve_replay",
        "attempt",
        "attempt_history",
        "configuration",
        "execute_attempt",
        "register_configuration",
        "replay_source",
    }
    forbidden = {
        "connection",
        "credentials",
        "cypher",
        "graph",
        "model",
        "publish",
        "raw_output",
        "run_cypher",
        "session",
        "write_entity",
        "write_relation",
    }
    assert not public & forbidden
    assert not hasattr(GovernedGraphitiProposalAdapter, "connection")
    assert not hasattr(GovernedGraphitiProposalAdapter, "store")


def test_graphiti_adapter_boundary_has_no_real_provider_network_or_graph_runtime_imports() -> None:
    files = sorted((_REPOSITORY_ROOT / "newsroom/graphiti_adapter").glob("*.py"))
    files += sorted(
        (_REPOSITORY_ROOT / "newsroom/authority").glob("*graphiti_adapter*.py")
    )
    forbidden_roots = {
        "anthropic",
        "cohere",
        "graphiti_core",
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


def test_graphiti_read_boundary_rejects_forged_authorization_provenance(
    tmp_path,
) -> None:
    delegate = graphiti_authorizer()

    class ForgedAuthorizer:
        def authorize(self, context, request, *, now):
            decision = delegate.authorize(context, request, now=now)
            return dataclasses.replace(
                decision,
                authorization_request_digest="sha256:" + "0" * 64,
            )

    boundary = _GraphitiAdapterBoundary(
        store=None,  # type: ignore[arg-type]
        command_service=None,  # type: ignore[arg-type]
        authenticator=extraction_authenticator(),
        authorizer=ForgedAuthorizer(),
        read_policy=graphiti_read_policy(),
        workspace_root=tmp_path.resolve(),
        clock=lambda: SOURCE_NOW,
    )
    with pytest.raises(PermissionError, match="authorization provenance differs"):
        boundary.configuration(
            GraphitiAdapterConfigurationId.parse(
                "00000000-0000-4000-8000-000000004901"
            ),
            extraction_proof(),
        )


def test_configuration_attempt_and_replay_read_scopes_are_independent(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        configuration = system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        attempt = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )
    approval_request = approval_from_authority(state, attempt)
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        approval = system.graphiti.approve_replay(
            approval_request, proof=extraction_proof()
        )

    with open_graphiti_system(
        state,
        workspace_root=workspace_root,
        scopes=frozenset({"authority.graphiti.read_configuration"}),
    ) as configuration_only:
        assert configuration_only.graphiti.configuration(
            configuration.configuration.configuration_id,
            proof=extraction_proof(),
        ) == configuration
        with pytest.raises(PermissionError):
            configuration_only.graphiti.attempt(
                attempt.attempt_id, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            configuration_only.graphiti.replay_source(
                approval.source.replay_source_id, proof=extraction_proof()
            )

    with open_graphiti_system(
        state,
        workspace_root=workspace_root,
        scopes=frozenset({"authority.graphiti.read_attempts"}),
    ) as attempt_only:
        assert attempt_only.graphiti.attempt(
            attempt.attempt_id, proof=extraction_proof()
        ) == attempt
        assert attempt_only.graphiti.attempt_history(
            attempt.run_id, limit=10, proof=extraction_proof()
        ) == (attempt,)
        with pytest.raises(PermissionError):
            attempt_only.graphiti.configuration(
                configuration.configuration.configuration_id,
                proof=extraction_proof(),
            )
        with pytest.raises(PermissionError):
            attempt_only.graphiti.replay_source(
                approval.source.replay_source_id, proof=extraction_proof()
            )

    with open_graphiti_system(
        state,
        workspace_root=workspace_root,
        scopes=frozenset({"authority.graphiti.read_replay"}),
    ) as replay_only:
        assert replay_only.graphiti.replay_source(
            approval.source.replay_source_id, proof=extraction_proof()
        ) == approval
        with pytest.raises(PermissionError):
            replay_only.graphiti.configuration(
                configuration.configuration.configuration_id,
                proof=extraction_proof(),
            )
        with pytest.raises(PermissionError):
            replay_only.graphiti.attempt(
                attempt.attempt_id, proof=extraction_proof()
            )


def test_safe_adapter_representations_exclude_governed_source_expression(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )
    rendered = "\n".join((repr(request), repr(retained)))
    for passage in state.input_binding.passages:
        assert passage.require_text() not in rendered
    assert "private_node_id" not in rendered
    assert "private_relation_id" not in rendered
