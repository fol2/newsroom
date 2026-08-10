"""Stable Event Hypothesis identities and immutable version snapshots.

This is the sole public Increment 6D1 surface.  A Hypothesis records an
editorially unverified proposal association; it grants no Candidate,
relationship, evidence, publication, model, provider, egress, or external
effect authority.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Self

from newsroom.authority.canonical import (
    MAX_SAFE_INTEGER,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.increment6.proposals import HypothesisRelationship

EVENT_HYPOTHESIS = "newsroom.increment6.event-hypothesis.v1"
EVENT_HYPOTHESIS_VERSION = "newsroom.increment6.event-hypothesis-version.v1"
HYPOTHESIS_CURRENT_VERSION = "EXACT_RETAINED_MAX_ORDINAL_HEAD"
MAX_HYPOTHESIS_VERSION_BYTES = 1_048_576
_NAMESPACE = uuid.UUID("435812df-489e-5e4c-9b3d-838148b1918a")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_CREATE_RELATIONSHIPS = {
    HypothesisRelationship.NO_ADEQUATE_PRIOR_MATCH,
    HypothesisRelationship.RELATED_DISTINCT,
    HypothesisRelationship.UNCERTAIN,
}
_APPEND_RELATIONSHIPS = {
    HypothesisRelationship.SAME_STATE,
    HypothesisRelationship.DEVELOPMENT_OF,
    HypothesisRelationship.CORRECTION_REVERSAL_OF,
}


class HypothesisContractError(ValueError):
    """A Hypothesis value, replay, or authority claim failed closed."""


class _NoEffect:
    authorises_persistence = False
    authorises_external_effect = False
    authorises_publication = False
    authorises_evidence = False
    authorises_egress = False
    creates_candidate = False
    creates_relationship = False
    model_authority = False
    provider_authority = False


def _normalise[T](operation: object, message: str) -> T:
    try:
        return operation()  # type: ignore[operator,no-any-return]
    except HypothesisContractError:
        raise
    except Exception as exc:
        raise HypothesisContractError(message) from exc


def _uuid(value: object, field: str) -> str:
    if type(value) is not str:
        raise HypothesisContractError(f"{field} must be a canonical UUID")
    parsed = _normalise(lambda: uuid.UUID(value), f"{field} must be a canonical UUID")
    if str(parsed) != value:
        raise HypothesisContractError(f"{field} must be a canonical UUID")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise HypothesisContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _token(value: object, field: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise HypothesisContractError(f"{field} must be bounded canonical text")
    return value


def _text(value: object, field: str) -> str:
    try:
        valid = (
            type(value) is str
            and bool(value)
            and value == value.strip()
            and len(value.encode("utf-8")) <= 4096
        )
    except Exception as exc:
        raise HypothesisContractError(
            f"{field} must be bounded canonical text"
        ) from exc
    if not valid:
        raise HypothesisContractError(f"{field} must be bounded canonical text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise HypothesisContractError(
            f"{field} must be an exact bounded positive integer"
        )
    return value


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str:
        raise HypothesisContractError(f"{field} must be an exact UTC timestamp")
    parsed = _normalise(
        lambda: UtcTimestamp.parse(value), f"{field} must be an exact UTC timestamp"
    )
    if parsed.to_text() != value:
        raise HypothesisContractError(f"{field} must be an exact UTC timestamp")
    return value


def _exact(value: object, fields: set[str], field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise HypothesisContractError(f"{field} fields are not exact")
    try:
        if set(value) != fields:
            raise HypothesisContractError(f"{field} fields are not exact")
    except HypothesisContractError:
        raise
    except Exception as exc:
        raise HypothesisContractError(f"{field} fields are not exact") from exc
    return value


def _decode(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_HYPOTHESIS_VERSION_BYTES:
        raise HypothesisContractError("canonical input is not bounded immutable bytes")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise HypothesisContractError(f"duplicate object name: {key}")
            result[key] = value
        return result

    def integer(text: str) -> int:
        if len(text.lstrip("-")) > 16:
            raise HypothesisContractError("integer exceeds the producer envelope")
        value = int(text)
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise HypothesisContractError("integer exceeds the producer envelope")
        return value

    def no_float(_: str) -> float:
        raise HypothesisContractError("floating-point values are unsupported")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_int=integer,
            parse_float=no_float,
            parse_constant=no_float,
        )
    except HypothesisContractError:
        raise
    except Exception as exc:
        raise HypothesisContractError("canonical input is invalid UTF-8 JSON") from exc
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 24 or nodes > 32768:
            raise HypothesisContractError("canonical input exceeds structural bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, bool, type(None)):
            raise HypothesisContractError(
                "canonical input contains an unsupported value"
            )
    if type(value) is not dict:
        raise HypothesisContractError("canonical input must be an object")
    try:
        if canonical_json_bytes(value) != raw:
            raise HypothesisContractError("canonical input bytes differ")
    except HypothesisContractError:
        raise
    except Exception as exc:
        raise HypothesisContractError("canonical input cannot be normalised") from exc
    return value


@dataclass(frozen=True, slots=True)
class EventHypothesis(_NoEffect):
    hypothesis_id: str

    def __post_init__(self) -> None:
        if type(self) is not EventHypothesis:
            raise HypothesisContractError("Hypothesis requires the exact contract type")
        _uuid(self.hypothesis_id, "hypothesis_id")

    @classmethod
    def allocate(cls, proposal_id: str, proposal_local_id: str) -> Self:
        _token(proposal_id, "proposal_id")
        _token(proposal_local_id, "proposal_local_id")
        return cls(str(uuid.uuid5(_NAMESPACE, f"{proposal_id}\0{proposal_local_id}")))

    @property
    def canonical_bytes(self) -> bytes:
        return _normalise(
            lambda: canonical_json_bytes(
                {
                    "schema_version": EVENT_HYPOTHESIS,
                    "hypothesis_id": self.hypothesis_id,
                }
            ),
            "Hypothesis cannot be canonicalised",
        )

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        root = _exact(_decode(raw), {"schema_version", "hypothesis_id"}, "Hypothesis")
        if root["schema_version"] != EVENT_HYPOTHESIS:
            raise HypothesisContractError("Hypothesis schema is unsupported")
        return _normalise(
            lambda: cls(_uuid(root["hypothesis_id"], "hypothesis_id")),
            "Hypothesis replay failed",
        )


@dataclass(frozen=True, slots=True)
class HypothesisSourceBinding:
    disposition_id: str
    disposition_digest: str
    finding_set_digest: str
    route_binding_digest: str
    decision_lead_id: str
    decision_lead_digest: str
    decision_lead_head_id: str
    decision_lead_head_digest: str

    def __post_init__(self) -> None:
        if type(self) is not HypothesisSourceBinding:
            raise HypothesisContractError(
                "source binding requires the exact contract type"
            )
        _digest(self.disposition_id, "disposition_id")
        for name in (
            "disposition_digest",
            "finding_set_digest",
            "route_binding_digest",
            "decision_lead_digest",
            "decision_lead_head_digest",
        ):
            _digest(getattr(self, name), name)
        _uuid(self.decision_lead_id, "decision_lead_id")
        _uuid(self.decision_lead_head_id, "decision_lead_head_id")

    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {name: getattr(self, name) for name in self.__dataclass_fields__},
            "source binding cannot be canonicalised",
        )

    @classmethod
    def from_value(cls, value: object) -> Self:
        fields = set(cls.__dataclass_fields__)
        item = _exact(value, fields, "source binding")
        return cls(**{name: item[name] for name in fields})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EventHypothesisVersion(_NoEffect):
    version_id: str
    hypothesis_id: str
    ordinal: int
    previous_version_id: str | None
    previous_version_digest: str | None
    proposed_summary: str
    proposed_relationship: HypothesisRelationship
    proposed_target_hypothesis_id: str | None
    target_version_id: str | None
    target_version_digest: str | None
    proposal_id: str
    proposal_content_identity: str
    proposal_canonical_digest: str
    proposal_local_id: str
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    retrieval_context_id: str
    retrieval_context_digest: str
    source_bindings: tuple[HypothesisSourceBinding, ...]
    actor_identity_digest: str
    authority_event_id: str
    recorded_at: str

    def __post_init__(self) -> None:
        if type(self) is not EventHypothesisVersion:
            raise HypothesisContractError(
                "Hypothesis Version requires the exact contract type"
            )
        _uuid(self.hypothesis_id, "hypothesis_id")
        _uuid(self.version_id, "version_id")
        ordinal = _integer(self.ordinal, "ordinal")
        expected = str(uuid.uuid5(uuid.UUID(self.hypothesis_id), f"version:{ordinal}"))
        if self.version_id != expected:
            raise HypothesisContractError(
                "version_id differs from stable identity and ordinal"
            )
        if (ordinal == 1) != (
            self.previous_version_id is None and self.previous_version_digest is None
        ):
            raise HypothesisContractError("predecessor binding differs from ordinal")
        if self.previous_version_id is not None:
            _uuid(self.previous_version_id, "previous_version_id")
        if self.previous_version_digest is not None:
            _digest(self.previous_version_digest, "previous_version_digest")
        _text(self.proposed_summary, "proposed_summary")
        if type(self.proposed_relationship) is not HypothesisRelationship:
            raise HypothesisContractError("proposed_relationship must be exact")
        target_required = (
            self.proposed_relationship
            is not HypothesisRelationship.NO_ADEQUATE_PRIOR_MATCH
        )
        if target_required != (
            self.proposed_target_hypothesis_id is not None
            and self.target_version_id is not None
            and self.target_version_digest is not None
        ):
            raise HypothesisContractError("proposed target differs from relationship")
        if not target_required and (
            self.target_version_id is not None or self.target_version_digest is not None
        ):
            raise HypothesisContractError(
                "target Version must be absent without a target"
            )
        if self.proposed_target_hypothesis_id is not None:
            _uuid(self.proposed_target_hypothesis_id, "proposed_target_hypothesis_id")
        if self.target_version_id is not None:
            _uuid(self.target_version_id, "target_version_id")
        if self.target_version_digest is not None:
            _digest(self.target_version_digest, "target_version_digest")
        for name in (
            "proposal_id",
            "proposal_local_id",
            "work_item_id",
            "work_item_version_id",
            "retrieval_context_id",
        ):
            _token(getattr(self, name), name)
        if ordinal == 1:
            if self.proposed_relationship not in _CREATE_RELATIONSHIPS:
                raise HypothesisContractError(
                    "first Version requires a create relationship"
                )
            stable_identity = EventHypothesis.allocate(
                self.proposal_id, self.proposal_local_id
            )
            if self.hypothesis_id != stable_identity.hypothesis_id:
                raise HypothesisContractError(
                    "Hypothesis differs from stable identity allocation"
                )
        else:
            if self.proposed_relationship not in _APPEND_RELATIONSHIPS:
                raise HypothesisContractError(
                    "later Version requires an append relationship"
                )
            if (
                self.proposed_target_hypothesis_id != self.hypothesis_id
                or self.target_version_id != self.previous_version_id
                or self.target_version_digest != self.previous_version_digest
            ):
                raise HypothesisContractError(
                    "append target differs from the exact predecessor"
                )
        for name in (
            "proposal_content_identity",
            "proposal_canonical_digest",
            "work_item_version_digest",
            "retrieval_context_digest",
        ):
            _digest(getattr(self, name), name)
        _digest(self.actor_identity_digest, "actor_identity_digest")
        _uuid(self.authority_event_id, "authority_event_id")
        _timestamp(self.recorded_at, "recorded_at")
        if (
            type(self.source_bindings) is not tuple
            or not self.source_bindings
            or len(self.source_bindings) > 32
            or any(
                type(item) is not HypothesisSourceBinding
                for item in self.source_bindings
            )
        ):
            raise HypothesisContractError(
                "source_bindings must be a non-empty bounded exact tuple"
            )
        keys = tuple(
            (item.decision_lead_id, item.disposition_id)
            for item in self.source_bindings
        )
        if keys != tuple(sorted(set(keys))):
            raise HypothesisContractError("source_bindings must be sorted and unique")
        _normalise(
            lambda: self.canonical_bytes, "Hypothesis Version cannot be canonicalised"
        )

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "version_id": self.version_id,
                "hypothesis_id": self.hypothesis_id,
                "ordinal": self.ordinal,
                "previous_version_id": self.previous_version_id,
                "previous_version_digest": self.previous_version_digest,
                "proposed_summary": self.proposed_summary,
                "proposed_relationship": self.proposed_relationship.value,
                "proposed_target_hypothesis_id": self.proposed_target_hypothesis_id,
                "target_version_id": self.target_version_id,
                "target_version_digest": self.target_version_digest,
                "proposal_id": self.proposal_id,
                "proposal_content_identity": self.proposal_content_identity,
                "proposal_canonical_digest": self.proposal_canonical_digest,
                "proposal_local_id": self.proposal_local_id,
                "work_item_id": self.work_item_id,
                "work_item_version_id": self.work_item_version_id,
                "work_item_version_digest": self.work_item_version_digest,
                "retrieval_context_id": self.retrieval_context_id,
                "retrieval_context_digest": self.retrieval_context_digest,
                "source_bindings": [
                    item.canonical_value() for item in self.source_bindings
                ],
                "actor_identity_digest": self.actor_identity_digest,
                "authority_event_id": self.authority_event_id,
                "recorded_at": self.recorded_at,
            },
            "Hypothesis Version cannot be canonicalised",
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _normalise(
            lambda: canonical_json_bytes(
                {
                    "schema_version": EVENT_HYPOTHESIS_VERSION,
                    "version": self.canonical_value,
                }
            ),
            "Hypothesis Version cannot be canonicalised",
        )

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        root = _exact(
            _decode(raw), {"schema_version", "version"}, "Hypothesis Version document"
        )
        if root["schema_version"] != EVENT_HYPOTHESIS_VERSION:
            raise HypothesisContractError("Hypothesis Version schema is unsupported")
        fields = set(cls.__dataclass_fields__)
        item = _exact(root["version"], fields, "Hypothesis Version")
        relationship = _normalise(
            lambda: HypothesisRelationship(item["proposed_relationship"]),
            "proposed_relationship is unsupported",
        )
        raw_bindings = item["source_bindings"]
        if type(raw_bindings) is not list:
            raise HypothesisContractError("source_bindings must be an array")
        values = dict(item)
        values["proposed_relationship"] = relationship
        values["source_bindings"] = tuple(
            HypothesisSourceBinding.from_value(value) for value in raw_bindings
        )
        return _normalise(
            lambda: cls(**values),  # type: ignore[arg-type]
            "Hypothesis Version replay failed",
        )


_FACADE_TOKEN = object()


class EventHypothesisAuthority:
    """Narrow public facade over the private checked v21 store."""

    __slots__ = ("__authority",)

    def __init__(self, token: object, authority: object) -> None:
        if token is not _FACADE_TOKEN:
            raise HypothesisContractError(
                "Hypothesis authority facade requires the exact private authority"
            )
        self.__authority = authority

    def retain(self, *args: object, **kwargs: object) -> EventHypothesisVersion:
        return _normalise(
            lambda: self.__authority.retain(*args, **kwargs),
            "Hypothesis retention failed",
        )  # type: ignore[attr-defined,no-any-return]

    create_or_append = retain

    def current(self, hypothesis_id: str, *, proof: object) -> EventHypothesisVersion:
        return _normalise(
            lambda: self.__authority.current(hypothesis_id, proof=proof),
            "Hypothesis currentness failed",
        )  # type: ignore[attr-defined,no-any-return]

    require_current = current

    def load_version(self, version_id: str) -> EventHypothesisVersion:
        return _normalise(
            lambda: self.__authority.load_version(version_id),
            "Hypothesis Version load failed",
        )  # type: ignore[attr-defined,no-any-return]

    def load_hypothesis(self, hypothesis_id: str) -> EventHypothesis:
        return _normalise(
            lambda: self.__authority.load_hypothesis(hypothesis_id),
            "Hypothesis load failed",
        )  # type: ignore[attr-defined,no-any-return]

    def versions(self, hypothesis_id: str) -> tuple[EventHypothesisVersion, ...]:
        return _normalise(
            lambda: self.__authority.versions(hypothesis_id),
            "Hypothesis history load failed",
        )  # type: ignore[attr-defined,no-any-return]

    def close(self) -> None:
        _normalise(
            lambda: self.__authority.close(), "Hypothesis authority close failed"
        )  # type: ignore[attr-defined]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_event_hypothesis_authority(
    *args: object, **kwargs: object
) -> EventHypothesisAuthority:
    """Open the checked v21 authority without exposing SQLite mutation."""
    from newsroom.authority.event_hypothesis_system import (
        open_event_hypothesis_authority_system,
    )

    authority = _normalise(
        lambda: open_event_hypothesis_authority_system(*args, **kwargs),
        "Hypothesis authority open failed",
    )
    if type(authority) is not EventHypothesisAuthority:
        raise HypothesisContractError(
            "Hypothesis authority opener returned a forged facade"
        )
    return authority


def _compose_event_hypothesis_authority(
    authority: object,
) -> EventHypothesisAuthority:
    """Private composition seam used only by the authority opener."""

    return EventHypothesisAuthority(_FACADE_TOKEN, authority)


open_hypothesis_authority = open_event_hypothesis_authority


__all__ = [
    "EVENT_HYPOTHESIS",
    "EVENT_HYPOTHESIS_VERSION",
    "HYPOTHESIS_CURRENT_VERSION",
    "EventHypothesis",
    "EventHypothesisAuthority",
    "EventHypothesisVersion",
    "HypothesisContractError",
    "HypothesisSourceBinding",
    "open_event_hypothesis_authority",
    "open_hypothesis_authority",
]
