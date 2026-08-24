"""Bounded convenience summaries from governed assertions (#748)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import digest_canonical
from newsroom.graphiti_adapter.deterministic_contract import (
    DeterministicWorkContractError,
    require_bounded_text,
    require_text_tuple,
)
from newsroom.graphiti_adapter.deterministic_sidecar import AuthorityRecordRef


class DeterministicSummaryOutcome(StrEnum):
    DETERMINISTIC_SUMMARY = "DETERMINISTIC_SUMMARY"
    OMITTED_EMPTY = "OMITTED_EMPTY"
    OVERLONG_HOLD = "OVERLONG_HOLD"


@dataclass(frozen=True, slots=True)
class AdmittedSummaryAssertion:
    assertion_id: str
    text: str
    evidence_links: tuple[str, ...]
    temporal_links: tuple[str, ...]
    admission_decision: AuthorityRecordRef

    def __post_init__(self) -> None:
        require_bounded_text(self.assertion_id, field="governed assertion identity")
        require_bounded_text(
            self.text,
            field="governed assertion text",
            maximum_bytes=8192,
        )
        require_text_tuple(
            self.evidence_links,
            field="governed assertion evidence links",
            allow_empty=False,
        )
        require_text_tuple(
            self.temporal_links,
            field="governed assertion temporal links",
            allow_empty=True,
        )
        if not isinstance(self.admission_decision, AuthorityRecordRef):
            raise DeterministicWorkContractError(
                "summary assertion requires an exact admission decision binding"
            )
        admission_record = self.admission_decision.canonical_record
        if (
            admission_record.get("record_kind") != "ADMISSION_DECISION"
            or admission_record.get("admitted_assertion_id")
            != self.assertion_id
        ):
            raise DeterministicWorkContractError(
                "summary assertion must be proved by its admission decision record"
            )


@dataclass(frozen=True, slots=True)
class DeterministicSummary:
    outcome: DeterministicSummaryOutcome
    summary: str | None
    assertion_ids: tuple[str, ...]
    evidence_links: tuple[str, ...]
    temporal_links: tuple[str, ...]
    admission_decisions: tuple[AuthorityRecordRef, ...]
    maximum_bytes: int
    provider_leaf_count: int
    requires_separate_policy: bool

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "schema_version": "newsroom.graphiti-deterministic-summary.v1",
                "outcome": self.outcome.value,
                "summary": self.summary,
                "assertion_ids": list(self.assertion_ids),
                "evidence_links": list(self.evidence_links),
                "temporal_links": list(self.temporal_links),
                "admission_decisions": [
                    decision.canonical_value()
                    for decision in self.admission_decisions
                ],
                "maximum_bytes": self.maximum_bytes,
                "provider_leaf_count": self.provider_leaf_count,
                "requires_separate_policy": self.requires_separate_policy,
            }
        )


def build_deterministic_summary(
    assertions: tuple[AdmittedSummaryAssertion, ...],
    *,
    maximum_bytes: int = 1024,
    maximum_assertions: int = 8,
) -> DeterministicSummary:
    """Build bounded convenience text from governed assertions only."""

    if (
        not isinstance(assertions, tuple)
        or any(
            not isinstance(assertion, AdmittedSummaryAssertion)
            for assertion in assertions
        )
    ):
        raise DeterministicWorkContractError(
            "summary input must contain governed typed assertions"
        )
    for field, value in (
        ("summary maximum bytes", maximum_bytes),
        ("summary maximum assertions", maximum_assertions),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DeterministicWorkContractError(f"{field} must be positive")
    ordered = tuple(sorted(assertions, key=lambda item: item.assertion_id))
    if len({assertion.assertion_id for assertion in ordered}) != len(ordered):
        raise DeterministicWorkContractError(
            "governed summary assertion identities must be unique"
        )
    assertion_ids = tuple(assertion.assertion_id for assertion in ordered)
    evidence_links = tuple(
        link for assertion in ordered for link in assertion.evidence_links
    )
    temporal_links = tuple(
        link for assertion in ordered for link in assertion.temporal_links
    )
    admission_decisions = tuple(
        assertion.admission_decision for assertion in ordered
    )
    if not ordered:
        return DeterministicSummary(
            outcome=DeterministicSummaryOutcome.OMITTED_EMPTY,
            summary=None,
            assertion_ids=(),
            evidence_links=(),
            temporal_links=(),
            admission_decisions=(),
            maximum_bytes=maximum_bytes,
            provider_leaf_count=0,
            requires_separate_policy=False,
        )
    summary = "; ".join(assertion.text for assertion in ordered)
    if (
        len(ordered) > maximum_assertions
        or len(summary.encode("utf-8")) > maximum_bytes
    ):
        return DeterministicSummary(
            outcome=DeterministicSummaryOutcome.OVERLONG_HOLD,
            summary=None,
            assertion_ids=assertion_ids,
            evidence_links=evidence_links,
            temporal_links=temporal_links,
            admission_decisions=admission_decisions,
            maximum_bytes=maximum_bytes,
            provider_leaf_count=0,
            requires_separate_policy=True,
        )
    return DeterministicSummary(
        outcome=DeterministicSummaryOutcome.DETERMINISTIC_SUMMARY,
        summary=summary,
        assertion_ids=assertion_ids,
        evidence_links=evidence_links,
        temporal_links=temporal_links,
        admission_decisions=admission_decisions,
        maximum_bytes=maximum_bytes,
        provider_leaf_count=0,
        requires_separate_policy=False,
    )
__all__ = [
    "AdmittedSummaryAssertion",
    "DeterministicSummary",
    "DeterministicSummaryOutcome",
    "build_deterministic_summary",
]
