from __future__ import annotations

import json
from typing import Any, Mapping

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import TimePrecision, UtcTimestamp
from newsroom.sources.definition_models import (
    SourceDefinitionRequest,
    SourceDefinitionVersionRequest,
)
from newsroom.sources.item_models import (
    LocatorContinuityDecisionRequest,
    SourceItemRequest,
)
from newsroom.sources.observation_models import (
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationRequest,
    SourceRevisionRequest,
)
from newsroom.sources.types import (
    BaselinePolicy,
    BaselinePolicyKind,
    CheckOutcomeId,
    CoverageContribution,
    CoverageMapping,
    CoverageResponsibility,
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryRepresentationId,
    ExplicitSourceGap,
    IdentityComponent,
    LocatorContinuityDecisionId,
    LocatorContinuityOutcome,
    ObservationModel,
    PortfolioFunction,
    RightsReference,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceDependency,
    SourceDependencyKind,
    SourceItemId,
    SourceItemIdentityKind,
    SourceLifecycleStage,
    SourceRevisionId,
    SourceRole,
    SourceRoleAssignment,
    SourceTime,
    VersionedPolicyRef,
)


def canonical_object(
    data: bytes,
    digest: str,
    *,
    identity: str,
) -> dict[str, Any]:
    if digest_bytes(data) != digest:
        raise AuthorityPersistenceError(
            f"{identity} canonical digest is inconsistent"
        )
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityPersistenceError(
            f"{identity} canonical JSON is invalid"
        ) from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != data:
        raise AuthorityPersistenceError(
            f"{identity} is not an exact canonical object"
        )
    return value


def canonical_row_value(
    row: Mapping[str, Any], *, identity: str
) -> dict[str, Any]:
    return canonical_object(
        bytes(row["canonical_bytes"]),
        str(row["canonical_digest"]),
        identity=identity,
    )


