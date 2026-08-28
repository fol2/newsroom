"""Governed proposal projection — untrusted candidates to accepted atoms (#790 Step 16)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.combined_temporal_attribution import (
    attributed_scope,
    contains_name,
)
from newsroom.graphiti_adapter.combined_temporal_response import raw_digest
from newsroom.graphiti_adapter.combined_temporal_temporal import (
    _date_expectations,
    iso_timestamp,
)
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalError,
    CombinedTemporalFailureCode,
    EvidenceSegment,
)
from newsroom.graphiti_adapter.combined_temporal_validation import (
    VALIDATOR_CONTRACT_VERSION,
    _assert_fact_grounding,
    _assert_single_attribution,
    _canonical_entity,
    _canonical_fact,
    _entity,
    _fact,
    _resolve_segments,
    normalise,
)

PROJECTION_POLICY_VERSION = "NewsroomGovernedProposalProjectionV1"
PROJECTION_POLICY_DIGEST = digest_canonical(PROJECTION_POLICY_VERSION)
PROJECTION_RECEIPT_SCHEMA_VERSION = "newsroom.combined-temporal.projection-receipt.v1"

ATOM_LOCAL_FAILURE_CODES = frozenset(
    {
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
        CombinedTemporalFailureCode.TEMPORAL_INVALID,
    }
)

PAYLOAD_FATAL_FAILURE_CODES = frozenset(
    {
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
        CombinedTemporalFailureCode.IDENTITY_INVALID,
        CombinedTemporalFailureCode.PIPELINE_FAILED,
    }
)

# Fact-loop MALFORMED / IDENTITY_INVALID are proposal rejection; top-level parse,
# entity-table and post-accept normalise() raises of those codes stay leaf-fatal.
FACT_LOOP_ATOM_LOCAL_CODES = ATOM_LOCAL_FAILURE_CODES | {
    CombinedTemporalFailureCode.MALFORMED_OBJECT,
    CombinedTemporalFailureCode.IDENTITY_INVALID,
}


@dataclass(frozen=True, slots=True)
class GovernedProjectionResult:
    payload: dict[str, Any]
    ranges: dict[str, tuple[EvidenceSegment, ...]]
    receipt: dict[str, object]


def classify_combined_temporal_failure(
    code: CombinedTemporalFailureCode,
    *,
    grain: str = "payload",
) -> str:
    """Classify a failure code for the named grain.

    ``grain`` is one of ``payload`` (top-level parse / entity table / final
    normalise) or ``fact_loop`` (independently attributable proposal atoms).
    """

    if grain == "fact_loop":
        if code in FACT_LOOP_ATOM_LOCAL_CODES:
            return "atom_local"
        if code in PAYLOAD_FATAL_FAILURE_CODES - FACT_LOOP_ATOM_LOCAL_CODES:
            return "payload_fatal"
        raise ValueError(f"unclassified fact-loop failure code: {code}")
    if grain != "payload":
        raise ValueError(f"unknown classification grain: {grain}")
    if code in PAYLOAD_FATAL_FAILURE_CODES:
        return "payload_fatal"
    if code in ATOM_LOCAL_FAILURE_CODES:
        # Same code may still be leaf-fatal when raised outside the fact loop
        # (entity evidence table or post-accept normalise).
        return "atom_local"
    raise ValueError(f"unclassified combined-temporal failure code: {code}")


def project_temporal_bounds(
    *,
    fact_text: str,
    retained: str,
    reference_time: datetime,
) -> tuple[str | None, str | None]:
    """Derive governed temporal bounds from cited evidence only."""

    scoped = attributed_scope(retained, fact_text)
    valid_dates, invalid_dates = _date_expectations(scoped, reference_time)
    if len(valid_dates) > 1 or len(invalid_dates) > 1:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            "fact evidence has ambiguous temporal attribution",
        )
    valid_at = (
        None if not valid_dates else iso_timestamp(next(iter(valid_dates)))
    )
    invalid_at = (
        None if not invalid_dates else iso_timestamp(next(iter(invalid_dates)))
    )
    if (
        valid_at is not None
        and invalid_at is not None
        and UtcTimestamp.parse(valid_at).value >= UtcTimestamp.parse(invalid_at).value
    ):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            "projected valid_at must precede invalid_at",
        )
    return valid_at, invalid_at


def project_governed_proposals(
    payload: Mapping[str, Any],
    segments: tuple[EvidenceSegment, ...],
    reference_time: datetime,
    *,
    raw_provider_digest: str | None = None,
) -> GovernedProjectionResult:
    """Project an untrusted candidate set into a governed accepted payload."""

    provider_digest = raw_provider_digest or raw_digest(dict(payload))
    entities = [_entity(item) for item in payload["entities"]]
    raw_facts = list(payload["facts"])
    ids = [item["local_id"] for item in entities]
    if len(ids) != len(set(ids)):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "local_id values must be unique",
        )
    id_set = set(ids)
    entity_by_id = {item["local_id"]: item for item in entities}
    if raw_facts and not entities:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "facts require entities",
        )

    atom_actions: list[dict[str, object]] = []
    accepted_facts: list[dict[str, Any]] = []
    ranges: dict[str, tuple[EvidenceSegment, ...]] = {}
    connected: set[int] = set()

    for raw_fact in raw_facts:
        raw_temporal = {
            "valid_at": (
                raw_fact.get("valid_at") if isinstance(raw_fact, Mapping) else None
            ),
            "invalid_at": (
                raw_fact.get("invalid_at") if isinstance(raw_fact, Mapping) else None
            ),
        }
        try:
            if not isinstance(raw_fact, Mapping):
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.MALFORMED_OBJECT,
                    "fact is not an object",
                )
            if "valid_at" not in raw_fact or "invalid_at" not in raw_fact:
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.MALFORMED_OBJECT,
                    "fact must include valid_at and invalid_at",
                )
            # Model temporal values are untrusted receipt material only.
            wire = dict(raw_fact)
            wire["valid_at"] = None
            wire["invalid_at"] = None
            fact = _fact(wire)
            source = fact["source_local_id"]
            target = fact["target_local_id"]
            if source == target or source not in id_set or target not in id_set:
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                    "facts must reference two present distinct local IDs",
                )
            cited = _resolve_segments(
                fact["evidence_segment_ids"], segments, contiguous=True
            )
            retained = "".join(item.text for item in cited)
            source_entity = entity_by_id[source]
            target_entity = entity_by_id[target]
            source_name = source_entity["name"]
            target_name = target_entity["name"]
            if fact["fact"] not in retained:
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                    "fact is not present in cited segments",
                )
            _assert_fact_grounding(
                fact=fact,
                source_name=source_name,
                target_name=target_name,
            )
            fact_segment_ids = set(fact["evidence_segment_ids"])
            source_evidence = set(source_entity["evidence_segment_ids"])
            target_evidence = set(target_entity["evidence_segment_ids"])
            if (
                not fact_segment_ids & source_evidence
                or not fact_segment_ids & target_evidence
            ):
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                    "fact endpoints do not share their entity evidence",
                )
            _assert_single_attribution(
                retained,
                fact_text=fact["fact"],
                source_name=source_name,
                target_name=target_name,
            )
            for endpoint in (source_entity, target_entity):
                endpoint_cited = _resolve_segments(
                    endpoint["evidence_segment_ids"], segments
                )
                if any(
                    not contains_name(item.text, endpoint["name"])
                    for item in endpoint_cited
                ):
                    raise CombinedTemporalError(
                        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                        "entity name is not present in every cited segment",
                    )
            projected_valid, projected_invalid = project_temporal_bounds(
                fact_text=fact["fact"],
                retained=retained,
                reference_time=reference_time,
            )
            projected = {
                **fact,
                "valid_at": projected_valid,
                "invalid_at": projected_invalid,
            }
            raw_proposal_digest = digest_canonical(
                {
                    "evidence_segment_ids": fact["evidence_segment_ids"],
                    "fact": fact["fact"],
                    "raw_temporal": raw_temporal,
                    "relation_type": fact["relation_type"],
                    "source_local_id": source,
                    "target_local_id": target,
                }
            )
            accepted_digest = digest_canonical(projected)
            atom_actions.append(
                {
                    "action": "accept",
                    "reason_code": "PROJECTED",
                    "raw_proposal_digest": raw_proposal_digest,
                    "fact": fact["fact"],
                    "evidence_segment_ids": list(fact["evidence_segment_ids"]),
                    "raw_temporal": raw_temporal,
                    "projected_temporal": {
                        "valid_at": projected_valid,
                        "invalid_at": projected_invalid,
                    },
                    "accepted_object_digest": accepted_digest,
                }
            )
            accepted_facts.append(projected)
            ranges[projected["fact"]] = cited
            connected.update((source, target))
        except CombinedTemporalError as exc:
            if (
                classify_combined_temporal_failure(exc.code, grain="fact_loop")
                != "atom_local"
            ):
                raise
            raw_proposal_digest = digest_canonical(
                {
                    "raw_fact": (
                        dict(raw_fact) if isinstance(raw_fact, Mapping) else raw_fact
                    ),
                }
            )
            atom_actions.append(
                {
                    "action": "reject",
                    "reason_code": exc.code.value,
                    "raw_proposal_digest": raw_proposal_digest,
                    "fact": (
                        raw_fact.get("fact") if isinstance(raw_fact, Mapping) else None
                    ),
                    "evidence_segment_ids": (
                        list(raw_fact.get("evidence_segment_ids") or [])
                        if isinstance(raw_fact, Mapping)
                        else []
                    ),
                    "raw_temporal": raw_temporal,
                    "projected_temporal": {"valid_at": None, "invalid_at": None},
                    "accepted_object_digest": None,
                    "message": str(exc),
                }
            )

    orphan_ids = id_set - connected
    retained_entities = [item for item in entities if item["local_id"] in connected]
    projected_payload = {
        "entities": [
            _canonical_entity(item)
            for item in sorted(retained_entities, key=lambda item: item["local_id"])
        ],
        "facts": [
            _canonical_fact(item)
            for item in sorted(
                accepted_facts,
                key=lambda item: (
                    item["source_local_id"],
                    item["target_local_id"],
                    item["relation_type"],
                    item["fact"],
                ),
            )
        ],
    }
    normalised, ranges = normalise(projected_payload, segments, reference_time)

    receipt_body = {
        "schema_version": PROJECTION_RECEIPT_SCHEMA_VERSION,
        "projection_policy_version": PROJECTION_POLICY_VERSION,
        "projection_policy_digest": PROJECTION_POLICY_DIGEST,
        "validator_contract_version": VALIDATOR_CONTRACT_VERSION,
        "raw_provider_output_digest": provider_digest,
        "reference_time": iso_timestamp(reference_time),
        "reference_time_digest": digest_canonical(iso_timestamp(reference_time)),
        "atom_actions": atom_actions,
        "accepted_count": sum(
            1 for item in atom_actions if item["action"] == "accept"
        ),
        "rejected_count": sum(
            1 for item in atom_actions if item["action"] == "reject"
        ),
        "orphan_removed_count": len(orphan_ids),
        "accepted_payload_digest": digest_canonical(normalised),
    }
    receipt = {
        **receipt_body,
        "projection_receipt_digest": digest_canonical(receipt_body),
    }
    return GovernedProjectionResult(
        payload=normalised,
        ranges=ranges,
        receipt=receipt,
    )


def validate_projection_receipt(receipt: object) -> dict[str, object]:
    """Fail closed unless the Step 16 projection receipt is exact and consistent."""

    if not isinstance(receipt, Mapping):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "projection receipt must be an object",
        )
    required = (
        "schema_version",
        "projection_policy_version",
        "projection_policy_digest",
        "raw_provider_output_digest",
        "reference_time",
        "reference_time_digest",
        "atom_actions",
        "accepted_count",
        "rejected_count",
        "orphan_removed_count",
        "accepted_payload_digest",
        "projection_receipt_digest",
    )
    missing = [key for key in required if key not in receipt]
    if missing:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            f"projection receipt missing fields: {', '.join(missing)}",
        )
    if receipt.get("schema_version") != PROJECTION_RECEIPT_SCHEMA_VERSION:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "projection receipt schema_version is invalid",
        )
    if receipt.get("projection_policy_version") != PROJECTION_POLICY_VERSION:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "projection_policy_version is invalid",
        )
    if receipt.get("projection_policy_digest") != PROJECTION_POLICY_DIGEST:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "projection_policy_digest contradicts projection_policy_version",
        )
    reference_time = receipt.get("reference_time")
    if not isinstance(reference_time, str) or not reference_time:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "projection receipt reference_time is invalid",
        )
    if receipt.get("reference_time_digest") != digest_canonical(reference_time):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "reference_time_digest contradicts reference_time",
        )
    for key in (
        "raw_provider_output_digest",
        "accepted_payload_digest",
        "projection_receipt_digest",
    ):
        value = receipt.get(key)
        if not isinstance(value, str) or not value.startswith("sha256:"):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.PIPELINE_FAILED,
                f"{key} must be a sha256 digest",
            )
    atom_actions = receipt.get("atom_actions")
    if not isinstance(atom_actions, list):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "atom_actions must be a list",
        )
    accepted = 0
    rejected = 0
    for index, action in enumerate(atom_actions):
        if not isinstance(action, Mapping):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.PIPELINE_FAILED,
                f"atom_actions[{index}] must be an object",
            )
        kind = action.get("action")
        if kind == "accept":
            accepted += 1
            digest = action.get("accepted_object_digest")
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.PIPELINE_FAILED,
                    f"atom_actions[{index}] accepted_object_digest is invalid",
                )
        elif kind == "reject":
            rejected += 1
        else:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.PIPELINE_FAILED,
                f"atom_actions[{index}] action is invalid",
            )
        raw_digest = action.get("raw_proposal_digest")
        if not isinstance(raw_digest, str) or not raw_digest.startswith("sha256:"):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.PIPELINE_FAILED,
                f"atom_actions[{index}] raw_proposal_digest is invalid",
            )
    for key, expected in (
        ("accepted_count", accepted),
        ("rejected_count", rejected),
    ):
        value = receipt.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value != expected:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.PIPELINE_FAILED,
                f"{key} is inconsistent with atom_actions",
            )
    orphan = receipt.get("orphan_removed_count")
    if not isinstance(orphan, int) or isinstance(orphan, bool) or orphan < 0:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "orphan_removed_count must be a non-negative integer",
        )
    body = {key: receipt[key] for key in receipt if key != "projection_receipt_digest"}
    if receipt.get("projection_receipt_digest") != digest_canonical(body):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            "projection_receipt_digest contradicts receipt body",
        )
    return dict(receipt)


__all__ = [
    "ATOM_LOCAL_FAILURE_CODES",
    "FACT_LOOP_ATOM_LOCAL_CODES",
    "PAYLOAD_FATAL_FAILURE_CODES",
    "PROJECTION_POLICY_DIGEST",
    "PROJECTION_POLICY_VERSION",
    "PROJECTION_RECEIPT_SCHEMA_VERSION",
    "GovernedProjectionResult",
    "classify_combined_temporal_failure",
    "project_governed_proposals",
    "project_temporal_bounds",
    "validate_projection_receipt",
]
