from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.types import (
    EventId,
    ObjectAdmissionId,
    TrustScope,
    UUIDv4Id,
    UtcTimestamp,
    require_scope,
    require_token,
)


class RelationAuthorityError(RuntimeError):
    """Base error for governed relation authority."""


class RelationContractError(ValueError):
    """A typed relation, fixture, or lifecycle contract is malformed."""


class RelationStateError(RelationAuthorityError):
    """Current retained authority cannot support the requested transition."""


class RelationSemanticCollision(RelationStateError):
    """Another immutable proposal occupies the same exact semantic identity."""


class RelationConflict(RelationStateError):
    """An unresolved materially different proposal occupies the same relation slot."""


class RelationStaleDecision(RelationStateError):
    """A decision request was not pinned to the exact current decision head."""


class RelationPredicate(StrEnum):
    SAME_EVENT_AS = "SAME_EVENT_AS"
    DEVELOPMENT_OF = "DEVELOPMENT_OF"
    SAME_PROCESS_AS = "SAME_PROCESS_AS"
    CORRECTS = "CORRECTS"
    SUPERSEDES = "SUPERSEDES"
    SUPPORTS = "SUPPORTS"
    DISPUTES = "DISPUTES"
    CONTRADICTS = "CONTRADICTS"
    ABOUT_EVENT = "ABOUT_EVENT"


class RelationRecordType(StrEnum):
    SOURCE_REVISION = "SOURCE_REVISION"
    EVENT_HYPOTHESIS_VERSION = "EVENT_HYPOTHESIS_VERSION"
    STORY_CANDIDATE_VERSION = "STORY_CANDIDATE_VERSION"


class RelationProducerKind(StrEnum):
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    EXTRACTOR = "EXTRACTOR"
    AUTHORISED_OPERATOR = "AUTHORISED_OPERATOR"


class RelationDecisionAction(StrEnum):
    ADMIT = "ADMIT"
    REJECT = "REJECT"
    HOLD = "HOLD"
    INVALIDATE = "INVALIDATE"
    REVOKE = "REVOKE"
    SUPERSEDE = "SUPERSEDE"


class RelationProjectionAction(StrEnum):
    UPSERT = "UPSERT"
    REMOVE = "REMOVE"


