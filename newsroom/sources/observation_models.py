from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.types import UtcTimestamp, require_token

from ._model_common import require_idempotency_key, require_source_time, require_versioned_ref
from .types import (
    CheckOutcomeId,
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryRepresentationId,
    SourceContractError,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    SourceTime,
    VersionedPolicyRef,
    bounded_text,
    canonical_digest,
)


@dataclass(frozen=True, slots=True)
class SourceRevisionRequest:
    revision_id: SourceRevisionId
    item_id: SourceItemId
    definition_version_id: SourceDefinitionVersionId
    prior_revision_id: SourceRevisionId | None
    source_native_revision_token: str | None
    permitted_state_digest: str
    revision_policy: VersionedPolicyRef
    canonicalizer_version: str
    source_published_time: SourceTime
    source_updated_time: SourceTime
    observed_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.revision_id, SourceRevisionId):
            raise SourceContractError("source revision identity must be typed")
        if not isinstance(self.item_id, SourceItemId):
            raise SourceContractError("source item identity must be typed")
        if not isinstance(
            self.definition_version_id, SourceDefinitionVersionId
        ):
            raise SourceContractError("source definition version must be typed")
        if self.prior_revision_id is not None and not isinstance(
            self.prior_revision_id, SourceRevisionId
        ):
            raise SourceContractError("prior source revision must be typed")
        if self.prior_revision_id == self.revision_id:
            raise SourceContractError("source revision cannot precede itself")
        if self.source_native_revision_token is not None:
            bounded_text(
                self.source_native_revision_token,
                field="source_native_revision_token",
                maximum_bytes=2048,
            )
        canonical_digest(
            self.permitted_state_digest,
            field="permitted_source_state_digest",
        )
        require_versioned_ref(self.revision_policy, field="revision_policy")
        require_token(self.canonicalizer_version, field="revision_canonicalizer_version")
        require_source_time(self.source_published_time, field="source_published_time")
        require_source_time(self.source_updated_time, field="source_updated_time")
        if not isinstance(self.observed_at, UtcTimestamp):
            raise SourceContractError("revision observation time must be typed")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "revision_id": str(self.revision_id),
            "item_id": str(self.item_id),
            "definition_version_id": str(self.definition_version_id),
            "prior_revision_id": (
                None
                if self.prior_revision_id is None
                else str(self.prior_revision_id)
            ),
            "source_native_revision_token": self.source_native_revision_token,
            "permitted_state_digest": self.permitted_state_digest,
            "revision_policy": self.revision_policy.canonical_value(),
            "canonicalizer_version": self.canonicalizer_version,
            "source_published_time": self.source_published_time.canonical_value(),
            "source_updated_time": self.source_updated_time.canonical_value(),
            "observed_at": self.observed_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def revision_identity_digest(self) -> str:
        return digest_canonical(
            {
                "item_id": str(self.item_id),
                "source_native_revision_token": (
                    self.source_native_revision_token
                ),
                "permitted_state_digest": self.permitted_state_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class DiscoveryRepresentationRequest:
    representation_id: DiscoveryRepresentationId
    revision_id: SourceRevisionId
    definition_version_id: SourceDefinitionVersionId
    adapter_version: str
    parser_version: str
    normalizer_version: str
    extraction_scope_version: str
    permitted_fields_digest: str
    representation_digest: str
    produced_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.representation_id, DiscoveryRepresentationId):
            raise SourceContractError("representation identity must be typed")
        if not isinstance(self.revision_id, SourceRevisionId):
            raise SourceContractError("source revision identity must be typed")
        if not isinstance(
            self.definition_version_id, SourceDefinitionVersionId
        ):
            raise SourceContractError("source definition version must be typed")
        for field, value in (
            ("adapter_version", self.adapter_version),
            ("parser_version", self.parser_version),
            ("normalizer_version", self.normalizer_version),
            ("extraction_scope_version", self.extraction_scope_version),
        ):
            require_token(value, field=field)
        canonical_digest(
            self.permitted_fields_digest,
            field="permitted_fields_digest",
        )
        canonical_digest(
            self.representation_digest,
            field="discovery_representation_digest",
        )
        if not isinstance(self.produced_at, UtcTimestamp):
            raise SourceContractError("representation production time must be typed")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "representation_id": str(self.representation_id),
            "revision_id": str(self.revision_id),
            "definition_version_id": str(self.definition_version_id),
            "adapter_version": self.adapter_version,
            "parser_version": self.parser_version,
            "normalizer_version": self.normalizer_version,
            "extraction_scope_version": self.extraction_scope_version,
            "permitted_fields_digest": self.permitted_fields_digest,
            "representation_digest": self.representation_digest,
            "produced_at": self.produced_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def producer_slot_digest(self) -> str:
        return digest_canonical(
            {
                "revision_id": str(self.revision_id),
                "definition_version_id": str(self.definition_version_id),
                "adapter_version": self.adapter_version,
                "parser_version": self.parser_version,
                "normalizer_version": self.normalizer_version,
                "extraction_scope_version": self.extraction_scope_version,
                "permitted_fields_digest": self.permitted_fields_digest,
            }
        )

    @property
    def representation_identity_digest(self) -> str:
        return digest_canonical(
            {
                "producer_slot_digest": self.producer_slot_digest,
                "representation_digest": self.representation_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class DiscoveryOccurrenceRequest:
    occurrence_id: DiscoveryOccurrenceId
    check_outcome_id: CheckOutcomeId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId | None
    definition_version_id: SourceDefinitionVersionId
    kind: DiscoveryOccurrenceKind
    observed_at: UtcTimestamp
    receipt_digest: str
    source_asserted_time: SourceTime
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_id, DiscoveryOccurrenceId):
            raise SourceContractError("occurrence identity must be typed")
        if not isinstance(self.check_outcome_id, CheckOutcomeId):
            raise SourceContractError("check outcome identity must be typed")
        if not isinstance(self.revision_id, SourceRevisionId):
            raise SourceContractError("source revision identity must be typed")
        if self.representation_id is not None and not isinstance(
            self.representation_id, DiscoveryRepresentationId
        ):
            raise SourceContractError("representation identity must be typed")
        if not isinstance(
            self.definition_version_id, SourceDefinitionVersionId
        ):
            raise SourceContractError("source definition version must be typed")
        if not isinstance(self.kind, DiscoveryOccurrenceKind):
            raise SourceContractError("occurrence kind must be typed")
        if not isinstance(self.observed_at, UtcTimestamp):
            raise SourceContractError("occurrence observation time must be typed")
        canonical_digest(self.receipt_digest, field="occurrence_receipt_digest")
        require_source_time(self.source_asserted_time, field="source_asserted_time")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "occurrence_id": str(self.occurrence_id),
            "check_outcome_id": str(self.check_outcome_id),
            "revision_id": str(self.revision_id),
            "representation_id": (
                None
                if self.representation_id is None
                else str(self.representation_id)
            ),
            "definition_version_id": str(self.definition_version_id),
            "kind": self.kind.value,
            "observed_at": self.observed_at.to_text(),
            "receipt_digest": self.receipt_digest,
            "source_asserted_time": self.source_asserted_time.canonical_value(),
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
                "check_outcome_id": str(self.check_outcome_id),
                "revision_id": str(self.revision_id),
                "representation_id": (
                    None
                    if self.representation_id is None
                    else str(self.representation_id)
                ),
                "kind": self.kind.value,
            }
        )


__all__ = [
    "DiscoveryOccurrenceRequest",
    "DiscoveryRepresentationRequest",
    "SourceRevisionRequest",
]