def _mapping(value: object, *, identity: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthorityPersistenceError(f"{identity} is not an object")
    return value


def _list(value: object, *, identity: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuthorityPersistenceError(f"{identity} is not a list")
    return value


def _policy(value: object) -> VersionedPolicyRef:
    item = _mapping(value, identity="versioned policy")
    return VersionedPolicyRef(
        policy_id=str(item["policy_id"]),
        policy_version=str(item["policy_version"]),
    )


def _rights(value: object) -> RightsReference:
    item = _mapping(value, identity="rights reference")
    return RightsReference(
        rights_decision_id=str(item["rights_decision_id"]),
        rights_policy_version=str(item["rights_policy_version"]),
        allowed_use=str(item["allowed_use"]),
        retention_scope=str(item["retention_scope"]),
    )


def _source_time(value: object) -> SourceTime:
    item = _mapping(value, identity="source time")
    alternatives = item["conflicting_values"]
    if not isinstance(alternatives, list):
        raise AuthorityPersistenceError(
            "source time alternatives are not a list"
        )
    return SourceTime(
        precision=TimePrecision(str(item["precision"])),
        value=None if item["value"] is None else str(item["value"]),
        conflicting_values=tuple(str(entry) for entry in alternatives),
    )


def decode_source_definition(
    value: dict[str, Any], *, idempotency_key: str
) -> SourceDefinitionRequest:
    return SourceDefinitionRequest(
        definition_id=SourceDefinitionId.parse(str(value["definition_id"])),
        name=str(value["name"]),
        editorial_purpose=str(value["editorial_purpose"]),
        idempotency_key=idempotency_key,
    )


def decode_source_definition_version(
    value: dict[str, Any], *, idempotency_key: str
) -> SourceDefinitionVersionRequest:
    roles = tuple(
        SourceRoleAssignment(
            role=SourceRole(str(item["role"])),
            purpose=str(item["purpose"]),
            limitations=tuple(
                str(entry)
                for entry in _list(
                    item["limitations"],
                    identity="source role limitations",
                )
            ),
        )
        for item in (
            _mapping(entry, identity="source role")
            for entry in _list(value["roles"], identity="source roles")
        )
    )
    mappings = tuple(
        CoverageMapping(
            obligation_id=str(item["obligation_id"]),
            responsibility=CoverageResponsibility(
                str(item["responsibility"])
            ),
            contribution=CoverageContribution(str(item["contribution"])),
            geographies=tuple(
                str(entry)
                for entry in _list(
                    item["geographies"],
                    identity="coverage geographies",
                )
            ),
            languages=tuple(
                str(entry)
                for entry in _list(
                    item["languages"],
                    identity="coverage languages",
                )
            ),
            limitations=tuple(
                str(entry)
                for entry in _list(
                    item["limitations"],
                    identity="coverage limitations",
                )
            ),
            explicit_gap_id=(
                None
                if item["explicit_gap_id"] is None
                else str(item["explicit_gap_id"])
            ),
        )
        for item in (
            _mapping(entry, identity="coverage mapping")
            for entry in _list(
                value["coverage_mappings"],
                identity="coverage mappings",
            )
        )
    )
    dependencies = tuple(
        SourceDependency(
            dependency_id=str(item["dependency_id"]),
            kind=SourceDependencyKind(str(item["kind"])),
            description=str(item["description"]),
            upstream_source_definition_id=(
                None
                if item["upstream_source_definition_id"] is None
                else SourceDefinitionId.parse(
                    str(item["upstream_source_definition_id"])
                )
            ),
        )
        for item in (
            _mapping(entry, identity="source dependency")
            for entry in _list(
                value["dependencies"],
                identity="source dependencies",
            )
        )
    )
    gaps = tuple(
        ExplicitSourceGap(
            gap_id=str(item["gap_id"]),
            gap_class=str(item["gap_class"]),
            description=str(item["description"]),
            launch_blocking=bool(item["launch_blocking"]),
        )
        for item in (
            _mapping(entry, identity="source gap")
            for entry in _list(
                value["explicit_gaps"],
                identity="source gaps",
            )
        )
    )
    baseline_value = _mapping(
        value["baseline_policy"], identity="baseline policy"
    )
    previous = value["expected_previous_version_id"]
    return SourceDefinitionVersionRequest(
        version_id=SourceDefinitionVersionId.parse(str(value["version_id"])),
        definition_id=SourceDefinitionId.parse(str(value["definition_id"])),
        version_number=int(value["version_number"]),
        expected_previous_version_id=(
            None
            if previous is None
            else SourceDefinitionVersionId.parse(str(previous))
        ),
        locator=str(value["locator"]),
        adapter_contract=_policy(value["adapter_contract"]),
        extraction_scope=tuple(
            str(entry)
            for entry in _list(
                value["extraction_scope"], identity="extraction scope"
            )
        ),
        rights=_rights(value["rights"]),
        roles=roles,
        portfolio_functions=tuple(
            PortfolioFunction(str(entry))
            for entry in _list(
                value["portfolio_functions"],
                identity="portfolio functions",
            )
        ),
        coverage_mappings=mappings,
        dependencies=dependencies,
        explicit_gaps=gaps,
        observation_model=ObservationModel(
            str(value["observation_model"])
        ),
        baseline_policy=BaselinePolicy(
            reference=_policy(baseline_value["reference"]),
            kind=BaselinePolicyKind(str(baseline_value["kind"])),
            freshness_window_seconds=(
                None
                if baseline_value["freshness_window_seconds"] is None
                else int(baseline_value["freshness_window_seconds"])
            ),
            reset_requires_decision=bool(
                baseline_value["reset_requires_decision"]
            ),
            notes=str(baseline_value["notes"]),
        ),
        item_identity_policy=_policy(value["item_identity_policy"]),
        revision_policy=_policy(value["revision_policy"]),
        canonicalization_policy=_policy(
            value["canonicalization_policy"]
        ),
        lifecycle_stage=SourceLifecycleStage(
            str(value["lifecycle_stage"])
        ),
        change_reason=str(value["change_reason"]),
        execution_authority=str(value["execution_authority"]),
        idempotency_key=idempotency_key,
    )


def decode_source_item(
    value: dict[str, Any], *, idempotency_key: str
) -> SourceItemRequest:
    components = tuple(
        IdentityComponent(
            name=str(item["name"]), value=str(item["value"])
        )
        for item in (
            _mapping(entry, identity="identity component")
            for entry in _list(
                value["identity_components"],
                identity="identity components",
            )
        )
    )
    return SourceItemRequest(
        item_id=SourceItemId.parse(str(value["item_id"])),
        definition_id=SourceDefinitionId.parse(str(value["definition_id"])),
        definition_version_id=SourceDefinitionVersionId.parse(
            str(value["definition_version_id"])
        ),
        identity_kind=SourceItemIdentityKind(str(value["identity_kind"])),
        identity_policy=_policy(value["identity_policy"]),
        source_native_id=(
            None
            if value["source_native_id"] is None
            else str(value["source_native_id"])
        ),
        identity_components=components,
        uncertainties=tuple(
            str(entry)
            for entry in _list(
                value["uncertainties"], identity="uncertainties"
            )
        ),
        idempotency_key=idempotency_key,
    )


def decode_locator_continuity(
    value: dict[str, Any], *, idempotency_key: str
) -> LocatorContinuityDecisionRequest:
    return LocatorContinuityDecisionRequest(
        decision_id=LocatorContinuityDecisionId.parse(
            str(value["decision_id"])
        ),
        definition_id=SourceDefinitionId.parse(str(value["definition_id"])),
        definition_version_id=SourceDefinitionVersionId.parse(
            str(value["definition_version_id"])
        ),
        prior_item_id=SourceItemId.parse(str(value["prior_item_id"])),
        prior_locator=str(value["prior_locator"]),
        observed_locator=str(value["observed_locator"]),
        outcome=LocatorContinuityOutcome(str(value["outcome"])),
        related_item_id=SourceItemId.parse(str(value["related_item_id"])),
        rationale=str(value["rationale"]),
        decision_policy=_policy(value["decision_policy"]),
        observed_at=UtcTimestamp.parse(str(value["observed_at"])),
        idempotency_key=idempotency_key,
    )


def decode_source_revision(
    value: dict[str, Any], *, idempotency_key: str
) -> SourceRevisionRequest:
    previous = value["prior_revision_id"]
    return SourceRevisionRequest(
        revision_id=SourceRevisionId.parse(str(value["revision_id"])),
        item_id=SourceItemId.parse(str(value["item_id"])),
        definition_version_id=SourceDefinitionVersionId.parse(
            str(value["definition_version_id"])
        ),
        prior_revision_id=(
            None
            if previous is None
            else SourceRevisionId.parse(str(previous))
        ),
        source_native_revision_token=(
            None
            if value["source_native_revision_token"] is None
            else str(value["source_native_revision_token"])
        ),
        permitted_state_digest=str(value["permitted_state_digest"]),
        revision_policy=_policy(value["revision_policy"]),
        canonicalizer_version=str(value["canonicalizer_version"]),
        source_published_time=_source_time(value["source_published_time"]),
        source_updated_time=_source_time(value["source_updated_time"]),
        observed_at=UtcTimestamp.parse(str(value["observed_at"])),
        idempotency_key=idempotency_key,
    )


def decode_representation(
    value: dict[str, Any], *, idempotency_key: str
) -> DiscoveryRepresentationRequest:
    return DiscoveryRepresentationRequest(
        representation_id=DiscoveryRepresentationId.parse(
            str(value["representation_id"])
        ),
        revision_id=SourceRevisionId.parse(str(value["revision_id"])),
        definition_version_id=SourceDefinitionVersionId.parse(
            str(value["definition_version_id"])
        ),
        adapter_version=str(value["adapter_version"]),
        parser_version=str(value["parser_version"]),
        normalizer_version=str(value["normalizer_version"]),
        extraction_scope_version=str(value["extraction_scope_version"]),
        permitted_fields_digest=str(value["permitted_fields_digest"]),
        representation_digest=str(value["representation_digest"]),
        produced_at=UtcTimestamp.parse(str(value["produced_at"])),
        idempotency_key=idempotency_key,
    )


def decode_occurrence(
    value: dict[str, Any], *, idempotency_key: str
) -> DiscoveryOccurrenceRequest:
    representation = value["representation_id"]
    return DiscoveryOccurrenceRequest(
        occurrence_id=DiscoveryOccurrenceId.parse(
            str(value["occurrence_id"])
        ),
        check_outcome_id=CheckOutcomeId.parse(
            str(value["check_outcome_id"])
        ),
        revision_id=SourceRevisionId.parse(str(value["revision_id"])),
        representation_id=(
            None
            if representation is None
            else DiscoveryRepresentationId.parse(str(representation))
        ),
        definition_version_id=SourceDefinitionVersionId.parse(
            str(value["definition_version_id"])
        ),
        kind=DiscoveryOccurrenceKind(str(value["kind"])),
        observed_at=UtcTimestamp.parse(str(value["observed_at"])),
        receipt_digest=str(value["receipt_digest"]),
        source_asserted_time=_source_time(value["source_asserted_time"]),
        idempotency_key=idempotency_key,
    )


__all__ = [
    "canonical_object",
    "canonical_row_value",
    "decode_locator_continuity",
    "decode_occurrence",
    "decode_representation",
    "decode_source_definition",
    "decode_source_definition_version",
    "decode_source_item",
    "decode_source_revision",
]
