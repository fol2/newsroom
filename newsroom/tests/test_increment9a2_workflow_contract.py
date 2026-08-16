from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/increment9-shadow-readiness.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_pins_exact_runtime_and_increment9_database() -> None:
    text = _text()
    required = (
        "name: Increment 9A2 Neo4j 5.26.2 readiness",
        "NEO4J_INCREMENT9_IMAGE: neo4j:5.26.2",
        "NEO4J_INCREMENT9_IMAGE_DIGEST: neo4j@sha256:099b9f74968c123209972835417985ed2a1cc19c0422c0753a313e26a736c365",
        'NEO4J_initial_dbms_default__database=increment9',
        'database="increment9"',
        'server_version"] == "5.26.2"',
        "neo4j@sha256:099b9f74968c123209972835417985ed2a1cc19c0422c0753a313e26a736c365",
        'assert neo4j.__version__ == "6.2.0"',
    )
    for statement in required:
        assert statement in text


def test_workflow_uses_ephemeral_masked_credentials_and_loopback_only() -> None:
    text = _text()
    required = (
        "::add-mask::${password}",
        "chmod 600",
        "--publish 127.0.0.1:7687:7687",
        "bolt://localhost:7687",
        'rm -f "${credential_file}"',
        "test ! -e \"${RUNNER_TEMP}/increment9-neo4j.env\"",
        'NEWSROOM_INCREMENT9_EVIDENCE_DIR: ${{ runner.temp }}/increment9-protected-evidence',
        'install -d -m 0700 "${NEWSROOM_INCREMENT9_EVIDENCE_DIR}"',
        'stat -c \'%a\' "${NEWSROOM_INCREMENT9_EVIDENCE_DIR}"',
    )
    for statement in required:
        assert statement in text
    assert "GITHUB_ENV" not in text
    assert "${{ secrets." not in text


def test_workflow_executes_repository_probe_when_9a2_is_present() -> None:
    text = _text()
    assert "if test -f scripts/increment9_shadow_deployment.py" in text
    assert "uv run python scripts/increment9_shadow_deployment.py" in text
    assert "neo4j --output" in text
    assert text.index("if test -f scripts/increment9_shadow_deployment.py") < text.index(
        "Infrastructure bootstrap for #512 only"
    )


def test_workflow_proves_actual_indexes_round_trip_and_zero_orphans() -> None:
    text = _text()
    required = (
        "CREATE FULLTEXT INDEX",
        "CREATE VECTOR INDEX",
        "`vector.dimensions`: 1024",
        "`vector.similarity_function`: 'cosine'",
        "CALL db.awaitIndexes(30)",
        'remaining_probe_nodes"] == 0',
        "MATCH (n:Increment9ReadinessProbe) RETURN count(n) AS count",
        "WHERE name STARTS WITH 'i9_'",
        "assert names == []",
        "docker rm --force --volumes increment9-neo4j-readiness",
    )
    for statement in required:
        assert statement in text


def test_workflow_retains_canonical_secret_free_component_evidence() -> None:
    text = _text()
    required = (
        "secret_value_count",
        "od003_macm4_arm64_host_proved=False",
        "ACTUAL_X86_SERVICE_COMPONENT_PROOF_ONLY",
        "increment9-neo4j-5262-readiness-",
        "if-no-files-found: error",
        "retention-days: 30",
        "if: success() && steps.probe.outcome == 'success'",
        "sort_keys=True",
        "not in raw.decode()",
        "Purge protected readiness workspace",
        'rmdir "${NEWSROOM_INCREMENT9_EVIDENCE_DIR}"',
    )
    for statement in required:
        assert statement in text


def test_workflow_has_no_campaign_provider_publication_or_production_route() -> None:
    text = _text().casefold()
    prohibited = (
        "openai",
        "anthropic",
        "gemini",
        "grok",
        "source portfolio",
        "evidence intake",
        "publication adapter",
        "canary activation",
        "production activation",
    )
    for statement in prohibited:
        assert statement not in text