class RelationCurrentState(StrEnum):
    PROPOSED = "PROPOSED"
    HELD = "HELD"
    REJECTED = "REJECTED"
    ADMITTED = "ADMITTED"
    INVALIDATED = "INVALIDATED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2BindingId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RelationProposalId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RelationAdmissionDecisionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RelationAssertionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RelationReadPolicy:
    """Immutable authorization contract for governed-relation reads.

    The policy is intentionally separate from the event-ledger read policy.
    Projectors may read the admitted assertion seam without receiving proposal,
    decision, SQLite, or graph mutation authority.
    """

    policy_id: str
    purpose: str
    required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="relation_read_policy_id")
        require_token(self.purpose, field="relation_read_purpose")
        require_scope(self.required_scope, field="relation_read_scope")
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise RelationContractError(
                "relation read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            require_token(principal_id, field="relation_reader_principal")
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or self.max_results <= 0
            or self.max_results > 10_000
        ):
            raise RelationContractError(
                "relation read maximum must be between 1 and 10000"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "required_scope": self.required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "max_results": self.max_results,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError(
                "relation reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self.max_results
        ):
            raise PermissionError("relation read limit exceeds the read policy")


def _require_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise RelationContractError(f"{field} must be bounded canonical text")
    return value


def _require_text_tuple(
    value: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = False,
    maximum_items: int = 32,
    maximum_item_bytes: int = 1024,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise RelationContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not value:
        raise RelationContractError(f"{field} cannot be empty")
    if len(value) > maximum_items:
        raise RelationContractError(f"{field} exceeds its item bound")
    normalized = tuple(
        _require_text(item, field=field, maximum_bytes=maximum_item_bytes)
        for item in value
    )
    if tuple(sorted(set(normalized))) != normalized:
        raise RelationContractError(f"{field} must be sorted and unique")
    return normalized


@dataclass(frozen=True, slots=True)
class RelationEndpoint:
    record_type: RelationRecordType
    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.record_type, RelationRecordType):
            raise RelationContractError("relation endpoint type must be typed")
        # Current fixture identities are UUIDv4. The endpoint remains a typed
        # engine-neutral reference rather than a Neo4j internal identifier.
        UUIDv4Id.parse(self.record_id)

    def canonical_value(self) -> dict[str, str]:
        return {
            "record_type": self.record_type.value,
            "record_id": self.record_id,
        }


@dataclass(frozen=True, slots=True)
class RelationTemporalScope:
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    precision: str = "EXACT"

    def __post_init__(self) -> None:
        if not isinstance(self.valid_from, UtcTimestamp):
            raise RelationContractError("relation valid_from must be typed UTC")
        if self.valid_until is not None and not isinstance(
            self.valid_until, UtcTimestamp
        ):
            raise RelationContractError("relation valid_until must be typed UTC")
        if (
            self.valid_until is not None
            and self.valid_until.value <= self.valid_from.value
        ):
            raise RelationContractError(
                "relation valid_until must follow valid_from"
            )
        if self.precision != "EXACT":
            raise RelationContractError(
                "Increment 2A fixture relation requires exact temporal scope"
            )

    def canonical_value(self) -> dict[str, str | None]:
        return {
            "valid_from": self.valid_from.to_text(),
            "valid_until": (
                None if self.valid_until is None else self.valid_until.to_text()
            ),
            "precision": self.precision,
        }


@dataclass(frozen=True, slots=True)
class RelationProducer:
    kind: RelationProducerKind
    producer_id: str
    producer_version: str
    rule_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RelationProducerKind):
            raise RelationContractError("relation producer kind must be typed")
        for field_name in (
            "producer_id",
            "producer_version",
            "rule_version",
        ):
            require_token(getattr(self, field_name), field=field_name)

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "rule_version": self.rule_version,
        }


@dataclass(frozen=True, slots=True)
class FixturePassageObject:
    passage_id: str
    admission_id: ObjectAdmissionId
    blob_digest: str

    def __post_init__(self) -> None:
        require_token(self.passage_id, field="fixture_passage_id")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise RelationContractError(
                "fixture passage admission identity must be typed"
            )
        normalized = validate_sha256_digest(
            self.blob_digest, field="fixture_passage_blob_digest"
        )
        if normalized != self.blob_digest:
            raise RelationContractError(
                "fixture passage digest must be canonical lowercase"
            )

    def canonical_value(self) -> dict[str, str]:
        return {
            "passage_id": self.passage_id,
            "admission_id": str(self.admission_id),
            "blob_digest": self.blob_digest,
        }


