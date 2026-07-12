from __future__ import annotations

from copy import deepcopy

import pytest

from newsroom.editorial.decisions import (
    DecisionEvaluationError,
    evaluate_candidate,
)
from newsroom.editorial.packages import (
    build_candidate_package,
    build_evidence_package,
)
from newsroom.editorial.policy import load_shadow_policy, validate_policy


def evidence_value() -> dict[str, object]:
    return {
        "schema_version": "evidence_package_v1",
        "encoding_version": "rfc8785-restricted-v1",
        "digest_algorithm": "sha256",
        "provenance": {
            "run_id": "run-1",
            "story_id": "story_01",
            "source_refs": [
                {
                    "source_id": "official",
                    "source_digest": "sha256:" + "1" * 64,
                    "rights_status": "PERMITTED",
                }
            ],
        },
        "claims": [{"claim_id": "claim-1", "evidence_refs": ["official"]}],
        "component_versions": {"extractor": "shadow-fixture-v1"},
    }


def candidate_value(
    evidence_digest: str,
    *,
    gates: dict[str, str] | None = None,
    validators: dict[str, str] | None = None,
    target: str = "shadow-recording",
    stable_story_id: str = "event:42",
) -> dict[str, object]:
    return {
        "schema_version": "editorial_candidate_v1",
        "encoding_version": "rfc8785-restricted-v1",
        "digest_algorithm": "sha256",
        "candidate_id": "run-1:story_01",
        "stable_story_id": stable_story_id,
        "story_version": "v1",
        "evidence_digest": evidence_digest,
        "content_digest": "sha256:" + "2" * 64,
        "asset_digests": [],
        "gate_results": gates
        or {
            "claim_evidence": "PASS",
            "rights": "PASS",
            "sensitive_risk": "PASS",
            "jurisdiction": "PASS",
        },
        "policy_version": "editorial-shadow-v1",
        "controller_version": "shadow-controller-v1",
        "validator_results": validators or {"article_contract": "PASS"},
        "target": target,
        "provenance": {"run_id": "run-1", "story_id": "story_01"},
    }


def publication_content() -> dict[str, object]:
    return {
        "headline": "英國公共服務安排更新",
        "body": "呢份係純合成測試內容，唔包含第三方新聞原文。",
        "geographies": ["UK"],
        "categories": ["UK News"],
        "source_refs": ["official"],
        "publisher_id": "newsroom-shadow",
        "content_language": "zh-HK",
        "status": "READY",
    }


def evaluate(
    *,
    gates: dict[str, str] | None = None,
    validators: dict[str, str] | None = None,
    target: str = "shadow-recording",
    stable_story_id: str = "event:42",
    compatibility_reasons: tuple[str, ...] = (),
):  # type: ignore[no-untyped-def]
    evidence = build_evidence_package(evidence_value())
    candidate = build_candidate_package(
        candidate_value(
            evidence.digest,
            gates=gates,
            validators=validators,
            target=target,
            stable_story_id=stable_story_id,
        )
    )
    return evaluate_candidate(
        candidate=candidate,
        evidence=evidence,
        policy=load_shadow_policy(),
        publication_content=publication_content(),
        compatibility_reason_codes=compatibility_reasons,
    )


def test_complete_candidate_is_auto_publish_but_not_requested_for_delivery() -> None:
    result = evaluate()

    assert result.outcome == "AUTO_PUBLISH"
    assert result.reason_codes == ()
    assert result.publication_package is not None
    assert result.delivery_state == "NOT_REQUESTED"
    assert result.publication_package.value["decision_digest"] == result.decision.digest


def test_legacy_missing_structures_hold_in_policy_reason_order() -> None:
    result = evaluate(
        gates={
            "claim_evidence": "MISSING",
            "rights": "MISSING",
            "sensitive_risk": "MISSING",
            "jurisdiction": "MISSING",
        },
        validators={"article_contract": "MISSING"},
    )

    assert result.outcome == "HOLD_FOR_REVIEW"
    assert result.reason_codes == (
        "MISSING_CLAIM_EVIDENCE",
        "MISSING_RIGHTS",
        "MISSING_SENSITIVE_RISK",
        "MISSING_JURISDICTION",
        "MISSING_ARTICLE_CONTRACT",
    )
    assert result.publication_package is None


def test_known_prohibition_rejects_while_retaining_hold_reasons() -> None:
    result = evaluate(
        gates={
            "claim_evidence": "REJECT",
            "rights": "MISSING",
            "sensitive_risk": "PASS",
            "jurisdiction": "UNKNOWN",
        }
    )

    assert result.outcome == "REJECT"
    assert result.reason_codes == (
        "EVIDENCE_SUBSTANTIVELY_INSUFFICIENT",
        "MISSING_RIGHTS",
        "UNKNOWN_JURISDICTION",
    )
    assert result.publication_package is None


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    [
        ({"target": "discord"}, "UNKNOWN_TARGET"),
        ({"gates": {"claim_evidence": "PASS", "rights": "PASS", "sensitive_risk": "PASS", "jurisdiction": "PASS", "new_gate": "PASS"}}, "UNKNOWN_POLICY_INPUT"),
        ({"gates": {"claim_evidence": "PASS", "rights": "PASS", "sensitive_risk": "PASS", "jurisdiction": "INDETERMINATE"}}, "INDETERMINATE_JURISDICTION"),
    ],
)
def test_unknown_or_indeterminate_policy_input_never_becomes_eligible(
    changes: dict[str, object], expected_reason: str
) -> None:
    result = evaluate(**changes)  # type: ignore[arg-type]
    assert result.outcome == "HOLD_FOR_REVIEW"
    assert expected_reason in result.reason_codes
    assert result.publication_package is None


def test_compatibility_identity_forces_hold() -> None:
    result = evaluate(
        stable_story_id="compat-occurrence:abc",
        compatibility_reasons=("MIGRATION_MISSING_STABLE_STORY_ID",),
    )
    assert result.outcome == "HOLD_FOR_REVIEW"
    assert result.reason_codes == ("MIGRATION_MISSING_STABLE_STORY_ID",)


def test_decision_identity_is_deterministic_and_binds_policy_version() -> None:
    first = evaluate()
    second = evaluate()
    assert first.decision.digest == second.decision.digest

    raw = deepcopy(load_shadow_policy().raw)
    raw["policy_id"] = "editorial-shadow-v2"
    raw["component_versions"]["policy"] = "editorial-shadow-v2"
    candidate_evidence = build_evidence_package(evidence_value())
    value = candidate_value(candidate_evidence.digest)
    value["policy_version"] = "editorial-shadow-v2"
    candidate = build_candidate_package(value)
    changed = evaluate_candidate(
        candidate=candidate,
        evidence=candidate_evidence,
        policy=validate_policy(raw),
        publication_content=publication_content(),
    )
    assert first.decision.digest != changed.decision.digest


def test_evidence_reference_mismatch_is_an_admission_error() -> None:
    evidence = build_evidence_package(evidence_value())
    candidate = build_candidate_package(candidate_value("sha256:" + "f" * 64))
    with pytest.raises(DecisionEvaluationError, match="evidence"):
        evaluate_candidate(
            candidate=candidate,
            evidence=evidence,
            policy=load_shadow_policy(),
            publication_content=publication_content(),
        )
