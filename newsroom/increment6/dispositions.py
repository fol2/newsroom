"""Pure proposal validation and non-authoritative disposition contracts.

This module deliberately owns no store, authentication provider, controller or
effect.  Caller-supplied validator bindings remain pending claims.  A future v19
composition root must authenticate them, persist the complete finding set, and
only then commit every per-Lead disposition in one transaction.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment6.outcomes import (
    CanonicalNextAction,
    CanonicalOutcome,
    DecisionTerminality,
    OutcomeContractError,
    OutcomeSelection,
    ReasonCode,
    SUPPLEMENTAL_ACTION_MAPPING,
    WATCH_CONDITION_MAPPING,
)
from newsroom.increment6.proposals import (
    LeadRecommendation,
    ProposalContractError,
    ProposalRoute,
    TriageProposal,
)


PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION = (
    "newsroom.increment6.triage-proposal-finding.v1"
)
PROPOSAL_DISPOSITION_SCHEMA_VERSION = (
    "newsroom.increment6.triage-proposal-disposition.v1"
)
PROPOSAL_VALIDATION_FINDING = PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION
PROPOSAL_DISPOSITION = PROPOSAL_DISPOSITION_SCHEMA_VERSION
VALIDATED_PROPOSAL_LEAD_DISPOSITION_BINDING = (
    "EXACT_PROPOSAL_FINDING_SET_AND_CURRENT_LEAD_HEAD"
)

_FINDING_SET_SCHEMA_VERSION = "newsroom.increment6.triage-proposal-finding-set.v1"
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
# #356 has no public raw-byte constant. Its closed field bounds permit up to
# 32 recommendations, each with 64 citations and bounded 32-item text lists.
# Canonical JSON can expand each legal UTF-8 control byte to a six-byte escape,
# so the complete maximum producer envelope is materially larger than the
# ordinary-text equivalent. Sixty-four MiB covers that escaped 32-Lead envelope
# plus this module's finding and disposition wrappers; consumers must not impose
# the former private 1 MiB limit, which was smaller than a valid eight-Lead
# Proposal.
MAX_DISPOSITION_CANONICAL_BYTES = 67_108_864
_MAX_JSON_DEPTH = 64
_MAX_FINDINGS = 64


class DispositionContractError(ValueError):
    """Proposal validation or a pending disposition failed closed."""


class DispositionAuthority(StrEnum):
    """Phase-one authority states; neither state permits an effect."""

    NONE = "NONE"
    PENDING = "PENDING"


DISPOSITION_AUTHORITY = DispositionAuthority


class FindingSeverity(StrEnum):
    INFO = "INFO"
    ERROR = "ERROR"


class FindingCode(StrEnum):
    ROUTE_VALIDATED = "ROUTE_VALIDATED"
    OPERATIONAL_ACTION_AMBIGUOUS = "OPERATIONAL_ACTION_AMBIGUOUS"
    OPERATIONAL_ACTION_UNSUPPORTED = "OPERATIONAL_ACTION_UNSUPPORTED"


class DispositionJudgement(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    HOLD = "HOLD"
    ESCALATE = "ESCALATE"


class _NoEffect:
    @property
    def authorises_persistence(self) -> bool:
        return False

    @property
    def authorises_external_effect(self) -> bool:
        return False

    @property
    def authorises_publication(self) -> bool:
        return False

    @property
    def creates_hypothesis(self) -> bool:
        return False

    @property
    def creates_candidate(self) -> bool:
        return False


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise DispositionContractError(f"{field} must be a bounded canonical token")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise DispositionContractError(f"{field} must be a canonical SHA-256 digest")
    try:
        return validate_sha256_digest(value, field=field)
    except CanonicalizationError as exc:
        raise DispositionContractError(str(exc)) from exc


def _exact(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise DispositionContractError(f"{field} keys are not exact")
    try:
        actual_keys = set(value)
    except (
        AttributeError,
        KeyError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise DispositionContractError(f"{field} keys are not exact") from exc
    if actual_keys != keys:
        raise DispositionContractError(f"{field} keys are not exact")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DispositionContractError(
                f"JSON integrity contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _decode(raw: bytes, *, field: str) -> dict[str, object]:
    if (
        not isinstance(raw, bytes)
        or not raw
        or len(raw) > MAX_DISPOSITION_CANONICAL_BYTES
    ):
        raise DispositionContractError(f"{field} integrity requires bounded bytes")
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
        elif byte == ord('"'):
            in_string = True
        elif byte in (ord("{"), ord("[")):
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise DispositionContractError(f"{field} integrity exceeds depth bound")
        elif byte in (ord("}"), ord("]")):
            depth -= 1
            if depth < 0:
                raise DispositionContractError(f"{field} integrity has invalid depth")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                DispositionContractError(f"unsupported JSON constant: {item}")
            ),
        )
    except DispositionContractError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        MemoryError,
        RecursionError,
        ValueError,
    ) as exc:
        raise DispositionContractError(f"{field} integrity is not valid JSON") from exc
    if not isinstance(value, dict):
        raise DispositionContractError(f"{field} integrity requires an object")
    try:
        if canonical_json_bytes(value) != raw:
            raise DispositionContractError(f"{field} integrity is not canonical JSON")
    except (
        CanonicalizationError,
        KeyError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise DispositionContractError(f"{field} integrity is outside canonical JSON") from exc
    return value


def _bounded_canonical(value: object, *, field: str) -> bytes:
    try:
        raw = canonical_json_bytes(value)
    except (
        CanonicalizationError,
        KeyError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise DispositionContractError(f"{field} is outside canonical JSON") from exc
    if len(raw) > MAX_DISPOSITION_CANONICAL_BYTES:
        raise DispositionContractError(f"{field} exceeds the canonical byte bound")
    return raw


def _constructed_value(
    factory: Callable[[], object], *, field: str
) -> object:
    """Evaluate a constructed value without leaking nested type failures."""
    try:
        return factory()
    except (
        AttributeError,
        CanonicalizationError,
        KeyError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise DispositionContractError(f"{field} is outside canonical JSON") from exc


def _bounded_canonical_from(
    factory: Callable[[], object], *, field: str
) -> bytes:
    """Canonicalise a lazily constructed value under the public error contract."""

    return _bounded_canonical(
        _constructed_value(factory, field=field),
        field=field,
    )


@dataclass(frozen=True, slots=True)
class ValidatorInputBinding(_NoEffect):
    """An exact validator input claim, pending provider authentication."""

    validator_id: str
    validator_version: str
    authenticated_context_identity: str
    retrieval_request_id: str
    retrieval_request_digest: str
    retrieval_receipt_id: str
    retrieval_receipt_digest: str
    ruleset_id: str
    ruleset_version: str
    ruleset_digest: str
    input_digest: str
    authority: DispositionAuthority = DispositionAuthority.PENDING

    def __post_init__(self) -> None:
        if type(self) is not ValidatorInputBinding:
            raise DispositionContractError(
                "validator input constructor requires the exact contract type"
            )
        for field in (
            "validator_id", "validator_version", "retrieval_request_id",
            "retrieval_receipt_id", "ruleset_id", "ruleset_version",
        ):
            _token(getattr(self, field), field)
        for field in (
            "authenticated_context_identity", "retrieval_request_digest",
            "retrieval_receipt_digest", "ruleset_digest", "input_digest",
        ):
            _digest(getattr(self, field), field)
        if self.authority is not DispositionAuthority.PENDING:
            raise DispositionContractError("validator input authority must remain PENDING")

    def canonical_value(self) -> dict[str, object]:
        return {
            "validator_id": self.validator_id,
            "validator_version": self.validator_version,
            "authenticated_context_identity": self.authenticated_context_identity,
            "retrieval_request_id": self.retrieval_request_id,
            "retrieval_request_digest": self.retrieval_request_digest,
            "retrieval_receipt_id": self.retrieval_receipt_id,
            "retrieval_receipt_digest": self.retrieval_receipt_digest,
            "ruleset_id": self.ruleset_id,
            "ruleset_version": self.ruleset_version,
            "ruleset_digest": self.ruleset_digest,
            "input_digest": self.input_digest,
            "authority": self.authority.value,
        }

    def expected_input_digest(self, proposal_canonical_digest: str) -> str:
        """Derive the exact deterministic validation-envelope identity."""

        exact = _exact_validator_input(self, field="validator input binding")
        return exact._expected_input_digest(proposal_canonical_digest)

    def _expected_input_digest(self, proposal_canonical_digest: str) -> str:
        """Derive from an exact base-class binding without virtual dispatch."""

        _digest(proposal_canonical_digest, "proposal_canonical_digest")
        return digest_bytes(_bounded_canonical({
            "proposal_canonical_digest": proposal_canonical_digest,
            "validator_id": self.validator_id,
            "validator_version": self.validator_version,
            "authenticated_context_identity": self.authenticated_context_identity,
            "retrieval_request_id": self.retrieval_request_id,
            "retrieval_request_digest": self.retrieval_request_digest,
            "retrieval_receipt_id": self.retrieval_receipt_id,
            "retrieval_receipt_digest": self.retrieval_receipt_digest,
            "ruleset_id": self.ruleset_id,
            "ruleset_version": self.ruleset_version,
            "ruleset_digest": self.ruleset_digest,
        }, field="validator input envelope"))

    @classmethod
    def for_proposal(cls, *, proposal_bytes: bytes, **values: object) -> Self:
        """Create a pending binding whose input digest is derived, not asserted."""

        if cls is not ValidatorInputBinding:
            raise DispositionContractError(
                "validator input factory requires the exact contract type"
            )
        proposal_digest = digest_bytes(_bounded_canonical(
            _decode(proposal_bytes, field="proposal"), field="proposal"
        ))
        provisional = ValidatorInputBinding(
            input_digest="sha256:" + "0" * 64, **values  # type: ignore[arg-type]
        )
        return ValidatorInputBinding(
            input_digest=provisional._expected_input_digest(proposal_digest),
            **values,  # type: ignore[arg-type]
        )  # type: ignore[return-value]

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        if cls is not ValidatorInputBinding:
            raise DispositionContractError(
                "validator input parser requires the exact contract type"
            )
        item = _exact(value, {
            "validator_id", "validator_version", "authenticated_context_identity",
            "retrieval_request_id", "retrieval_request_digest", "retrieval_receipt_id",
            "retrieval_receipt_digest", "ruleset_id", "ruleset_version",
            "ruleset_digest", "input_digest", "authority",
        }, "validator input binding")
        authority = _constructed_value(
            lambda: item["authority"], field="validator input binding"
        )
        if authority != DispositionAuthority.PENDING.value:
            raise DispositionContractError("validator input authority must remain PENDING")
        values = _constructed_value(
            lambda: {
                key: item[key] for key in item if key != "authority"
            },
            field="validator input binding",
        )
        return _constructed_value(
            lambda: ValidatorInputBinding(**values),  # type: ignore[arg-type]
            field="validator input binding",
        )  # type: ignore[return-value]


def _exact_validator_input(
    value: ValidatorInputBinding, *, field: str
) -> ValidatorInputBinding:
    if type(value) is not ValidatorInputBinding:
        raise DispositionContractError(
            f"{field} is outside canonical JSON: exact contract type required"
        )
    canonical = _constructed_value(
        lambda: value.canonical_value(), field=field
    )
    _bounded_canonical(canonical, field=field)
    return _constructed_value(
        lambda: ValidatorInputBinding.from_mapping(canonical), field=field
    )  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ProposalValidationFinding(_NoEffect):
    finding_id: str
    proposal_id: str
    proposal_content_identity: str
    proposal_canonical_digest: str
    code: FindingCode
    severity: FindingSeverity
    path: str
    evidence_reference_type: str
    evidence_reference_id: str
    evidence_reference_digest: str
    validator_input: ValidatorInputBinding
    authority: DispositionAuthority = DispositionAuthority.NONE

    def __post_init__(self) -> None:
        if type(self) is not ProposalValidationFinding:
            raise DispositionContractError(
                "finding constructor requires the exact contract type"
            )
        _digest(self.finding_id, "finding_id")
        _token(self.proposal_id, "proposal_id")
        _digest(self.proposal_content_identity, "proposal_content_identity")
        _digest(self.proposal_canonical_digest, "proposal_canonical_digest")
        if not isinstance(self.code, FindingCode) or not isinstance(self.severity, FindingSeverity):
            raise DispositionContractError("finding code and severity must be typed")
        _token(self.path, "finding path")
        _token(self.evidence_reference_type, "evidence reference type")
        _token(self.evidence_reference_id, "evidence reference id")
        _digest(self.evidence_reference_digest, "evidence reference digest")
        if not isinstance(self.validator_input, ValidatorInputBinding):
            raise DispositionContractError("finding validator input must be typed")
        exact_validator = _exact_validator_input(
            self.validator_input, field="validator input"
        )
        object.__setattr__(self, "validator_input", exact_validator)
        if exact_validator.input_digest != exact_validator._expected_input_digest(
            self.proposal_canonical_digest
        ):
            raise DispositionContractError(
                "finding validator input differs from the exact validation envelope"
            )
        if self.authority is not DispositionAuthority.NONE:
            raise DispositionContractError("a pure finding has no authority")
        if self.finding_id != digest_bytes(
            _bounded_canonical_from(
                lambda: self._identity_value(), field="finding identity"
            )
        ):
            raise DispositionContractError("finding identity differs")
        _bounded_canonical_from(lambda: self.canonical_value(), field="finding")

    def _identity_value(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_content_identity": self.proposal_content_identity,
            "proposal_canonical_digest": self.proposal_canonical_digest,
            "code": self.code.value,
            "severity": self.severity.value,
            "path": self.path,
            "evidence_reference_type": self.evidence_reference_type,
            "evidence_reference_id": self.evidence_reference_id,
            "evidence_reference_digest": self.evidence_reference_digest,
            "validator_input_binding": self.validator_input.canonical_value(),
            "authority": self.authority.value,
        }

    def canonical_value(self) -> dict[str, object]:
        finding = {"finding_id": self.finding_id, **self._identity_value()}
        return {"schema_version": PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION, "finding": finding}

    @property
    def canonical_bytes(self) -> bytes:
        if type(self) is not ProposalValidationFinding:
            raise DispositionContractError(
                "finding property requires the exact contract type"
            )
        raw = _bounded_canonical_from(
            lambda: self.canonical_value(), field="finding"
        )
        exact = ProposalValidationFinding.from_canonical_bytes(raw)
        return _bounded_canonical_from(
            lambda: exact.canonical_value(), field="finding"
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if cls is not ProposalValidationFinding:
            raise DispositionContractError(
                "finding parser requires the exact contract type"
            )
        root = _exact(_decode(raw, field="finding"), {"schema_version", "finding"}, "finding document")
        if root["schema_version"] != PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION:
            raise DispositionContractError("finding schema version is unsupported")
        item = _exact(root["finding"], {
            "finding_id", "proposal_id", "proposal_content_identity", "proposal_canonical_digest",
            "code", "severity", "path", "evidence_reference_type", "evidence_reference_id",
            "evidence_reference_digest", "validator_input_binding", "authority",
        }, "finding")
        if item["authority"] != DispositionAuthority.NONE.value:
            raise DispositionContractError("a pure finding has no authority")
        try:
            result = ProposalValidationFinding(
                finding_id=item["finding_id"], proposal_id=item["proposal_id"],
                proposal_content_identity=item["proposal_content_identity"],
                proposal_canonical_digest=item["proposal_canonical_digest"],
                code=FindingCode(item["code"]), severity=FindingSeverity(item["severity"]),
                path=item["path"], evidence_reference_type=item["evidence_reference_type"],
                evidence_reference_id=item["evidence_reference_id"],
                evidence_reference_digest=item["evidence_reference_digest"],
                validator_input=ValidatorInputBinding.from_mapping(item["validator_input_binding"]),
            )
        except (
            CanonicalizationError,
            KeyError,
            MemoryError,
            OverflowError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise DispositionContractError("finding is malformed") from exc
        if _bounded_canonical_from(
            lambda: result.canonical_value(), field="finding"
        ) != raw:
            raise DispositionContractError("finding typed replay differs")
        return result  # type: ignore[return-value]


def _exact_proposal(value: TriageProposal, *, field: str) -> TriageProposal:
    if type(value) is not TriageProposal:
        raise DispositionContractError(
            f"{field} is outside canonical JSON: exact contract type required"
        )
    raw = _bounded_canonical_from(
        lambda: value.canonical_value(), field=field
    )
    return _constructed_value(
        lambda: TriageProposal.from_canonical_bytes(raw), field=field
    )  # type: ignore[return-value]


def _exact_finding(
    value: ProposalValidationFinding, *, field: str
) -> ProposalValidationFinding:
    if type(value) is not ProposalValidationFinding:
        raise DispositionContractError(
            f"{field} is outside canonical JSON: exact contract type required"
        )
    raw = _bounded_canonical_from(
        lambda: value.canonical_value(), field=field
    )
    return _constructed_value(
        lambda: ProposalValidationFinding.from_canonical_bytes(raw), field=field
    )  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ProposalValidationResult(_NoEffect):
    proposal: TriageProposal
    validator_input: ValidatorInputBinding
    findings: tuple[ProposalValidationFinding, ...]
    finding_set_digest: str
    authority: DispositionAuthority = DispositionAuthority.NONE

    def __post_init__(self) -> None:
        if type(self) is not ProposalValidationResult:
            raise DispositionContractError(
                "validation result constructor requires the exact contract type"
            )
        if not isinstance(self.proposal, TriageProposal):
            raise DispositionContractError("validation result proposal must be typed")
        if not isinstance(self.validator_input, ValidatorInputBinding):
            raise DispositionContractError("validation result input must be typed")
        if (
            not isinstance(self.findings, tuple)
            or not 1 <= len(self.findings) <= _MAX_FINDINGS
            or any(
                not isinstance(item, ProposalValidationFinding)
                for item in self.findings
            )
        ):
            raise DispositionContractError("finding set must be complete and bounded")
        exact_proposal = _exact_proposal(self.proposal, field="proposal")
        exact_validator = _exact_validator_input(
            self.validator_input, field="validator input binding"
        )
        exact_findings = tuple(
            _exact_finding(item, field="finding") for item in self.findings
        )
        object.__setattr__(self, "proposal", exact_proposal)
        object.__setattr__(self, "validator_input", exact_validator)
        object.__setattr__(self, "findings", exact_findings)
        proposal_bytes = _bounded_canonical_from(
            lambda: exact_proposal.canonical_value(), field="proposal"
        )
        proposal_digest = digest_bytes(proposal_bytes)
        if any(
            item.proposal_id != self.proposal.proposal_id
            or item.proposal_content_identity != self.proposal.content_identity
            or item.proposal_canonical_digest != proposal_digest
            or item.validator_input != self.validator_input
            for item in self.findings
        ):
            raise DispositionContractError(
                "finding set differs from its exact Proposal or validator input"
            )
        if {
            item.evidence_reference_id for item in self.findings
        } != set(self.proposal.decision_lead_ids):
            raise DispositionContractError(
                "finding set does not cover every decision Lead exactly"
            )
        ids = tuple(item.finding_id for item in self.findings)
        if ids != tuple(sorted(set(ids))):
            raise DispositionContractError("findings must be sorted and deduplicated")
        if self.finding_set_digest != digest_bytes(self.canonical_bytes):
            raise DispositionContractError("finding set digest differs")
        if self.authority is not DispositionAuthority.NONE:
            raise DispositionContractError("pure validation has no authority")
        if len(self.canonical_bytes) > MAX_DISPOSITION_CANONICAL_BYTES:
            raise DispositionContractError("finding set exceeds the canonical byte bound")

    @property
    def canonical_bytes(self) -> bytes:
        if type(self) is not ProposalValidationResult:
            raise DispositionContractError(
                "validation result property requires the exact contract type"
            )
        if self.authority is not DispositionAuthority.NONE:
            raise DispositionContractError("pure validation has no authority")
        proposal = _exact_proposal(self.proposal, field="proposal")
        validator = _exact_validator_input(
            self.validator_input, field="validator input binding"
        )
        findings = tuple(
            _exact_finding(item, field="finding") for item in self.findings
        )
        return _bounded_canonical_from(
            lambda: {
                "schema_version": _FINDING_SET_SCHEMA_VERSION,
                "proposal_content_identity": proposal.content_identity,
                "validator_input_binding": validator.canonical_value(),
                "finding_ids": [item.finding_id for item in findings],
                "authority": self.authority.value,
            },
            field="finding set",
        )


@dataclass(frozen=True, slots=True)
class LeadDispositionHeadBinding:
    decision_lead_id: str
    decision_lead_digest: str
    current_disposition_head_id: str
    current_disposition_head_digest: str

    def __post_init__(self) -> None:
        if type(self) is not LeadDispositionHeadBinding:
            raise DispositionContractError(
                "Lead head constructor requires the exact contract type"
            )
        _token(self.decision_lead_id, "decision_lead_id")
        _digest(self.decision_lead_digest, "decision_lead_digest")
        _token(self.current_disposition_head_id, "current_disposition_head_id")
        _digest(self.current_disposition_head_digest, "current_disposition_head_digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_lead_id": self.decision_lead_id,
            "decision_lead_digest": self.decision_lead_digest,
            "current_disposition_head_id": self.current_disposition_head_id,
            "current_disposition_head_digest": self.current_disposition_head_digest,
        }

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        if cls is not LeadDispositionHeadBinding:
            raise DispositionContractError(
                "Lead head parser requires the exact contract type"
            )
        item = _exact(value, {"decision_lead_id", "decision_lead_digest", "current_disposition_head_id", "current_disposition_head_digest"}, "Lead head binding")
        return _constructed_value(
            lambda: LeadDispositionHeadBinding(**item),  # type: ignore[arg-type]
            field="Lead head binding",
        )  # type: ignore[return-value]


def _exact_lead_head(
    value: LeadDispositionHeadBinding, *, field: str
) -> LeadDispositionHeadBinding:
    if type(value) is not LeadDispositionHeadBinding:
        raise DispositionContractError(
            f"{field} is outside canonical JSON: exact contract type required"
        )
    canonical = _constructed_value(
        lambda: value.canonical_value(), field=field
    )
    _bounded_canonical(canonical, field=field)
    return _constructed_value(
        lambda: LeadDispositionHeadBinding.from_mapping(canonical), field=field
    )  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class _RouteRule:
    judgement: DispositionJudgement
    outcome: CanonicalOutcome
    reasons: frozenset[ReasonCode]
    actions: frozenset[tuple[DecisionTerminality, CanonicalNextAction]]


_ROUTE_RULES: Mapping[ProposalRoute, _RouteRule] = MappingProxyType({
    ProposalRoute.EDITORIAL_REJECT: _RouteRule(DispositionJudgement.REJECT, CanonicalOutcome.LEAD_EDITORIAL_REJECT, frozenset({ReasonCode.NOVELTY_EXACT_DUPLICATE, ReasonCode.NOVELTY_SAME_STATE_REPEAT, ReasonCode.SCOPE_EXCLUDED, ReasonCode.UTILITY_EDITORIAL_MATERIALITY}), frozenset({(DecisionTerminality.TERMINAL_EXACT_VERSION, CanonicalNextAction.CLOSE_DECISION)})),
    ProposalRoute.WATCH_DEFER: _RouteRule(DispositionJudgement.HOLD, CanonicalOutcome.LEAD_WATCH_DEFER, frozenset({ReasonCode.TIME_WATCH_REVIEW, ReasonCode.NOVELTY_INSUFFICIENT_INFORMATION}), frozenset({(next(iter(WATCH_CONDITION_MAPPING.values())).terminality, next(iter(WATCH_CONDITION_MAPPING.values())).next_action)})),
    ProposalRoute.ASSOCIATE_WITHOUT_CANDIDATE: _RouteRule(DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE, frozenset({ReasonCode.REL_SAME_STATE, ReasonCode.REL_RELATED_DISTINCT, ReasonCode.REL_UNCERTAIN}), frozenset({(DecisionTerminality.TERMINAL_EXACT_VERSION, CanonicalNextAction.CLOSE_DECISION)})),
    ProposalRoute.SUPPLEMENTAL_DISCOVERY: _RouteRule(DispositionJudgement.ESCALATE, CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY, frozenset({ReasonCode.SEARCH_ZERO_RESULTS, ReasonCode.SEARCH_PARTIAL_RESULTS, ReasonCode.SEARCH_PROVIDER_FAILURE, ReasonCode.NOVELTY_INSUFFICIENT_INFORMATION}), frozenset({(next(iter(SUPPLEMENTAL_ACTION_MAPPING.values())).terminality, next(iter(SUPPLEMENTAL_ACTION_MAPPING.values())).next_action)})),
    ProposalRoute.OPERATIONAL_HOLD: _RouteRule(DispositionJudgement.HOLD, CanonicalOutcome.LEAD_OPERATIONAL_HOLD, frozenset({item for item in ReasonCode if item.value.startswith(("OPS.", "CAPACITY."))}), frozenset({(DecisionTerminality.PENDING_CONDITION, CanonicalNextAction.RETRY_SAME_REQUEST), (DecisionTerminality.PENDING_CONDITION, CanonicalNextAction.REQUEST_REVIEW), (DecisionTerminality.PENDING_CONDITION, CanonicalNextAction.WAIT_FOR_DEPENDENCY), (DecisionTerminality.RETRYABLE_SAME_REQUEST, CanonicalNextAction.RETRY_SAME_REQUEST)})),
    ProposalRoute.NEW_EVENT_CANDIDATE: _RouteRule(DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE, frozenset({ReasonCode.NOVELTY_LIKELY_NEW_EVENT, ReasonCode.REL_NO_ADEQUATE_PRIOR_MATCH}), frozenset({(DecisionTerminality.TERMINAL_EXACT_VERSION, CanonicalNextAction.HANDOFF_FOR_EVALUATION)})),
    ProposalRoute.DEVELOPMENT_CANDIDATE: _RouteRule(DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_DEVELOPMENT_CANDIDATE, frozenset({ReasonCode.NOVELTY_LIKELY_DEVELOPMENT, ReasonCode.REL_DEVELOPMENT}), frozenset({(DecisionTerminality.TERMINAL_EXACT_VERSION, CanonicalNextAction.HANDOFF_FOR_EVALUATION)})),
    ProposalRoute.CORRECTION_CANDIDATE: _RouteRule(DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_CORRECTION_CANDIDATE, frozenset({ReasonCode.REL_CORRECTION_REVERSAL, ReasonCode.CHANGE_REVISION, ReasonCode.CHANGE_WITHDRAWAL}), frozenset({(DecisionTerminality.TERMINAL_EXACT_VERSION, CanonicalNextAction.HANDOFF_FOR_EVALUATION)})),
})

_OPERATIONAL_REASONS: Mapping[CanonicalNextAction, frozenset[ReasonCode]] = (
    MappingProxyType({
        CanonicalNextAction.RETRY_SAME_REQUEST: frozenset({
            ReasonCode.OPS_TRANSPORT,
            ReasonCode.OPS_PARSER,
            ReasonCode.OPS_RETRIEVAL,
            ReasonCode.OPS_COLLISION,
            ReasonCode.OPS_MODEL,
            ReasonCode.OPS_QUEUE,
            ReasonCode.OPS_HANDOFF,
        }),
        CanonicalNextAction.REQUEST_REVIEW: frozenset({
            ReasonCode.OPS_PARTIAL,
            ReasonCode.OPS_COLLISION,
            ReasonCode.OPS_QUARANTINE,
            ReasonCode.OPS_STALE_STATE,
        }),
        CanonicalNextAction.WAIT_FOR_DEPENDENCY: frozenset({
            ReasonCode.OPS_RETRIEVAL,
            ReasonCode.OPS_QUEUE,
            ReasonCode.OPS_HANDOFF,
            ReasonCode.CAPACITY_SEARCH,
            ReasonCode.CAPACITY_MODEL,
            ReasonCode.CAPACITY_QUEUE,
            ReasonCode.CAPACITY_URGENT_RESERVE,
            ReasonCode.CAPACITY_REVIEWER,
        }),
    })
)

_OPERATIONAL_ACTION_KINDS: Mapping[str, CanonicalNextAction] = MappingProxyType({
    "RETRY_RETRIEVAL": CanonicalNextAction.RETRY_SAME_REQUEST,
    "REQUEST_REVIEW": CanonicalNextAction.REQUEST_REVIEW,
    "WAIT_FOR_DEPENDENCY": CanonicalNextAction.WAIT_FOR_DEPENDENCY,
})


def _exact_recommendation(
    value: LeadRecommendation, *, field: str
) -> tuple[LeadRecommendation, object]:
    if type(value) is not LeadRecommendation:
        raise DispositionContractError(
            f"{field} is outside canonical JSON: exact contract type required"
        )
    canonical = _constructed_value(
        lambda: value.canonical_value(), field=field
    )
    _bounded_canonical(canonical, field=field)
    exact = _constructed_value(
        lambda: LeadRecommendation.from_value(canonical), field=field
    )
    return exact, canonical  # type: ignore[return-value]


def _exact_selection(
    value: OutcomeSelection, *, field: str
) -> tuple[OutcomeSelection, object]:
    if type(value) is not OutcomeSelection:
        raise DispositionContractError(
            f"{field} is outside canonical JSON: exact contract type required"
        )
    canonical = _constructed_value(
        lambda: value.canonical_value(), field=field
    )
    _bounded_canonical(canonical, field=field)
    exact = _constructed_value(
        lambda: OutcomeSelection.from_mapping(canonical), field=field
    )
    return exact, canonical  # type: ignore[return-value]


def _operational_expected_action(
    recommendation: LeadRecommendation,
) -> CanonicalNextAction:
    operational = recommendation.operational_action
    assert operational is not None
    expected = _OPERATIONAL_ACTION_KINDS.get(operational.action_kind)
    if expected is None:
        raise DispositionContractError("operational action kind is unsupported")
    selected_seam = {
        CanonicalNextAction.RETRY_SAME_REQUEST: operational.retry_condition,
        CanonicalNextAction.REQUEST_REVIEW: (
            operational.review_condition
            or operational.expiry_condition
            or operational.owner_id
        ),
        CanonicalNextAction.WAIT_FOR_DEPENDENCY: operational.dependency,
    }[expected]
    if selected_seam is None:
        raise DispositionContractError(
            "operational action kind lacks its exact deterministic seam"
        )
    competing_present = {
        CanonicalNextAction.RETRY_SAME_REQUEST: any((
            operational.owner_id,
            operational.review_condition,
            operational.expiry_condition,
            operational.dependency,
        )),
        CanonicalNextAction.REQUEST_REVIEW: any((
            operational.retry_condition,
            operational.dependency,
        )),
        CanonicalNextAction.WAIT_FOR_DEPENDENCY: any((
            operational.owner_id,
            operational.retry_condition,
            operational.review_condition,
            operational.expiry_condition,
        )),
    }[expected]
    if competing_present:
        raise DispositionContractError(
            "operational action contains a competing action seam"
        )
    return expected


def _validate_exact_route_seam(
    recommendation: LeadRecommendation,
    selection: OutcomeSelection,
    route_binding_digest: str,
) -> None:
    """Bind conditional actions one-to-one to the Proposal seam they consume."""

    ProposalDisposition.validate_route_selection(recommendation.route, selection)
    action = selection.next_action
    assert action is not None
    conditional_routes = {
        ProposalRoute.WATCH_DEFER,
        ProposalRoute.SUPPLEMENTAL_DISCOVERY,
        ProposalRoute.OPERATIONAL_HOLD,
    }
    if recommendation.route in conditional_routes:
        if action.condition_reference != route_binding_digest:
            raise DispositionContractError(
                "next action does not bind the exact route-specific Proposal seam"
            )
    if recommendation.route is not ProposalRoute.OPERATIONAL_HOLD:
        return
    expected = _operational_expected_action(recommendation)
    if (
        action.action_code is not expected
        or selection.primary_reason.code not in _OPERATIONAL_REASONS[expected]
    ):
        raise DispositionContractError(
            "operational selection differs from its exact action and reason seam"
        )


@dataclass(frozen=True, slots=True)
class ProposalDisposition(_NoEffect):
    SCHEMA_VERSION: ClassVar[str] = PROPOSAL_DISPOSITION_SCHEMA_VERSION

    disposition_id: str
    judgement: DispositionJudgement
    proposal_id: str
    proposal_content_identity: str
    proposal_canonical_digest: str
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    retrieval_context_id: str
    retrieval_context_digest: str
    lead_head: LeadDispositionHeadBinding
    validator_input: ValidatorInputBinding
    finding_set_digest: str
    route: ProposalRoute
    route_binding: LeadRecommendation
    route_binding_digest: str
    selection: OutcomeSelection
    authority: DispositionAuthority = DispositionAuthority.NONE

    def __post_init__(self) -> None:
        if type(self) is not ProposalDisposition:
            raise DispositionContractError(
                "disposition constructor requires the exact contract type"
            )
        _digest(self.disposition_id, "disposition_id")
        if not isinstance(self.judgement, DispositionJudgement) or not isinstance(self.route, ProposalRoute):
            raise DispositionContractError("disposition judgement and route must be typed")
        for field in ("proposal_id", "work_item_id", "work_item_version_id", "retrieval_context_id"):
            _token(getattr(self, field), field)
        for field in ("proposal_content_identity", "proposal_canonical_digest", "work_item_version_digest", "retrieval_context_digest", "finding_set_digest", "route_binding_digest"):
            _digest(getattr(self, field), field)
        if not isinstance(self.lead_head, LeadDispositionHeadBinding) or not isinstance(self.validator_input, ValidatorInputBinding):
            raise DispositionContractError("disposition bindings must be typed")
        exact_head = _exact_lead_head(self.lead_head, field="Lead head binding")
        exact_validator = _exact_validator_input(
            self.validator_input, field="validator input"
        )
        object.__setattr__(self, "lead_head", exact_head)
        object.__setattr__(self, "validator_input", exact_validator)
        if exact_validator.input_digest != exact_validator._expected_input_digest(
            self.proposal_canonical_digest
        ):
            raise DispositionContractError(
                "disposition validator input differs from the exact validation envelope"
            )
        if not isinstance(self.route_binding, LeadRecommendation):
            raise DispositionContractError("route binding must be typed")
        if not isinstance(self.selection, OutcomeSelection):
            raise DispositionContractError("outcome selection must be typed")
        exact_route, route_value = _exact_recommendation(
            self.route_binding, field="route binding"
        )
        exact_selection, selection_value = _exact_selection(
            self.selection, field="selection"
        )
        object.__setattr__(self, "route_binding", exact_route)
        object.__setattr__(self, "selection", exact_selection)
        if (
            exact_route.route is not self.route
            or exact_route.decision_lead_id != exact_head.decision_lead_id
        ):
            raise DispositionContractError("route binding differs from the exact Lead route")
        expected_route_digest = digest_bytes(
            _bounded_canonical(route_value, field="route binding")
        )
        if self.route_binding_digest != expected_route_digest:
            raise DispositionContractError("route binding digest differs")
        citation_digests = {
            citation.source_digest
            for citation in exact_route.input_citations
            if citation.source_kind.value == "DECISION_LEAD"
            and citation.source_id == exact_head.decision_lead_id
        }
        if citation_digests != {exact_head.decision_lead_digest}:
            raise DispositionContractError(
                "Lead head digest differs from the exact Proposal citation"
            )
        _validate_exact_route_seam(
            exact_route, exact_selection, self.route_binding_digest
        )
        if self.judgement is not _ROUTE_RULES[self.route].judgement:
            raise DispositionContractError("judgement differs from route matrix")
        if self.authority is not DispositionAuthority.NONE:
            raise DispositionContractError("phase-one disposition has no authority")
        if self.disposition_id != digest_bytes(
            _bounded_canonical_from(
                lambda: self._identity_value(), field="disposition identity"
            )
        ):
            raise DispositionContractError("disposition identity differs")
        _bounded_canonical_from(
            lambda: self.canonical_value(), field="disposition"
        )

    @staticmethod
    def validate_route_selection(route: ProposalRoute, selection: OutcomeSelection) -> None:
        if not isinstance(route, ProposalRoute) or not isinstance(selection, OutcomeSelection):
            raise DispositionContractError("route selection must be typed")
        selection, _ = _exact_selection(selection, field="selection")
        rule = _ROUTE_RULES[route]
        action = selection.next_action
        reason_codes = {
            selection.primary_reason.code,
            *(reason.code for reason in selection.supporting_reasons),
        }
        if (
            selection.outcome is not rule.outcome
            or not reason_codes <= rule.reasons
            or action is None
            or (selection.terminality, action.action_code) not in rule.actions
        ):
            raise DispositionContractError("selection is outside the exact route matrix")

    def _identity_value(self) -> dict[str, object]:
        return {
            "judgement": self.judgement.value, "proposal_id": self.proposal_id,
            "proposal_content_identity": self.proposal_content_identity,
            "proposal_canonical_digest": self.proposal_canonical_digest,
            "work_item_id": self.work_item_id, "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "retrieval_context_id": self.retrieval_context_id,
            "retrieval_context_digest": self.retrieval_context_digest,
            "lead_head_binding": self.lead_head.canonical_value(),
            "validator_input_binding": self.validator_input.canonical_value(),
            "finding_set_digest": self.finding_set_digest, "route": self.route.value,
            "route_binding": self.route_binding.canonical_value(),
            "route_binding_digest": self.route_binding_digest,
            "selection": self.selection.canonical_value(), "authority": self.authority.value,
        }

    def canonical_value(self) -> dict[str, object]:
        return {"schema_version": self.SCHEMA_VERSION, "disposition": {"disposition_id": self.disposition_id, **self._identity_value()}}

    @property
    def canonical_bytes(self) -> bytes:
        if type(self) is not ProposalDisposition:
            raise DispositionContractError(
                "disposition property requires the exact contract type"
            )
        raw = _bounded_canonical_from(
            lambda: self.canonical_value(), field="disposition"
        )
        exact = ProposalDisposition.from_canonical_bytes(raw)
        return _bounded_canonical_from(
            lambda: exact.canonical_value(), field="disposition"
        )

    @property
    def decision_lead_id(self) -> str:
        if type(self) is not ProposalDisposition:
            raise DispositionContractError(
                "disposition property requires the exact contract type"
            )
        return _exact_lead_head(
            self.lead_head, field="Lead head binding"
        ).decision_lead_id

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if cls is not ProposalDisposition:
            raise DispositionContractError(
                "disposition parser requires the exact contract type"
            )
        root = _exact(_decode(raw, field="disposition"), {"schema_version", "disposition"}, "disposition document")
        if root["schema_version"] != ProposalDisposition.SCHEMA_VERSION:
            raise DispositionContractError("disposition schema version is unsupported")
        keys = {"disposition_id", "judgement", "proposal_id", "proposal_content_identity", "proposal_canonical_digest", "work_item_id", "work_item_version_id", "work_item_version_digest", "retrieval_context_id", "retrieval_context_digest", "lead_head_binding", "validator_input_binding", "finding_set_digest", "route", "route_binding", "route_binding_digest", "selection", "authority"}
        item = _exact(root["disposition"], keys, "disposition")
        if item["authority"] != DispositionAuthority.NONE.value:
            raise DispositionContractError("phase-one disposition has no authority")
        try:
            result = ProposalDisposition(
                disposition_id=item["disposition_id"], judgement=DispositionJudgement(item["judgement"]),
                proposal_id=item["proposal_id"], proposal_content_identity=item["proposal_content_identity"],
                proposal_canonical_digest=item["proposal_canonical_digest"], work_item_id=item["work_item_id"],
                work_item_version_id=item["work_item_version_id"], work_item_version_digest=item["work_item_version_digest"],
                retrieval_context_id=item["retrieval_context_id"], retrieval_context_digest=item["retrieval_context_digest"],
                lead_head=LeadDispositionHeadBinding.from_mapping(item["lead_head_binding"]),
                validator_input=ValidatorInputBinding.from_mapping(item["validator_input_binding"]),
                finding_set_digest=item["finding_set_digest"], route=ProposalRoute(item["route"]),
                route_binding=LeadRecommendation.from_value(item["route_binding"]),
                route_binding_digest=item["route_binding_digest"], selection=OutcomeSelection.from_mapping(item["selection"]),
            )
        except (
            CanonicalizationError,
            KeyError,
            MemoryError,
            OutcomeContractError,
            OverflowError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise DispositionContractError("disposition is malformed") from exc
        if _bounded_canonical_from(
            lambda: result.canonical_value(), field="disposition"
        ) != raw:
            raise DispositionContractError("disposition typed replay differs")
        return result  # type: ignore[return-value]


def validate_proposal(raw: bytes, validator_input: ValidatorInputBinding) -> ProposalValidationResult:
    """Parse and deterministically validate one exact, untrusted Proposal."""

    if not isinstance(validator_input, ValidatorInputBinding):
        raise DispositionContractError("validator input binding must be typed")
    validator_input = _exact_validator_input(
        validator_input, field="validator input binding"
    )
    _decode(raw, field="proposal")
    try:
        proposal = TriageProposal.from_canonical_bytes(raw)
    except (
        CanonicalizationError,
        KeyError,
        MemoryError,
        OverflowError,
        ProposalContractError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise DispositionContractError("proposal integrity validation failed") from exc
    proposal_digest = digest_bytes(raw)
    if validator_input.input_digest != validator_input._expected_input_digest(
        proposal_digest
    ):
        raise DispositionContractError(
            "validator input integrity differs from the exact validation envelope"
        )
    findings: list[ProposalValidationFinding] = []
    for recommendation in proposal.recommendations:
        finding_code = FindingCode.ROUTE_VALIDATED
        finding_severity = FindingSeverity.INFO
        finding_path = f"recommendations:{recommendation.decision_lead_id}"
        if recommendation.route is ProposalRoute.OPERATIONAL_HOLD:
            try:
                _operational_expected_action(recommendation)
            except DispositionContractError as exc:
                finding_code = (
                    FindingCode.OPERATIONAL_ACTION_UNSUPPORTED
                    if "unsupported" in str(exc)
                    else FindingCode.OPERATIONAL_ACTION_AMBIGUOUS
                )
                finding_severity = FindingSeverity.ERROR
                finding_path += ":operational_action"
        seed = {
            "proposal_id": proposal.proposal_id,
            "proposal_content_identity": proposal.content_identity,
            "proposal_canonical_digest": proposal_digest,
            "code": finding_code.value,
            "severity": finding_severity.value,
            "path": finding_path,
            "evidence_reference_type": "PROPOSAL_RECOMMENDATION",
            "evidence_reference_id": recommendation.decision_lead_id,
            "evidence_reference_digest": digest_bytes(
                _bounded_canonical_from(
                    lambda: recommendation.canonical_value(),
                    field="recommendation",
                )
            ),
            "validator_input_binding": validator_input.canonical_value(),
            "authority": DispositionAuthority.NONE.value,
        }
        findings.append(ProposalValidationFinding(finding_id=digest_bytes(_bounded_canonical(seed, field="finding identity")), proposal_id=proposal.proposal_id, proposal_content_identity=proposal.content_identity, proposal_canonical_digest=proposal_digest, code=finding_code, severity=finding_severity, path=finding_path, evidence_reference_type="PROPOSAL_RECOMMENDATION", evidence_reference_id=recommendation.decision_lead_id, evidence_reference_digest=seed["evidence_reference_digest"], validator_input=validator_input))  # type: ignore[arg-type]
    ordered = tuple(sorted(findings, key=lambda item: item.finding_id))
    canonical = _bounded_canonical({"schema_version": _FINDING_SET_SCHEMA_VERSION, "proposal_content_identity": proposal.content_identity, "validator_input_binding": validator_input.canonical_value(), "finding_ids": [item.finding_id for item in ordered], "authority": DispositionAuthority.NONE.value}, field="finding set")
    return ProposalValidationResult(proposal, validator_input, ordered, digest_bytes(canonical))


def build_pending_dispositions(
    validation: ProposalValidationResult,
    lead_heads: Mapping[str, LeadDispositionHeadBinding],
    selections: Mapping[str, OutcomeSelection],
) -> tuple[ProposalDisposition, ...]:
    """Build a complete no-authority per-Lead set; persistence remains v19 work."""

    if type(validation) is not ProposalValidationResult:
        raise DispositionContractError("validation result must be typed")
    if not isinstance(lead_heads, Mapping) or not isinstance(selections, Mapping):
        raise DispositionContractError("per-Lead disposition inputs must be mappings")
    if (
        not isinstance(validation.findings, tuple)
        or any(
            not isinstance(finding, ProposalValidationFinding)
            for finding in validation.findings
        )
    ):
        raise DispositionContractError("finding manifest must be typed")
    proposal = _exact_proposal(validation.proposal, field="proposal")
    validator_input = _exact_validator_input(
        validation.validator_input, field="validator input binding"
    )
    findings = tuple(
        _exact_finding(item, field="finding") for item in validation.findings
    )
    exact_validation = _constructed_value(
        lambda: ProposalValidationResult(
            proposal,
            validator_input,
            findings,
            validation.finding_set_digest,
            validation.authority,
        ),
        field="validation result",
    )
    proposal = exact_validation.proposal  # type: ignore[union-attr]
    validator_input = exact_validation.validator_input  # type: ignore[union-attr]
    findings = exact_validation.findings  # type: ignore[union-attr]
    proposal_bytes = _bounded_canonical_from(
        lambda: proposal.canonical_value(), field="proposal"
    )
    proposal_digest = digest_bytes(proposal_bytes)
    if any(
        finding.severity is FindingSeverity.ERROR
        for finding in findings
    ):
        raise DispositionContractError(
            "a disposition requires a complete finding set without validation errors"
        )
    expected = set(proposal.decision_lead_ids)
    head_keys = _constructed_value(lambda: set(lead_heads), field="Lead heads")
    selection_keys = _constructed_value(
        lambda: set(selections), field="outcome selections"
    )
    if head_keys != expected or selection_keys != expected:
        raise DispositionContractError("per-Lead disposition set must be complete")
    findings_by_lead = {
        item.evidence_reference_id for item in findings
    }
    if findings_by_lead != expected:
        raise DispositionContractError("finding manifest must be complete")
    recommendations = {
        item.decision_lead_id: item for item in proposal.recommendations
    }
    validator_value = _constructed_value(
        lambda: validator_input.canonical_value(), field="validator input binding"
    )
    _bounded_canonical(validator_value, field="validator input binding")
    result: list[ProposalDisposition] = []
    for lead_id in proposal.decision_lead_ids:
        head = _constructed_value(
            lambda: lead_heads[lead_id], field="Lead head binding"
        )
        selection = _constructed_value(
            lambda: selections[lead_id], field="outcome selection"
        )
        if not isinstance(head, LeadDispositionHeadBinding):
            raise DispositionContractError("Lead head binding must be typed")
        if not isinstance(selection, OutcomeSelection):
            raise DispositionContractError("outcome selection must be typed")
        head = _exact_lead_head(head, field="Lead head binding")
        head_value = _constructed_value(
            lambda: head.canonical_value(), field="Lead head binding"
        )
        if head.decision_lead_id != lead_id:
            raise DispositionContractError("Lead head binding differs from manifest")
        recommendation = recommendations[lead_id]
        if not isinstance(recommendation, LeadRecommendation):
            raise DispositionContractError("Proposal recommendation must be typed")
        recommendation, route_value = _exact_recommendation(
            recommendation, field="recommendation"
        )
        route_digest = digest_bytes(
            _bounded_canonical(route_value, field="recommendation")
        )
        rule = _ROUTE_RULES[recommendation.route]
        selection, selection_value = _exact_selection(
            selection, field="selection"
        )
        citation_digests = {
            citation.source_digest
            for citation in recommendation.input_citations
            if citation.source_kind.value == "DECISION_LEAD"
            and citation.source_id == lead_id
        }
        if citation_digests != {head.decision_lead_digest}:
            raise DispositionContractError(
                "Lead head digest differs from the exact Proposal citation"
            )
        _validate_exact_route_seam(recommendation, selection, route_digest)
        kwargs = dict(
            judgement=rule.judgement, proposal_id=proposal.proposal_id,
            proposal_content_identity=proposal.content_identity,
            proposal_canonical_digest=proposal_digest,
            work_item_id=proposal.work_item.work_item_id,
            work_item_version_id=proposal.work_item.work_item_version_id,
            work_item_version_digest=proposal.work_item.work_item_version_digest,
            retrieval_context_id=proposal.retrieval_context.context_id,
            retrieval_context_digest=proposal.retrieval_context.context_digest,
            lead_head=head, validator_input=validator_input,
            finding_set_digest=exact_validation.finding_set_digest,
            route=recommendation.route, route_binding=recommendation,
            route_binding_digest=route_digest, selection=selection,
        )
        identity = {
            "judgement": rule.judgement.value,
            "proposal_id": proposal.proposal_id,
            "proposal_content_identity": proposal.content_identity,
            "proposal_canonical_digest": proposal_digest,
            "work_item_id": proposal.work_item.work_item_id,
            "work_item_version_id": proposal.work_item.work_item_version_id,
            "work_item_version_digest": proposal.work_item.work_item_version_digest,
            "retrieval_context_id": proposal.retrieval_context.context_id,
            "retrieval_context_digest": proposal.retrieval_context.context_digest,
            "lead_head_binding": head_value,
            "validator_input_binding": validator_value,
            "finding_set_digest": exact_validation.finding_set_digest,
            "route": recommendation.route.value,
            "route_binding": route_value,
            "route_binding_digest": route_digest,
            "selection": selection_value,
            "authority": DispositionAuthority.NONE.value,
        }
        disposition_id = digest_bytes(
            _bounded_canonical(identity, field="disposition identity")
        )
        result.append(ProposalDisposition(disposition_id=disposition_id, **kwargs))  # type: ignore[arg-type]
    return tuple(result)


__all__ = [
    "DISPOSITION_AUTHORITY", "MAX_DISPOSITION_CANONICAL_BYTES",
    "PROPOSAL_DISPOSITION", "PROPOSAL_DISPOSITION_SCHEMA_VERSION",
    "PROPOSAL_VALIDATION_FINDING", "PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION",
    "VALIDATED_PROPOSAL_LEAD_DISPOSITION_BINDING", "DispositionAuthority",
    "DispositionContractError", "DispositionJudgement", "FindingCode", "FindingSeverity",
    "LeadDispositionHeadBinding", "ProposalDisposition", "ProposalValidationFinding",
    "ProposalValidationResult", "ValidatorInputBinding", "build_pending_dispositions",
    "validate_proposal",
]
