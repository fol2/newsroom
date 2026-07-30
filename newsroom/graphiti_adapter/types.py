from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from newsroom.authority.canonical import validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, require_scope, require_token


class GraphitiAdapterError(RuntimeError):
    """Base error for the isolated proposal-only adapter boundary."""


class GraphitiAdapterContractError(ValueError):
    """A configuration, request, replay record, or result is malformed."""


class GraphitiAdapterStateError(GraphitiAdapterError):
    """Retained adapter state cannot support the requested operation."""


class GraphitiRuntimeNotAuthorized(PermissionError, GraphitiAdapterError):
    """Real Graphiti/model execution has no complete owner authority packet."""


class GraphitiWorkspaceError(GraphitiAdapterError):
    """The disposable proposal workspace violated its isolation contract."""


class GraphitiReplayError(GraphitiAdapterStateError):
    """Approved replay material is incomplete, changed, or ineligible."""


class GraphitiAdapterConfigurationId(UUIDv4Id):
    pass


class GraphitiWorkspacePolicyId(UUIDv4Id):
    pass


class GraphitiWorkspaceId(UUIDv4Id):
    pass


class GraphitiAttemptId(UUIDv4Id):
    pass


class GraphitiInputManifestId(UUIDv4Id):
    pass


class GraphitiCleanupReceiptId(UUIDv4Id):
    pass


class GraphitiReplaySourceId(UUIDv4Id):
    pass


class GraphitiRuntimeMode(StrEnum):
    DETERMINISTIC_FAKE = "DETERMINISTIC_FAKE"
    APPROVED_REPLAY = "APPROVED_REPLAY"
    REAL_GRAPHITI = "REAL_GRAPHITI"


class GraphitiExecutionProfile(StrEnum):
    QUALIFICATION = "QUALIFICATION"
    REPLAY = "REPLAY"
    EVALUATION = "EVALUATION"
    PRODUCTION = "PRODUCTION"


class GraphitiAdapterOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    FAILED = "FAILED"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"

    @property
    def terminal(self) -> bool:
        return self in {
            GraphitiAdapterOutcome.COMPLETE,
            GraphitiAdapterOutcome.MALFORMED_OUTPUT,
            GraphitiAdapterOutcome.PROVIDER_REJECTED,
            GraphitiAdapterOutcome.POLICY_BLOCKED,
            GraphitiAdapterOutcome.AMBIGUOUS_EFFECT,
        }

    @property
    def may_reference_output(self) -> bool:
        return self in {
            GraphitiAdapterOutcome.COMPLETE,
            GraphitiAdapterOutcome.PARTIAL,
            GraphitiAdapterOutcome.MALFORMED_OUTPUT,
        }

    @property
    def may_reference_proposals(self) -> bool:
        return self in {
            GraphitiAdapterOutcome.COMPLETE,
            GraphitiAdapterOutcome.PARTIAL,
        }


class GraphitiWorkspaceState(StrEnum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    CLEANED = "CLEANED"
    LOST = "LOST"


class GraphitiCleanupReason(StrEnum):
    NORMAL = "NORMAL"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    FAILED = "FAILED"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    SIMULATED_LOSS = "SIMULATED_LOSS"


class GraphitiEgressPolicy(StrEnum):
    DENY_ALL = "DENY_ALL"
    APPROVED_PROVIDER_ONLY = "APPROVED_PROVIDER_ONLY"


class GraphitiCredentialClass(StrEnum):
    NONE = "NONE"
    PROPOSAL_WORKSPACE_ONLY = "PROPOSAL_WORKSPACE_ONLY"


class GraphitiReplayEligibility(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"


@dataclass(frozen=True, slots=True)
class GraphitiAdapterReadPolicy:
    policy_id: str
    purpose: str
    attempt_required_scope: str
    configuration_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        token(self.policy_id, field="graphiti_adapter_read_policy_id")
        token(self.purpose, field="graphiti_adapter_read_purpose")
        for name, value in (
            ("graphiti_attempt_read_scope", self.attempt_required_scope),
            ("graphiti_configuration_read_scope", self.configuration_required_scope),
        ):
            try:
                require_scope(value, field=name)
            except ValueError as exc:
                raise GraphitiAdapterContractError(str(exc)) from exc
        if self.attempt_required_scope == self.configuration_required_scope:
            raise GraphitiAdapterContractError(
                "adapter attempt and configuration reads require distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise GraphitiAdapterContractError(
                "adapter read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            token(principal_id, field="graphiti_adapter_reader_principal")
        integer(
            self.max_results,
            field="graphiti_adapter_read_maximum",
            minimum=1,
            maximum=10_000,
        )


def token(value: str, *, field: str) -> str:
    try:
        return require_token(value, field=field)
    except ValueError as exc:
        raise GraphitiAdapterContractError(str(exc)) from exc


def text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise GraphitiAdapterContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise GraphitiAdapterContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise GraphitiAdapterContractError(f"{field} exceeds its byte bound")
    return value


def digest(value: str, *, field: str) -> str:
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise GraphitiAdapterContractError(str(exc)) from exc
    if normalized != value:
        raise GraphitiAdapterContractError(
            f"{field} must use canonical lowercase text"
        )
    return value


def integer(
    value: int,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise GraphitiAdapterContractError(
            f"{field} must be an integer between {minimum} and {maximum}"
        )
    return value


_PROHIBITED_PUBLIC_KEYS = frozenset(
    {
        "api_key",
        "access_token",
        "credential",
        "credentials",
        "cypher",
        "graphiti_node_id",
        "graphiti_relation_id",
        "neo4j_id",
        "private_node_id",
        "private_relation_id",
        "secret",
        "token",
    }
)


def reject_private_graph_state(value: Any, *, path: str = "$") -> None:
    """Reject private graph identifiers, query text, and credentials publicly."""

    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise GraphitiAdapterContractError(
                    f"public adapter object key must be text at {path}"
                )
            lowered = key.lower()
            if lowered in _PROHIBITED_PUBLIC_KEYS:
                raise GraphitiAdapterContractError(
                    f"private graph or secret field is prohibited at {path}.{key}"
                )
            reject_private_graph_state(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        for index, item in enumerate(value):
            reject_private_graph_state(item, path=f"{path}[{index}]")
        return
    raise GraphitiAdapterContractError(
        f"unsupported public adapter value at {path}: {type(value).__name__}"
    )


__all__ = [
    "GraphitiAdapterConfigurationId",
    "GraphitiAdapterContractError",
    "GraphitiAdapterError",
    "GraphitiAdapterOutcome",
    "GraphitiAdapterReadPolicy",
    "GraphitiAdapterStateError",
    "GraphitiAttemptId",
    "GraphitiCleanupReason",
    "GraphitiCleanupReceiptId",
    "GraphitiCredentialClass",
    "GraphitiEgressPolicy",
    "GraphitiExecutionProfile",
    "GraphitiInputManifestId",
    "GraphitiReplayEligibility",
    "GraphitiReplayError",
    "GraphitiReplaySourceId",
    "GraphitiRuntimeMode",
    "GraphitiRuntimeNotAuthorized",
    "GraphitiWorkspaceError",
    "GraphitiWorkspaceId",
    "GraphitiWorkspacePolicyId",
    "GraphitiWorkspaceState",
    "digest",
    "integer",
    "reject_private_graph_state",
    "text",
    "token",
]
