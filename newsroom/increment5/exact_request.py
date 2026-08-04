"""Typed exact-identity request and fixed alias normalisation for 5B1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
import unicodedata

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UUIDv4Id

from ._retrieval_validation import Increment5RetrievalContractError, bounded_text
from .contract_types import RetrievalMode
from .retrieval_context import BranchRequestContext
from .retrieval_snapshot import BranchSourceSystem

EXACT_RETRIEVAL_PURPOSE: Final[str] = "retrieval.exact_identity"
EXACT_RETRIEVAL_REQUIRED_SCOPE: Final[str] = "authority.retrieval.read"
PERSONAL_METADATA_SCOPE: Final[str] = "authority.retrieval.personal_metadata"
EXACT_COMPONENT_CONTRACT_DIGEST: Final[str] = digest_canonical(
    {
        "contract": "newsroom.increment5b.sqlite-exact-retriever.v1",
        "authority": "sqlite-ledger-and-governed-objects",
        "query_surface": "fixed-enum-owned-parameterised-sql",
        "result_limit": 8,
        "timeout_ms": 5000,
        "authority_effect": "NONE",
    }
)
_QUERY_VALUE_MAXIMUM_BYTES: Final[int] = 1024


class ExactLookupKind(StrEnum):
    SOURCE_REVISION_ID = "SOURCE_REVISION_ID"
    SOURCE_NATIVE_REVISION_TOKEN = "SOURCE_NATIVE_REVISION_TOKEN"
    SOURCE_ITEM_ID = "SOURCE_ITEM_ID"
    SOURCE_NATIVE_ITEM_ID = "SOURCE_NATIVE_ITEM_ID"
    REPRESENTATION_ID = "REPRESENTATION_ID"
    CANONICAL_ENTITY_ID = "CANONICAL_ENTITY_ID"
    ENTITY_ALIAS_NORMALIZED = "ENTITY_ALIAS_NORMALIZED"
    CANONICAL_PROCESS_ID = "CANONICAL_PROCESS_ID"
    CANDIDATE_VERSION_ID = "CANDIDATE_VERSION_ID"


_UUID_LOOKUPS: Final[frozenset[ExactLookupKind]] = frozenset(
    {
        ExactLookupKind.SOURCE_REVISION_ID,
        ExactLookupKind.SOURCE_ITEM_ID,
        ExactLookupKind.REPRESENTATION_ID,
        ExactLookupKind.CANONICAL_ENTITY_ID,
        ExactLookupKind.CANDIDATE_VERSION_ID,
    }
)


def normalize_authority_alias(value: str) -> str:
    """Apply only the fixed NFKC/casefold/LF/whitespace contract."""

    if not isinstance(value, str) or "\x00" in value:
        raise Increment5RetrievalContractError("authority alias must be text without NUL")
    if not value or len(value.encode("utf-8")) > _QUERY_VALUE_MAXIMUM_BYTES:
        raise Increment5RetrievalContractError("authority alias exceeds its fixed bound")
    normalized = unicodedata.normalize(
        "NFKC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    normalized = " ".join(normalized.casefold().split())
    if not normalized or len(normalized.encode("utf-8")) > _QUERY_VALUE_MAXIMUM_BYTES:
        raise Increment5RetrievalContractError(
            "normalised alias is empty or exceeds its fixed bound"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ExactRetrieverRequest:
    context: BranchRequestContext
    lookup_kind: ExactLookupKind
    lookup_value: str

    def __post_init__(self) -> None:
        if not isinstance(self.context, BranchRequestContext):
            raise Increment5RetrievalContractError("exact context must be typed")
        if self.context.mode is not RetrievalMode.EXACT:
            raise Increment5RetrievalContractError("exact request must select EXACT")
        if self.context.purpose != EXACT_RETRIEVAL_PURPOSE:
            raise Increment5RetrievalContractError("exact request purpose differs")
        if self.context.required_scope != EXACT_RETRIEVAL_REQUIRED_SCOPE:
            raise Increment5RetrievalContractError("exact request scope differs")
        if self.context.component_contract_digest != EXACT_COMPONENT_CONTRACT_DIGEST:
            raise Increment5RetrievalContractError("exact component contract differs")
        if self.context.source_snapshot.source_system is not BranchSourceSystem.SQLITE_AUTHORITY:
            raise Increment5RetrievalContractError("exact request requires SQLite authority")
        if not isinstance(self.lookup_kind, ExactLookupKind):
            raise Increment5RetrievalContractError("exact lookup kind must be typed")
        if not isinstance(self.lookup_value, str):
            raise Increment5RetrievalContractError("exact lookup value must be text")
        value = self.lookup_value
        if self.lookup_kind is ExactLookupKind.ENTITY_ALIAS_NORMALIZED:
            value = normalize_authority_alias(value)
        else:
            bounded_text(value, field="exact lookup value", maximum_bytes=1024)
        if self.lookup_kind in _UUID_LOOKUPS:
            try:
                UUIDv4Id.parse(value)
            except ValueError as exc:
                raise Increment5RetrievalContractError(
                    "exact identifier requires canonical UUIDv4 text"
                ) from exc
        object.__setattr__(self, "lookup_value", value)

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom.increment5b.exact-request.v1",
            "context": self.context.canonical_value(),
            "lookup_kind": self.lookup_kind.value,
            "lookup_value": self.lookup_value,
        }

    @property
    def request_digest(self) -> str:
        return digest_canonical(self.canonical_value())


__all__ = [
    "EXACT_COMPONENT_CONTRACT_DIGEST",
    "EXACT_RETRIEVAL_PURPOSE",
    "EXACT_RETRIEVAL_REQUIRED_SCOPE",
    "PERSONAL_METADATA_SCOPE",
    "ExactLookupKind",
    "ExactRetrieverRequest",
    "normalize_authority_alias",
]
