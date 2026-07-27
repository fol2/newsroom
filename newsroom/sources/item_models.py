from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.types import UtcTimestamp

from ._model_common import require_idempotency_key, require_locator, require_versioned_ref
from .types import (
    IdentityComponent,
    LocatorContinuityDecisionId,
    LocatorContinuityOutcome,
    SourceContractError,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceItemIdentityKind,
    VersionedPolicyRef,
    bounded_text,
    bounded_text_tuple,
    sorted_identity_components,
)

@dataclass(frozen=True, slots=True)
class SourceItemRequest:
    item_id: SourceItemId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    identity_kind: SourceItemIdentityKind
    identity_policy: VersionedPolicyRef
    source_native_id: str | None
    identity_components: tuple[IdentityComponent, ...]
    uncertainties: tuple[str, ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, SourceItemId):
            raise SourceContractError("source item identity must be typed")
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise SourceContractError("source definition identity must be typed")
        if not isinstance(
            self.definition_version_id, SourceDefinitionVersionId
        ):
            raise SourceContractError("source definition version must be typed")
        if not isinstance(self.identity_kind, SourceItemIdentityKind):
            raise SourceContractError("source item identity kind must be typed")
        require_versioned_ref(self.identity_policy, field="source_item_identity_policy")
        if self.source_native_id is not None:
            bounded_text(
                self.source_native_id,
                field="source_native_item_id",
                maximum_bytes=2048,
            )
        if self.identity_components != sorted_identity_components(
            self.identity_components
        ):
            raise SourceContractError(
                "source item identity components must be canonically sorted"
            )
        bounded_text_tuple(
            self.uncertainties,
            field="source_item_uncertainties",
            allow_empty=True,
            maximum_items=16,
            maximum_item_bytes=1024,
        )
        require_idempotency_key(self.idempotency_key)
        self._validate_identity_basis()

    def _validate_identity_basis(self) -> None:
        components = {item.name: item.value for item in self.identity_components}
        locator_names = {"locator", "url", "uri"}
        if self.identity_kind is SourceItemIdentityKind.SOURCE_NATIVE:
            if self.source_native_id is None:
                raise SourceContractError(
                    "source-native identity requires a native item identifier"
                )
        elif self.identity_kind is SourceItemIdentityKind.COMPOSITE:
            if len(components) < 2:
                raise SourceContractError(
                    "composite source identity requires at least two components"
                )
            if set(components) <= locator_names:
                raise SourceContractError(
                    "external locator cannot be the sole item identity"
                )
        elif (
            self.identity_kind
            is SourceItemIdentityKind.ASSIGNED_WITH_UNCERTAINTY
        ):
            if not self.uncertainties:
                raise SourceContractError(
                    "assigned uncertain identity must retain its uncertainty"
                )
            if self.source_native_id is not None:
                raise SourceContractError(
                    "assigned uncertain identity cannot claim native identity"
                )
        if self.source_native_id is None and not self.identity_components:
            raise SourceContractError("source item has no retained identity basis")

    def canonical_value(self) -> dict[str, object]:
        return {
            "item_id": str(self.item_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "identity_kind": self.identity_kind.value,
            "identity_policy": self.identity_policy.canonical_value(),
            "source_native_id": self.source_native_id,
            "identity_components": [
                item.canonical_value() for item in self.identity_components
            ],
            "uncertainties": list(self.uncertainties),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def identity_digest(self) -> str:
        return digest_canonical(
            {
                "definition_id": str(self.definition_id),
                "identity_kind": self.identity_kind.value,
                "identity_policy": self.identity_policy.canonical_value(),
                "source_native_id": self.source_native_id,
                "identity_components": [
                    item.canonical_value() for item in self.identity_components
                ],
                "uncertainties": list(self.uncertainties),
            }
        )


@dataclass(frozen=True, slots=True)
class LocatorContinuityDecisionRequest:
    decision_id: LocatorContinuityDecisionId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    prior_item_id: SourceItemId
    prior_locator: str
    observed_locator: str
    outcome: LocatorContinuityOutcome
    related_item_id: SourceItemId
    rationale: str
    decision_policy: VersionedPolicyRef
    observed_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, LocatorContinuityDecisionId):
            raise SourceContractError("locator decision identity must be typed")
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise SourceContractError("source definition identity must be typed")
        if not isinstance(
            self.definition_version_id, SourceDefinitionVersionId
        ):
            raise SourceContractError("source definition version must be typed")
        if not isinstance(self.prior_item_id, SourceItemId):
            raise SourceContractError("prior source item identity must be typed")
        if not isinstance(self.related_item_id, SourceItemId):
            raise SourceContractError("related source item identity must be typed")
        require_locator(self.prior_locator, field="prior_locator")
        require_locator(self.observed_locator, field="observed_locator")
        if self.prior_locator == self.observed_locator:
            raise SourceContractError(
                "locator continuity decision requires distinct locators"
            )
        if not isinstance(self.outcome, LocatorContinuityOutcome):
            raise SourceContractError("locator continuity outcome must be typed")
        if self.outcome is LocatorContinuityOutcome.SAME_ITEM:
            if self.related_item_id != self.prior_item_id:
                raise SourceContractError(
                    "same-item locator decision must retain the prior item"
                )
        elif self.related_item_id == self.prior_item_id:
            raise SourceContractError(
                "uncertain or separate locator decision requires a separate item"
            )
        bounded_text(
            self.rationale,
            field="locator_continuity_rationale",
            maximum_bytes=4096,
        )
        require_versioned_ref(self.decision_policy, field="locator_decision_policy")
        if not isinstance(self.observed_at, UtcTimestamp):
            raise SourceContractError("locator observation time must be typed")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": str(self.decision_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "prior_item_id": str(self.prior_item_id),
            "prior_locator": self.prior_locator,
            "observed_locator": self.observed_locator,
            "outcome": self.outcome.value,
            "related_item_id": str(self.related_item_id),
            "rationale": self.rationale,
            "decision_policy": self.decision_policy.canonical_value(),
            "observed_at": self.observed_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                "definition_id": str(self.definition_id),
                "definition_version_id": str(self.definition_version_id),
                "prior_item_id": str(self.prior_item_id),
                "prior_locator": self.prior_locator,
                "observed_locator": self.observed_locator,
                "outcome": self.outcome.value,
                "related_item_id": str(self.related_item_id),
                "decision_policy": self.decision_policy.canonical_value(),
            }
        )


__all__ = ["LocatorContinuityDecisionRequest", "SourceItemRequest"]
