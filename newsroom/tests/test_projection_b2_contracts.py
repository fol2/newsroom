from __future__ import annotations

import inspect

import pytest

from newsroom.projection import ProjectionRelationType
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
    Neo4jConfigurationError,
    Neo4jProjectorConfig,
)


def test_exact_neo4j_and_driver_targets_are_pinned() -> None:
    assert NEO4J_B2_IMAGE == "neo4j:2026.06.0-community-trixie"
    assert NEO4J_B2_SERVER_VERSION == "2026.06.0"
    assert NEO4J_B2_DRIVER_VERSION == "6.2.0"
    assert "latest" not in NEO4J_B2_IMAGE


def test_projector_config_is_explicit_authenticated_and_redacted() -> None:
    config = Neo4jProjectorConfig(
        uri="bolt://localhost:7687",
        database="neo4j",
        username="newsroom_projector",
        password="sensitive-password",
    )
    representation = repr(config)
    assert "sensitive-password" not in representation
    assert "<redacted>" in representation
    assert config.password == "sensitive-password"

    with pytest.raises(Neo4jConfigurationError, match="embedded"):
        Neo4jProjectorConfig(
            uri="bolt://user:secret@localhost:7687",
            database="neo4j",
            username="projector",
            password="secret",
        )
    with pytest.raises(Neo4jConfigurationError, match="disabled"):
        Neo4jProjectorConfig(
            uri="bolt://localhost:7687",
            database="neo4j",
            username="projector",
            password="none",
        )
    for unsafe_uri in (
        "bolt://localhost:7687/neo4j",
        "bolt://localhost:7687?token=secret",
        "bolt://localhost:7687#secret",
        "bolt://localhost:not-a-port",
    ):
        with pytest.raises(Neo4jConfigurationError):
            Neo4jProjectorConfig(
                uri=unsafe_uri,
                database="neo4j",
                username="projector",
                password="secret",
            )


def test_environment_config_has_no_unauthenticated_fallback() -> None:
    with pytest.raises(Neo4jConfigurationError, match="incomplete"):
        Neo4jProjectorConfig.from_environment({})
    config = Neo4jProjectorConfig.from_environment(
        {
            "NEWSROOM_NEO4J_URI": "bolt://neo4j:7687",
            "NEWSROOM_NEO4J_DATABASE": "neo4j",
            "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "projector",
            "NEWSROOM_NEO4J_PROJECTOR_PASSWORD": "secret",
        }
    )
    assert config.username == "projector"


def test_relation_contract_is_exact_and_has_no_generic_predicate() -> None:
    assert {item.value for item in ProjectionRelationType} == {
        "HAS_VERSION",
        "HAS_REVISION",
        "HAS_REPRESENTATION",
        "PRODUCED_SIGNAL",
        "PROMOTED_TO_LEAD",
        "DERIVED_FROM",
        "CONTAINS_PAYLOAD",
        "PROJECTED_FROM_EVENT",
    }
    assert "RELATED_TO" not in {item.value for item in ProjectionRelationType}


def test_public_models_expose_no_driver_or_cypher_parameter() -> None:
    from newsroom.projection import neo4j as public

    public_names = set(public.__all__)
    assert "_Neo4jAdapter" not in public_names
    assert "GraphDatabase" not in public_names
    for name in public_names:
        value = getattr(public, name)
        if inspect.isclass(value) and not issubclass(value, BaseException):
            parameters = set(inspect.signature(value).parameters)
            assert not {"cypher", "query", "driver", "session"} & parameters