@dataclass(frozen=True, slots=True)
class FixturePassageLifecycleLink:
    """Exact governed-object lifecycle evidence observed at fixture binding."""

    passage_id: str
    expected_lifecycle: str
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        require_token(self.passage_id, field="fixture_passage_id")
        if self.expected_lifecycle not in {"ACTIVE", "TOMBSTONED"}:
            raise RelationContractError(
                "fixture passage lifecycle link has an invalid state"
            )
        if not isinstance(self.authority_event_id, EventId):
            raise RelationContractError(
                "fixture passage lifecycle event identity must be typed"
            )
        if (
            isinstance(self.authority_ledger_seq, bool)
            or not isinstance(self.authority_ledger_seq, int)
            or self.authority_ledger_seq <= 0
        ):
            raise RelationContractError(
                "fixture passage lifecycle ledger sequence must be positive"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise RelationContractError(
                "fixture passage lifecycle time must be typed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": self.passage_id,
            "expected_lifecycle": self.expected_lifecycle,
            "authority_event_id": str(self.authority_event_id),
            "authority_ledger_seq": self.authority_ledger_seq,
            "recorded_at": self.recorded_at.to_text(),
        }


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2BindingRequest:
    binding_id: IntegratedFixtureV2BindingId
    fixture_id: str
    schema_version: str
    fixture_digest: str
    manifest_admission_id: ObjectAdmissionId
    manifest_blob_digest: str
    passage_objects: tuple[FixturePassageObject, ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding_id, IntegratedFixtureV2BindingId):
            raise RelationContractError("fixture binding identity must be typed")
        UUIDv4Id.parse(self.fixture_id)
        if self.schema_version != "integrated_fixture_v2":
            raise RelationContractError(
                "fixture binding requires integrated_fixture_v2"
            )
        for field_name in ("fixture_digest", "manifest_blob_digest"):
            normalized = validate_sha256_digest(
                getattr(self, field_name), field=field_name
            )
            if normalized != getattr(self, field_name):
                raise RelationContractError(
                    f"{field_name} must be canonical lowercase"
                )
        if self.fixture_digest != self.manifest_blob_digest:
            raise RelationContractError(
                "fixture manifest object must equal canonical fixture bytes"
            )
        if not isinstance(self.manifest_admission_id, ObjectAdmissionId):
            raise RelationContractError(
                "fixture manifest admission identity must be typed"
            )
        if not isinstance(self.passage_objects, tuple) or not self.passage_objects:
            raise RelationContractError(
                "fixture binding requires immutable passage objects"
            )
        if not all(
            isinstance(item, FixturePassageObject)
            for item in self.passage_objects
        ):
            raise RelationContractError(
                "fixture binding passage objects must be typed"
            )
        passage_ids = tuple(item.passage_id for item in self.passage_objects)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise RelationContractError(
                "fixture passage objects must be sorted and unique"
            )
        _require_text(
            self.idempotency_key,
            field="fixture_binding_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "binding_id": str(self.binding_id),
            "fixture_id": self.fixture_id,
            "schema_version": self.schema_version,
            "fixture_digest": self.fixture_digest,
            "manifest_admission_id": str(self.manifest_admission_id),
            "manifest_blob_digest": self.manifest_blob_digest,
            "passage_objects": [
                item.canonical_value() for item in self.passage_objects
            ],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2Binding:
    binding_id: IntegratedFixtureV2BindingId
    fixture_id: str
    schema_version: str
    fixture_digest: str
    manifest_admission_id: ObjectAdmissionId
    manifest_blob_digest: str
    passage_objects: tuple[FixturePassageObject, ...]
    passage_lifecycle_links: tuple[FixturePassageLifecycleLink, ...]
    authority_event_id: EventId
    authority_ledger_seq: int
    authority_aggregate_version: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.binding_id, IntegratedFixtureV2BindingId):
            raise RelationContractError("fixture binding identity must be typed")
        UUIDv4Id.parse(self.fixture_id)
        if self.schema_version != "integrated_fixture_v2":
            raise RelationContractError("fixture binding schema is invalid")
        for field_name in ("fixture_digest", "manifest_blob_digest"):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if self.fixture_digest != self.manifest_blob_digest:
            raise RelationContractError("fixture binding digest mismatch")
        if not isinstance(self.manifest_admission_id, ObjectAdmissionId):
            raise RelationContractError("manifest admission identity must be typed")
        if not isinstance(self.passage_objects, tuple) or not all(
            isinstance(item, FixturePassageObject)
            for item in self.passage_objects
        ):
            raise RelationContractError(
                "fixture binding passage objects must be typed"
            )
        passage_ids = tuple(item.passage_id for item in self.passage_objects)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise RelationContractError(
                "fixture binding passage objects must be sorted and unique"
            )
        if not isinstance(self.passage_lifecycle_links, tuple) or not all(
            isinstance(item, FixturePassageLifecycleLink)
            for item in self.passage_lifecycle_links
        ):
            raise RelationContractError(
                "fixture binding lifecycle links must be typed"
            )
        lifecycle_ids = tuple(
            item.passage_id for item in self.passage_lifecycle_links
        )
        if lifecycle_ids != passage_ids:
            raise RelationContractError(
                "fixture binding lifecycle links must cover every passage exactly"
            )
        if not isinstance(self.authority_event_id, EventId):
            raise RelationContractError("fixture authority event must be typed")
        for field_name in ("authority_ledger_seq", "authority_aggregate_version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise RelationContractError(f"{field_name} must be positive")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise RelationContractError("fixture binding time must be typed")
        if not isinstance(self.replayed, bool):
            raise RelationContractError("fixture binding replay flag must be boolean")


@dataclass(frozen=True, slots=True)
class RelationProposalRequest:
    proposal_id: RelationProposalId
    fixture_binding_id: IntegratedFixtureV2BindingId
    subject: RelationEndpoint
    predicate: RelationPredicate
    object: RelationEndpoint
    temporal_scope: RelationTemporalScope
    evidence_passage_ids: tuple[str, ...]
    producer: RelationProducer
    statement: str
    uncertainties: tuple[str, ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, RelationProposalId):
            raise RelationContractError("relation proposal identity must be typed")
        if not isinstance(
            self.fixture_binding_id, IntegratedFixtureV2BindingId
        ):
            raise RelationContractError("fixture binding identity must be typed")
        if not isinstance(self.subject, RelationEndpoint) or not isinstance(
            self.object, RelationEndpoint
        ):
            raise RelationContractError("relation endpoints must be typed")
        if self.subject == self.object:
            raise RelationContractError("relation endpoints must be distinct")
        if not isinstance(self.predicate, RelationPredicate):
            raise RelationContractError("relation predicate must be typed")
        if not isinstance(self.temporal_scope, RelationTemporalScope):
            raise RelationContractError("relation temporal scope must be typed")
        object.__setattr__(
            self,
            "evidence_passage_ids",
            _require_text_tuple(
                self.evidence_passage_ids,
                field="evidence_passage_ids",
                maximum_items=16,
                maximum_item_bytes=128,
            ),
        )
        if not isinstance(self.producer, RelationProducer):
            raise RelationContractError("relation producer must be typed")
        _require_text(self.statement, field="relation_statement")
        object.__setattr__(
            self,
            "uncertainties",
            _require_text_tuple(
                self.uncertainties,
                field="relation_uncertainties",
                allow_empty=True,
                maximum_items=16,
                maximum_item_bytes=512,
            ),
        )
        _require_text(
            self.idempotency_key,
            field="relation_proposal_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "fixture_binding_id": str(self.fixture_binding_id),
            "subject": self.subject.canonical_value(),
            "predicate": self.predicate.value,
            "object": self.object.canonical_value(),
            "trust_scope": TrustScope.PROPOSED.value,
            "temporal_scope": self.temporal_scope.canonical_value(),
            "evidence_passage_ids": list(self.evidence_passage_ids),
            "producer": self.producer.canonical_value(),
            "statement": self.statement,
            "uncertainties": list(self.uncertainties),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def proposal_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_slot_digest(self) -> str:
        return digest_canonical(
            {
                "subject": self.subject.canonical_value(),
                "predicate": self.predicate.value,
                "object": self.object.canonical_value(),
                "temporal_scope": self.temporal_scope.canonical_value(),
            }
        )

    @property
    def semantic_identity_digest(self) -> str:
        value = self.canonical_value().copy()
        value.pop("proposal_id")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class RelationProposal:
    proposal_id: RelationProposalId
    fixture_binding_id: IntegratedFixtureV2BindingId
    subject: RelationEndpoint
    predicate: RelationPredicate
    object: RelationEndpoint
    temporal_scope: RelationTemporalScope
    evidence_passage_ids: tuple[str, ...]
    evidence_objects: tuple[FixturePassageObject, ...]
    producer: RelationProducer
    statement: str
    uncertainties: tuple[str, ...]
    proposal_digest: str
    semantic_slot_digest: str
    semantic_identity_digest: str
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, RelationProposalId):
            raise RelationContractError("relation proposal identity must be typed")
        if not isinstance(
            self.fixture_binding_id, IntegratedFixtureV2BindingId
        ):
            raise RelationContractError("fixture binding identity must be typed")
        if not isinstance(self.subject, RelationEndpoint) or not isinstance(
            self.object, RelationEndpoint
        ):
            raise RelationContractError("relation endpoints must be typed")
        if self.subject == self.object:
            raise RelationContractError("relation endpoints must be distinct")
        if not isinstance(self.predicate, RelationPredicate):
            raise RelationContractError("relation predicate must be typed")
        if not isinstance(self.temporal_scope, RelationTemporalScope):
            raise RelationContractError("relation temporal scope must be typed")
        _require_text_tuple(
            self.evidence_passage_ids,
            field="evidence_passage_ids",
            maximum_items=16,
            maximum_item_bytes=128,
        )
        if not isinstance(self.evidence_objects, tuple) or not all(
            isinstance(item, FixturePassageObject)
            for item in self.evidence_objects
        ):
            raise RelationContractError(
                "relation proposal evidence objects must be a typed tuple"
            )
        object_ids = tuple(item.passage_id for item in self.evidence_objects)
        if object_ids != self.evidence_passage_ids:
            raise RelationContractError(
                "relation proposal evidence objects must resolve every passage exactly"
            )
        if not isinstance(self.producer, RelationProducer):
            raise RelationContractError("relation producer must be typed")
        _require_text(self.statement, field="relation_statement")
        _require_text_tuple(
            self.uncertainties,
            field="relation_uncertainties",
            allow_empty=True,
            maximum_items=16,
            maximum_item_bytes=512,
        )
        for field_name in (
            "proposal_digest",
            "semantic_slot_digest",
            "semantic_identity_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.authority_event_id, EventId):
            raise RelationContractError("proposal authority event must be typed")
        if (
            isinstance(self.authority_ledger_seq, bool)
            or not isinstance(self.authority_ledger_seq, int)
            or self.authority_ledger_seq <= 0
        ):
            raise RelationContractError("proposal ledger sequence must be positive")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise RelationContractError("proposal time must be typed")
        if not isinstance(self.replayed, bool):
            raise RelationContractError("proposal replay flag must be boolean")

    @property
    def trust_scope(self) -> TrustScope:
        return TrustScope.PROPOSED

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "fixture_binding_id": str(self.fixture_binding_id),
            "subject": self.subject.canonical_value(),
            "predicate": self.predicate.value,
            "object": self.object.canonical_value(),
            "trust_scope": self.trust_scope.value,
            "temporal_scope": self.temporal_scope.canonical_value(),
            "evidence_passage_ids": list(self.evidence_passage_ids),
            "producer": self.producer.canonical_value(),
            "statement": self.statement,
            "uncertainties": list(self.uncertainties),
        }


@dataclass(frozen=True, slots=True)
class RelationDecisionRequest:
    proposal_id: RelationProposalId
    action: RelationDecisionAction
    expected_proposal_digest: str
    expected_decision_version: int
    expected_previous_decision_id: RelationAdmissionDecisionId | None
    reason_code: str
    decision_policy_version: str
    successor_proposal_id: RelationProposalId | None
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, RelationProposalId):
            raise RelationContractError("decision proposal identity must be typed")
        if not isinstance(self.action, RelationDecisionAction):
            raise RelationContractError("decision action must be typed")
        normalized = validate_sha256_digest(
            self.expected_proposal_digest,
            field="expected_proposal_digest",
        )
        if normalized != self.expected_proposal_digest:
            raise RelationContractError(
                "expected proposal digest must be canonical lowercase"
            )
        if (
            isinstance(self.expected_decision_version, bool)
            or not isinstance(self.expected_decision_version, int)
            or self.expected_decision_version < 0
        ):
            raise RelationContractError(
                "expected decision version must be non-negative"
            )
        if self.expected_decision_version == 0:
            if self.expected_previous_decision_id is not None:
                raise RelationContractError(
                    "initial decision cannot name a previous decision"
                )
        elif not isinstance(
            self.expected_previous_decision_id, RelationAdmissionDecisionId
        ):
            raise RelationContractError(
                "later decision requires the exact previous decision identity"
            )
        require_token(self.reason_code, field="relation_decision_reason_code")
        require_token(
            self.decision_policy_version,
            field="relation_decision_policy_version",
        )
        if self.action is RelationDecisionAction.SUPERSEDE:
            if not isinstance(self.successor_proposal_id, RelationProposalId):
                raise RelationContractError(
                    "supersession requires a successor proposal identity"
                )
            if self.successor_proposal_id == self.proposal_id:
                raise RelationContractError(
                    "proposal cannot supersede itself"
                )
        elif self.successor_proposal_id is not None:
            raise RelationContractError(
                "only supersession may name a successor proposal"
            )
        _require_text(
            self.idempotency_key,
            field="relation_decision_idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "action": self.action.value,
            "expected_proposal_digest": self.expected_proposal_digest,
            "expected_decision_version": self.expected_decision_version,
            "expected_previous_decision_id": (
                None
                if self.expected_previous_decision_id is None
                else str(self.expected_previous_decision_id)
            ),
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
            "successor_proposal_id": (
                None
                if self.successor_proposal_id is None
                else str(self.successor_proposal_id)
            ),
        }


@dataclass(frozen=True, slots=True)
class RelationAdmissionDecision:
    decision_id: RelationAdmissionDecisionId
    proposal_id: RelationProposalId
    action: RelationDecisionAction
    decision_version: int
    previous_decision_id: RelationAdmissionDecisionId | None
    proposal_digest: str
    reason_code: str
    decision_policy_version: str
    successor_proposal_id: RelationProposalId | None
    assertion_id: RelationAssertionId | None
    authority_event_id: EventId
    authority_ledger_seq: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, RelationAdmissionDecisionId):
            raise RelationContractError("relation decision identity must be typed")
        if not isinstance(self.proposal_id, RelationProposalId):
            raise RelationContractError("relation proposal identity must be typed")
        if not isinstance(self.action, RelationDecisionAction):
            raise RelationContractError("relation decision action must be typed")
        if (
            isinstance(self.decision_version, bool)
            or not isinstance(self.decision_version, int)
            or self.decision_version <= 0
        ):
            raise RelationContractError("decision version must be positive")
        if self.decision_version == 1 and self.previous_decision_id is not None:
            raise RelationContractError(
                "first relation decision cannot have a predecessor"
            )
        if self.decision_version > 1 and not isinstance(
            self.previous_decision_id, RelationAdmissionDecisionId
        ):
            raise RelationContractError(
                "later relation decision requires predecessor identity"
            )
        validate_sha256_digest(self.proposal_digest, field="proposal_digest")
        require_token(self.reason_code, field="relation_decision_reason_code")
        require_token(
            self.decision_policy_version,
            field="relation_decision_policy_version",
        )
        if self.action is RelationDecisionAction.ADMIT:
            if not isinstance(self.assertion_id, RelationAssertionId):
                raise RelationContractError(
                    "admission decision requires assertion identity"
                )
        elif self.assertion_id is not None:
            raise RelationContractError(
                "non-admission decision cannot allocate assertion identity"
            )
        if self.action is RelationDecisionAction.SUPERSEDE:
            if not isinstance(self.successor_proposal_id, RelationProposalId):
                raise RelationContractError(
                    "supersession decision requires successor proposal"
                )
        elif self.successor_proposal_id is not None:
            raise RelationContractError(
                "only supersession decision may name a successor proposal"
            )
        if not isinstance(self.authority_event_id, EventId):
            raise RelationContractError("decision authority event must be typed")
        if (
            isinstance(self.authority_ledger_seq, bool)
            or not isinstance(self.authority_ledger_seq, int)
            or self.authority_ledger_seq <= 0
        ):
            raise RelationContractError("decision ledger sequence must be positive")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise RelationContractError("decision time must be typed")


