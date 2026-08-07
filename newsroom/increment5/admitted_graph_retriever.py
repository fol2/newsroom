"""Bounded read-only admitted-graph retrieval for Increment 5B4.

The retriever accepts one canonical root and traverses at most two fixed phases
through an authority-owned read port.  The port exposes no Cypher, driver,
session, transaction, label, predicate, direction, depth, fan-out, order, or
limit selection surface.  Projection paths remain advisory and cannot create
identity, relationship, Candidate, evidence, publication, or production
authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from newsroom.increment5.branch_contracts import BranchMode, BranchOutcome


RETRIEVAL_CONTRACT_DIGEST = (
    "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
)
GRAPH_QUERY_COMPONENT_DIGEST = (
    "sha256:98a92b1c46c08b614a0e15714a5cd071d49e916d6d2b45ead4924b194cf4525b"
)
GRAPH_PROFILE_ID = "increment5-admitted-graph-retrieval-v1"
GRAPH_POLICY_ID = "increment5-admitted-graph-read-v1"
GRAPH_ACTOR_ID = "retrieval_worker"
GRAPH_PURPOSE = "admitted_graph_retrieval"
GRAPH_TRUST_SCOPE = "ADMITTED"
GRAPH_MAX_DEPTH = 2
GRAPH_MAX_FANOUT = 32
GRAPH_TEMPORAL_WINDOW_SECONDS = 2_678_400
GRAPH_RESULT_LIMIT = 8
GRAPH_TIMEOUT_MS = 5_000
GRAPH_RESPONSE_LIMIT_BYTES = 262_144
GRAPH_EXTERNAL_CALLS = 0
GRAPH_PROVIDER_CALLS = 0
GRAPH_MODEL_CALLS = 0
GRAPH_EMBEDDING_CALLS = 0
GRAPH_PROVIDER_SPEND_MICROS = 0

ALLOWED_PREDICATES = (
    "ABOUT_EVENT",
    "CORRECTS",
    "DEVELOPMENT_OF",
    "DISPUTES",
    "SAME_EVENT_AS",
    "SAME_PROCESS_AS",
    "SUPERSEDES",
    "SUPPORTS",
)
ALLOWED_NODE_LABELS = (
    "Candidate",
    "CanonicalEntity",
    "FormalProcess",
    "Hypothesis",
    "Lead",
    "Revision",
    "Signal",
    "Source",
)
GRAPH_RELATION_CONTRACT_DIGEST = "sha256:" + hashlib.sha256(
    json.dumps(
        {
            "allowed_node_labels": list(ALLOWED_NODE_LABELS),
            "allowed_predicates": list(ALLOWED_PREDICATES),
            "direction": "BOTH",
            "maximum_depth": GRAPH_MAX_DEPTH,
            "maximum_fanout": GRAPH_MAX_FANOUT,
            "temporal_window_seconds": GRAPH_TEMPORAL_WINDOW_SECONDS,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class AdmittedGraphContractError(ValueError):
    """A graph request, authority record, projection record, or receipt is malformed."""


class AdmittedGraphJournalError(RuntimeError):
    """The immutable graph receipt journal is unavailable or inconsistent."""


class AdmittedGraphPortError(RuntimeError):
    """The fixed read-only graph port could not complete a bounded read."""


class AdmittedGraphPortTimeout(AdmittedGraphPortError):
    """The cumulative graph-port deadline, including lock wait, was exhausted."""


class GraphFailureReason(StrEnum):
    NO_MATCH = "NO_MATCH"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    GRAPH_COMPONENT_MISMATCH = "GRAPH_COMPONENT_MISMATCH"
    RELATION_CONTRACT_MISMATCH = "RELATION_CONTRACT_MISMATCH"
    ROOT_NOT_ACCEPTED = "ROOT_NOT_ACCEPTED"
    ROOT_IDENTITY_MISMATCH = "ROOT_IDENTITY_MISMATCH"
    AUTHORITY_VIEW_UNAVAILABLE = "AUTHORITY_VIEW_UNAVAILABLE"
    GENERATION_INACTIVE = "GENERATION_INACTIVE"
    GENERATION_INCOMPLETE = "GENERATION_INCOMPLETE"
    GENERATION_IDENTITY_MISMATCH = "GENERATION_IDENTITY_MISMATCH"
    RIGHTS_MANIFEST_MISMATCH = "RIGHTS_MANIFEST_MISMATCH"
    WATERMARK_BEHIND = "WATERMARK_BEHIND"
    REQUIRED_GAP_OPEN = "REQUIRED_GAP_OPEN"
    DEAD_LETTER_PRESENT = "DEAD_LETTER_PRESENT"
    AUTHORITY_VIEW_STALE = "AUTHORITY_VIEW_STALE"
    ROOT_PROJECTION_MISSING = "ROOT_PROJECTION_MISSING"
    ROOT_PROJECTION_AMBIGUOUS = "ROOT_PROJECTION_AMBIGUOUS"
    PROJECTION_UNAVAILABLE = "PROJECTION_UNAVAILABLE"
    PROJECTION_GENERATION_MISMATCH = "PROJECTION_GENERATION_MISMATCH"
    PROJECTION_SCOPE_ESCAPE = "PROJECTION_SCOPE_ESCAPE"
    PROJECTION_RECORD_MALFORMED = "PROJECTION_RECORD_MALFORMED"
    NODE_AUTHORITY_MISSING = "NODE_AUTHORITY_MISSING"
    RELATION_AUTHORITY_MISSING = "RELATION_AUTHORITY_MISSING"
    AUTHORITY_BINDING_INTEGRITY = "AUTHORITY_BINDING_INTEGRITY"
    FANOUT_EXCEEDED = "FANOUT_EXCEEDED"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"


class GraphExclusionReason(StrEnum):
    RIGHTS_NOT_CURRENT = "RIGHTS_NOT_CURRENT"
    LIFECYCLE_NOT_ACTIVE = "LIFECYCLE_NOT_ACTIVE"
    TOMBSTONED = "TOMBSTONED"
    TRUST_NOT_ADMITTED = "TRUST_NOT_ADMITTED"
    OUTSIDE_QUERY_VALID_TIME = "OUTSIDE_QUERY_VALID_TIME"
    OUTSIDE_TEMPORAL_WINDOW = "OUTSIDE_TEMPORAL_WINDOW"
    CYCLE_REJECTED = "CYCLE_REJECTED"
    DUPLICATE_PATH = "DUPLICATE_PATH"
    ROOT_REPEATED = "ROOT_REPEATED"


class GraphLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    UNRESOLVED = "UNRESOLVED"
    PROPOSAL_ONLY = "PROPOSAL_ONLY"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    TOMBSTONED = "TOMBSTONED"


class GraphDirection(StrEnum):
    OUTGOING = "OUTGOING"
    INCOMING = "INCOMING"


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdmittedGraphContractError("value is not canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_node_digest(canonical_id: str) -> str:
    _require_text(canonical_id, field="canonical_node_id")
    return _digest_bytes(f"canonical-node:{canonical_id}".encode("utf-8"))


def _require_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise AdmittedGraphContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise AdmittedGraphContractError(f"{field} must be a bounded canonical token")
    return value


def _require_text(value: str, *, field: str, maximum_bytes: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise AdmittedGraphContractError(f"{field} must be bounded canonical text")
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdmittedGraphContractError(f"{field} must be a non-negative integer")
    return value


def _parse_utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise AdmittedGraphContractError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise AdmittedGraphContractError(
            f"{field} must be canonical second-resolution UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise AdmittedGraphContractError(
            f"{field} must be canonical second-resolution UTC"
        )
    return parsed


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise AdmittedGraphContractError("UTC value must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_uuid4(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise AdmittedGraphContractError(f"{field} must be a UUIDv4 string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise AdmittedGraphContractError(f"{field} must be a UUIDv4 string") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise AdmittedGraphContractError(f"{field} must be a canonical UUIDv4 string")
    return value


def _validate_labels(labels: Sequence[str], *, field: str) -> tuple[str, ...]:
    if not labels:
        raise AdmittedGraphContractError(f"{field} must contain an admitted label")
    normalized = tuple(sorted(set(labels)))
    if len(normalized) != len(labels):
        raise AdmittedGraphContractError(f"{field} labels must be unique")
    for label in normalized:
        _require_token(label, field=field)
        if label not in ALLOWED_NODE_LABELS:
            raise AdmittedGraphContractError(f"{field} contains an unapproved label")
    return normalized


@dataclass(frozen=True, slots=True)
class GraphNodeAuthority:
    canonical_id: str
    identity_digest: str
    labels: tuple[str, ...]
    dependency_root_id: str
    source_revision_id: str
    lifecycle: GraphLifecycle
    rights_current: bool
    rights_digest: str
    provenance_digest: str

    def __post_init__(self) -> None:
        for name in ("canonical_id", "dependency_root_id", "source_revision_id"):
            _require_text(getattr(self, name), field=name)
        _require_digest(self.identity_digest, field="node_identity_digest")
        if self.identity_digest != canonical_node_digest(self.canonical_id):
            raise AdmittedGraphContractError("node identity digest does not match canonical id")
        object.__setattr__(
            self,
            "labels",
            _validate_labels(self.labels, field="node_labels"),
        )
        if not isinstance(self.lifecycle, GraphLifecycle):
            raise AdmittedGraphContractError("node lifecycle must be typed")
        if not isinstance(self.rights_current, bool):
            raise AdmittedGraphContractError("node rights_current must be boolean")
        _require_digest(self.rights_digest, field="node_rights_digest")
        _require_digest(self.provenance_digest, field="node_provenance_digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "identity_digest": self.identity_digest,
            "labels": list(self.labels),
            "dependency_root_id": self.dependency_root_id,
            "source_revision_id": self.source_revision_id,
            "lifecycle": self.lifecycle.value,
            "rights_current": self.rights_current,
            "rights_digest": self.rights_digest,
            "provenance_digest": self.provenance_digest,
        }


@dataclass(frozen=True, slots=True)
class GraphRelationAuthority:
    relation_id: str
    source_id: str
    target_id: str
    predicate: str
    trust_scope: str
    valid_from: str
    valid_to: str
    observed_at: str
    lifecycle: GraphLifecycle
    rights_current: bool
    rights_digest: str
    provenance_digest: str
    decision_digest: str

    def __post_init__(self) -> None:
        for name in ("relation_id", "source_id", "target_id"):
            _require_text(getattr(self, name), field=name)
        if self.source_id == self.target_id:
            raise AdmittedGraphContractError("self-loop relation authority is prohibited")
        _require_token(self.predicate, field="relation_predicate")
        if self.predicate not in ALLOWED_PREDICATES:
            raise AdmittedGraphContractError("relation predicate is not allowed")
        if self.trust_scope != GRAPH_TRUST_SCOPE:
            _require_token(self.trust_scope, field="relation_trust_scope")
        valid_from = _parse_utc(self.valid_from, field="relation_valid_from")
        valid_to = _parse_utc(self.valid_to, field="relation_valid_to")
        observed = _parse_utc(self.observed_at, field="relation_observed_at")
        if valid_from >= valid_to or observed > valid_to:
            raise AdmittedGraphContractError("relation temporal authority is inconsistent")
        if not isinstance(self.lifecycle, GraphLifecycle):
            raise AdmittedGraphContractError("relation lifecycle must be typed")
        if not isinstance(self.rights_current, bool):
            raise AdmittedGraphContractError("relation rights_current must be boolean")
        for name in ("rights_digest", "provenance_digest", "decision_digest"):
            _require_digest(getattr(self, name), field=name)

    def canonical_value(self) -> dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "predicate": self.predicate,
            "trust_scope": self.trust_scope,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "observed_at": self.observed_at,
            "lifecycle": self.lifecycle.value,
            "rights_current": self.rights_current,
            "rights_digest": self.rights_digest,
            "provenance_digest": self.provenance_digest,
            "decision_digest": self.decision_digest,
        }


@dataclass(frozen=True, slots=True)
class AdmittedGraphAuthorityView:
    generation_id: str
    generation_digest: str
    active: bool
    complete: bool
    profile_id: str
    graph_component_digest: str
    relation_contract_digest: str
    rights_manifest_digest: str
    watermark_seq: int
    open_gap_count: int
    dead_letter_count: int
    validated_at: str
    maximum_age_seconds: int
    nodes: tuple[GraphNodeAuthority, ...]
    relations: tuple[GraphRelationAuthority, ...]

    def __post_init__(self) -> None:
        _require_token(self.generation_id, field="graph_generation_id")
        for name in (
            "generation_digest",
            "graph_component_digest",
            "relation_contract_digest",
            "rights_manifest_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        _require_token(self.profile_id, field="graph_profile_id")
        if not isinstance(self.active, bool) or not isinstance(self.complete, bool):
            raise AdmittedGraphContractError("generation active/complete flags must be boolean")
        for name in ("watermark_seq", "open_gap_count", "dead_letter_count"):
            _require_non_negative_int(getattr(self, name), field=name)
        _parse_utc(self.validated_at, field="graph_validated_at")
        if (
            isinstance(self.maximum_age_seconds, bool)
            or not isinstance(self.maximum_age_seconds, int)
            or self.maximum_age_seconds <= 0
        ):
            raise AdmittedGraphContractError("maximum_age_seconds must be positive")
        node_ids = [node.canonical_id for node in self.nodes]
        relation_ids = [relation.relation_id for relation in self.relations]
        if len(node_ids) != len(set(node_ids)):
            raise AdmittedGraphContractError("authority node identities must be unique")
        if len(relation_ids) != len(set(relation_ids)):
            raise AdmittedGraphContractError("authority relation identities must be unique")
        known_nodes = set(node_ids)
        for relation in self.relations:
            if relation.source_id not in known_nodes or relation.target_id not in known_nodes:
                raise AdmittedGraphContractError("relation endpoint authority is missing")
        expected = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.admitted-graph-authority.v1",
                    "generation_id": self.generation_id,
                    "profile_id": self.profile_id,
                    "graph_component_digest": self.graph_component_digest,
                    "relation_contract_digest": self.relation_contract_digest,
                    "rights_manifest_digest": self.rights_manifest_digest,
                    "watermark_seq": self.watermark_seq,
                    "nodes": [node.canonical_value() for node in self.nodes],
                    "relations": [relation.canonical_value() for relation in self.relations],
                }
            )
        )
        if self.generation_digest != expected:
            raise AdmittedGraphContractError("generation digest does not match authority bytes")

    @classmethod
    def build(
        cls,
        *,
        generation_id: str,
        validated_at: str,
        nodes: Sequence[GraphNodeAuthority],
        relations: Sequence[GraphRelationAuthority],
        watermark_seq: int = 1,
        active: bool = True,
        complete: bool = True,
        open_gap_count: int = 0,
        dead_letter_count: int = 0,
        maximum_age_seconds: int = 86_400,
        profile_id: str = GRAPH_PROFILE_ID,
        graph_component_digest: str = GRAPH_QUERY_COMPONENT_DIGEST,
        relation_contract_digest: str = GRAPH_RELATION_CONTRACT_DIGEST,
        rights_manifest_digest: str | None = None,
    ) -> "AdmittedGraphAuthorityView":
        selected_nodes = tuple(nodes)
        selected_relations = tuple(relations)
        selected_rights = rights_manifest_digest or _digest_bytes(
            _canonical_json_bytes(
                {
                    "nodes": [
                        {
                            "canonical_id": node.canonical_id,
                            "rights_current": node.rights_current,
                            "rights_digest": node.rights_digest,
                        }
                        for node in selected_nodes
                    ],
                    "relations": [
                        {
                            "relation_id": relation.relation_id,
                            "rights_current": relation.rights_current,
                            "rights_digest": relation.rights_digest,
                        }
                        for relation in selected_relations
                    ],
                }
            )
        )
        payload = {
            "schema_version": "newsroom.increment5.admitted-graph-authority.v1",
            "generation_id": generation_id,
            "profile_id": profile_id,
            "graph_component_digest": graph_component_digest,
            "relation_contract_digest": relation_contract_digest,
            "rights_manifest_digest": selected_rights,
            "watermark_seq": watermark_seq,
            "nodes": [node.canonical_value() for node in selected_nodes],
            "relations": [relation.canonical_value() for relation in selected_relations],
        }
        return cls(
            generation_id=generation_id,
            generation_digest=_digest_bytes(_canonical_json_bytes(payload)),
            active=active,
            complete=complete,
            profile_id=profile_id,
            graph_component_digest=graph_component_digest,
            relation_contract_digest=relation_contract_digest,
            rights_manifest_digest=selected_rights,
            watermark_seq=watermark_seq,
            open_gap_count=open_gap_count,
            dead_letter_count=dead_letter_count,
            validated_at=validated_at,
            maximum_age_seconds=maximum_age_seconds,
            nodes=selected_nodes,
            relations=selected_relations,
        )


@dataclass(frozen=True, slots=True)
class GraphProjectionNode:
    generation_id: str
    canonical_id: str
    identity_digest: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.generation_id, field="projection_generation_id")
        _require_text(self.canonical_id, field="projection_canonical_id")
        _require_digest(self.identity_digest, field="projection_identity_digest")
        object.__setattr__(
            self,
            "labels",
            _validate_labels(self.labels, field="projection_node_labels"),
        )


@dataclass(frozen=True, slots=True)
class GraphProjectionEdge:
    generation_id: str
    frontier_id: str
    relation_id: str
    source_id: str
    target_id: str
    predicate: str
    source_labels: tuple[str, ...]
    target_labels: tuple[str, ...]
    valid_from: str
    valid_to: str
    observed_at: str

    def __post_init__(self) -> None:
        _require_token(self.generation_id, field="projection_edge_generation_id")
        for name in ("frontier_id", "relation_id", "source_id", "target_id"):
            _require_text(getattr(self, name), field=name)
        if self.source_id == self.target_id:
            raise AdmittedGraphContractError("projection self-loop is prohibited")
        _require_token(self.predicate, field="projection_predicate")
        object.__setattr__(
            self,
            "source_labels",
            _validate_labels(self.source_labels, field="projection_source_labels"),
        )
        object.__setattr__(
            self,
            "target_labels",
            _validate_labels(self.target_labels, field="projection_target_labels"),
        )
        valid_from = _parse_utc(self.valid_from, field="projection_valid_from")
        valid_to = _parse_utc(self.valid_to, field="projection_valid_to")
        observed = _parse_utc(self.observed_at, field="projection_observed_at")
        if valid_from >= valid_to or observed > valid_to:
            raise AdmittedGraphContractError("projection temporal fields are inconsistent")

    def canonical_key(self) -> tuple[str, ...]:
        return (
            self.frontier_id,
            self.predicate,
            self.source_id,
            self.target_id,
            self.relation_id,
        )


class AdmittedGraphReadPort(Protocol):
    """Authority-owned fixed-operation port; no raw query capability crosses it."""

    def read_root(
        self,
        *,
        generation_id: str,
        canonical_id: str,
        timeout_ms: int,
    ) -> GraphProjectionNode | None:
        ...

    def expand_frontier(
        self,
        *,
        generation_id: str,
        frontier_ids: tuple[str, ...],
        query_valid_time: str,
        temporal_lower_bound: str,
        timeout_ms: int,
    ) -> tuple[GraphProjectionEdge, ...]:
        ...


@dataclass(frozen=True, slots=True)
class AdmittedGraphRequest:
    request_id: str
    idempotency_key: str
    actor_id: str
    purpose: str
    policy_id: str
    contract_digest: str
    profile_id: str
    graph_component_digest: str
    relation_contract_digest: str
    root_id: str
    root_identity_digest: str
    query_valid_time: str
    serving_time: str
    minimum_watermark_seq: int = 0
    maximum_depth: int = GRAPH_MAX_DEPTH
    maximum_fanout: int = GRAPH_MAX_FANOUT
    temporal_window_seconds: int = GRAPH_TEMPORAL_WINDOW_SECONDS
    result_limit: int = GRAPH_RESULT_LIMIT
    timeout_ms: int = GRAPH_TIMEOUT_MS
    response_limit_bytes: int = GRAPH_RESPONSE_LIMIT_BYTES

    def __post_init__(self) -> None:
        _require_uuid4(self.request_id, field="graph_request_id")
        _require_text(self.idempotency_key, field="graph_idempotency_key", maximum_bytes=256)
        for name in ("actor_id", "purpose", "policy_id", "profile_id"):
            _require_token(getattr(self, name), field=name)
        for name in (
            "contract_digest",
            "graph_component_digest",
            "relation_contract_digest",
            "root_identity_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        _require_text(self.root_id, field="graph_root_id")
        if self.root_identity_digest != canonical_node_digest(self.root_id):
            raise AdmittedGraphContractError("root identity digest does not match root id")
        valid = _parse_utc(self.query_valid_time, field="graph_query_valid_time")
        serving = _parse_utc(self.serving_time, field="graph_serving_time")
        if valid > serving:
            raise AdmittedGraphContractError("query-valid time cannot be after serving time")
        _require_non_negative_int(self.minimum_watermark_seq, field="graph_minimum_watermark")
        fixed = {
            "maximum_depth": (self.maximum_depth, GRAPH_MAX_DEPTH),
            "maximum_fanout": (self.maximum_fanout, GRAPH_MAX_FANOUT),
            "temporal_window_seconds": (
                self.temporal_window_seconds,
                GRAPH_TEMPORAL_WINDOW_SECONDS,
            ),
            "result_limit": (self.result_limit, GRAPH_RESULT_LIMIT),
            "timeout_ms": (self.timeout_ms, GRAPH_TIMEOUT_MS),
            "response_limit_bytes": (
                self.response_limit_bytes,
                GRAPH_RESPONSE_LIMIT_BYTES,
            ),
        }
        for name, (actual, expected) in fixed.items():
            if actual != expected:
                raise AdmittedGraphContractError(
                    f"{name} must remain fixed at {expected}"
                )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.admitted-graph-request.v1",
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "actor_id": self.actor_id,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "contract_digest": self.contract_digest,
            "profile_id": self.profile_id,
            "graph_component_digest": self.graph_component_digest,
            "relation_contract_digest": self.relation_contract_digest,
            "root_id": self.root_id,
            "root_identity_digest": self.root_identity_digest,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "minimum_watermark_seq": self.minimum_watermark_seq,
            "maximum_depth": self.maximum_depth,
            "maximum_fanout": self.maximum_fanout,
            "temporal_window_seconds": self.temporal_window_seconds,
            "result_limit": self.result_limit,
            "timeout_ms": self.timeout_ms,
            "response_limit_bytes": self.response_limit_bytes,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def request_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class AdmittedGraphHop:
    relation_id: str
    predicate: str
    source_id: str
    target_id: str
    direction: GraphDirection
    relation_decision_digest: str
    relation_provenance_digest: str

    def __post_init__(self) -> None:
        for name in ("relation_id", "source_id", "target_id"):
            _require_text(getattr(self, name), field=name)
        if self.source_id == self.target_id:
            raise AdmittedGraphContractError("graph hop self-loop is prohibited")
        _require_token(self.predicate, field="graph_hop_predicate")
        if self.predicate not in ALLOWED_PREDICATES:
            raise AdmittedGraphContractError("graph hop predicate is not admitted")
        if not isinstance(self.direction, GraphDirection):
            raise AdmittedGraphContractError("graph hop direction must be typed")
        _require_digest(
            self.relation_decision_digest,
            field="graph_hop_decision_digest",
        )
        _require_digest(
            self.relation_provenance_digest,
            field="graph_hop_provenance_digest",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "relation_id": self.relation_id,
            "predicate": self.predicate,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "direction": self.direction.value,
            "relation_decision_digest": self.relation_decision_digest,
            "relation_provenance_digest": self.relation_provenance_digest,
        }


@dataclass(frozen=True, slots=True)
class AdmittedGraphHit:
    rank: int
    canonical_id: str
    identity_digest: str
    labels: tuple[str, ...]
    dependency_root_id: str
    source_revision_id: str
    rights_digest: str
    provenance_digest: str
    path: tuple[AdmittedGraphHop, ...]

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not 1 <= self.rank <= GRAPH_RESULT_LIMIT:
            raise AdmittedGraphContractError("graph hit rank exceeds fixed result bound")
        for name in ("canonical_id", "dependency_root_id", "source_revision_id"):
            _require_text(getattr(self, name), field=name)
        _require_digest(self.identity_digest, field="graph_hit_identity_digest")
        object.__setattr__(
            self,
            "labels",
            _validate_labels(self.labels, field="graph_hit_labels"),
        )
        _require_digest(self.rights_digest, field="graph_hit_rights_digest")
        _require_digest(self.provenance_digest, field="graph_hit_provenance_digest")
        if not 1 <= len(self.path) <= GRAPH_MAX_DEPTH:
            raise AdmittedGraphContractError("graph hit path depth is outside the bound")

    def canonical_value(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "canonical_id": self.canonical_id,
            "identity_digest": self.identity_digest,
            "labels": list(self.labels),
            "dependency_root_id": self.dependency_root_id,
            "source_revision_id": self.source_revision_id,
            "rights_digest": self.rights_digest,
            "provenance_digest": self.provenance_digest,
            "path": [hop.canonical_value() for hop in self.path],
        }


@dataclass(frozen=True, slots=True)
class AdmittedGraphExclusion:
    subject_id: str
    reason: GraphExclusionReason
    relation_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.subject_id, field="graph_exclusion_subject")
        if not isinstance(self.reason, GraphExclusionReason):
            raise AdmittedGraphContractError("graph exclusion reason must be typed")
        if self.relation_id is not None:
            _require_text(self.relation_id, field="graph_exclusion_relation")

    def canonical_value(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "reason": self.reason.value,
            "relation_id": self.relation_id,
        }


@dataclass(frozen=True, slots=True)
class AdmittedGraphReceipt:
    receipt_id: str
    request_digest: str
    mode: BranchMode
    outcome: BranchOutcome
    reason: GraphFailureReason | None
    generation_id: str | None
    generation_digest: str | None
    profile_id: str
    graph_component_digest: str
    relation_contract_digest: str
    root_id: str
    root_identity_digest: str
    query_valid_time: str
    serving_time: str
    temporal_lower_bound: str
    elapsed_ms: int
    watermark_seq: int | None
    rights_manifest_digest: str | None
    hits: tuple[AdmittedGraphHit, ...]
    exclusions: tuple[AdmittedGraphExclusion, ...]
    authority_read_count: int
    graph_port_read_count: int
    projection_edge_count: int
    external_call_count: int = GRAPH_EXTERNAL_CALLS
    provider_call_count: int = GRAPH_PROVIDER_CALLS
    model_call_count: int = GRAPH_MODEL_CALLS
    embedding_call_count: int = GRAPH_EMBEDDING_CALLS
    provider_spend_micros: int = GRAPH_PROVIDER_SPEND_MICROS
    read_only: bool = True
    authority_effect: str = "NONE"
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.receipt_id)
        except (ValueError, AttributeError) as exc:
            raise AdmittedGraphContractError("graph receipt_id must be a UUID") from exc
        if str(parsed) != self.receipt_id:
            raise AdmittedGraphContractError("graph receipt_id must be canonical")
        _require_digest(self.request_digest, field="graph_receipt_request_digest")
        if self.mode is not BranchMode.ADMITTED_GRAPH:
            raise AdmittedGraphContractError("graph receipt mode must be ADMITTED_GRAPH")
        if not isinstance(self.outcome, BranchOutcome):
            raise AdmittedGraphContractError("graph receipt outcome must be typed")
        if self.reason is not None and not isinstance(self.reason, GraphFailureReason):
            raise AdmittedGraphContractError("graph receipt reason must be typed")
        if self.generation_id is not None:
            _require_token(self.generation_id, field="graph_receipt_generation_id")
        if self.generation_digest is not None:
            _require_digest(self.generation_digest, field="graph_receipt_generation_digest")
        _require_token(self.profile_id, field="graph_receipt_profile_id")
        _require_digest(self.graph_component_digest, field="graph_receipt_component")
        _require_digest(
            self.relation_contract_digest,
            field="graph_receipt_relation_contract",
        )
        if self.profile_id != GRAPH_PROFILE_ID:
            raise AdmittedGraphContractError("graph receipt profile identity drifted")
        if self.graph_component_digest != GRAPH_QUERY_COMPONENT_DIGEST:
            raise AdmittedGraphContractError("graph receipt component identity drifted")
        if self.relation_contract_digest != GRAPH_RELATION_CONTRACT_DIGEST:
            raise AdmittedGraphContractError("graph receipt relation contract drifted")
        _require_text(self.root_id, field="graph_receipt_root")
        _require_digest(self.root_identity_digest, field="graph_receipt_root_digest")
        if self.root_identity_digest != canonical_node_digest(self.root_id):
            raise AdmittedGraphContractError("graph receipt root identity does not match root")
        query_valid = _parse_utc(
            self.query_valid_time,
            field="graph_receipt_query_valid",
        )
        serving = _parse_utc(self.serving_time, field="graph_receipt_serving")
        temporal_lower = _parse_utc(
            self.temporal_lower_bound,
            field="graph_receipt_temporal_lower",
        )
        if query_valid > serving:
            raise AdmittedGraphContractError("graph receipt query-valid time is after serving")
        expected_lower = query_valid - timedelta(
            seconds=GRAPH_TEMPORAL_WINDOW_SECONDS
        )
        if temporal_lower != expected_lower:
            raise AdmittedGraphContractError("graph receipt temporal lower bound drifted")
        if isinstance(self.elapsed_ms, bool) or not 0 <= self.elapsed_ms <= GRAPH_TIMEOUT_MS:
            raise AdmittedGraphContractError("graph receipt elapsed time exceeds budget")
        if self.watermark_seq is not None:
            _require_non_negative_int(self.watermark_seq, field="graph_receipt_watermark")
        if self.rights_manifest_digest is not None:
            _require_digest(self.rights_manifest_digest, field="graph_receipt_rights")
        for name in (
            "authority_read_count",
            "graph_port_read_count",
            "projection_edge_count",
        ):
            _require_non_negative_int(getattr(self, name), field=name)
        if self.authority_read_count not in {0, 1}:
            raise AdmittedGraphContractError("graph authority read count must be zero or one")
        if self.graph_port_read_count > GRAPH_MAX_DEPTH + 1:
            raise AdmittedGraphContractError("graph port read count exceeds fixed traversal")
        maximum_projection_edges = (GRAPH_MAX_FANOUT + 1) * (GRAPH_MAX_FANOUT + 1)
        if self.projection_edge_count > maximum_projection_edges:
            raise AdmittedGraphContractError("graph projection edge count exceeds fixed traversal")
        authority_metadata = (
            self.generation_id,
            self.generation_digest,
            self.watermark_seq,
            self.rights_manifest_digest,
        )
        if self.authority_read_count == 0:
            if any(value is not None for value in authority_metadata):
                raise AdmittedGraphContractError("graph receipt has authority metadata without a read")
            if self.graph_port_read_count or self.projection_edge_count:
                raise AdmittedGraphContractError("graph receipt has projection work without authority")
        else:
            if any(value is None for value in authority_metadata):
                raise AdmittedGraphContractError("graph receipt is missing authority attribution")
        if self.graph_port_read_count and self.authority_read_count != 1:
            raise AdmittedGraphContractError("graph port work requires one authority read")
        if self.projection_edge_count and self.graph_port_read_count < 2:
            raise AdmittedGraphContractError("graph edges require a frontier read")
        if any(
            value != 0
            for value in (
                self.external_call_count,
                self.provider_call_count,
                self.model_call_count,
                self.embedding_call_count,
                self.provider_spend_micros,
            )
        ):
            raise AdmittedGraphContractError("graph receipt cannot report provider work or spend")
        if not self.read_only or self.authority_effect != "NONE":
            raise AdmittedGraphContractError("graph receipt cannot claim write or authority effect")
        if self.production_activation_authorized:
            raise AdmittedGraphContractError("graph receipt cannot authorize production activation")
        if len(self.hits) > GRAPH_RESULT_LIMIT:
            raise AdmittedGraphContractError("graph receipt exceeds result bound")
        if [hit.rank for hit in self.hits] != list(range(1, len(self.hits) + 1)):
            raise AdmittedGraphContractError("graph hit ranks must be contiguous")
        hit_ids: set[str] = set()
        for hit in self.hits:
            if hit.canonical_id in hit_ids:
                raise AdmittedGraphContractError("graph receipt contains duplicate hits")
            hit_ids.add(hit.canonical_id)
            if hit.canonical_id == self.root_id:
                raise AdmittedGraphContractError("graph receipt cannot return the root as a hit")
            if hit.identity_digest != canonical_node_digest(hit.canonical_id):
                raise AdmittedGraphContractError("graph hit identity does not match canonical id")
            current = self.root_id
            seen_nodes = {self.root_id}
            seen_relations: set[str] = set()
            for hop in hit.path:
                if hop.relation_id in seen_relations:
                    raise AdmittedGraphContractError("graph path repeats a relation")
                seen_relations.add(hop.relation_id)
                if hop.direction is GraphDirection.OUTGOING:
                    if hop.source_id != current:
                        raise AdmittedGraphContractError("graph path is not root-contiguous")
                    next_node = hop.target_id
                else:
                    if hop.target_id != current:
                        raise AdmittedGraphContractError("graph path is not root-contiguous")
                    next_node = hop.source_id
                if next_node in seen_nodes:
                    raise AdmittedGraphContractError("graph path repeats a node")
                seen_nodes.add(next_node)
                current = next_node
            if current != hit.canonical_id:
                raise AdmittedGraphContractError("graph path does not end at its hit")
        if self.outcome is not BranchOutcome.COMPLETE and self.reason is None:
            raise AdmittedGraphContractError("non-complete graph receipt requires a reason")
        if self.outcome is BranchOutcome.COMPLETE:
            if self.authority_read_count != 1 or self.graph_port_read_count < 2:
                raise AdmittedGraphContractError("complete graph receipt lacks mandatory reads")
            if self.hits and self.reason is not None:
                raise AdmittedGraphContractError("complete graph hits cannot carry a failure reason")
            if not self.hits and self.reason is not GraphFailureReason.NO_MATCH:
                raise AdmittedGraphContractError("empty complete graph receipt must state NO_MATCH")
        elif self.hits:
            raise AdmittedGraphContractError("non-complete graph receipt cannot retain hits")
        if self.reason is GraphFailureReason.QUERY_TIMEOUT and self.elapsed_ms != GRAPH_TIMEOUT_MS:
            raise AdmittedGraphContractError("graph timeout must retain exact 5000 ms")
        expected_receipt_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        self.request_digest,
                        self.outcome.value,
                        "NONE" if self.reason is None else self.reason.value,
                        self.generation_digest or "NO_GENERATION",
                    )
                ),
            )
        )
        if self.receipt_id != expected_receipt_id:
            raise AdmittedGraphContractError("graph receipt identity does not match evidence")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.admitted-graph-receipt.v1",
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "mode": self.mode.value,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "generation_id": self.generation_id,
            "generation_digest": self.generation_digest,
            "profile_id": self.profile_id,
            "graph_component_digest": self.graph_component_digest,
            "relation_contract_digest": self.relation_contract_digest,
            "root_id": self.root_id,
            "root_identity_digest": self.root_identity_digest,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "temporal_lower_bound": self.temporal_lower_bound,
            "elapsed_ms": self.elapsed_ms,
            "watermark_seq": self.watermark_seq,
            "rights_manifest_digest": self.rights_manifest_digest,
            "hits": [hit.canonical_value() for hit in self.hits],
            "exclusions": [exclusion.canonical_value() for exclusion in self.exclusions],
            "authority_read_count": self.authority_read_count,
            "graph_port_read_count": self.graph_port_read_count,
            "projection_edge_count": self.projection_edge_count,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "read_only": self.read_only,
            "authority_effect": self.authority_effect,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "AdmittedGraphReceipt":
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdmittedGraphJournalError("retained graph receipt is not JSON") from exc
        if not isinstance(payload, dict):
            raise AdmittedGraphJournalError("retained graph receipt root is not an object")
        schema = payload.pop("schema_version", None)
        if schema != "newsroom.increment5.admitted-graph-receipt.v1":
            raise AdmittedGraphJournalError("retained graph receipt schema is not accepted")
        try:
            hits = tuple(
                AdmittedGraphHit(
                    rank=item["rank"],
                    canonical_id=item["canonical_id"],
                    identity_digest=item["identity_digest"],
                    labels=tuple(item["labels"]),
                    dependency_root_id=item["dependency_root_id"],
                    source_revision_id=item["source_revision_id"],
                    rights_digest=item["rights_digest"],
                    provenance_digest=item["provenance_digest"],
                    path=tuple(
                        AdmittedGraphHop(
                            relation_id=hop["relation_id"],
                            predicate=hop["predicate"],
                            source_id=hop["source_id"],
                            target_id=hop["target_id"],
                            direction=GraphDirection(hop["direction"]),
                            relation_decision_digest=hop[
                                "relation_decision_digest"
                            ],
                            relation_provenance_digest=hop[
                                "relation_provenance_digest"
                            ],
                        )
                        for hop in item["path"]
                    ),
                )
                for item in payload["hits"]
            )
            exclusions = tuple(
                AdmittedGraphExclusion(
                    subject_id=item["subject_id"],
                    reason=GraphExclusionReason(item["reason"]),
                    relation_id=item["relation_id"],
                )
                for item in payload["exclusions"]
            )
            receipt = cls(
                receipt_id=payload["receipt_id"],
                request_digest=payload["request_digest"],
                mode=BranchMode(payload["mode"]),
                outcome=BranchOutcome(payload["outcome"]),
                reason=(
                    None
                    if payload["reason"] is None
                    else GraphFailureReason(payload["reason"])
                ),
                generation_id=payload["generation_id"],
                generation_digest=payload["generation_digest"],
                profile_id=payload["profile_id"],
                graph_component_digest=payload["graph_component_digest"],
                relation_contract_digest=payload["relation_contract_digest"],
                root_id=payload["root_id"],
                root_identity_digest=payload["root_identity_digest"],
                query_valid_time=payload["query_valid_time"],
                serving_time=payload["serving_time"],
                temporal_lower_bound=payload["temporal_lower_bound"],
                elapsed_ms=payload["elapsed_ms"],
                watermark_seq=payload["watermark_seq"],
                rights_manifest_digest=payload["rights_manifest_digest"],
                hits=hits,
                exclusions=exclusions,
                authority_read_count=payload["authority_read_count"],
                graph_port_read_count=payload["graph_port_read_count"],
                projection_edge_count=payload["projection_edge_count"],
                external_call_count=payload["external_call_count"],
                provider_call_count=payload["provider_call_count"],
                model_call_count=payload["model_call_count"],
                embedding_call_count=payload["embedding_call_count"],
                provider_spend_micros=payload["provider_spend_micros"],
                read_only=payload["read_only"],
                authority_effect=payload["authority_effect"],
                production_activation_authorized=payload[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError, AdmittedGraphContractError) as exc:
            raise AdmittedGraphJournalError("retained graph receipt is malformed") from exc
        if receipt.canonical_bytes != raw:
            raise AdmittedGraphJournalError("retained graph receipt bytes are not canonical")
        return receipt


@dataclass(frozen=True, slots=True)
class _TraversalPath:
    node_ids: tuple[str, ...]
    hops: tuple[AdmittedGraphHop, ...]

    @property
    def end(self) -> str:
        return self.node_ids[-1]

    def order_key(self) -> tuple[object, ...]:
        return (
            len(self.hops),
            tuple(
                (
                    hop.predicate,
                    hop.source_id,
                    hop.target_id,
                    hop.relation_id,
                    hop.direction.value,
                )
                for hop in self.hops
            ),
            self.end,
        )


class AdmittedGraphReceiptJournal:
    """Immutable SQLite graph receipt journal with production outside write lock."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialization_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._initialization_lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS increment5_admitted_graph_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    receipt_bytes BLOB NOT NULL,
                    receipt_digest TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _decode(
        request_digest: str,
        receipt_bytes: bytes,
        receipt_digest: str,
    ) -> AdmittedGraphReceipt:
        if _digest_bytes(receipt_bytes) != receipt_digest:
            raise AdmittedGraphJournalError("retained graph receipt digest mismatch")
        receipt = AdmittedGraphReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.request_digest != request_digest:
            raise AdmittedGraphJournalError("retained graph request binding mismatch")
        return receipt

    def _existing(self, request: AdmittedGraphRequest) -> AdmittedGraphReceipt | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT request_digest, receipt_bytes, receipt_digest
                    FROM increment5_admitted_graph_receipts
                    WHERE idempotency_key = ?
                    """,
                    (request.idempotency_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise AdmittedGraphJournalError("graph journal read failed") from exc
        if row is None:
            return None
        if row[0] != request.request_digest:
            raise AdmittedGraphJournalError("graph idempotency key semantic conflict")
        return self._decode(row[0], bytes(row[1]), row[2])

    def execute(
        self,
        request: AdmittedGraphRequest,
        producer: Callable[[], AdmittedGraphReceipt],
    ) -> AdmittedGraphReceipt:
        existing = self._existing(request)
        if existing is not None:
            return existing
        receipt = producer()
        if receipt.request_digest != request.request_digest:
            raise AdmittedGraphJournalError("produced graph receipt does not bind request")
        raw = receipt.canonical_bytes
        if len(raw) > request.response_limit_bytes:
            raise AdmittedGraphJournalError("produced graph receipt exceeds response bound")
        digest = _digest_bytes(raw)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_digest, receipt_bytes, receipt_digest
                FROM increment5_admitted_graph_receipts
                WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.execute("ROLLBACK")
                if row[0] != request.request_digest:
                    raise AdmittedGraphJournalError(
                        "graph idempotency key concurrent semantic conflict"
                    )
                return self._decode(row[0], bytes(row[1]), row[2])
            connection.execute(
                """
                INSERT INTO increment5_admitted_graph_receipts (
                    idempotency_key, request_digest, receipt_bytes, receipt_digest
                ) VALUES (?, ?, ?, ?)
                """,
                (request.idempotency_key, request.request_digest, raw, digest),
            )
            connection.execute("COMMIT")
        except AdmittedGraphJournalError:
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise AdmittedGraphJournalError("graph journal write failed") from exc
        finally:
            if connection is not None:
                connection.close()
        return receipt


class AdmittedGraphRetriever:
    """Two-phase bounded admitted-graph traversal with exact authority validation."""

    def __init__(
        self,
        *,
        authority_provider: Callable[[AdmittedGraphRequest], AdmittedGraphAuthorityView],
        graph_port: AdmittedGraphReadPort,
        journal: AdmittedGraphReceiptJournal,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.authority_provider = authority_provider
        self.graph_port = graph_port
        self.journal = journal
        self.monotonic_ns = monotonic_ns

    def retrieve(self, request: AdmittedGraphRequest) -> AdmittedGraphReceipt:
        return self.journal.execute(request, lambda: self._produce(request))

    def _produce(self, request: AdmittedGraphRequest) -> AdmittedGraphReceipt:
        started = self.monotonic_ns()
        deadline = started + GRAPH_TIMEOUT_MS * 1_000_000
        port_reads = 0
        projection_edges = 0

        def remaining_ms() -> int:
            remaining = deadline - self.monotonic_ns()
            if remaining <= 0:
                return 0
            return max(1, remaining // 1_000_000)

        def elapsed_ms() -> int:
            remaining = deadline - self.monotonic_ns()
            if remaining <= 0:
                return GRAPH_TIMEOUT_MS
            return max(0, GRAPH_TIMEOUT_MS - remaining // 1_000_000)

        lower_bound = _format_utc(
            _parse_utc(request.query_valid_time, field="graph_query_valid_time")
            - timedelta(seconds=GRAPH_TEMPORAL_WINDOW_SECONDS)
        )

        if (
            request.actor_id != GRAPH_ACTOR_ID
            or request.purpose != GRAPH_PURPOSE
            or request.policy_id != GRAPH_POLICY_ID
            or request.contract_digest != RETRIEVAL_CONTRACT_DIGEST
        ):
            return self._failure(
                request,
                GraphFailureReason.CONTRACT_MISMATCH,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
            )
        if request.profile_id != GRAPH_PROFILE_ID:
            return self._failure(
                request,
                GraphFailureReason.PROFILE_MISMATCH,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
            )
        if request.graph_component_digest != GRAPH_QUERY_COMPONENT_DIGEST:
            return self._failure(
                request,
                GraphFailureReason.GRAPH_COMPONENT_MISMATCH,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
            )
        if request.relation_contract_digest != GRAPH_RELATION_CONTRACT_DIGEST:
            return self._failure(
                request,
                GraphFailureReason.RELATION_CONTRACT_MISMATCH,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
            )
        if remaining_ms() <= 0:
            return self._timeout(request, lower_bound)

        try:
            view = self.authority_provider(request)
        except Exception:
            return self._failure(
                request,
                GraphFailureReason.AUTHORITY_VIEW_UNAVAILABLE,
                BranchOutcome.UNAVAILABLE,
                lower_bound,
                elapsed_ms(),
            )
        if not isinstance(view, AdmittedGraphAuthorityView):
            return self._failure(
                request,
                GraphFailureReason.AUTHORITY_VIEW_UNAVAILABLE,
                BranchOutcome.UNAVAILABLE,
                lower_bound,
                elapsed_ms(),
            )
        validation = self._validate_view(request, view)
        if validation is not None:
            reason, outcome = validation
            return self._failure(
                request,
                reason,
                outcome,
                lower_bound,
                elapsed_ms(),
                view=view,
            )
        if remaining_ms() <= 0:
            return self._timeout(request, lower_bound, view=view)

        node_by_id = {node.canonical_id: node for node in view.nodes}
        relation_by_id = {relation.relation_id: relation for relation in view.relations}
        root_authority = node_by_id.get(request.root_id)
        if root_authority is None:
            return self._failure(
                request,
                GraphFailureReason.ROOT_NOT_ACCEPTED,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
                view=view,
            )
        if root_authority.identity_digest != request.root_identity_digest:
            return self._failure(
                request,
                GraphFailureReason.ROOT_IDENTITY_MISMATCH,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
                view=view,
            )
        root_exclusion = self._node_exclusion(root_authority)
        if root_exclusion is not None:
            return self._failure(
                request,
                GraphFailureReason.ROOT_NOT_ACCEPTED,
                BranchOutcome.POLICY_BLOCKED,
                lower_bound,
                elapsed_ms(),
                view=view,
                exclusions=(
                    AdmittedGraphExclusion(
                        subject_id=request.root_id,
                        reason=root_exclusion,
                    ),
                ),
            )

        try:
            root_projection = self.graph_port.read_root(
                generation_id=view.generation_id,
                canonical_id=request.root_id,
                timeout_ms=remaining_ms(),
            )
            port_reads += 1
        except AdmittedGraphPortTimeout:
            return self._timeout(
                request,
                lower_bound,
                view=view,
                port_reads=port_reads + 1,
            )
        except Exception:
            return self._failure(
                request,
                GraphFailureReason.PROJECTION_UNAVAILABLE,
                BranchOutcome.UNAVAILABLE,
                lower_bound,
                elapsed_ms(),
                view=view,
                port_reads=port_reads + 1,
            )
        if root_projection is None:
            return self._failure(
                request,
                GraphFailureReason.ROOT_PROJECTION_MISSING,
                BranchOutcome.INCOMPLETE,
                lower_bound,
                elapsed_ms(),
                view=view,
                port_reads=port_reads,
            )
        if (
            root_projection.generation_id != view.generation_id
            or root_projection.canonical_id != request.root_id
        ):
            return self._failure(
                request,
                GraphFailureReason.PROJECTION_GENERATION_MISMATCH,
                BranchOutcome.UNAVAILABLE,
                lower_bound,
                elapsed_ms(),
                view=view,
                port_reads=port_reads,
            )
        if (
            root_projection.identity_digest != root_authority.identity_digest
            or root_projection.labels != root_authority.labels
        ):
            return self._failure(
                request,
                GraphFailureReason.AUTHORITY_BINDING_INTEGRITY,
                BranchOutcome.UNAVAILABLE,
                lower_bound,
                elapsed_ms(),
                view=view,
                port_reads=port_reads,
            )

        exclusions: list[AdmittedGraphExclusion] = []
        frontier = (_TraversalPath(node_ids=(request.root_id,), hops=()),)
        candidate_paths: list[_TraversalPath] = []
        seen_edge_keys: set[tuple[str, ...]] = set()

        for _depth in range(1, GRAPH_MAX_DEPTH + 1):
            frontier_ids = tuple(sorted({path.end for path in frontier}))
            if not frontier_ids:
                break
            try:
                edges = self.graph_port.expand_frontier(
                    generation_id=view.generation_id,
                    frontier_ids=frontier_ids,
                    query_valid_time=request.query_valid_time,
                    temporal_lower_bound=lower_bound,
                    timeout_ms=remaining_ms(),
                )
                port_reads += 1
            except AdmittedGraphPortTimeout:
                return self._timeout(
                    request,
                    lower_bound,
                    view=view,
                    exclusions=tuple(exclusions),
                    port_reads=port_reads + 1,
                    projection_edges=projection_edges,
                )
            except Exception:
                return self._failure(
                    request,
                    GraphFailureReason.PROJECTION_UNAVAILABLE,
                    BranchOutcome.UNAVAILABLE,
                    lower_bound,
                    elapsed_ms(),
                    view=view,
                    exclusions=tuple(exclusions),
                    port_reads=port_reads + 1,
                    projection_edges=projection_edges,
                )
            projection_edges += len(edges)
            if remaining_ms() <= 0:
                return self._timeout(
                    request,
                    lower_bound,
                    view=view,
                    exclusions=tuple(exclusions),
                    port_reads=port_reads,
                    projection_edges=projection_edges,
                )
            grouped: dict[str, list[GraphProjectionEdge]] = {
                frontier_id: [] for frontier_id in frontier_ids
            }
            for edge in edges:
                if edge.generation_id != view.generation_id:
                    return self._failure(
                        request,
                        GraphFailureReason.PROJECTION_GENERATION_MISMATCH,
                        BranchOutcome.UNAVAILABLE,
                        lower_bound,
                        elapsed_ms(),
                        view=view,
                        exclusions=tuple(exclusions),
                        port_reads=port_reads,
                        projection_edges=projection_edges,
                    )
                if edge.frontier_id not in grouped:
                    return self._failure(
                        request,
                        GraphFailureReason.PROJECTION_SCOPE_ESCAPE,
                        BranchOutcome.UNAVAILABLE,
                        lower_bound,
                        elapsed_ms(),
                        view=view,
                        exclusions=tuple(exclusions),
                        port_reads=port_reads,
                        projection_edges=projection_edges,
                    )
                if edge.predicate not in ALLOWED_PREDICATES:
                    return self._failure(
                        request,
                        GraphFailureReason.PROJECTION_SCOPE_ESCAPE,
                        BranchOutcome.UNAVAILABLE,
                        lower_bound,
                        elapsed_ms(),
                        view=view,
                        exclusions=tuple(exclusions),
                        port_reads=port_reads,
                        projection_edges=projection_edges,
                    )
                grouped[edge.frontier_id].append(edge)
            if any(len(items) > GRAPH_MAX_FANOUT for items in grouped.values()):
                return self._failure(
                    request,
                    GraphFailureReason.FANOUT_EXCEEDED,
                    BranchOutcome.INCOMPLETE,
                    lower_bound,
                    elapsed_ms(),
                    view=view,
                    exclusions=tuple(exclusions),
                    port_reads=port_reads,
                    projection_edges=projection_edges,
                )

            next_frontier: list[_TraversalPath] = []
            for path in sorted(frontier, key=_TraversalPath.order_key):
                for edge in sorted(grouped[path.end], key=GraphProjectionEdge.canonical_key):
                    edge_key = edge.canonical_key()
                    if edge_key in seen_edge_keys:
                        exclusions.append(
                            AdmittedGraphExclusion(
                                subject_id=path.end,
                                relation_id=edge.relation_id,
                                reason=GraphExclusionReason.DUPLICATE_PATH,
                            )
                        )
                        continue
                    seen_edge_keys.add(edge_key)
                    if edge.source_id == path.end:
                        other_id = edge.target_id
                        other_labels = edge.target_labels
                        direction = GraphDirection.OUTGOING
                    elif edge.target_id == path.end:
                        other_id = edge.source_id
                        other_labels = edge.source_labels
                        direction = GraphDirection.INCOMING
                    else:
                        return self._failure(
                            request,
                            GraphFailureReason.PROJECTION_RECORD_MALFORMED,
                            BranchOutcome.UNAVAILABLE,
                            lower_bound,
                            elapsed_ms(),
                            view=view,
                            exclusions=tuple(exclusions),
                            port_reads=port_reads,
                            projection_edges=projection_edges,
                        )
                    if other_id == request.root_id:
                        exclusions.append(
                            AdmittedGraphExclusion(
                                subject_id=other_id,
                                relation_id=edge.relation_id,
                                reason=GraphExclusionReason.ROOT_REPEATED,
                            )
                        )
                        continue
                    if other_id in path.node_ids:
                        exclusions.append(
                            AdmittedGraphExclusion(
                                subject_id=other_id,
                                relation_id=edge.relation_id,
                                reason=GraphExclusionReason.CYCLE_REJECTED,
                            )
                        )
                        continue
                    node = node_by_id.get(other_id)
                    if node is None:
                        return self._failure(
                            request,
                            GraphFailureReason.NODE_AUTHORITY_MISSING,
                            BranchOutcome.INCOMPLETE,
                            lower_bound,
                            elapsed_ms(),
                            view=view,
                            exclusions=tuple(exclusions),
                            port_reads=port_reads,
                            projection_edges=projection_edges,
                        )
                    relation = relation_by_id.get(edge.relation_id)
                    if relation is None:
                        return self._failure(
                            request,
                            GraphFailureReason.RELATION_AUTHORITY_MISSING,
                            BranchOutcome.INCOMPLETE,
                            lower_bound,
                            elapsed_ms(),
                            view=view,
                            exclusions=tuple(exclusions),
                            port_reads=port_reads,
                            projection_edges=projection_edges,
                        )
                    if (
                        node.labels != other_labels
                        or node.identity_digest != canonical_node_digest(other_id)
                        or relation.source_id != edge.source_id
                        or relation.target_id != edge.target_id
                        or relation.predicate != edge.predicate
                        or relation.valid_from != edge.valid_from
                        or relation.valid_to != edge.valid_to
                        or relation.observed_at != edge.observed_at
                    ):
                        return self._failure(
                            request,
                            GraphFailureReason.AUTHORITY_BINDING_INTEGRITY,
                            BranchOutcome.UNAVAILABLE,
                            lower_bound,
                            elapsed_ms(),
                            view=view,
                            exclusions=tuple(exclusions),
                            port_reads=port_reads,
                            projection_edges=projection_edges,
                        )
                    relation_exclusion = self._relation_exclusion(
                        relation,
                        query_valid_time=request.query_valid_time,
                        lower_bound=lower_bound,
                    )
                    if relation_exclusion is not None:
                        exclusions.append(
                            AdmittedGraphExclusion(
                                subject_id=other_id,
                                relation_id=edge.relation_id,
                                reason=relation_exclusion,
                            )
                        )
                        continue
                    node_exclusion = self._node_exclusion(node)
                    if node_exclusion is not None:
                        exclusions.append(
                            AdmittedGraphExclusion(
                                subject_id=other_id,
                                relation_id=edge.relation_id,
                                reason=node_exclusion,
                            )
                        )
                        continue
                    hop = AdmittedGraphHop(
                        relation_id=relation.relation_id,
                        predicate=relation.predicate,
                        source_id=relation.source_id,
                        target_id=relation.target_id,
                        direction=direction,
                        relation_decision_digest=relation.decision_digest,
                        relation_provenance_digest=relation.provenance_digest,
                    )
                    new_path = _TraversalPath(
                        node_ids=path.node_ids + (other_id,),
                        hops=path.hops + (hop,),
                    )
                    candidate_paths.append(new_path)
                    next_frontier.append(new_path)
            frontier = tuple(sorted(next_frontier, key=_TraversalPath.order_key))

        best_by_node: dict[str, _TraversalPath] = {}
        for path in sorted(candidate_paths, key=_TraversalPath.order_key):
            existing = best_by_node.get(path.end)
            if existing is None:
                best_by_node[path.end] = path
            else:
                exclusions.append(
                    AdmittedGraphExclusion(
                        subject_id=path.end,
                        relation_id=path.hops[-1].relation_id,
                        reason=GraphExclusionReason.DUPLICATE_PATH,
                    )
                )
        ordered_paths = sorted(best_by_node.values(), key=_TraversalPath.order_key)
        if len(ordered_paths) > GRAPH_RESULT_LIMIT:
            return self._failure(
                request,
                GraphFailureReason.RESULT_LIMIT_EXCEEDED,
                BranchOutcome.INCOMPLETE,
                lower_bound,
                elapsed_ms(),
                view=view,
                exclusions=tuple(exclusions),
                port_reads=port_reads,
                projection_edges=projection_edges,
            )
        hits = tuple(
            AdmittedGraphHit(
                rank=rank,
                canonical_id=path.end,
                identity_digest=node_by_id[path.end].identity_digest,
                labels=node_by_id[path.end].labels,
                dependency_root_id=node_by_id[path.end].dependency_root_id,
                source_revision_id=node_by_id[path.end].source_revision_id,
                rights_digest=node_by_id[path.end].rights_digest,
                provenance_digest=node_by_id[path.end].provenance_digest,
                path=path.hops,
            )
            for rank, path in enumerate(ordered_paths, start=1)
        )
        receipt = self._receipt(
            request,
            outcome=BranchOutcome.COMPLETE,
            reason=None if hits else GraphFailureReason.NO_MATCH,
            lower_bound=lower_bound,
            elapsed_ms=elapsed_ms(),
            view=view,
            hits=hits,
            exclusions=tuple(exclusions),
            port_reads=port_reads,
            projection_edges=projection_edges,
        )
        if len(receipt.canonical_bytes) > request.response_limit_bytes:
            return self._failure(
                request,
                GraphFailureReason.RESPONSE_LIMIT_EXCEEDED,
                BranchOutcome.INCOMPLETE,
                lower_bound,
                elapsed_ms(),
                view=view,
                exclusions=tuple(exclusions),
                port_reads=port_reads,
                projection_edges=projection_edges,
            )
        return receipt

    @staticmethod
    def _validate_view(
        request: AdmittedGraphRequest,
        view: AdmittedGraphAuthorityView,
    ) -> tuple[GraphFailureReason, BranchOutcome] | None:
        if not view.active:
            return GraphFailureReason.GENERATION_INACTIVE, BranchOutcome.STALE
        if not view.complete:
            return GraphFailureReason.GENERATION_INCOMPLETE, BranchOutcome.INCOMPLETE
        if view.profile_id != GRAPH_PROFILE_ID:
            return GraphFailureReason.PROFILE_MISMATCH, BranchOutcome.STALE
        if view.graph_component_digest != GRAPH_QUERY_COMPONENT_DIGEST:
            return GraphFailureReason.GRAPH_COMPONENT_MISMATCH, BranchOutcome.STALE
        if view.relation_contract_digest != GRAPH_RELATION_CONTRACT_DIGEST:
            return GraphFailureReason.RELATION_CONTRACT_MISMATCH, BranchOutcome.STALE
        if view.watermark_seq < request.minimum_watermark_seq:
            return GraphFailureReason.WATERMARK_BEHIND, BranchOutcome.STALE
        if view.open_gap_count:
            return GraphFailureReason.REQUIRED_GAP_OPEN, BranchOutcome.INCOMPLETE
        if view.dead_letter_count:
            return GraphFailureReason.DEAD_LETTER_PRESENT, BranchOutcome.INCOMPLETE
        serving = _parse_utc(request.serving_time, field="graph_serving_time")
        validated = _parse_utc(view.validated_at, field="graph_validated_at")
        if serving < validated or (serving - validated).total_seconds() > view.maximum_age_seconds:
            return GraphFailureReason.AUTHORITY_VIEW_STALE, BranchOutcome.STALE
        return None

    @staticmethod
    def _node_exclusion(node: GraphNodeAuthority) -> GraphExclusionReason | None:
        if not node.rights_current:
            return GraphExclusionReason.RIGHTS_NOT_CURRENT
        if node.lifecycle is GraphLifecycle.TOMBSTONED:
            return GraphExclusionReason.TOMBSTONED
        if node.lifecycle is not GraphLifecycle.ACTIVE:
            return GraphExclusionReason.LIFECYCLE_NOT_ACTIVE
        return None

    @staticmethod
    def _relation_exclusion(
        relation: GraphRelationAuthority,
        *,
        query_valid_time: str,
        lower_bound: str,
    ) -> GraphExclusionReason | None:
        if relation.trust_scope != GRAPH_TRUST_SCOPE:
            return GraphExclusionReason.TRUST_NOT_ADMITTED
        if not relation.rights_current:
            return GraphExclusionReason.RIGHTS_NOT_CURRENT
        if relation.lifecycle is GraphLifecycle.TOMBSTONED:
            return GraphExclusionReason.TOMBSTONED
        if relation.lifecycle is not GraphLifecycle.ACTIVE:
            return GraphExclusionReason.LIFECYCLE_NOT_ACTIVE
        valid = _parse_utc(query_valid_time, field="graph_query_valid_time")
        observed = _parse_utc(relation.observed_at, field="relation_observed_at")
        if observed > valid:
            return GraphExclusionReason.OUTSIDE_QUERY_VALID_TIME
        if not (
            _parse_utc(relation.valid_from, field="relation_valid_from")
            <= valid
            < _parse_utc(relation.valid_to, field="relation_valid_to")
        ):
            return GraphExclusionReason.OUTSIDE_QUERY_VALID_TIME
        if observed < _parse_utc(
            lower_bound,
            field="graph_temporal_lower_bound",
        ):
            return GraphExclusionReason.OUTSIDE_TEMPORAL_WINDOW
        return None

    @staticmethod
    def _receipt_id(
        request: AdmittedGraphRequest,
        outcome: BranchOutcome,
        reason: GraphFailureReason | None,
        generation_digest: str | None,
    ) -> str:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        request.request_digest,
                        outcome.value,
                        "NONE" if reason is None else reason.value,
                        generation_digest or "NO_GENERATION",
                    )
                ),
            )
        )

    def _receipt(
        self,
        request: AdmittedGraphRequest,
        *,
        outcome: BranchOutcome,
        reason: GraphFailureReason | None,
        lower_bound: str,
        elapsed_ms: int,
        view: AdmittedGraphAuthorityView | None = None,
        hits: tuple[AdmittedGraphHit, ...] = (),
        exclusions: tuple[AdmittedGraphExclusion, ...] = (),
        port_reads: int = 0,
        projection_edges: int = 0,
    ) -> AdmittedGraphReceipt:
        return AdmittedGraphReceipt(
            receipt_id=self._receipt_id(
                request,
                outcome,
                reason,
                None if view is None else view.generation_digest,
            ),
            request_digest=request.request_digest,
            mode=BranchMode.ADMITTED_GRAPH,
            outcome=outcome,
            reason=reason,
            generation_id=None if view is None else view.generation_id,
            generation_digest=None if view is None else view.generation_digest,
            profile_id=GRAPH_PROFILE_ID,
            graph_component_digest=GRAPH_QUERY_COMPONENT_DIGEST,
            relation_contract_digest=GRAPH_RELATION_CONTRACT_DIGEST,
            root_id=request.root_id,
            root_identity_digest=request.root_identity_digest,
            query_valid_time=request.query_valid_time,
            serving_time=request.serving_time,
            temporal_lower_bound=lower_bound,
            elapsed_ms=elapsed_ms,
            watermark_seq=None if view is None else view.watermark_seq,
            rights_manifest_digest=None if view is None else view.rights_manifest_digest,
            hits=hits,
            exclusions=exclusions,
            authority_read_count=0 if view is None else 1,
            graph_port_read_count=port_reads,
            projection_edge_count=projection_edges,
        )

    def _failure(
        self,
        request: AdmittedGraphRequest,
        reason: GraphFailureReason,
        outcome: BranchOutcome,
        lower_bound: str,
        elapsed_ms: int,
        *,
        view: AdmittedGraphAuthorityView | None = None,
        exclusions: tuple[AdmittedGraphExclusion, ...] = (),
        port_reads: int = 0,
        projection_edges: int = 0,
    ) -> AdmittedGraphReceipt:
        receipt = self._receipt(
            request,
            outcome=outcome,
            reason=reason,
            lower_bound=lower_bound,
            elapsed_ms=elapsed_ms,
            view=view,
            exclusions=exclusions,
            port_reads=port_reads,
            projection_edges=projection_edges,
        )
        if len(receipt.canonical_bytes) <= request.response_limit_bytes:
            return receipt
        compact = self._receipt(
            request,
            outcome=BranchOutcome.INCOMPLETE,
            reason=GraphFailureReason.RESPONSE_LIMIT_EXCEEDED,
            lower_bound=lower_bound,
            elapsed_ms=elapsed_ms,
            view=view,
            exclusions=(),
            port_reads=port_reads,
            projection_edges=projection_edges,
        )
        if len(compact.canonical_bytes) > request.response_limit_bytes:
            raise AssertionError("compact graph response-limit receipt exceeds bound")
        return compact

    def _timeout(
        self,
        request: AdmittedGraphRequest,
        lower_bound: str,
        *,
        view: AdmittedGraphAuthorityView | None = None,
        exclusions: tuple[AdmittedGraphExclusion, ...] = (),
        port_reads: int = 0,
        projection_edges: int = 0,
    ) -> AdmittedGraphReceipt:
        return self._failure(
            request,
            GraphFailureReason.QUERY_TIMEOUT,
            BranchOutcome.INCOMPLETE,
            lower_bound,
            GRAPH_TIMEOUT_MS,
            view=view,
            exclusions=exclusions,
            port_reads=port_reads,
            projection_edges=projection_edges,
        )


__all__ = [
    "ALLOWED_NODE_LABELS",
    "ALLOWED_PREDICATES",
    "GRAPH_ACTOR_ID",
    "GRAPH_MAX_DEPTH",
    "GRAPH_MAX_FANOUT",
    "GRAPH_POLICY_ID",
    "GRAPH_PROFILE_ID",
    "GRAPH_PURPOSE",
    "GRAPH_QUERY_COMPONENT_DIGEST",
    "GRAPH_RELATION_CONTRACT_DIGEST",
    "GRAPH_RESPONSE_LIMIT_BYTES",
    "GRAPH_RESULT_LIMIT",
    "GRAPH_TEMPORAL_WINDOW_SECONDS",
    "GRAPH_TIMEOUT_MS",
    "AdmittedGraphAuthorityView",
    "AdmittedGraphContractError",
    "AdmittedGraphExclusion",
    "AdmittedGraphHit",
    "AdmittedGraphHop",
    "AdmittedGraphJournalError",
    "AdmittedGraphPortError",
    "AdmittedGraphPortTimeout",
    "AdmittedGraphReadPort",
    "AdmittedGraphReceipt",
    "AdmittedGraphReceiptJournal",
    "AdmittedGraphRequest",
    "AdmittedGraphRetriever",
    "GraphDirection",
    "GraphExclusionReason",
    "GraphFailureReason",
    "GraphLifecycle",
    "GraphNodeAuthority",
    "GraphProjectionEdge",
    "GraphProjectionNode",
    "GraphRelationAuthority",
    "canonical_node_digest",
]
