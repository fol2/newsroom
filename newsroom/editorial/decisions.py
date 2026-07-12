from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from .packages import (
    DIGEST_ALGORITHM,
    ENCODING_VERSION,
    PackageArtifact,
    PackageValidationError,
    build_decision_digest,
    build_publication_package,
    parse_json_bytes,
)
from .policy import EditorialPolicy, GatePolicy


_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "editorial_decision_v1.schema.json"


class DecisionEvaluationError(ValueError):
    """Raised when admitted packages do not form a coherent decision input."""


@dataclass(frozen=True, slots=True)
class DecisionResult:
    outcome: str
    reason_codes: tuple[str, ...]
    decision: PackageArtifact
    publication_package: PackageArtifact | None
    delivery_state: str = "NOT_REQUESTED"


def _load_decision_validator() -> Draft202012Validator:
    schema = parse_json_bytes(_SCHEMA_PATH.read_bytes())
    if not isinstance(schema, dict):
        raise RuntimeError("Editorial decision schema root must be an object")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


_DECISION_VALIDATOR = _load_decision_validator()


def _status_reason(gate: GatePolicy, status: str) -> str | None:
    if status == "PASS":
        return None
    if status == "REJECT":
        return gate.reject_reason
    if status == "HOLD":
        return gate.hold_reason
    if status == "MISSING":
        return gate.missing_reason
    if status == "UNKNOWN":
        return gate.unknown_reason
    if status == "INDETERMINATE":
        return gate.indeterminate_reason
    return "UNKNOWN_POLICY_INPUT"


def _ordered_reasons(policy: EditorialPolicy, reasons: set[str]) -> tuple[str, ...]:
    return tuple(reason for reason in policy.reason_order if reason in reasons)


def _validate_decision(artifact: PackageArtifact) -> None:
    errors = sorted(
        _DECISION_VALIDATOR.iter_errors(artifact.value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise DecisionEvaluationError(f"invalid decision package: {details}")


def evaluate_candidate(
    *,
    candidate: PackageArtifact,
    evidence: PackageArtifact,
    policy: EditorialPolicy,
    publication_content: Mapping[str, Any] | None,
    compatibility_reason_codes: Sequence[str] = (),
) -> DecisionResult:
    if candidate.kind != "candidate" or evidence.kind != "evidence":
        raise DecisionEvaluationError("candidate and evidence package kinds are required")
    candidate_value = candidate.value
    if candidate_value.get("evidence_digest") != evidence.digest:
        raise DecisionEvaluationError("candidate evidence reference does not match evidence package")
    if candidate_value.get("policy_version") != policy.policy_id:
        raise DecisionEvaluationError("candidate policy version does not match loaded policy")
    controller_version = str(policy.component_versions["controller"])
    if candidate_value.get("controller_version") != controller_version:
        raise DecisionEvaluationError("candidate controller version does not match loaded policy")

    reason_set: set[str] = set()
    required_outcomes: set[str] = set()
    target = str(candidate_value.get("target", ""))
    if target not in policy.target_allowlist:
        reason_set.add("UNKNOWN_TARGET")
        required_outcomes.add("HOLD_FOR_REVIEW")

    known_gate_keys = {
        gate.gate_id for gate in policy.gates if gate.source == "gate_results"
    }
    known_validator_keys = {
        gate.gate_id for gate in policy.gates if gate.source == "validator_results"
    }
    gate_results = dict(candidate_value.get("gate_results", {}))
    validator_results = dict(candidate_value.get("validator_results", {}))
    if set(gate_results) - known_gate_keys or set(validator_results) - known_validator_keys:
        reason_set.add("UNKNOWN_POLICY_INPUT")
        required_outcomes.add("HOLD_FOR_REVIEW")

    for gate in policy.gates:
        source = gate_results if gate.source == "gate_results" else validator_results
        status = str(source.get(gate.gate_id, "MISSING"))
        reason = _status_reason(gate, status)
        if reason is not None:
            reason_set.add(reason)
        required_outcomes.add(policy.status_outcomes.get(status, "HOLD_FOR_REVIEW"))

    known_reasons = set(policy.reason_order)
    for reason in compatibility_reason_codes:
        if reason not in known_reasons:
            reason_set.add("UNKNOWN_POLICY_INPUT")
        else:
            reason_set.add(reason)
        required_outcomes.add("HOLD_FOR_REVIEW")
    if str(candidate_value.get("stable_story_id", "")).startswith("compat-occurrence:"):
        reason_set.add("MIGRATION_MISSING_STABLE_STORY_ID")
        required_outcomes.add("HOLD_FOR_REVIEW")

    if not reason_set and publication_content is None:
        reason_set.add("MISSING_PUBLICATION_CONTENT")
        required_outcomes.add("HOLD_FOR_REVIEW")

    outcome = next(
        (item for item in policy.outcome_precedence if item in required_outcomes),
        "AUTO_PUBLISH",
    )
    reason_codes = _ordered_reasons(policy, reason_set)
    if reason_set - set(reason_codes):
        raise DecisionEvaluationError("policy reason order cannot represent every decision reason")

    decision = build_decision_digest(
        candidate_digest=candidate.digest,
        evidence_digest=evidence.digest,
        policy_version=policy.policy_id,
        controller_version=controller_version,
        outcome=outcome,
        reason_codes=list(reason_codes),
    )
    _validate_decision(decision)

    publication_package: PackageArtifact | None = None
    if outcome == "AUTO_PUBLISH":
        assert publication_content is not None
        publication_value = {
            "schema_version": "publication_package_v1",
            "encoding_version": ENCODING_VERSION,
            "digest_algorithm": DIGEST_ALGORITHM,
            "stable_story_id": candidate_value["stable_story_id"],
            "story_version": candidate_value["story_version"],
            "candidate_digest": candidate.digest,
            "evidence_digest": evidence.digest,
            "decision_digest": decision.digest,
            "outcome": outcome,
            "headline": publication_content.get("headline"),
            "body": publication_content.get("body"),
            "geographies": publication_content.get("geographies"),
            "categories": publication_content.get("categories"),
            "source_refs": publication_content.get("source_refs"),
            "publisher_id": publication_content.get("publisher_id"),
            "content_language": publication_content.get("content_language"),
            "status": publication_content.get("status"),
            "target": target,
            "content_digest": candidate_value["content_digest"],
            "asset_digests": candidate_value["asset_digests"],
            "policy_version": policy.policy_id,
            "controller_version": controller_version,
        }
        try:
            publication_package = build_publication_package(
                publication_value,
                outcome=outcome,
            )
        except PackageValidationError as exc:
            raise DecisionEvaluationError(f"invalid publication content: {exc}") from exc

    return DecisionResult(
        outcome=outcome,
        reason_codes=reason_codes,
        decision=decision,
        publication_package=publication_package,
    )