@dataclass(frozen=True, slots=True)
class RelationAssertion:
    assertion_id: RelationAssertionId
    proposal_id: RelationProposalId
    admission_decision_id: RelationAdmissionDecisionId
    subject: RelationEndpoint
    predicate: RelationPredicate
    object: RelationEndpoint
    temporal_scope: RelationTemporalScope
    evidence_objects: tuple[FixturePassageObject, ...]
    producer: RelationProducer
    statement: str
    uncertainties: tuple[str, ...]
    proposal_digest: str
    relation_key: str
    admitted_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.assertion_id, RelationAssertionId):
            raise RelationContractError("relation assertion identity must be typed")
        if not isinstance(self.proposal_id, RelationProposalId):
            raise RelationContractError("assertion proposal identity must be typed")
        if not isinstance(
            self.admission_decision_id, RelationAdmissionDecisionId
        ):
            raise RelationContractError("assertion decision identity must be typed")
        if not isinstance(self.subject, RelationEndpoint) or not isinstance(
            self.object, RelationEndpoint
        ):
            raise RelationContractError("assertion endpoints must be typed")
        if self.subject == self.object:
            raise RelationContractError("assertion endpoints must be distinct")
        if not isinstance(self.predicate, RelationPredicate):
            raise RelationContractError("assertion predicate must be typed")
        if not isinstance(self.temporal_scope, RelationTemporalScope):
            raise RelationContractError("assertion temporal scope must be typed")
        if not isinstance(self.evidence_objects, tuple) or not self.evidence_objects:
            raise RelationContractError(
                "assertion evidence objects must be a non-empty tuple"
            )
        if not all(
            isinstance(item, FixturePassageObject)
            for item in self.evidence_objects
        ):
            raise RelationContractError(
                "assertion evidence objects must be typed"
            )
        passage_ids = tuple(item.passage_id for item in self.evidence_objects)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise RelationContractError(
                "assertion evidence objects must be sorted and unique"
            )
        if not isinstance(self.producer, RelationProducer):
            raise RelationContractError("assertion producer must be typed")
        _require_text(self.statement, field="assertion_statement")
        _require_text_tuple(
            self.uncertainties,
            field="assertion_uncertainties",
            allow_empty=True,
            maximum_items=16,
            maximum_item_bytes=512,
        )
        validate_sha256_digest(self.proposal_digest, field="proposal_digest")
        validate_sha256_digest(self.relation_key, field="relation_key")
        if not isinstance(self.admitted_at, UtcTimestamp):
            raise RelationContractError("assertion admission time must be typed")

    @property
    def trust_scope(self) -> TrustScope:
        return TrustScope.ADMITTED

    @property
    def evidence_passage_ids(self) -> tuple[str, ...]:
        return tuple(item.passage_id for item in self.evidence_objects)

    @property
    def evidence_admission_ids(self) -> tuple[ObjectAdmissionId, ...]:
        return tuple(item.admission_id for item in self.evidence_objects)

    def canonical_value(self) -> dict[str, object]:
        return {
            "assertion_id": str(self.assertion_id),
            "proposal_id": str(self.proposal_id),
            "admission_decision_id": str(self.admission_decision_id),
            "subject": self.subject.canonical_value(),
            "predicate": self.predicate.value,
            "object": self.object.canonical_value(),
            "trust_scope": self.trust_scope.value,
            "temporal_scope": self.temporal_scope.canonical_value(),
            "evidence_objects": [
                item.canonical_value() for item in self.evidence_objects
            ],
            "producer": self.producer.canonical_value(),
            "statement": self.statement,
            "uncertainties": list(self.uncertainties),
            "proposal_digest": self.proposal_digest,
            "relation_key": self.relation_key,
            "admitted_at": self.admitted_at.to_text(),
        }


