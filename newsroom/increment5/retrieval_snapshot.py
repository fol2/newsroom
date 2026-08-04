"""Immutable source snapshot bound to an Increment 5B branch request."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.types import UtcTimestamp

from ._retrieval_validation import (
    Increment5RetrievalContractError,
    bounded_int,
    bounded_text,
    require_digest,
    require_mapping,
)


class BranchSourceSystem(StrEnum):
    SQLITE_AUTHORITY = "SQLITE_AUTHORITY"
    NEO4J_PROJECTION = "NEO4J_PROJECTION"
    FIXTURE_REPLAY = "FIXTURE_REPLAY"


@dataclass(frozen=True, slots=True)
class BranchSourceSnapshot:
    source_system: BranchSourceSystem
    authority_watermark: int
    authority_state_digest: str
    captured_at: UtcTimestamp
    generation_id: str | None = None
    index_contract_digest: str | None = None
    open_gap_count: int = 0
    dead_letter_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_system, BranchSourceSystem):
            raise Increment5RetrievalContractError("branch source system must be typed")
        bounded_int(self.authority_watermark, field="authority watermark")
        require_digest(self.authority_state_digest, field="authority state digest")
        if not isinstance(self.captured_at, UtcTimestamp):
            raise Increment5RetrievalContractError("snapshot capture time must be typed")
        bounded_int(self.open_gap_count, field="open gap count")
        bounded_int(self.dead_letter_count, field="dead letter count")
        if self.generation_id is not None:
            bounded_text(self.generation_id, field="generation identity", maximum_bytes=128)
        if self.index_contract_digest is not None:
            require_digest(self.index_contract_digest, field="index contract digest")
        if self.source_system is BranchSourceSystem.SQLITE_AUTHORITY and (
            self.generation_id is not None or self.index_contract_digest is not None
        ):
            raise Increment5RetrievalContractError(
                "SQLite authority snapshot cannot claim a generation or index"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "source_system": self.source_system.value,
            "authority_watermark": self.authority_watermark,
            "authority_state_digest": self.authority_state_digest,
            "captured_at": self.captured_at.to_text(),
            "generation_id": self.generation_id,
            "index_contract_digest": self.index_contract_digest,
            "open_gap_count": self.open_gap_count,
            "dead_letter_count": self.dead_letter_count,
        }

    @classmethod
    def from_value(cls, value: object) -> "BranchSourceSnapshot":
        item = require_mapping(value, field="branch source snapshot")
        return cls(
            source_system=BranchSourceSystem(item["source_system"]),
            authority_watermark=item["authority_watermark"],
            authority_state_digest=str(item["authority_state_digest"]),
            captured_at=UtcTimestamp.parse(str(item["captured_at"])),
            generation_id=None if item.get("generation_id") is None else str(item["generation_id"]),
            index_contract_digest=(
                None if item.get("index_contract_digest") is None
                else str(item["index_contract_digest"])
            ),
            open_gap_count=item["open_gap_count"],
            dead_letter_count=item["dead_letter_count"],
        )


__all__ = ["BranchSourceSnapshot", "BranchSourceSystem"]
