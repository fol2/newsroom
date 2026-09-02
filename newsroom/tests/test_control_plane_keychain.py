"""Host Keychain probes. Skip on CI hosts without the classes. Never print secrets."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Literal

import pytest

from newsroom.control_plane.broker import (
    NEO4J_KEYCHAIN_SKIP,
    NEO4J_PROJECTOR_ACCOUNT,
    NEO4J_PROJECTOR_SERVICE,
    NEO4J_PROJECTOR_USERNAME,
    OPENROUTER_KEYCHAIN_SKIP,
    BrokerError,
    neo4j_community_password,
    neo4j_keychain_ready,
    neo4j_projector_config,
    neo4j_projector_keychain_ready,
    neo4j_projector_password,
    openrouter_api_key,
    openrouter_keychain_ready,
    prove_neo4j_keychain,
    prove_openrouter_keychain,
)
from newsroom.control_plane.writer import (
    cursor_agent_cli_ready,
    grok_cli_ready,
    prove_cursor_agent_cli,
    prove_grok_cli,
)


@pytest.mark.parametrize("file_descriptor", [1, 2], ids=["stdout", "stderr"])
def test_non_utf8_keychain_output_is_a_secret_safe_broker_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_descriptor: Literal[1, 2],
) -> None:
    security = tmp_path / "security"
    security.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        f"os.write({file_descriptor}, b'\\xffprivate-output')\n",
        encoding="utf-8",
    )
    security.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    with pytest.raises(
        BrokerError, match=r"^Keychain class OPENROUTER_API lookup failed$"
    ) as raised:
        openrouter_api_key()

    message = str(raised.value)
    assert "private-output" not in message


def test_projector_credential_is_separate_and_builds_non_admin_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def password(*, account: str, service: str) -> str:
        calls.append((account, service))
        return "projector-password-long-enough"

    monkeypatch.setattr("newsroom.control_plane.broker._keychain_password", password)

    assert neo4j_projector_password() == "projector-password-long-enough"
    config = neo4j_projector_config()
    assert config.username == NEO4J_PROJECTOR_USERNAME == "newsroom_projector"
    assert config.database == "neo4j"
    assert config.uri == "bolt://127.0.0.1:7687"
    assert calls == [
        (NEO4J_PROJECTOR_ACCOUNT, NEO4J_PROJECTOR_SERVICE),
        (NEO4J_PROJECTOR_ACCOUNT, NEO4J_PROJECTOR_SERVICE),
    ]


def test_projector_readiness_uses_its_dedicated_keychain_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def present(*, account: str, service: str) -> bool:
        calls.append((account, service))
        return True

    monkeypatch.setattr("newsroom.control_plane.broker.keychain_present", present)

    assert neo4j_projector_keychain_ready() is True
    assert calls == [(NEO4J_PROJECTOR_ACCOUNT, NEO4J_PROJECTOR_SERVICE)]


@pytest.mark.skipif(not grok_cli_ready(), reason="Grok Build CLI not on this host")
def test_grok_build_cli_is_logged_in() -> None:
    prove_grok_cli()


@pytest.mark.skipif(not cursor_agent_cli_ready(), reason="cursor-agent CLI not on this host")
def test_cursor_agent_cli_is_logged_in() -> None:
    prove_cursor_agent_cli()


@pytest.mark.skipif(not openrouter_keychain_ready(), reason=OPENROUTER_KEYCHAIN_SKIP)
def test_openrouter_keychain_injects_and_is_accepted() -> None:
    prove_openrouter_keychain()


@pytest.mark.skipif(not neo4j_keychain_ready(), reason=NEO4J_KEYCHAIN_SKIP)
def test_neo4j_keychain_injects_and_bolt_accepts() -> None:
    from neo4j import GraphDatabase

    prove_neo4j_keychain(driver_factory=GraphDatabase.driver)


@pytest.mark.skipif(not neo4j_keychain_ready(), reason=NEO4J_KEYCHAIN_SKIP)
def test_graphiti_mutation_guard_restores_preexisting_values() -> None:
    graphiti_driver = pytest.importorskip("graphiti_core.driver.neo4j_driver")
    from newsroom.graphiti_adapter.neo4j_guard import Neo4jMutationGuard

    async def exercise() -> None:
        suffix = str(uuid.uuid4())
        group_id = f"newsroom-guard-service-{suffix}"
        episode_uuid = str(uuid.uuid4())
        driver = graphiti_driver.Neo4jDriver(
            "bolt://127.0.0.1:7687",
            "neo4j",
            neo4j_community_password(),
        )

        async def query(cypher: str, **parameters: object) -> object:
            return await driver.execute_query(
                cypher, params=parameters, routing_="w"
            )

        try:
            await query(
                """
                CREATE (a:Entity {uuid:$a, group_id:$group_id, name:'before'}),
                       (b:Entity {uuid:$b, group_id:$group_id, name:'other'}),
                       (a)-[:REL {uuid:$relationship, fact:'before'}]->(b)
                """,
                a=f"a-{suffix}",
                b=f"b-{suffix}",
                relationship=f"relationship-{suffix}",
                group_id=group_id,
            )
            guard = Neo4jMutationGuard(
                driver,
                group_id=group_id,
                episode_uuid=episode_uuid,
                attempt_number=1,
                input_digest="sha256:" + "1" * 64,
            )
            assert (await guard.begin()).state.value == "CREATED"
            await query(
                """
                MATCH (a {uuid:$a})-[r]->()
                SET a.name='after', r.fact='after'
                CREATE (:Entity {uuid:$new, group_id:$group_id, name:'new'})
                """,
                a=f"a-{suffix}",
                new=f"new-{suffix}",
                group_id=group_id,
            )
            await guard.rollback_pending(
                chat_invocations=[],
                embedding_usage={
                    "usage_basis": "NO_EMBEDDING_CALL",
                    "request_count": 0,
                },
                reason="SERVICE_TEST",
            )
            result = await query(
                """
                MATCH (n {group_id:$group_id})
                WHERE n.uuid IS NOT NULL
                OPTIONAL MATCH (n)-[r]->()
                RETURN collect(DISTINCT [n.uuid,n.name]) AS nodes,
                       collect(DISTINCT [r.uuid,r.fact]) AS relationships
                """,
                group_id=group_id,
            )
            record = result.records[0]
            assert sorted(record["nodes"]) == sorted(
                [[f"a-{suffix}", "before"], [f"b-{suffix}", "other"]]
            )
            assert [
                item for item in record["relationships"] if item[0] is not None
            ] == [[f"relationship-{suffix}", "before"]]
        finally:
            await query(
                """
                MATCH (n)
                WHERE n.group_id=$group_id OR n.episode_uuid=$episode_uuid
                DETACH DELETE n
                """,
                group_id=group_id,
                episode_uuid=episode_uuid,
            )
            await driver.close()

    asyncio.run(exercise())
    neo4j_community_password,
