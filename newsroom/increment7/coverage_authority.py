"""Checked Coverage Audit and Gap persistence with deterministic assessment.

The authority retains caller-supplied fixture/replay records only. It has no
clock, provider, credential, network, scheduler, evidence acquisition,
publication or production activation capability. Comparators and Gap decisions
remain best-effort review assertions rather than ground truth.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.migrations import (
    SCHEMA_VERSION,
    apply_pending_migrations,
    prepare_pending_migration_backup,
)
from newsroom.increment7.coverage import (
    CoverageAssessmentState,
    CoverageAudit,
    CoverageComparator,
    CoverageGap,
    CoverageGapDecision,
    CoverageObservationKind,
    validate_coverage_chain,
)
from newsroom.increment7.locality_qualification import (
    LocalityCoverageDecision,
    LocalityCoverageProposal,
    LocalityCoverageUnit,
    LocalityReference,
    validate_locality_coverage_chain,
)
from newsroom.increment7.provider_qualification import (
    ProviderDecision,
    ProviderProposal,
)
from newsroom.increment7.search import (
    SearchAttempt,
    SearchOutcome,
    SearchPurpose,
    SearchRequest,
    SearchResultReference,
    SearchReviewDecision,
    validate_search_attempt,
    validate_search_outcome,
    validate_search_request,
    validate_search_result,
    validate_search_review,
)

COVERAGE_COMMAND = "newsroom.increment7.coverage-command.v1"
COVERAGE_ASSESSMENT = "newsroom.increment7.coverage-assessment.v1"
COVERAGE_AUDIT_AUTHORITY = "CHECKED_SQLITE_TRANSACTIONAL_V28"
COVERAGE_ASSESSMENT_AUTHORITY = "DETERMINISTIC_DEPENDENCY_TIMELINESS_HEALTH"
MAX_COVERAGE_COMMAND_BYTES = 8_388_608

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class CoverageAuthorityError(ValueError):
    """An assessment, command, retained row or identity binding failed closed."""


class DependencyState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class TimelinessState(StrEnum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    UNKNOWN = "UNKNOWN"


class HealthState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class _NoEffect:
    authorises_external_effect = False
    authorises_search = False
    authorises_provider = False
    authorises_locality = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_evidence = False
    authorises_publication = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    creates_watch = False
    comparator_is_ground_truth = False
    gap_is_automatic_truth = False
    production_activation_authorised = False


def _total(label: str):
    def decorate(function):
        def wrapped(*args: object, **kwargs: object):
            try:
                return function(*args, **kwargs)
            except CoverageAuthorityError:
                raise
            except Exception as exc:
                raise CoverageAuthorityError(label) from exc

        return wrapped

    return decorate


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise CoverageAuthorityError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CoverageAuthorityError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise CoverageAuthorityError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise CoverageAuthorityError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise CoverageAuthorityError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise CoverageAuthorityError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise CoverageAuthorityError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise CoverageAuthorityError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise CoverageAuthorityError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise CoverageAuthorityError(f"{field} differs") from exc


def _strings(
    value: object, field: str, *, required: bool = False, digests: bool = False
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > 256 or (required and not value):
        raise CoverageAuthorityError(f"{field} must be a bounded array")
    validator = _digest if digests else _token
    result = tuple(validator(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise CoverageAuthorityError(f"{field} must be unique and sorted")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CoverageAuthorityError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_COVERAGE_COMMAND_BYTES:
        raise CoverageAuthorityError("Coverage document bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except CoverageAuthorityError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise CoverageAuthorityError("Coverage document is not canonical JSON") from exc
    if type(value) is not dict or raw != canonical:
        raise CoverageAuthorityError("Coverage document is not exact canonical JSON")
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise CoverageAuthorityError("Coverage document fields or schema differ")
    return value


def _embedded(record: object) -> dict[str, object]:
    return json.loads(record.canonical_bytes)


def _embedded_record(value: object, field: str, kind):
    if type(value) is not dict:
        raise CoverageAuthorityError(f"{field} differs")
    return kind.from_canonical_bytes(canonical_json_bytes(value))


_FACTOR_FIELDS = ("evidence_digest", "factor_key", "state")


@dataclass(frozen=True, slots=True)
class AssessmentFactor(_NoEffect):
    factor_key: str
    state: DependencyState | TimelinessState | HealthState
    evidence_digest: str

    def __post_init__(self) -> None:
        _token(self.factor_key, "factor_key")
        if type(self.state) not in (DependencyState, TimelinessState, HealthState):
            raise CoverageAuthorityError("assessment factor state differs")
        _digest(self.evidence_digest, "evidence_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_digest": self.evidence_digest,
            "factor_key": self.factor_key,
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, value: object, state_kind):
        if type(value) is not dict or tuple(value) != _FACTOR_FIELDS:
            raise CoverageAuthorityError("assessment factor fields differ")
        return cls(
            factor_key=value["factor_key"],
            state=_enum(state_kind, value["state"], "state"),
            evidence_digest=value["evidence_digest"],
        )


_ASSESSMENT_FIELDS = (
    "schema_version",
    "assessment_id",
    "dependency_factors",
    "timeliness_factors",
    "health_factors",
    "declared_limitation_codes",
    "derived_state",
    "derived_limitation_codes",
    "assessed_at",
)


def _factor_limitations(
    prefix: str, factors: tuple[AssessmentFactor, ...], healthy: StrEnum
) -> set[str]:
    return {
        f"{prefix}.{factor.factor_key}.{factor.state.value.lower()}"
        for factor in factors
        if factor.state is not healthy
    }


def deterministic_assessment(
    dependency_factors: tuple[AssessmentFactor, ...],
    timeliness_factors: tuple[AssessmentFactor, ...],
    health_factors: tuple[AssessmentFactor, ...],
    declared_limitation_codes: tuple[str, ...],
) -> tuple[CoverageAssessmentState, tuple[str, ...]]:
    groups = (
        (dependency_factors, DependencyState),
        (timeliness_factors, TimelinessState),
        (health_factors, HealthState),
    )
    for factors, kind in groups:
        if type(factors) is not tuple or not factors or len(factors) > 64:
            raise CoverageAuthorityError("assessment factors must be bounded")
        if any(
            type(item) is not AssessmentFactor or type(item.state) is not kind
            for item in factors
        ):
            raise CoverageAuthorityError("assessment factor vocabulary differs")
        if tuple(item.factor_key for item in factors) != tuple(
            sorted({item.factor_key for item in factors})
        ):
            raise CoverageAuthorityError("assessment factors must be unique and sorted")
    declared = _strings(
        declared_limitation_codes,
        "declared_limitation_codes",
        required=True,
    )
    deferred = (
        any(
            item.state in (DependencyState.UNAVAILABLE, DependencyState.UNKNOWN)
            for item in dependency_factors
        )
        or any(item.state is TimelinessState.UNKNOWN for item in timeliness_factors)
        or any(
            item.state in (HealthState.UNAVAILABLE, HealthState.UNKNOWN)
            for item in health_factors
        )
    )
    partial = (
        any(item.state is DependencyState.DEGRADED for item in dependency_factors)
        or any(item.state is TimelinessState.LATE for item in timeliness_factors)
        or any(item.state is HealthState.DEGRADED for item in health_factors)
    )
    state = (
        CoverageAssessmentState.DEFERRED
        if deferred
        else CoverageAssessmentState.PARTIAL_LIMITED
        if partial
        else CoverageAssessmentState.COMPLETE_BEST_EFFORT
    )
    limitations = set(declared)
    limitations.update(
        _factor_limitations("dependency", dependency_factors, DependencyState.AVAILABLE)
    )
    limitations.update(
        _factor_limitations("timeliness", timeliness_factors, TimelinessState.ON_TIME)
    )
    limitations.update(
        _factor_limitations("health", health_factors, HealthState.HEALTHY)
    )
    return state, tuple(sorted(limitations))


@dataclass(frozen=True, slots=True)
class CoverageAssessment(_NoEffect):
    assessment_id: str
    dependency_factors: tuple[AssessmentFactor, ...]
    timeliness_factors: tuple[AssessmentFactor, ...]
    health_factors: tuple[AssessmentFactor, ...]
    declared_limitation_codes: tuple[str, ...]
    derived_state: CoverageAssessmentState
    derived_limitation_codes: tuple[str, ...]
    assessed_at: str
    schema_version: str = COVERAGE_ASSESSMENT

    def __post_init__(self) -> None:
        if self.schema_version != COVERAGE_ASSESSMENT:
            raise CoverageAuthorityError("Coverage Assessment schema differs")
        _uuid(self.assessment_id, "assessment_id")
        object.__setattr__(
            self,
            "derived_state",
            _enum(CoverageAssessmentState, self.derived_state, "derived_state"),
        )
        expected_state, expected_codes = deterministic_assessment(
            self.dependency_factors,
            self.timeliness_factors,
            self.health_factors,
            self.declared_limitation_codes,
        )
        object.__setattr__(
            self,
            "declared_limitation_codes",
            _strings(
                self.declared_limitation_codes,
                "declared_limitation_codes",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "derived_limitation_codes",
            _strings(
                self.derived_limitation_codes,
                "derived_limitation_codes",
                required=True,
            ),
        )
        if (
            self.derived_state is not expected_state
            or self.derived_limitation_codes != expected_codes
        ):
            raise CoverageAuthorityError("Coverage Assessment derivation differs")
        _timestamp(self.assessed_at, "assessed_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "assessed_at": self.assessed_at,
                "assessment_id": self.assessment_id,
                "declared_limitation_codes": list(self.declared_limitation_codes),
                "dependency_factors": [
                    item.to_dict() for item in self.dependency_factors
                ],
                "derived_limitation_codes": list(self.derived_limitation_codes),
                "derived_state": self.derived_state.value,
                "health_factors": [item.to_dict() for item in self.health_factors],
                "schema_version": self.schema_version,
                "timeliness_factors": [
                    item.to_dict() for item in self.timeliness_factors
                ],
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, COVERAGE_ASSESSMENT, _ASSESSMENT_FIELDS)
        for field, kind in (
            ("dependency_factors", DependencyState),
            ("timeliness_factors", TimelinessState),
            ("health_factors", HealthState),
        ):
            items = value[field]
            if type(items) is not list:
                raise CoverageAuthorityError("assessment factors must be arrays")
            value[field] = tuple(
                AssessmentFactor.from_dict(item, kind) for item in items
            )
        for field in ("declared_limitation_codes", "derived_limitation_codes"):
            if type(value[field]) is not list:
                raise CoverageAuthorityError("assessment limitations must be arrays")
            value[field] = tuple(value[field])
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise CoverageAuthorityError("Coverage Assessment replay differs")
        return result


_COMMAND_FIELDS = (
    "schema_version",
    "command_id",
    "comparator",
    "assessment",
    "audit",
    "gap",
    "decision",
    "search_request_digests",
    "search_result_digests",
    "search_review_decision_digests",
    "provider_decision_digests",
    "locality_reference_digest",
    "locality_coverage_unit_digest",
    "locality_decision_digest",
    "expected_previous_decision_digest",
    "request_id",
    "actor_identity_digest",
    "idempotency_key",
)


@dataclass(frozen=True, slots=True)
class CoverageCommand(_NoEffect):
    command_id: str
    comparator: CoverageComparator
    assessment: CoverageAssessment
    audit: CoverageAudit
    gap: CoverageGap
    decision: CoverageGapDecision
    search_request_digests: tuple[str, ...]
    search_result_digests: tuple[str, ...]
    search_review_decision_digests: tuple[str, ...]
    provider_decision_digests: tuple[str, ...]
    locality_reference_digest: str
    locality_coverage_unit_digest: str
    locality_decision_digest: str
    expected_previous_decision_digest: str | None
    request_id: str
    actor_identity_digest: str
    idempotency_key: str
    schema_version: str = COVERAGE_COMMAND

    def __post_init__(self) -> None:
        if self.schema_version != COVERAGE_COMMAND:
            raise CoverageAuthorityError("Coverage Command schema differs")
        for field in ("command_id", "request_id"):
            _uuid(getattr(self, field), field)
        for field, kind in (
            ("comparator", CoverageComparator),
            ("assessment", CoverageAssessment),
            ("audit", CoverageAudit),
            ("gap", CoverageGap),
            ("decision", CoverageGapDecision),
        ):
            if type(getattr(self, field)) is not kind:
                raise CoverageAuthorityError(f"Coverage Command {field} differs")
        for field in (
            "search_request_digests",
            "search_result_digests",
            "search_review_decision_digests",
            "provider_decision_digests",
        ):
            object.__setattr__(
                self,
                field,
                _strings(getattr(self, field), field, required=True, digests=True),
            )
        for field in (
            "locality_reference_digest",
            "locality_coverage_unit_digest",
            "locality_decision_digest",
            "actor_identity_digest",
        ):
            _digest(getattr(self, field), field)
        if self.expected_previous_decision_digest is not None:
            _digest(
                self.expected_previous_decision_digest,
                "expected_previous_decision_digest",
            )
        _token(self.idempotency_key, "idempotency_key")
        if (
            self.audit.assessment_state is not self.assessment.derived_state
            or self.audit.limitation_codes != self.assessment.derived_limitation_codes
            or self.audit.completed_at != self.assessment.assessed_at
            or self.comparator.search_request_digests != self.search_request_digests
            or self.locality_coverage_unit_digest
            not in self.comparator.coverage_unit_digests
            or self.decision.supersedes_decision_digest
            != self.expected_previous_decision_digest
        ):
            raise CoverageAuthorityError(
                "Coverage Command assessment or lineage differs"
            )

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "actor_identity_digest": self.actor_identity_digest,
                "assessment": _embedded(self.assessment),
                "audit": _embedded(self.audit),
                "command_id": self.command_id,
                "comparator": _embedded(self.comparator),
                "decision": _embedded(self.decision),
                "expected_previous_decision_digest": self.expected_previous_decision_digest,
                "gap": _embedded(self.gap),
                "idempotency_key": self.idempotency_key,
                "locality_coverage_unit_digest": self.locality_coverage_unit_digest,
                "locality_decision_digest": self.locality_decision_digest,
                "locality_reference_digest": self.locality_reference_digest,
                "provider_decision_digests": list(self.provider_decision_digests),
                "request_id": self.request_id,
                "schema_version": self.schema_version,
                "search_request_digests": list(self.search_request_digests),
                "search_result_digests": list(self.search_result_digests),
                "search_review_decision_digests": list(
                    self.search_review_decision_digests
                ),
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, COVERAGE_COMMAND, _COMMAND_FIELDS)
        for field, kind in (
            ("comparator", CoverageComparator),
            ("assessment", CoverageAssessment),
            ("audit", CoverageAudit),
            ("gap", CoverageGap),
            ("decision", CoverageGapDecision),
        ):
            value[field] = _embedded_record(value[field], field, kind)
        for field in (
            "search_request_digests",
            "search_result_digests",
            "search_review_decision_digests",
            "provider_decision_digests",
        ):
            if type(value[field]) is not list:
                raise CoverageAuthorityError(f"{field} must be an array")
            value[field] = tuple(value[field])
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise CoverageAuthorityError("Coverage Command replay differs")
        return result


type SearchEvidenceChain = tuple[
    SearchPurpose,
    SearchRequest,
    SearchAttempt,
    SearchOutcome,
    tuple[SearchResultReference, ...],
    SearchReviewDecision,
]
type ProviderQualification = tuple[
    ProviderProposal, ProviderDecision, tuple[ProviderDecision, ...]
]
type LocalityQualification = tuple[
    LocalityReference,
    LocalityCoverageUnit,
    LocalityCoverageProposal,
    LocalityCoverageDecision,
]


def validate_coverage_command(
    command: CoverageCommand,
    *,
    search_evidence: tuple[SearchEvidenceChain, ...],
    provider_qualifications: tuple[ProviderQualification, ...],
    locality_qualification: LocalityQualification,
    previous_decision: CoverageGapDecision | None = None,
) -> None:
    if type(command) is not CoverageCommand:
        raise CoverageAuthorityError("Coverage validation requires an exact command")
    if type(search_evidence) is not tuple or not search_evidence:
        raise CoverageAuthorityError("Coverage Search evidence differs")
    requests: list[SearchRequest] = []
    results: list[SearchResultReference] = []
    reviews: list[SearchReviewDecision] = []
    for chain in search_evidence:
        if type(chain) is not tuple or len(chain) != 6:
            raise CoverageAuthorityError("Coverage Search evidence differs")
        purpose, request, attempt, outcome, chain_results, review = chain
        if (
            type(purpose) is not SearchPurpose
            or type(request) is not SearchRequest
            or type(attempt) is not SearchAttempt
            or type(outcome) is not SearchOutcome
            or type(chain_results) is not tuple
            or not chain_results
            or any(type(item) is not SearchResultReference for item in chain_results)
            or type(review) is not SearchReviewDecision
        ):
            raise CoverageAuthorityError("Coverage Search evidence differs")
        validate_search_request(purpose, request)
        validate_search_attempt(request, attempt)
        validate_search_outcome(attempt, outcome, request)
        for result in chain_results:
            validate_search_result(outcome, result, attempt)
        validate_search_review(chain_results, review, request)
        requests.append(request)
        results.extend(chain_results)
        reviews.append(review)
    digest_groups = (
        (
            tuple(sorted({item.digest for item in requests})),
            command.search_request_digests,
        ),
        (
            tuple(sorted({item.digest for item in results})),
            command.search_result_digests,
        ),
        (
            tuple(sorted({item.digest for item in reviews})),
            command.search_review_decision_digests,
        ),
    )
    if any(actual != expected for actual, expected in digest_groups):
        raise CoverageAuthorityError("Coverage Search identity set differs")
    observed_search = tuple(
        sorted(
            item.reference_digest
            for item in command.audit.observations
            if item.kind is CoverageObservationKind.SEARCH_RESULT_REFERENCE
        )
    )
    if observed_search != command.search_result_digests:
        raise CoverageAuthorityError("Coverage Search observations differ")
    if type(locality_qualification) is not tuple or len(locality_qualification) != 4:
        raise CoverageAuthorityError("Coverage locality qualification differs")
    reference, unit, proposal, locality_decision = locality_qualification
    try:
        validate_locality_coverage_chain(
            reference,
            unit,
            proposal,
            locality_decision,
            provider_qualifications=provider_qualifications,
        )
        validate_coverage_chain(
            command.comparator,
            command.audit,
            command.gap,
            command.decision,
            previous_decision,
        )
    except Exception as exc:
        raise CoverageAuthorityError(f"Coverage accepted chain differs: {exc}") from exc
    if (
        tuple(sorted(item[1].digest for item in provider_qualifications))
        != command.provider_decision_digests
        or reference.digest != command.locality_reference_digest
        or unit.digest != command.locality_coverage_unit_digest
        or locality_decision.digest != command.locality_decision_digest
        or command.expected_previous_decision_digest
        != (None if previous_decision is None else previous_decision.digest)
    ):
        raise CoverageAuthorityError("Coverage qualification identity set differs")


_TOKEN_PORT = object()


class CoverageAuditReadPort(_NoEffect):
    __slots__ = ("_connection",)

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        if token is not _TOKEN_PORT:
            raise CoverageAuthorityError("Coverage read port construction is private")
        object.__setattr__(self, "_connection", connection)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("CoverageAuditReadPort is immutable")

    def _snapshot(self, function, *args):
        owns = not self._connection.in_transaction
        if owns:
            self._connection.execute("BEGIN")
        try:
            result = function(*args)
        except BaseException:
            if owns and self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        if owns:
            self._connection.execute("COMMIT")
        return result

    def _audit(
        self, audit_id: str
    ) -> tuple[CoverageComparator, CoverageAssessment, CoverageAudit]:
        row = self._connection.execute(
            "SELECT comparator_bytes,comparator_digest,assessment_bytes,assessment_digest,"
            "audit_bytes,audit_digest,assessment_state,completed_at FROM coverage_audits WHERE audit_id=?",
            (audit_id,),
        ).fetchone()
        if row is None:
            raise CoverageAuthorityError("Coverage Audit is absent")
        comparator = CoverageComparator.from_canonical_bytes(bytes(row[0]))
        assessment = CoverageAssessment.from_canonical_bytes(bytes(row[2]))
        audit = CoverageAudit.from_canonical_bytes(bytes(row[4]))
        observations = self._connection.execute(
            "SELECT observation_ordinal,kind,reference_digest,observed_at FROM coverage_audit_observations WHERE audit_id=? ORDER BY observation_ordinal",
            (audit_id,),
        ).fetchall()
        expected = [
            (ordinal, item.kind.value, item.reference_digest, item.observed_at)
            for ordinal, item in enumerate(audit.observations, 1)
        ]
        if (
            comparator.digest != row[1]
            or assessment.digest != row[3]
            or audit.digest != row[5]
            or audit.assessment_state.value != row[6]
            or audit.completed_at != row[7]
            or observations != expected
            or audit.comparator_id != comparator.comparator_id
            or audit.comparator_digest != comparator.digest
            or audit.assessment_state is not assessment.derived_state
            or audit.limitation_codes != assessment.derived_limitation_codes
        ):
            raise CoverageAuthorityError(
                "Coverage Audit retained representation differs"
            )
        return comparator, assessment, audit

    @_total("Coverage Audit replay failed")
    def audit(self, audit_id: str) -> CoverageAudit:
        return self._snapshot(lambda: self._audit(audit_id)[2])

    @_total("Coverage Assessment replay failed")
    def assessment(self, audit_id: str) -> CoverageAssessment:
        return self._snapshot(lambda: self._audit(audit_id)[1])

    def _gap(self, gap_id: str) -> CoverageGap:
        row = self._connection.execute(
            "SELECT gap_bytes,gap_digest,audit_id,gap_state,proposed_at FROM coverage_gaps WHERE gap_id=?",
            (gap_id,),
        ).fetchone()
        if row is None:
            raise CoverageAuthorityError("Coverage Gap is absent")
        gap = CoverageGap.from_canonical_bytes(bytes(row[0]))
        audit = self._audit(str(row[2]))[2]
        if (
            gap.digest != row[1]
            or gap.audit_id != row[2]
            or gap.gap_state.value != row[3]
            or gap.proposed_at != row[4]
            or gap.audit_digest != audit.digest
        ):
            raise CoverageAuthorityError("Coverage Gap retained representation differs")
        return gap

    @_total("Coverage Gap replay failed")
    def gap(self, gap_id: str) -> CoverageGap:
        return self._snapshot(lambda: self._gap(gap_id))

    def _decision(
        self, decision_id: str
    ) -> tuple[CoverageGapDecision, CoverageCommand]:
        row = self._connection.execute(
            "SELECT decision_bytes,decision_digest,gap_id,decision_ordinal,previous_decision_digest,"
            "command_bytes,command_digest,command_id,request_id,actor_identity_digest,idempotency_key,decided_at "
            "FROM coverage_gap_decisions WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise CoverageAuthorityError("Coverage Gap Decision is absent")
        decision = CoverageGapDecision.from_canonical_bytes(bytes(row[0]))
        command = CoverageCommand.from_canonical_bytes(bytes(row[5]))
        gap = self._gap(str(row[2]))
        predecessor = None
        if row[4] is not None:
            prior_row = self._connection.execute(
                "SELECT decision_bytes FROM coverage_gap_decisions WHERE decision_digest=?",
                (row[4],),
            ).fetchone()
            if prior_row is None:
                raise CoverageAuthorityError("Coverage Decision predecessor is absent")
            predecessor = CoverageGapDecision.from_canonical_bytes(bytes(prior_row[0]))
        validate_coverage_chain(
            command.comparator, command.audit, gap, decision, predecessor
        )
        if (
            decision.digest != row[1]
            or decision.gap_id != row[2]
            or decision.supersedes_decision_digest != row[4]
            or command.digest != row[6]
            or command.command_id != row[7]
            or command.request_id != row[8]
            or command.actor_identity_digest != row[9]
            or command.idempotency_key != row[10]
            or decision.decided_at != row[11]
            or command.decision != decision
            or command.gap != gap
            or command.expected_previous_decision_digest != row[4]
            or int(row[3])
            != (
                1
                + self._connection.execute(
                    "SELECT COUNT(*) FROM coverage_gap_decisions WHERE gap_id=? AND decision_ordinal<?",
                    (row[2], row[3]),
                ).fetchone()[0]
            )
        ):
            raise CoverageAuthorityError(
                "Coverage Decision retained representation differs"
            )
        return decision, command

    @_total("Coverage Gap Decision replay failed")
    def decision(self, decision_id: str) -> CoverageGapDecision:
        return self._snapshot(lambda: self._decision(decision_id)[0])

    @_total("Coverage Command replay failed")
    def command(self, command_id: str) -> CoverageCommand:
        def read() -> CoverageCommand:
            row = self._connection.execute(
                "SELECT decision_id FROM coverage_gap_decisions WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if row is None:
                raise CoverageAuthorityError("Coverage Command is absent")
            return self._decision(str(row[0]))[1]

        return self._snapshot(read)


class CoverageAuditAuthority(CoverageAuditReadPort):
    """Transactional v28 writer with exact replay and immutable Gap decisions."""

    __slots__ = ()

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        super().__init__(token, connection)

    def _previous(self, gap_id: str) -> CoverageGapDecision | None:
        row = self._connection.execute(
            "SELECT decision_bytes FROM coverage_gap_decisions WHERE gap_id=? ORDER BY decision_ordinal DESC LIMIT 1",
            (gap_id,),
        ).fetchone()
        return (
            None
            if row is None
            else CoverageGapDecision.from_canonical_bytes(bytes(row[0]))
        )

    @_total("Coverage command failed")
    def record(
        self,
        raw: bytes,
        *,
        search_evidence: tuple[SearchEvidenceChain, ...],
        provider_qualifications: tuple[ProviderQualification, ...],
        locality_qualification: LocalityQualification,
    ) -> CoverageGapDecision:
        command = CoverageCommand.from_canonical_bytes(raw)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._connection.execute(
                "SELECT command_bytes,decision_id,previous_decision_digest "
                "FROM coverage_gap_decisions "
                "WHERE command_id=? OR request_id=? OR idempotency_key=?",
                (command.command_id, command.request_id, command.idempotency_key),
            ).fetchall()
            if replay:
                if len(replay) != 1 or bytes(replay[0][0]) != raw:
                    raise CoverageAuthorityError("Coverage command identity collision")
                predecessor = None
                if replay[0][2] is not None:
                    prior = self._connection.execute(
                        "SELECT decision_bytes FROM coverage_gap_decisions "
                        "WHERE decision_digest=?",
                        (replay[0][2],),
                    ).fetchone()
                    if prior is None:
                        raise CoverageAuthorityError(
                            "Coverage Decision predecessor is absent"
                        )
                    predecessor = CoverageGapDecision.from_canonical_bytes(
                        bytes(prior[0])
                    )
                validate_coverage_command(
                    command,
                    search_evidence=search_evidence,
                    provider_qualifications=provider_qualifications,
                    locality_qualification=locality_qualification,
                    previous_decision=predecessor,
                )
                decision = self._decision(str(replay[0][1]))[0]
                self._connection.execute("COMMIT")
                return decision
            previous = self._previous(command.gap.gap_id)
            validate_coverage_command(
                command,
                search_evidence=search_evidence,
                provider_qualifications=provider_qualifications,
                locality_qualification=locality_qualification,
                previous_decision=previous,
            )
            existing_audit = self._connection.execute(
                "SELECT audit_bytes,assessment_bytes,comparator_bytes FROM coverage_audits WHERE audit_id=?",
                (command.audit.audit_id,),
            ).fetchone()
            existing_gap = self._connection.execute(
                "SELECT gap_bytes FROM coverage_gaps WHERE gap_id=?",
                (command.gap.gap_id,),
            ).fetchone()
            if (existing_audit is None) != (existing_gap is None):
                raise CoverageAuthorityError("Coverage retained chain is incomplete")
            if existing_audit is None:
                if previous is not None:
                    raise CoverageAuthorityError(
                        "Coverage Decision predecessor differs"
                    )
                self._connection.execute(
                    "INSERT INTO coverage_audits VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        command.audit.audit_id,
                        command.comparator.canonical_bytes,
                        command.comparator.digest,
                        command.assessment.canonical_bytes,
                        command.assessment.digest,
                        command.audit.canonical_bytes,
                        command.audit.digest,
                        command.audit.assessment_state.value,
                        command.audit.completed_at,
                        command.actor_identity_digest,
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO coverage_audit_observations VALUES(?,?,?,?,?)",
                    [
                        (
                            command.audit.audit_id,
                            ordinal,
                            item.kind.value,
                            item.reference_digest,
                            item.observed_at,
                        )
                        for ordinal, item in enumerate(command.audit.observations, 1)
                    ],
                )
                self._connection.execute(
                    "INSERT INTO coverage_gaps VALUES(?,?,?,?,?,?)",
                    (
                        command.gap.gap_id,
                        command.gap.canonical_bytes,
                        command.gap.digest,
                        command.gap.audit_id,
                        command.gap.gap_state.value,
                        command.gap.proposed_at,
                    ),
                )
            elif (
                bytes(existing_audit[0]) != command.audit.canonical_bytes
                or bytes(existing_audit[1]) != command.assessment.canonical_bytes
                or bytes(existing_audit[2]) != command.comparator.canonical_bytes
                or bytes(existing_gap[0]) != command.gap.canonical_bytes
            ):
                raise CoverageAuthorityError("Coverage immutable chain differs")
            ordinal = (
                1
                if previous is None
                else self._connection.execute(
                    "SELECT MAX(decision_ordinal)+1 FROM coverage_gap_decisions WHERE gap_id=?",
                    (command.gap.gap_id,),
                ).fetchone()[0]
            )
            self._connection.execute(
                "INSERT INTO coverage_gap_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    command.decision.decision_id,
                    command.decision.canonical_bytes,
                    command.decision.digest,
                    command.gap.gap_id,
                    ordinal,
                    command.expected_previous_decision_digest,
                    raw,
                    command.digest,
                    command.command_id,
                    command.request_id,
                    command.actor_identity_digest,
                    command.idempotency_key,
                    command.decision.disposition.value,
                    command.decision.decided_at,
                    command.locality_decision_digest,
                ),
            )
            retained = self._decision(command.decision.decision_id)[0]
            self._connection.execute("COMMIT")
            return retained
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def read_port(self) -> CoverageAuditReadPort:
        return CoverageAuditReadPort(_TOKEN_PORT, self._connection)

    def close(self) -> None:
        self._connection.close()


def open_coverage_audit_authority(
    path: str | Path,
    *,
    applied_at: str,
    timeout_seconds: float = 5.0,
) -> CoverageAuditAuthority:
    database = Path(path)
    existed = database.exists() and database.stat().st_size > 0
    connection = sqlite3.connect(
        database,
        isolation_level=None,
        timeout=timeout_seconds,
        check_same_thread=False,
    )
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        if existed:
            prepare_pending_migration_backup(connection)
        apply_pending_migrations(connection, applied_at=applied_at)
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise CoverageAuthorityError("checked v28 schema differs")
        return CoverageAuditAuthority(_TOKEN_PORT, connection)
    except BaseException:
        connection.close()
        raise


__all__ = [
    "COVERAGE_ASSESSMENT",
    "COVERAGE_ASSESSMENT_AUTHORITY",
    "COVERAGE_AUDIT_AUTHORITY",
    "COVERAGE_COMMAND",
    "AssessmentFactor",
    "CoverageAssessment",
    "CoverageAuditAuthority",
    "CoverageAuditReadPort",
    "CoverageAuthorityError",
    "CoverageCommand",
    "DependencyState",
    "HealthState",
    "LocalityQualification",
    "ProviderQualification",
    "SearchEvidenceChain",
    "TimelinessState",
    "deterministic_assessment",
    "open_coverage_audit_authority",
    "validate_coverage_command",
]
