from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    replace_exact(
        "scripts/sdlc/classify_change.py",
        '''            for path in (repo_root / "newsroom" / "tests").glob(
                "test_projection_*_neo4j_service.py"
            )''',
        '''            for path in (repo_root / "newsroom" / "tests").glob(
                "test_*_neo4j_service.py"
            )''',
    )
    replace_exact(
        "scripts/sdlc/workflow_lane.py",
        '''_OPTIONAL_CORE_TEST_IDS = (
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",''',
        '''_OPTIONAL_CORE_TEST_IDS = (
    "newsroom.tests.test_integrated_c1_neo4j_service::test_actual_service_integrated_foundation_replay_recovery_and_tombstone",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",''',
    )
    replace_exact(
        "scripts/sdlc/workflow_lane.py",
        '''            for path in (repo_root / "newsroom" / "tests").glob(
                "test_projection_*_neo4j_service.py"
            )''',
        '''            for path in (repo_root / "newsroom" / "tests").glob(
                "test_*_neo4j_service.py"
            )''',
    )
    replace_exact(
        ".sdlc/gates.toml",
        '''contract_control = [
  ".sdlc/**",
  "docs/specs/sdlc/**",
  "docs/plans/*sdlc*",
  ".github/workflows/**",
  "scripts/sdlc/**",
  "newsroom/tests/test_sdlc_*.py",
]''',
        '''contract_control = [
  ".sdlc/**",
  "docs/specs/sdlc/**",
  "docs/plans/*sdlc*",
  ".github/workflows/**",
  "scripts/sdlc/**",
  "newsroom/tests/test_sdlc_*.py",
  "newsroom/tests/test_integrated_c1_sdlc_contract.py",
  "newsroom/tests/test_integrated_c1_workflow_contract.py",
]''',
    )
    replace_exact(
        ".sdlc/gates.toml",
        '''stateful_contract = [
  "newsroom/authority/**",
  "newsroom/projection/models.py",''',
        '''stateful_contract = [
  "newsroom/authority/**",
  "newsroom/integrated/**",
  "newsroom/projection/models.py",''',
    )
    replace_exact(
        ".sdlc/gates.toml",
        '''  "newsroom/authority/_neo4j_projection_system.py",
  "newsroom/authority/neo4j_projection_system.py",
  "newsroom/authority/_projection_store.py",''',
        '''  "newsroom/authority/_neo4j_projection_system.py",
  "newsroom/authority/neo4j_projection_system.py",
  "newsroom/authority/_integrated_system.py",
  "newsroom/authority/integrated_system.py",
  "newsroom/integrated/proof.py",
  "newsroom/authority/_projection_store.py",''',
    )
    replace_exact(
        ".sdlc/gates.toml",
        '''  "newsroom/tests/test_projection_b1_*.py",
  "newsroom/tests/test_projection_b2_*.py",''',
        '''  "newsroom/tests/test_integrated_c1_neo4j_service.py",
  "newsroom/tests/test_projection_b1_*.py",
  "newsroom/tests/test_projection_b2_*.py",''',
    )
    replace_exact(
        "newsroom/tests/test_sdlc_classifier.py",
        '''    paths = (
        "scripts/sdlc/classify_change.py",
        "newsroom/tests/test_sdlc_classifier.py",
        "newsroom/projection/policy.py",
        ".github/workflows/evidence.yml",
    )''',
        '''    paths = (
        "scripts/sdlc/classify_change.py",
        "newsroom/tests/test_sdlc_classifier.py",
        "newsroom/projection/policy.py",
        "newsroom/authority/_integrated_system.py",
        "newsroom/authority/integrated_system.py",
        "newsroom/integrated/proof.py",
        "newsroom/tests/test_integrated_c1_neo4j_service.py",
        ".github/workflows/evidence.yml",
    )''',
    )
    replace_exact(
        "newsroom/tests/test_sdlc_classifier.py",
        '''        assert route["service_tests"] == [
            "newsroom/tests/test_projection_b2_neo4j_service.py",
            "newsroom/tests/test_projection_b3_neo4j_service.py",
        ]''',
        '''        assert route["service_tests"] == [
            "newsroom/tests/test_integrated_c1_neo4j_service.py",
            "newsroom/tests/test_projection_b2_neo4j_service.py",
            "newsroom/tests/test_projection_b3_neo4j_service.py",
        ]''',
    )
    replace_exact(
        "newsroom/tests/test_sdlc_workflow_lane.py",
        '''        "service_tests": (
            ["newsroom/tests/test_projection_b2_neo4j_service.py"] if service else []
        ),''',
        '''        "service_tests": (
            [
                "newsroom/tests/test_integrated_c1_neo4j_service.py",
                "newsroom/tests/test_projection_b2_neo4j_service.py",
                "newsroom/tests/test_projection_b3_neo4j_service.py",
            ]
            if service
            else []
        ),''',
    )
    replace_exact(
        "newsroom/tests/test_sdlc_workflow_lane.py",
        '''    expected = (
        "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",''',
        '''    expected = (
        "newsroom.tests.test_integrated_c1_neo4j_service::test_actual_service_integrated_foundation_replay_recovery_and_tombstone",
        "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",''',
    )


if __name__ == "__main__":
    main()
