from __future__ import annotations

from pathlib import Path

import newsroom.discovery_adapters as adapters
from newsroom.discovery_adapters import (
    INCREMENT_3B_DEFERRED,
    INCREMENT_3B_EXCLUSIONS,
    INCREMENT_3B_TRACEABILITY,
)


def test_increment_3b_traceability_is_complete_and_explicitly_bounded() -> None:
    assert len(INCREMENT_3B_TRACEABILITY) == 10
    assert all(key.startswith("3B-") for key in INCREMENT_3B_TRACEABILITY)
    assert all(values for values in INCREMENT_3B_TRACEABILITY.values())
    assert {
        "REAL_NETWORK_OR_SOCKET_ACCESS",
        "NAMED_LIVE_SOURCE_OR_CREDENTIAL",
        "CHECK_REQUEST_ATTEMPT_OR_OUTCOME_AUTHORITY_INCREMENT_3C",
        "SIGNAL_GATE_LEAD_OR_CANDIDATE_AUTHORITY_INCREMENT_3D",
        "NEO4J_DISCOVERY_LINEAGE_OR_HEALTH_INCREMENT_3E",
        "SHADOW_CANARY_PRODUCTION_PUBLICATION_SPENDING_OR_PUBLIC_EFFECT",
    } <= INCREMENT_3B_EXCLUSIONS
    assert {
        "AUTHORITATIVE_CHECK_AND_BASELINE_STATE_INCREMENT_3C",
        "SIGNAL_DETERMINISTIC_GATE_AND_LEAD_INCREMENT_3D",
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
    } <= INCREMENT_3B_DEFERRED


def test_public_package_exports_proposals_not_later_authority() -> None:
    assert adapters.run_fixture_adapter
    assert adapters.ObservationProposal
    for name in (
        "CheckRequest",
        "CheckAttempt",
        "CheckOutcome",
        "OperationalFinding",
        "DiscoverySignal",
        "NewsLead",
        "StoryCandidate",
        "ProjectionWriter",
    ):
        assert not hasattr(adapters, name)


def test_adapter_package_has_no_external_io_or_authority_writer_imports() -> None:
    package = Path(adapters.__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(package.glob("*.py"))
    )
    for forbidden in (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import aiohttp",
        "import socket",
        "from socket",
        "urllib.request",
        "selenium",
        "playwright",
        "CommandService",
        "SemanticCommand",
        "source_registry_system",
        "open_governed_source_registry_authority_system",
    ):
        assert forbidden not in source


def test_fixture_runner_retains_no_named_source_or_legacy_identity_path() -> None:
    package = Path(adapters.__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(package.glob("*.py"))
    ).lower()
    for forbidden in (
        "gdelt",
        "rss_pool",
        "news_pool",
        "legacy links",
        "legacy events",
        "cluster_id",
        "event_id =",
    ):
        assert forbidden not in source
    assert "fixture_replay_only" in source
    assert "authority_effect" in source


def test_traceability_references_durable_tests_and_operations() -> None:
    flattened = {
        reference
        for references in INCREMENT_3B_TRACEABILITY.values()
        for reference in references
    }
    assert "newsroom.tests.test_discovery_adapter_3b_contracts" in flattened
    assert "newsroom.tests.test_discovery_adapter_3b_security" in flattened
    assert "newsroom.tests.test_discovery_adapter_3b_parsers" in flattened
    assert "newsroom.tests.test_discovery_adapter_3b_runner" in flattened
    assert "newsroom.tests.test_discovery_adapter_3b_traceability" in flattened
    assert "docs.operations.increment-3b-fixture-adapters" in flattened
