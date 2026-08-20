"""CONT-001 Evidence Package for unpublished staging."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.editorial import StoryCandidateRecord


@dataclass(frozen=True, slots=True)
class EvidencePackage:
    candidate_id: str
    hypothesis_id: str
    signal_ids: tuple[str, ...]
    lead_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    observation_digests: tuple[str, ...]
    passages: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.signal_ids or not self.lead_ids or not self.observation_digests:
            raise ValueError("Evidence Package requires Signal, Lead and retained observations")
        if not self.passages:
            raise ValueError("Evidence Package requires at least one retained passage")

    @property
    def digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "candidate_id": self.candidate_id,
                    "hypothesis_id": self.hypothesis_id,
                    "signal_ids": list(self.signal_ids),
                    "lead_ids": list(self.lead_ids),
                    "source_ids": list(self.source_ids),
                    "observation_digests": list(self.observation_digests),
                    "passages": list(self.passages),
                }
            )
        )


def package_for(candidate: StoryCandidateRecord) -> EvidencePackage:
    passages = tuple(
        f"{item.source_id}: {item.headline}\n{item.body}".strip()
        for item in candidate.items
    )
    return EvidencePackage(
        candidate_id=candidate.candidate_id,
        hypothesis_id=candidate.hypothesis_id,
        signal_ids=tuple(signal.signal_id for signal in candidate.signals),
        lead_ids=tuple(lead.lead_id for lead in candidate.leads),
        source_ids=tuple(sorted({item.source_id for item in candidate.items})),
        observation_digests=tuple(
            signal.observation_digest for signal in candidate.signals
        ),
        passages=passages,
    )
