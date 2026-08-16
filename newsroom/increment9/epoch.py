"""Immutable Increment 9B1 Epoch, cohort, Run and evidence authority.

This module is effect-free apart from writes to an explicitly initialised,
isolated SQLite shadow authority.  It performs no source/provider/model call and
holds no external or production credential.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Mapping, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.increment9_shadow_migrations import (
    INCREMENT9_SHADOW_APPLICATION_ID,
    INCREMENT9_SHADOW_SCHEMA_VERSION,
    install_increment9_shadow_schema,
    verify_increment9_shadow_schema,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

MAX_RECORD_BYTES = 1_048_576
MAX_EPOCH_RECORDS = 200_000
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)

EFFECTIVE_MANIFEST_IDENTITY_KEYS = frozenset(
    {
        "candidate",
        "code",
        "config",
        "embedding",
        "handoff",
        "image",
        "index",
        "model",
        "ontology",
        "operational_profile",
        "projector",
        "prompt",
        "provider",
        "retrieval",
        "source",
        "triage",
    }
)
INCOMPATIBLE_EVALUATION_DIMENSIONS = frozenset(
    {
        "budget_rules",
        "comparator_rules",
        "prospective_universe",
        "reviewer_rules",
        "rights_rules",
        "slice_rules",
        "source_portfolio",
        "thresholds",
    }
)
COMPATIBLE_COHORT_DIMENSIONS = EFFECTIVE_MANIFEST_IDENTITY_KEYS


class EpochAuthorityError(ValueError):
    """An Epoch record or isolated-authority operation failed closed."""


class RunKind(StrEnum):
    REPLAY_QUALIFICATION = "REPLAY_QUALIFICATION"
    READINESS_PROBE = "READINESS_PROBE"
    PROSPECTIVE_BASELINE = "PROSPECTIVE_BASELINE"
    COMPARATOR = "COMPARATOR"
    FAULT = "FAULT"
    RECOVERY_PROOF = "RECOVERY_PROOF"


class RecordOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    EARLY_STOPPED = "EARLY_STOPPED"
    INCONCLUSIVE = "INCONCLUSIVE"
    LOST_RESPONSE = "LOST_RESPONSE"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"


class EffectKind(StrEnum):
    SOURCE_REQUEST = "SOURCE_REQUEST"
    PROVIDER_CALL = "PROVIDER_CALL"
    MODEL_CALL = "MODEL_CALL"
    EMBEDDING_CALL = "EMBEDDING_CALL"


class ChangeClassification(StrEnum):
    UNCHANGED = "UNCHANGED"
    COMPATIBLE_NEW_COHORT = "COMPATIBLE_NEW_COHORT"
    INCOMPATIBLE_NEW_EPOCH = "INCOMPATIBLE_NEW_EPOCH"
    UNRESOLVED_NOT_DECISION_BEARING = "UNRESOLVED_NOT_DECISION_BEARING"


class _NoExternalEffect:
    authorises_live_call = False
    authorises_credentials = False
    authorises_external_egress = False
    authorises_spend = False
    authorises_publication = False
    authorises_evidence_intake = False
    authorises_canary = False
    authorises_production_mutation = False
    authorises_production_activation = False


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EpochAuthorityError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _text(value: object, field: str, maximum: int = 2048) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8", errors="strict")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise EpochAuthorityError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise EpochAuthorityError(f"{field} must be a canonical token")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise EpochAuthorityError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise EpochAuthorityError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise EpochAuthorityError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise EpochAuthorityError(f"{field} must be a bounded integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise EpochAuthorityError(f"{field} must be a boolean")
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    try:
        if type(value) is not str and type(value) is not kind:
            raise ValueError
        return kind(value)
    except ValueError as exc:
        raise EpochAuthorityError(f"{field} differs") from exc


def _tokens(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if (
        type(value) not in (list, tuple)
        or (not value and not allow_empty)
        or len(value) > 256
    ):
        raise EpochAuthorityError(f"{field} must be a bounded array")
    result = tuple(_token(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise EpochAuthorityError(f"{field} must be unique and sorted")
    return result


def _digests(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if (
        type(value) not in (list, tuple)
        or (not value and not allow_empty)
        or len(value) > 4096
    ):
        raise EpochAuthorityError(f"{field} must be a bounded array")
    result = tuple(_digest(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise EpochAuthorityError(f"{field} must be unique and sorted")
    return result


def _mapping(value: object, fields: frozenset[str], field: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise EpochAuthorityError(f"{field} fields differ")
    return value


@dataclass(frozen=True, slots=True)
class _Record(_NoExternalEffect):
    schema_version: ClassVar[str]

    def primitive(self) -> dict[str, object]:
        raise NotImplementedError

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def _document(cls, raw: bytes, fields: frozenset[str]) -> dict[str, object]:
        if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
            raise EpochAuthorityError("Epoch record bytes are not bounded")
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
            canonical = canonical_json_bytes(value)
        except EpochAuthorityError:
            raise
        except (UnicodeError, json.JSONDecodeError, CanonicalizationError, RecursionError) as exc:
            raise EpochAuthorityError("Epoch record bytes are invalid") from exc
        if canonical != raw:
            raise EpochAuthorityError("Epoch record bytes must be exact canonical JSON")
        value = _mapping(value, fields | {"schema_version"}, "Epoch record")
        if value.pop("schema_version") != cls.schema_version:
            raise EpochAuthorityError("Epoch record schema differs")
        return value


@dataclass(frozen=True, slots=True)
class EvaluationEpoch(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.evaluation-epoch.v1"
    epoch_id: str
    plan_digest: str
    shadow_scope_digest: str
    source_portfolio_digest: str
    prospective_universe_digest: str
    slice_rules_digest: str
    thresholds_digest: str
    comparator_rules_digest: str
    reviewer_rules_digest: str
    budget_rules_digest: str
    rights_rules_digest: str
    opened_at: str
    cutoff_at: str
    closes_at: str
    prospective_only: bool = True
    hindsight_changes_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.epoch_id, "epoch_id")
        for field in (
            "plan_digest", "shadow_scope_digest", "source_portfolio_digest",
            "prospective_universe_digest", "slice_rules_digest", "thresholds_digest",
            "comparator_rules_digest", "reviewer_rules_digest", "budget_rules_digest",
            "rights_rules_digest",
        ):
            _digest(getattr(self, field), field)
        if self.plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise EpochAuthorityError("Epoch plan digest differs")
        for field in ("opened_at", "cutoff_at", "closes_at"):
            _timestamp(getattr(self, field), field)
        if not (_instant(self.opened_at) <= _instant(self.cutoff_at) < _instant(self.closes_at)):
            raise EpochAuthorityError("Epoch chronology differs")
        if self.prospective_only is not True or self.hindsight_changes_allowed is not False:
            raise EpochAuthorityError("Epoch prospective rules differ")

    def primitive(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, **{name: getattr(self, name) for name in self.__dataclass_fields__ if name != "schema_version"}}

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = cls._document(raw, frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version"))
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EffectiveManifest(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.effective-manifest.v1"
    manifest_id: str
    identity_digests: Mapping[str, str]
    observed_at: str
    identity_resolved: bool

    def __post_init__(self) -> None:
        _token(self.manifest_id, "manifest_id")
        if not isinstance(self.identity_digests, Mapping) or set(self.identity_digests) != EFFECTIVE_MANIFEST_IDENTITY_KEYS:
            raise EpochAuthorityError("Effective Manifest identity fields differ")
        frozen = {key: _digest(value, f"identity_digests.{key}") for key, value in self.identity_digests.items()}
        object.__setattr__(self, "identity_digests", MappingProxyType(dict(sorted(frozen.items()))))
        _timestamp(self.observed_at, "observed_at")
        _boolean(self.identity_resolved, "identity_resolved")

    @property
    def decision_bearing(self) -> bool:
        return self.identity_resolved

    def primitive(self) -> dict[str, object]:
        return {
            "identity_digests": dict(self.identity_digests),
            "identity_resolved": self.identity_resolved,
            "manifest_id": self.manifest_id,
            "observed_at": self.observed_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = cls._document(raw, frozenset({"manifest_id", "identity_digests", "observed_at", "identity_resolved"}))
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ManifestCohort(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.manifest-cohort.v1"
    cohort_id: str
    epoch_id: str
    epoch_digest: str
    manifest_digest: str
    ordinal: int
    previous_cohort_digest: str | None
    exposure_contract_digest: str
    required_slices: tuple[str, ...]
    opened_at: str
    decision_bearing: bool

    def __post_init__(self) -> None:
        _token(self.cohort_id, "cohort_id"); _token(self.epoch_id, "epoch_id")
        for field in ("epoch_digest", "manifest_digest", "exposure_contract_digest"):
            _digest(getattr(self, field), field)
        _integer(self.ordinal, "ordinal", minimum=1)
        if (self.ordinal == 1) != (self.previous_cohort_digest is None):
            raise EpochAuthorityError("cohort predecessor differs")
        if self.previous_cohort_digest is not None:
            _digest(self.previous_cohort_digest, "previous_cohort_digest")
        _tokens(self.required_slices, "required_slices")
        _timestamp(self.opened_at, "opened_at")
        _boolean(self.decision_bearing, "decision_bearing")

    def primitive(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "cohort_id": self.cohort_id, "epoch_id": self.epoch_id, "epoch_digest": self.epoch_digest, "manifest_digest": self.manifest_digest, "ordinal": self.ordinal, "previous_cohort_digest": self.previous_cohort_digest, "exposure_contract_digest": self.exposure_contract_digest, "required_slices": list(self.required_slices), "opened_at": self.opened_at, "decision_bearing": self.decision_bearing}

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = cls._document(raw, frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version"))
        value["required_slices"] = _tokens(value["required_slices"], "required_slices")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CohortCloseout(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.cohort-closeout.v1"
    closeout_id: str
    epoch_id: str
    epoch_digest: str
    final_cohort_digest: str
    observed_slice_ids: tuple[str, ...]
    exposure_minima_met: bool
    complete_denominators: bool
    unresolved_identity_count: int
    qualifies: bool
    closed_at: str

    def __post_init__(self) -> None:
        _token(self.closeout_id, "closeout_id")
        _token(self.epoch_id, "epoch_id")
        _digest(self.epoch_digest, "epoch_digest")
        _digest(self.final_cohort_digest, "final_cohort_digest")
        _tokens(self.observed_slice_ids, "observed_slice_ids", allow_empty=True)
        _boolean(self.exposure_minima_met, "exposure_minima_met")
        _boolean(self.complete_denominators, "complete_denominators")
        _integer(self.unresolved_identity_count, "unresolved_identity_count")
        _boolean(self.qualifies, "qualifies")
        _timestamp(self.closed_at, "closed_at")

    def primitive(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "closeout_id": self.closeout_id,
            "epoch_id": self.epoch_id,
            "epoch_digest": self.epoch_digest,
            "final_cohort_digest": self.final_cohort_digest,
            "observed_slice_ids": list(self.observed_slice_ids),
            "exposure_minima_met": self.exposure_minima_met,
            "complete_denominators": self.complete_denominators,
            "unresolved_identity_count": self.unresolved_identity_count,
            "qualifies": self.qualifies,
            "closed_at": self.closed_at,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = cls._document(
            raw,
            frozenset(
                name for name in cls.__dataclass_fields__ if name != "schema_version"
            ),
        )
        value["observed_slice_ids"] = _tokens(
            value["observed_slice_ids"], "observed_slice_ids", allow_empty=True
        )
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ShadowRun(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.shadow-run.v1"
    run_id: str
    epoch_id: str
    epoch_digest: str
    cohort_id: str
    cohort_digest: str
    manifest_digest: str
    production_snapshot_digest: str
    production_nonmutation_before_digest: str
    run_kind: RunKind
    started_at: str
    prospective: bool

    def __post_init__(self) -> None:
        for field in ("run_id", "epoch_id", "cohort_id"):
            _token(getattr(self, field), field)
        for field in ("epoch_digest", "cohort_digest", "manifest_digest", "production_snapshot_digest", "production_nonmutation_before_digest"):
            _digest(getattr(self, field), field)
        _enum(RunKind, self.run_kind, "run_kind")
        _timestamp(self.started_at, "started_at")
        _boolean(self.prospective, "prospective")
        if self.run_kind not in {RunKind.REPLAY_QUALIFICATION, RunKind.READINESS_PROBE} and self.prospective is not True:
            raise EpochAuthorityError("decision-bearing Run must be prospective")

    def primitive(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, **{name: (str(getattr(self, name)) if name == "run_kind" else getattr(self, name)) for name in self.__dataclass_fields__ if name != "schema_version"}}

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = cls._document(raw, frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version"))
        value["run_kind"] = _enum(RunKind, value["run_kind"], "run_kind")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RunAttempt(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.run-attempt.v1"
    attempt_id: str
    run_id: str
    run_digest: str
    ordinal: int
    previous_attempt_digest: str | None
    started_at: str
    restart_reason: str | None

    def __post_init__(self) -> None:
        _token(self.attempt_id, "attempt_id"); _token(self.run_id, "run_id"); _digest(self.run_digest, "run_digest")
        _integer(self.ordinal, "ordinal", minimum=1)
        if (self.ordinal == 1) != (self.previous_attempt_digest is None):
            raise EpochAuthorityError("Attempt predecessor differs")
        if self.previous_attempt_digest is not None: _digest(self.previous_attempt_digest, "previous_attempt_digest")
        _timestamp(self.started_at, "started_at")
        if self.ordinal > 1 and self.restart_reason is None: raise EpochAuthorityError("restart reason is required")
        if self.restart_reason is not None: _token(self.restart_reason, "restart_reason")

    def primitive(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, **{name: getattr(self, name) for name in self.__dataclass_fields__ if name != "schema_version"}}

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        return cls(**cls._document(raw, frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EffectIntent(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.effect-intent.v1"
    intent_id: str
    attempt_id: str
    attempt_digest: str
    sequence: int
    effect_kind: EffectKind
    request_digest: str
    budget_reservation_digest: str
    persisted_at: str

    def __post_init__(self) -> None:
        _token(self.intent_id, "intent_id"); _token(self.attempt_id, "attempt_id"); _digest(self.attempt_digest, "attempt_digest")
        _integer(self.sequence, "sequence", minimum=1); _enum(EffectKind, self.effect_kind, "effect_kind")
        _digest(self.request_digest, "request_digest"); _digest(self.budget_reservation_digest, "budget_reservation_digest"); _timestamp(self.persisted_at, "persisted_at")

    def primitive(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, **{name: (str(getattr(self, name)) if name == "effect_kind" else getattr(self, name)) for name in self.__dataclass_fields__ if name != "schema_version"}}

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value=cls._document(raw,frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")); value["effect_kind"]=_enum(EffectKind,value["effect_kind"],"effect_kind"); return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EffectResult(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.effect-result.v1"
    result_id: str
    intent_id: str
    intent_digest: str
    response_digest: str | None
    usage_digest: str
    outcome: RecordOutcome
    observed_valid_at: str
    completed_at: str
    recorded_at: str

    def __post_init__(self) -> None:
        _token(self.result_id,"result_id"); _token(self.intent_id,"intent_id"); _digest(self.intent_digest,"intent_digest")
        if self.response_digest is not None: _digest(self.response_digest,"response_digest")
        _digest(self.usage_digest,"usage_digest"); _enum(RecordOutcome,self.outcome,"outcome"); _timestamp(self.observed_valid_at,"observed_valid_at"); _timestamp(self.completed_at,"completed_at"); _timestamp(self.recorded_at,"recorded_at")
        if _instant(self.recorded_at)<_instant(self.completed_at):raise EpochAuthorityError("result transaction time precedes completion")
        if self.response_digest is None and self.outcome not in {RecordOutcome.LOST_RESPONSE,RecordOutcome.AMBIGUOUS_EFFECT,RecordOutcome.UNAVAILABLE,RecordOutcome.FAILED}:
            raise EpochAuthorityError("missing response outcome differs")

    def primitive(self)->dict[str,object]:
        return {"schema_version":self.schema_version,**{name:(str(getattr(self,name)) if name=="outcome" else getattr(self,name)) for name in self.__dataclass_fields__ if name!="schema_version"}}

    @classmethod
    def from_bytes(cls,raw:bytes)->Self:
        value=cls._document(raw,frozenset(name for name in cls.__dataclass_fields__ if name!="schema_version"));value["outcome"]=_enum(RecordOutcome,value["outcome"],"outcome");return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Checkpoint(_Record):
    schema_version: ClassVar[str]="newsroom.increment9.checkpoint.v1"
    checkpoint_id:str; attempt_id:str; attempt_digest:str; sequence:int; watermark:str; inventory_digest:str; ledger_digest:str; recorded_at:str
    def __post_init__(self)->None:
        _token(self.checkpoint_id,"checkpoint_id");_token(self.attempt_id,"attempt_id");_digest(self.attempt_digest,"attempt_digest");_integer(self.sequence,"sequence",minimum=0);_token(self.watermark,"watermark");_digest(self.inventory_digest,"inventory_digest");_digest(self.ledger_digest,"ledger_digest");_timestamp(self.recorded_at,"recorded_at")
    def primitive(self)->dict[str,object]:return {"schema_version":self.schema_version,**{n:getattr(self,n) for n in self.__dataclass_fields__ if n!="schema_version"}}
    @classmethod
    def from_bytes(cls,raw:bytes)->Self:return cls(**cls._document(raw,frozenset(n for n in cls.__dataclass_fields__ if n!="schema_version")))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CostRecord(_Record):
    schema_version: ClassVar[str]="newsroom.increment9.cost-record.v1"
    cost_id:str; attempt_id:str; intent_digest:str; provider:str; input_units:int; output_units:int; monetary_minor_units:int; storage_byte_days:int; recorded_at:str
    def __post_init__(self)->None:
        _token(self.cost_id,"cost_id");_token(self.attempt_id,"attempt_id");_digest(self.intent_digest,"intent_digest");_token(self.provider,"provider")
        for f in ("input_units","output_units","monetary_minor_units","storage_byte_days"):_integer(getattr(self,f),f)
        _timestamp(self.recorded_at,"recorded_at")
    def primitive(self)->dict[str,object]:return {"schema_version":self.schema_version,**{n:getattr(self,n) for n in self.__dataclass_fields__ if n!="schema_version"}}
    @classmethod
    def from_bytes(cls,raw:bytes)->Self:return cls(**cls._document(raw,frozenset(n for n in cls.__dataclass_fields__ if n!="schema_version")))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RunOutcome(_Record):
    schema_version: ClassVar[str]="newsroom.increment9.run-outcome.v1"
    outcome_id:str; run_id:str; run_digest:str; attempt_digest:str; cohort_digest:str; outcome:RecordOutcome; evidence_inventory_digest:str; production_nonmutation_after_digest:str; decision_bearing:bool; recorded_at:str
    def __post_init__(self)->None:
        _token(self.outcome_id,"outcome_id");_token(self.run_id,"run_id")
        for f in ("run_digest","attempt_digest","cohort_digest","evidence_inventory_digest","production_nonmutation_after_digest"):_digest(getattr(self,f),f)
        _enum(RecordOutcome,self.outcome,"outcome");_boolean(self.decision_bearing,"decision_bearing");_timestamp(self.recorded_at,"recorded_at")
        if self.outcome in {RecordOutcome.PARTIAL,RecordOutcome.STALE,RecordOutcome.UNAVAILABLE,RecordOutcome.BLOCKED,RecordOutcome.FAILED,RecordOutcome.EARLY_STOPPED,RecordOutcome.INCONCLUSIVE,RecordOutcome.LOST_RESPONSE,RecordOutcome.AMBIGUOUS_EFFECT} and self.decision_bearing:
            raise EpochAuthorityError("non-complete outcome cannot be decision-bearing")
    def primitive(self)->dict[str,object]:return {"schema_version":self.schema_version,**{n:(str(getattr(self,n)) if n=="outcome" else getattr(self,n)) for n in self.__dataclass_fields__ if n!="schema_version"}}
    @classmethod
    def from_bytes(cls,raw:bytes)->Self:
        v=cls._document(raw,frozenset(n for n in cls.__dataclass_fields__ if n!="schema_version"));v["outcome"]=_enum(RecordOutcome,v["outcome"],"outcome");return cls(**v)  # type: ignore[arg-type]


RECORD_TYPES: Mapping[str,type[_Record]]=MappingProxyType({c.schema_version:c for c in (EvaluationEpoch,EffectiveManifest,ManifestCohort,CohortCloseout,ShadowRun,RunAttempt,EffectIntent,EffectResult,Checkpoint,CostRecord,RunOutcome)})


def classify_manifest_change(changed_dimensions: tuple[str,...], *, identities_resolved: bool)->ChangeClassification:
    dimensions=_tokens(changed_dimensions,"changed_dimensions",allow_empty=True)
    if not identities_resolved:return ChangeClassification.UNRESOLVED_NOT_DECISION_BEARING
    if not dimensions:return ChangeClassification.UNCHANGED
    unknown=set(dimensions)-INCOMPATIBLE_EVALUATION_DIMENSIONS-COMPATIBLE_COHORT_DIMENSIONS
    if unknown:raise EpochAuthorityError("change dimension is not classified")
    if set(dimensions)&INCOMPATIBLE_EVALUATION_DIMENSIONS:return ChangeClassification.INCOMPATIBLE_NEW_EPOCH
    return ChangeClassification.COMPATIBLE_NEW_COHORT


def validate_cohort_chain(epoch:EvaluationEpoch, manifests:Mapping[str,EffectiveManifest], cohorts:tuple[ManifestCohort,...])->tuple[ManifestCohort,...]:
    if type(cohorts) is not tuple or not cohorts:raise EpochAuthorityError("cohort chain must be non-empty")
    previous=None
    for ordinal,cohort in enumerate(cohorts,1):
        if type(cohort) is not ManifestCohort or cohort.epoch_id!=epoch.epoch_id or cohort.epoch_digest!=epoch.canonical_digest or cohort.ordinal!=ordinal:raise EpochAuthorityError("cohort Epoch binding differs")
        expected=None if previous is None else previous.canonical_digest
        if cohort.previous_cohort_digest!=expected:raise EpochAuthorityError("cohort predecessor differs")
        manifest=manifests.get(cohort.manifest_digest)
        if type(manifest) is not EffectiveManifest or cohort.decision_bearing!=manifest.decision_bearing:raise EpochAuthorityError("cohort manifest identity differs")
        if not (_instant(epoch.cutoff_at)<=_instant(cohort.opened_at)<_instant(epoch.closes_at)):raise EpochAuthorityError("cohort Epoch chronology differs")
        if previous is not None and _instant(previous.opened_at)>=_instant(cohort.opened_at):raise EpochAuthorityError("cohort transition chronology differs")
        previous=cohort
    return cohorts


def validate_cohort_closeout(epoch:EvaluationEpoch, cohorts:tuple[ManifestCohort,...], closeout:CohortCloseout)->CohortCloseout:
    if type(closeout) is not CohortCloseout or not cohorts:raise EpochAuthorityError("cohort closeout differs")
    final=cohorts[-1]
    if closeout.epoch_id!=epoch.epoch_id or closeout.epoch_digest!=epoch.canonical_digest or closeout.final_cohort_digest!=final.canonical_digest:raise EpochAuthorityError("only the final cohort may close out")
    if _instant(closeout.closed_at)<=_instant(final.opened_at):raise EpochAuthorityError("final cohort is not closed")
    expected=bool(final.decision_bearing and set(closeout.observed_slice_ids)==set(final.required_slices) and closeout.exposure_minima_met and closeout.complete_denominators and closeout.unresolved_identity_count==0)
    if closeout.qualifies is not expected:raise EpochAuthorityError("cohort qualification truth differs")
    if _instant(closeout.closed_at)>_instant(epoch.closes_at):raise EpochAuthorityError("cohort closeout exceeds Epoch")
    return closeout


def qualify_final_cohort(epoch:EvaluationEpoch, cohorts:tuple[ManifestCohort,...], closeout:CohortCloseout)->bool:
    validate_cohort_closeout(epoch,cohorts,closeout);return closeout.qualifies


class ShadowEpochAuthority(_NoExternalEffect):
    """Checked append-only persistence over an isolated Increment 9 database."""
    def __init__(self,connection:sqlite3.Connection)->None:
        if not isinstance(connection,sqlite3.Connection):raise EpochAuthorityError("SQLite connection is required")
        verify_increment9_shadow_schema(connection);self.__connection=connection
    def append(self,record:_Record,*,epoch_id:str)->str:
        verify_increment9_shadow_schema(self.__connection)
        if type(record) not in set(RECORD_TYPES.values()):raise EpochAuthorityError("record type is not admitted")
        _token(epoch_id,"epoch_id")
        raw=record.canonical_bytes;digest=record.canonical_digest
        try:
            self.__connection.execute("BEGIN IMMEDIATE")
            if self.__connection.execute("SELECT 1 FROM shadow_epoch_records WHERE epoch_id=? AND record_schema=? LIMIT 1",(epoch_id,CohortCloseout.schema_version)).fetchone() is not None:raise EpochAuthorityError("Epoch is already closed out")
            count=self.__connection.execute("SELECT count(*) FROM shadow_epoch_records WHERE epoch_id=?",(epoch_id,)).fetchone()[0]
            if count>=MAX_EPOCH_RECORDS:raise EpochAuthorityError("Epoch record inventory limit reached")
            cohort_digest,run_id,attempt_id,sequence=self._validate_dependencies(record,epoch_id)
            self.__connection.execute("INSERT INTO shadow_epoch_records(record_schema,record_id,record_bytes,record_digest,epoch_id,cohort_digest,run_id,attempt_id,sequence) VALUES(?,?,?,?,?,?,?,?,?)",(record.schema_version,_record_id(record),raw,digest,epoch_id,cohort_digest,run_id,attempt_id,sequence))
            self.__connection.commit()
        except sqlite3.Error as exc:
            if self.__connection.in_transaction:self.__connection.rollback()
            raise EpochAuthorityError("isolated shadow append failed") from exc
        except EpochAuthorityError:
            if self.__connection.in_transaction:self.__connection.rollback()
            raise
        return digest
    def _required(self,digest:str,schema:str)->_Record:
        row=self.__connection.execute("SELECT record_schema,record_bytes FROM shadow_epoch_records WHERE record_digest=?",(digest,)).fetchone()
        if row is None or row[0]!=schema:raise EpochAuthorityError("required predecessor record is absent")
        kind=RECORD_TYPES[schema];return kind.from_bytes(bytes(row[1]))
    def _required_id(self,schema:str,record_id:str)->_Record:
        row=self.__connection.execute("SELECT record_bytes FROM shadow_epoch_records WHERE record_schema=? AND record_id=?",(schema,record_id)).fetchone()
        if row is None:raise EpochAuthorityError("required predecessor record is absent")
        return RECORD_TYPES[schema].from_bytes(bytes(row[0]))
    def _run_for_attempt(self,attempt:RunAttempt,epoch_id:str)->ShadowRun:
        run=self._required(attempt.run_digest,ShadowRun.schema_version)
        if not isinstance(run,ShadowRun) or run.run_id!=attempt.run_id or run.epoch_id!=epoch_id:raise EpochAuthorityError("Attempt Run binding differs")
        return run
    def _validate_dependencies(self,record:_Record,epoch_id:str)->tuple[str|None,str|None,str|None,int|None]:
        if isinstance(record,EvaluationEpoch):
            if record.epoch_id!=epoch_id:raise EpochAuthorityError("Epoch persistence identity differs")
            return None,None,None,None
        persisted_epoch=self._required_id(EvaluationEpoch.schema_version,epoch_id)
        if not isinstance(persisted_epoch,EvaluationEpoch):raise EpochAuthorityError("Epoch persistence identity differs")
        if isinstance(record,EffectiveManifest):return None,None,None,None
        if isinstance(record,ManifestCohort):
            epoch=self._required(record.epoch_digest,EvaluationEpoch.schema_version)
            self._required(record.manifest_digest,EffectiveManifest.schema_version)
            if not isinstance(epoch,EvaluationEpoch) or epoch.epoch_id!=record.epoch_id or record.epoch_id!=epoch_id:raise EpochAuthorityError("cohort persistence binding differs")
            if record.previous_cohort_digest is not None:self._required(record.previous_cohort_digest,ManifestCohort.schema_version)
            prior=tuple(sorted((ManifestCohort.from_bytes(bytes(row[0])) for row in self.__connection.execute("SELECT record_bytes FROM shadow_epoch_records WHERE epoch_id=? AND record_schema=?",(epoch_id,ManifestCohort.schema_version))),key=lambda item:item.ordinal))
            cohorts=prior+(record,)
            manifests={cohort.manifest_digest:self._required(cohort.manifest_digest,EffectiveManifest.schema_version) for cohort in cohorts}
            validate_cohort_chain(epoch,manifests,cohorts)
            return record.canonical_digest,None,None,None
        if isinstance(record,CohortCloseout):
            epoch=self._required(record.epoch_digest,EvaluationEpoch.schema_version);self._required(record.final_cohort_digest,ManifestCohort.schema_version)
            if not isinstance(epoch,EvaluationEpoch) or epoch.epoch_id!=record.epoch_id:raise EpochAuthorityError("cohort closeout persistence binding differs")
            cohorts=tuple(sorted((ManifestCohort.from_bytes(bytes(row[0])) for row in self.__connection.execute("SELECT record_bytes FROM shadow_epoch_records WHERE epoch_id=? AND record_schema=?",(epoch_id,ManifestCohort.schema_version))),key=lambda item:item.ordinal))
            manifests={cohort.manifest_digest:self._required(cohort.manifest_digest,EffectiveManifest.schema_version) for cohort in cohorts}
            validate_cohort_chain(epoch,manifests,cohorts)
            validate_cohort_closeout(epoch,cohorts,record)
            return record.final_cohort_digest,None,None,None
        if isinstance(record,ShadowRun):
            epoch=self._required(record.epoch_digest,EvaluationEpoch.schema_version);cohort=self._required(record.cohort_digest,ManifestCohort.schema_version);self._required(record.manifest_digest,EffectiveManifest.schema_version)
            if not isinstance(epoch,EvaluationEpoch) or not isinstance(cohort,ManifestCohort) or epoch.epoch_id!=record.epoch_id or cohort.cohort_id!=record.cohort_id or cohort.manifest_digest!=record.manifest_digest or epoch_id!=record.epoch_id:raise EpochAuthorityError("Run persistence binding differs")
            cohorts=tuple(ManifestCohort.from_bytes(bytes(row[0])) for row in self.__connection.execute("SELECT record_bytes FROM shadow_epoch_records WHERE epoch_id=? AND record_schema=?",(epoch_id,ManifestCohort.schema_version)))
            if not cohorts or max(cohorts,key=lambda item:item.ordinal).canonical_digest!=record.cohort_digest:raise EpochAuthorityError("Run cohort is not current")
            return record.cohort_digest,record.run_id,None,None
        if isinstance(record,RunAttempt):
            run=self._run_for_attempt(record,epoch_id)
            if record.previous_attempt_digest is not None:
                previous=self._required(record.previous_attempt_digest,RunAttempt.schema_version)
                if not isinstance(previous,RunAttempt) or previous.run_id!=record.run_id or previous.ordinal+1!=record.ordinal:raise EpochAuthorityError("Attempt predecessor binding differs")
            return run.cohort_digest,run.run_id,record.attempt_id,None
        if isinstance(record,EffectIntent):
            attempt=self._required(record.attempt_digest,RunAttempt.schema_version)
            if not isinstance(attempt,RunAttempt) or attempt.attempt_id!=record.attempt_id or _instant(record.persisted_at)<_instant(attempt.started_at):raise EpochAuthorityError("intent Attempt binding differs")
            run=self._run_for_attempt(attempt,epoch_id)
            return run.cohort_digest,run.run_id,attempt.attempt_id,record.sequence
        if isinstance(record,EffectResult):
            intent=self._required(record.intent_digest,EffectIntent.schema_version)
            if not isinstance(intent,EffectIntent) or intent.intent_id!=record.intent_id or _instant(record.completed_at)<_instant(intent.persisted_at):raise EpochAuthorityError("result intent binding differs")
            attempt=self._required(intent.attempt_digest,RunAttempt.schema_version)
            if not isinstance(attempt,RunAttempt):raise EpochAuthorityError("result Attempt binding differs")
            run=self._required(attempt.run_digest,ShadowRun.schema_version)
            if not isinstance(run,ShadowRun):raise EpochAuthorityError("result Run binding differs")
            epoch=self._required(run.epoch_digest,EvaluationEpoch.schema_version)
            if not isinstance(epoch,EvaluationEpoch) or (run.prospective and _instant(record.observed_valid_at)<_instant(epoch.cutoff_at)):raise EpochAuthorityError("result prospective cutoff differs")
            return run.cohort_digest,run.run_id,attempt.attempt_id,intent.sequence
        if isinstance(record,Checkpoint):
            attempt=self._required(record.attempt_digest,RunAttempt.schema_version)
            if not isinstance(attempt,RunAttempt) or attempt.attempt_id!=record.attempt_id or _instant(record.recorded_at)<_instant(attempt.started_at):raise EpochAuthorityError("checkpoint Attempt binding differs")
            run=self._run_for_attempt(attempt,epoch_id);return run.cohort_digest,run.run_id,attempt.attempt_id,record.sequence
        if isinstance(record,CostRecord):
            intent=self._required(record.intent_digest,EffectIntent.schema_version)
            if not isinstance(intent,EffectIntent) or intent.attempt_id!=record.attempt_id or _instant(record.recorded_at)<_instant(intent.persisted_at):raise EpochAuthorityError("cost intent binding differs")
            attempt=self._required(intent.attempt_digest,RunAttempt.schema_version)
            if not isinstance(attempt,RunAttempt):raise EpochAuthorityError("cost Attempt binding differs")
            run=self._run_for_attempt(attempt,epoch_id);return run.cohort_digest,run.run_id,attempt.attempt_id,intent.sequence
        if isinstance(record,RunOutcome):
            run=self._required(record.run_digest,ShadowRun.schema_version);attempt=self._required(record.attempt_digest,RunAttempt.schema_version);cohort=self._required(record.cohort_digest,ManifestCohort.schema_version)
            if not isinstance(run,ShadowRun) or not isinstance(attempt,RunAttempt) or not isinstance(cohort,ManifestCohort) or run.run_id!=record.run_id or run.epoch_id!=epoch_id or attempt.run_digest!=record.run_digest or record.cohort_digest!=run.cohort_digest or (record.decision_bearing and (record.outcome is not RecordOutcome.COMPLETE or not cohort.decision_bearing)) or _instant(record.recorded_at)<_instant(attempt.started_at):raise EpochAuthorityError("Run outcome binding differs")
            return run.cohort_digest,run.run_id,attempt.attempt_id,None
        raise EpochAuthorityError("record dependency policy is absent")
    def read(self,digest:str)->_Record:
        verify_increment9_shadow_schema(self.__connection)
        digest=_digest(digest,"record_digest");row=self.__connection.execute("SELECT record_schema,record_bytes FROM shadow_epoch_records WHERE record_digest=?",(digest,)).fetchone()
        if row is None:raise EpochAuthorityError("record is absent")
        kind=RECORD_TYPES.get(row[0])
        if kind is None:raise EpochAuthorityError("stored record schema differs")
        record=kind.from_bytes(bytes(row[1]))
        if record.canonical_digest!=digest:raise EpochAuthorityError("stored record digest differs")
        return record
    def inventory(self,epoch_id:str)->tuple[str,...]:
        verify_increment9_shadow_schema(self.__connection);_token(epoch_id,"epoch_id");return tuple(row[0] for row in self.__connection.execute("SELECT record_digest FROM shadow_epoch_records WHERE epoch_id=? ORDER BY record_schema,record_id",(epoch_id,)))


def _record_id(record:_Record)->str:
    fields:Mapping[type[_Record],str]=MappingProxyType({
        EvaluationEpoch:"epoch_id",
        EffectiveManifest:"manifest_id",
        ManifestCohort:"cohort_id",
        CohortCloseout:"closeout_id",
        ShadowRun:"run_id",
        RunAttempt:"attempt_id",
        EffectIntent:"intent_id",
        EffectResult:"result_id",
        Checkpoint:"checkpoint_id",
        CostRecord:"cost_id",
        RunOutcome:"outcome_id",
    })
    name=fields.get(type(record))
    if name is None:raise EpochAuthorityError("record identity is absent")
    return _token(getattr(record,name),"record_id")


def initialise_shadow_epoch_authority(connection:sqlite3.Connection)->ShadowEpochAuthority:
    install_increment9_shadow_schema(connection);return ShadowEpochAuthority(connection)


class ReplayController(_NoExternalEffect):
    """Deterministic fake/replay recorder; it never executes an intent."""
    def __init__(self,authority:ShadowEpochAuthority)->None:self._authority=authority
    def replay(self,records:tuple[_Record,...],*,epoch_id:str)->tuple[str,...]:
        digests=[]
        for record in records:
            digests.append(self._authority.append(record,epoch_id=epoch_id))
        return tuple(digests)
