from __future__ import annotations

import json

import pytest

from newsroom.editorial.packages import (
    PackageIntegrityError,
    PackageValidationError,
    build_candidate_package,
    build_decision_digest,
    build_evidence_package,
    build_publication_package,
    canonicalise_json,
    parse_json_bytes,
    verify_package_bytes,
)


def evidence_value() -> dict[str, object]:
    return {
        "schema_version": "evidence_package_v1",
        "encoding_version": "rfc8785-restricted-v1",
        "digest_algorithm": "sha256",
        "provenance": {
            "run_id": "discord-multi-2026-07-12-10-00",
            "story_id": "story_01",
            "source_refs": [
                {
                    "source_id": "official-notice",
                    "source_digest": "sha256:" + "1" * 64,
                    "rights_status": "PERMITTED_METADATA_ONLY",
                }
            ],
        },
        "claims": [
            {
                "claim_id": "claim-1",
                "evidence_refs": ["official-notice"],
            }
        ],
        "component_versions": {"extractor": "shadow-fixture-v1"},
    }


def candidate_value(evidence_digest: str) -> dict[str, object]:
    return {
        "schema_version": "editorial_candidate_v1",
        "encoding_version": "rfc8785-restricted-v1",
        "digest_algorithm": "sha256",
        "candidate_id": "discord-multi-2026-07-12-10-00:story_01",
        "stable_story_id": "event:4242",
        "story_version": "v1",
        "evidence_digest": evidence_digest,
        "content_digest": "sha256:" + "2" * 64,
        "asset_digests": [],
        "gate_results": {
            "claim_evidence": "PASS",
            "rights": "PASS",
            "sensitive_risk": "PASS",
            "jurisdiction": "PASS",
        },
        "policy_version": "editorial-shadow-v1",
        "controller_version": "shadow-controller-v1",
        "validator_results": {"article_contract": "PASS"},
        "target": "shadow-recording",
        "provenance": {
            "run_id": "discord-multi-2026-07-12-10-00",
            "story_id": "story_01",
        },
    }


def publication_value(
    *, evidence_digest: str, candidate_digest: str, decision_digest: str
) -> dict[str, object]:
    return {
        "schema_version": "publication_package_v1",
        "encoding_version": "rfc8785-restricted-v1",
        "digest_algorithm": "sha256",
        "stable_story_id": "event:4242",
        "story_version": "v1",
        "candidate_digest": candidate_digest,
        "evidence_digest": evidence_digest,
        "decision_digest": decision_digest,
        "outcome": "AUTO_PUBLISH",
        "headline": "英國公共服務安排更新",
        "body": "呢份係純合成測試內容，唔包含第三方新聞原文。",
        "geographies": ["UK"],
        "categories": ["UK News"],
        "source_refs": ["official-notice"],
        "publisher_id": "newsroom-shadow",
        "content_language": "zh-HK",
        "status": "READY",
        "target": "shadow-recording",
        "content_digest": "sha256:" + "2" * 64,
        "asset_digests": [],
        "policy_version": "editorial-shadow-v1",
        "controller_version": "shadow-controller-v1",
    }


def test_canonical_bytes_are_stable_and_use_utf16_key_order() -> None:
    left = {"香港": "新聞", "\ue000": 1, "😀": 2, "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "😀": 2, "\ue000": 1, "香港": "新聞"}

    expected = '{"nested":{"a":1,"b":2},"香港":"新聞","😀":2,"":1}'.encode()
    assert canonicalise_json(left) == expected
    assert canonicalise_json(right) == expected


@pytest.mark.parametrize(
    "value",
    [
        {"value": 1.5},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": 9_007_199_254_740_992},
        {"value": -9_007_199_254_740_992},
        {"value": "\ud800"},
        {1: "non-string-key"},
        {"value": object()},
    ],
)
def test_canonicalisation_rejects_values_outside_the_restricted_domain(
    value: object,
) -> None:
    with pytest.raises(PackageValidationError):
        canonicalise_json(value)


def test_parse_rejects_duplicate_names_and_invalid_utf8() -> None:
    with pytest.raises(PackageValidationError, match="duplicate"):
        parse_json_bytes(b'{"same":1,"same":2}')

    with pytest.raises(PackageValidationError, match="UTF-8"):
        parse_json_bytes(b'\xff')


def test_package_builders_validate_closed_schemas_and_non_circular_identity() -> None:
    evidence = build_evidence_package(evidence_value())
    candidate = build_candidate_package(candidate_value(evidence.digest))

    assert evidence.digest.startswith("sha256:")
    assert evidence.byte_size == len(evidence.canonical_bytes)
    assert candidate.value["evidence_digest"] == evidence.digest
    assert "decision_digest" not in candidate.value
    assert "outcome" not in candidate.value

    invalid = candidate_value(evidence.digest)
    invalid["outcome"] = "AUTO_PUBLISH"
    with pytest.raises(PackageValidationError, match="outcome"):
        build_candidate_package(invalid)


def test_decision_digest_binds_every_authority_input() -> None:
    evidence = build_evidence_package(evidence_value())
    candidate = build_candidate_package(candidate_value(evidence.digest))

    decision = build_decision_digest(
        candidate_digest=candidate.digest,
        evidence_digest=evidence.digest,
        policy_version="editorial-shadow-v1",
        controller_version="shadow-controller-v1",
        outcome="AUTO_PUBLISH",
        reason_codes=[],
    )
    changed = build_decision_digest(
        candidate_digest=candidate.digest,
        evidence_digest=evidence.digest,
        policy_version="editorial-shadow-v2",
        controller_version="shadow-controller-v1",
        outcome="AUTO_PUBLISH",
        reason_codes=[],
    )

    assert decision.digest != changed.digest
    assert decision.value["candidate_digest"] == candidate.digest
    assert "publication_digest" not in decision.value


def test_publication_package_is_available_only_for_auto_publish() -> None:
    evidence = build_evidence_package(evidence_value())
    candidate = build_candidate_package(candidate_value(evidence.digest))
    decision = build_decision_digest(
        candidate_digest=candidate.digest,
        evidence_digest=evidence.digest,
        policy_version="editorial-shadow-v1",
        controller_version="shadow-controller-v1",
        outcome="AUTO_PUBLISH",
        reason_codes=[],
    )
    value = publication_value(
        evidence_digest=evidence.digest,
        candidate_digest=candidate.digest,
        decision_digest=decision.digest,
    )

    package = build_publication_package(value, outcome="AUTO_PUBLISH")
    assert package.value["decision_digest"] == decision.digest

    for outcome in ("HOLD_FOR_REVIEW", "REJECT"):
        with pytest.raises(PackageValidationError, match="AUTO_PUBLISH"):
            build_publication_package(value, outcome=outcome)


def test_integrity_verification_rejects_tampering_and_noncanonical_bytes() -> None:
    artifact = build_evidence_package(evidence_value())
    assert verify_package_bytes(artifact.canonical_bytes, artifact.digest) == artifact.value

    tampered = artifact.canonical_bytes.replace(b"claim-1", b"claim-2")
    with pytest.raises(PackageIntegrityError, match="digest"):
        verify_package_bytes(tampered, artifact.digest)

    pretty = json.dumps(artifact.value, ensure_ascii=False, indent=2).encode()
    with pytest.raises(PackageIntegrityError, match="canonical"):
        verify_package_bytes(pretty, "sha256:" + "0" * 64, check_digest=False)