@dataclass(frozen=True, slots=True)
class RelationProjectionEvent:
    action: RelationProjectionAction
    assertion_id: RelationAssertionId
    relation_key: str
    source_event_id: EventId
    source_ledger_seq: int
    reason_code: str
    assertion: RelationAssertion | None
    tombstone_object_admission_ids: tuple[ObjectAdmissionId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.action, RelationProjectionAction):
            raise RelationContractError("projection action must be typed")
        if not isinstance(self.assertion_id, RelationAssertionId):
            raise RelationContractError("projection assertion identity must be typed")
        validate_sha256_digest(self.relation_key, field="relation_key")
        if not isinstance(self.source_event_id, EventId):
            raise RelationContractError("projection source event must be typed")
        if (
            isinstance(self.source_ledger_seq, bool)
            or not isinstance(self.source_ledger_seq, int)
            or self.source_ledger_seq <= 0
        ):
            raise RelationContractError(
                "projection source ledger sequence must be positive"
            )
        require_token(self.reason_code, field="projection_reason_code")
        if self.action is RelationProjectionAction.UPSERT:
            if not isinstance(self.assertion, RelationAssertion):
                raise RelationContractError(
                    "projection UPSERT requires admitted assertion"
                )
            if self.tombstone_object_admission_ids:
                raise RelationContractError(
                    "projection UPSERT cannot carry tombstones"
                )
        else:
            if self.assertion is not None:
                raise RelationContractError(
                    "projection REMOVE cannot expose admitted assertion payload"
                )
            if not isinstance(self.tombstone_object_admission_ids, tuple):
                raise RelationContractError(
                    "projection tombstone identities must be immutable"
                )
            if not all(
                isinstance(item, ObjectAdmissionId)
                for item in self.tombstone_object_admission_ids
            ):
                raise RelationContractError(
                    "projection tombstone identities must be typed"
                )
            identities = tuple(
                str(item) for item in self.tombstone_object_admission_ids
            )
            if identities != tuple(sorted(set(identities))):
                raise RelationContractError(
                    "projection tombstone identities must be sorted and unique"
                )


