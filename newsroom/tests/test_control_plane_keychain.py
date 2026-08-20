"""Host Keychain probes. Skip on CI hosts without the classes. Never print secrets."""

from __future__ import annotations

import pytest

from newsroom.control_plane.broker import (
    NEO4J_KEYCHAIN_SKIP,
    OPENROUTER_KEYCHAIN_SKIP,
    neo4j_keychain_ready,
    openrouter_keychain_ready,
    prove_neo4j_keychain,
    prove_openrouter_keychain,
)


@pytest.mark.skipif(not openrouter_keychain_ready(), reason=OPENROUTER_KEYCHAIN_SKIP)
def test_openrouter_keychain_injects_and_is_accepted() -> None:
    prove_openrouter_keychain()


@pytest.mark.skipif(not neo4j_keychain_ready(), reason=NEO4J_KEYCHAIN_SKIP)
def test_neo4j_keychain_injects_and_bolt_accepts() -> None:
    prove_neo4j_keychain()
