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
        "newsroom/tests/test_integrated_c1_sdlc_contract.py",
        '''def test_increment_1c_contract_models_are_stateful_even_without_service_execution() -> None:
    for path in (
        "newsroom/integrated/models.py",
        "newsroom/integrated/policy.py",
        "newsroom/integrated/traceability.py",
    ):
        route = _route(path)
        assert route["risk_tier"] == "R2_STATEFUL_CONTRACT"
        assert route["core_required"] is True''',
        '''def test_increment_1c_contract_models_are_stateful_and_service_qualified() -> None:
    for path in (
        "newsroom/integrated/models.py",
        "newsroom/integrated/policy.py",
        "newsroom/integrated/traceability.py",
    ):
        route = _route(path)
        assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
        assert route["core_required"] is True
        assert route["service_required"] is True
        assert (
            f"path:{path}:stateful_contract:R2_STATEFUL_CONTRACT"
            in route["reasons"]
        )''',
    )
    replace_exact(
        "newsroom/tests/test_sdlc_workflow_lane.py",
        '''    service_tests = ("newsroom/tests/test_projection_b2_neo4j_service.py",)''',
        '''    service_tests = (
        "newsroom/tests/test_integrated_c1_neo4j_service.py",
        "newsroom/tests/test_projection_b2_neo4j_service.py",
        "newsroom/tests/test_projection_b3_neo4j_service.py",
    )''',
    )


if __name__ == "__main__":
    main()
