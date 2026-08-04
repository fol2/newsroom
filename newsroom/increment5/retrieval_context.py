"""Immutable policy-bound request context for one Increment 5B branch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp

from ._retrieval_validation import (
    Increment5RetrievalContractError,
    bounded_int,
    bounded_text,
    require_digest,
    require_mapping,
)
from .contract_types import RetrievalMode, RetrievalProfileKind
from .decision import INCREMENT_5A_CONTRACT_DIGEST
from .retrieval_snapshot import BranchSourceSnapshot
from .retrieval_subject import (
    BranchRequestId,
    RetrievalCaller,
    RetrievalRightsContext,
)

BRANCH_RESULT_LIMIT: Final[int] = 8
BRANCH_TIMEOUT_MS: Final[int] = 5_000
MAX_EXTERNAL_CALLS: Final[int] = 0
MAX_PROVIDER_COST_MICROUNITS: Final[int] = 0


def branch_policy_digest(
    *, mode: RetrievalMode, purpose: str, required_scope: str,
    component_contract_digest: str,
) -> str:
    if not isinstance(mode, RetrievalMode):
        raise Increment5RetrievalContractError("branch policy mode must be typed")
    bounded_text(purpose, field="branch purpose", maximum_bytes=128)
    bounded_text(required_scope, field="required scope", maximum_bytes=256)
    require_digest(component_contract_digest, field="component contract digest")
    return digest_canonical({
        "contract": "newsroom.increment5b.branch-policy.v1",
        "mode": mode.value,
        "purpose": purpose,
        "required_scope": required_scope,
        "increment5a_contract_digest": INCREMENT_5A_CONTRACT_DIGEST,
        "component_contract_digest": component_contract_digest,
        "result_limit": BRANCH_RESULT_LIMIT,
        "timeout_ms": BRANCH_TIMEOUT_MS,
        "max_external_calls": 0,
        "max_provider_cost_microunits": 0,
        "authority_effect": "NONE",
    })


@dataclass(frozen=True, slots=True)
class BranchRequestContext:
    request_id: BranchRequestId
    mode: RetrievalMode
    profile: RetrievalProfileKind
    caller: RetrievalCaller
    purpose: str
    required_scope: str
    query_valid_time: UtcTimestamp
    rights: RetrievalRightsContext
    source_snapshot: BranchSourceSnapshot
    component_contract_digest: str
    policy_digest: str
    contract_digest: str = INCREMENT_5A_CONTRACT_DIGEST
    result_limit: int = BRANCH_RESULT_LIMIT
    timeout_ms: int = BRANCH_TIMEOUT_MS
    max_external_calls: int = MAX_EXTERNAL_CALLS
    max_provider_cost_microunits: int = MAX_PROVIDER_COST_MICROUNITS

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, BranchRequestId):
            raise Increment5RetrievalContractError("branch request identity must be typed")
        if not isinstance(self.mode, RetrievalMode):
            raise Increment5RetrievalContractError("branch mode must be typed")
        if not isinstance(self.profile, RetrievalProfileKind):
            raise Increment5RetrievalContractError("branch profile must be typed")
        if not isinstance(self.caller, RetrievalCaller):
            raise Increment5RetrievalContractError("branch caller must be typed")
        bounded_text(self.purpose, field="branch purpose", maximum_bytes=128)
        bounded_text(self.required_scope, field="required scope", maximum_bytes=256)
        if not isinstance(self.query_valid_time, UtcTimestamp):
            raise Increment5RetrievalContractError("query-valid time must be typed")
        if not isinstance(self.rights, RetrievalRightsContext):
            raise Increment5RetrievalContractError("branch rights must be typed")
        if not isinstance(self.source_snapshot, BranchSourceSnapshot):
            raise Increment5RetrievalContractError("source snapshot must be typed")
        require_digest(self.component_contract_digest, field="component contract digest")
        require_digest(self.policy_digest, field="branch policy digest")
        require_digest(self.contract_digest, field="Increment 5A contract digest")
        if self.contract_digest != INCREMENT_5A_CONTRACT_DIGEST:
            raise Increment5RetrievalContractError("request is not bound to reviewed 5A")
        for field, value in (
            ("result limit", self.result_limit),
            ("timeout ms", self.timeout_ms),
            ("external call budget", self.max_external_calls),
            ("provider cost budget", self.max_provider_cost_microunits),
        ):
            bounded_int(value, field=field)
        if self.result_limit != 8 or self.timeout_ms != 5000:
            raise Increment5RetrievalContractError("branch limits differ from 5A")
        if self.max_external_calls or self.max_provider_cost_microunits:
            raise Increment5RetrievalContractError("5B permits zero calls and spend")
        expected = branch_policy_digest(
            mode=self.mode, purpose=self.purpose,
            required_scope=self.required_scope,
            component_contract_digest=self.component_contract_digest,
        )
        if self.policy_digest != expected:
            raise Increment5RetrievalContractError("branch policy digest differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "request_id": str(self.request_id), "mode": self.mode.value,
            "profile": self.profile.value, "caller": self.caller.canonical_value(),
            "purpose": self.purpose, "required_scope": self.required_scope,
            "query_valid_time": self.query_valid_time.to_text(),
            "rights": self.rights.canonical_value(),
            "source_snapshot": self.source_snapshot.canonical_value(),
            "component_contract_digest": self.component_contract_digest,
            "policy_digest": self.policy_digest, "contract_digest": self.contract_digest,
            "result_limit": self.result_limit, "timeout_ms": self.timeout_ms,
            "max_external_calls": self.max_external_calls,
            "max_provider_cost_microunits": self.max_provider_cost_microunits,
        }

    @property
    def context_digest(self) -> str:
        return digest_canonical(self.canonical_value())

    @classmethod
    def from_value(cls, value: object) -> "BranchRequestContext":
        item = require_mapping(value, field="branch request context")
        return cls(
            request_id=BranchRequestId.parse(str(item["request_id"])),
            mode=RetrievalMode(item["mode"]), profile=RetrievalProfileKind(item["profile"]),
            caller=RetrievalCaller.from_value(item["caller"]),
            purpose=str(item["purpose"]), required_scope=str(item["required_scope"]),
            query_valid_time=UtcTimestamp.parse(str(item["query_valid_time"])),
            rights=RetrievalRightsContext.from_value(item["rights"]),
            source_snapshot=BranchSourceSnapshot.from_value(item["source_snapshot"]),
            component_contract_digest=str(item["component_contract_digest"]),
            policy_digest=str(item["policy_digest"]), contract_digest=str(item["contract_digest"]),
            result_limit=item["result_limit"], timeout_ms=item["timeout_ms"],
            max_external_calls=item["max_external_calls"],
            max_provider_cost_microunits=item["max_provider_cost_microunits"],
        )


__all__ = [
    "BRANCH_RESULT_LIMIT", "BRANCH_TIMEOUT_MS", "MAX_EXTERNAL_CALLS",
    "MAX_PROVIDER_COST_MICROUNITS", "BranchRequestContext",
    "branch_policy_digest",
]