@dataclass(frozen=True, slots=True)
class RelationDecisionResult:
    decision: RelationAdmissionDecision
    assertion: RelationAssertion | None
    current_state: RelationCurrentState

    def __post_init__(self) -> None:
        if not isinstance(self.decision, RelationAdmissionDecision):
            raise RelationContractError("decision result requires typed decision")
        if self.assertion is not None and not isinstance(
            self.assertion, RelationAssertion
        ):
            raise RelationContractError("decision assertion must be typed")
        if not isinstance(self.current_state, RelationCurrentState):
            raise RelationContractError("current relation state must be typed")


def sorted_passage_objects(
    values: Iterable[FixturePassageObject],
) -> tuple[FixturePassageObject, ...]:
    return tuple(sorted(values, key=lambda item: item.passage_id))


__all__ = [
    "FixturePassageObject",
    "FixturePassageLifecycleLink",
    "IntegratedFixtureV2Binding",
    "IntegratedFixtureV2BindingId",
    "IntegratedFixtureV2BindingRequest",
    "RelationAdmissionDecision",
    "RelationAdmissionDecisionId",
    "RelationAssertion",
    "RelationAssertionId",
    "RelationAuthorityError",
    "RelationConflict",
    "RelationContractError",
    "RelationCurrentState",
    "RelationDecisionAction",
    "RelationDecisionRequest",
    "RelationDecisionResult",
    "RelationEndpoint",
    "RelationPredicate",
    "RelationProducer",
    "RelationProducerKind",
    "RelationProjectionAction",
    "RelationProjectionEvent",
    "RelationProposal",
    "RelationProposalId",
    "RelationProposalRequest",
    "RelationReadPolicy",
    "RelationRecordType",
    "RelationSemanticCollision",
    "RelationStaleDecision",
    "RelationStateError",
    "RelationTemporalScope",
    "sorted_passage_objects",
]
