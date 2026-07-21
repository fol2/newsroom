from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import newsroom.projection as projection
from newsroom.authority import AggregateId, InlinePayload, SemanticCommand
from newsroom.projection import (
    GraphitiProposalWorkspaceContract,
    GraphitiWorkspaceMode,
    ProjectionAuthorizationError,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationId,
)

from .projection_b1_helpers import FAMILY_ID, open_projection_system, proof


def test_graphiti_contract_is_proposal_only_and_non_executable() -> None:
    fields = set(GraphitiProposalWorkspaceContract.__dataclass_fields__)
    assert fields == {
        "workspace_id",
        "contract_version",
        "implementation_version",
        "endpoint_reference",
        "secret_reference",
        "mode",
    }
    contract = GraphitiProposalWorkspaceContract(
        workspace_id="graphiti.proposals",
        contract_version="workspace-v1",
        implementation_version="seam-v1",
        endpoint_reference="config://graphiti/proposal-endpoint",
        secret_reference="secret://graphiti/proposal-token",
    )
    assert contract.mode is GraphitiWorkspaceMode.PROPOSAL_ONLY
    assert not any(
        name in dir(contract)
        for name in ("execute", "write", "query", "run", "run_cypher")
    )


def test_projection_package_has_no_neo4j_graphiti_or_generic_write_imports() -> None:
    root = Path(projection.__file__).parent
    forbidden_modules = {"neo4j", "graphiti", "graphiti_core"}
    forbidden_symbols = {"run_cypher", "execute_cypher", "write_graph"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {
                    alias.name.split(".")[0] for alias in node.names
                } & forbidden_modules
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_modules
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in forbidden_symbols


def test_public_facade_exposes_no_store_or_general_graph_write_api(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        assert not hasattr(system, "store")
        assert not hasattr(system.projections, "store")
        public = {
            name
            for name, _ in inspect.getmembers(
                system.projections, predicate=callable
            )
            if not name.startswith("_")
        }
        assert public == {
            "register_family",
            "create_generation",
            "transition_generation",
            "record_delivery",
            "resolve_gap",
            "status",
            "generations",
            "gaps",
            "dead_letters",
        }
        assert "run_cypher" not in public
        assert "write_graph" not in public
    finally:
        system.close()


def test_generic_command_facade_cannot_submit_projection_internal_command(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        with pytest.raises(PermissionError, match="internal authority"):
            system.commands.execute(
                SemanticCommand(
                    command_type="projection.family.register",
                    aggregate_id=AggregateId.new(),
                    expected_aggregate_version=0,
                    payload=InlinePayload(
                        {
                            "family_id": FAMILY_ID,
                            "definition_digest": "sha256:" + "0" * 64,
                        }
                    ),
                    idempotency_key="direct-projection-command",
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_projection_reads_are_currently_authenticated_and_policy_bounded(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        system.projections.register_family(
            ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
            proof=proof(),
        )
        with pytest.raises(Exception):
            system.projections.status(
                FAMILY_ID,
                proof=type(proof())(
                    method="STATIC_TOKEN",
                    credential="wrong-token",
                ),
            )
    finally:
        system.close()


def test_b1_traceability_and_exclusions_are_explicit() -> None:
    from newsroom.projection import (
        INCREMENT_1B1_DEFERRED,
        INCREMENT_1B1_EXCLUSIONS,
        INCREMENT_1B1_TRACEABILITY,
    )

    required_modules = {
        "newsroom.authority.projection_migrations",
        "newsroom.projection.ontology",
        "newsroom.projection.mapping",
        "newsroom.projection.policy",
        "newsroom.authority._projection_store",
        "newsroom.authority.projection_system",
        "newsroom.tests.test_projection_b1_contracts",
        "newsroom.tests.test_projection_b1_authority",
        "newsroom.tests.test_projection_b1_migrations",
        "newsroom.tests.test_projection_b1_boundaries",
    }
    assert required_modules <= set(INCREMENT_1B1_TRACEABILITY)
    assert "NEO4J_CLIENT_OR_SERVICE" in INCREMENT_1B1_EXCLUSIONS
    assert "GRAPHITI_EXECUTION" in INCREMENT_1B1_EXCLUSIONS
    assert "NEO4J_IMAGE_AND_RELEASE_QUALIFICATION" in INCREMENT_1B1_DEFERRED
    assert all(INCREMENT_1B1_TRACEABILITY.values())


def test_projection_public_facades_are_import_order_independent() -> None:
    import importlib
    import sys

    for name in (
        "newsroom.projection.system",
        "newsroom.projection",
        "newsroom.authority.projection_system",
        "newsroom.authority._projection_system",
        "newsroom.authority._projection_store",
    ):
        sys.modules.pop(name, None)
    authority_facade = importlib.import_module("newsroom.authority.projection_system")
    projection_package = importlib.import_module("newsroom.projection")
    assert (
        projection_package.NativeProjectionAuthoritySystem
        is authority_facade.NativeProjectionAuthoritySystem
    )



def test_projection_reads_authenticate_before_unknown_family_or_generation_lookup(
    tmp_path: Path,
) -> None:
    class RejectingAuthenticator:
        def authenticate(self, _proof: object, *, now: object) -> object:
            raise RuntimeError("AUTHENTICATION_FIRST")

    system = open_projection_system(
        tmp_path / "authority.sqlite3",
        authenticator=RejectingAuthenticator(),
    )
    try:
        with pytest.raises(RuntimeError, match="AUTHENTICATION_FIRST"):
            system.projections.status("unknown.family", proof=proof())
        with pytest.raises(RuntimeError, match="AUTHENTICATION_FIRST"):
            system.projections.gaps(
                ProjectionGenerationId.new(), proof=proof()
            )
    finally:
        system.close()
