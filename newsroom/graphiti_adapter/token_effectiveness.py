"""Average provider-token effectiveness and uncertainty model (#748)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from newsroom.graphiti_adapter.deterministic_contract import (
    DeterministicWorkContractError,
    require_bounded_text,
)


@dataclass(frozen=True, slots=True)
class TokenEstimateRange:
    low: int
    base: int
    high: int

    def __post_init__(self) -> None:
        for field, value in (
            ("low token estimate", self.low),
            ("base token estimate", self.base),
            ("high token estimate", self.high),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DeterministicWorkContractError(
                    f"{field} must be a non-negative integer"
                )
        if not self.low <= self.base <= self.high:
            raise DeterministicWorkContractError(
                "token estimate range must be ordered low/base/high"
            )

    def canonical_value(self) -> dict[str, int]:
        return {"low": self.low, "base": self.base, "high": self.high}

    def plus(self, other: TokenEstimateRange) -> TokenEstimateRange:
        return TokenEstimateRange(
            self.low + other.low,
            self.base + other.base,
            self.high + other.high,
        )

    def times(self, multiplier: int) -> TokenEstimateRange:
        return TokenEstimateRange(
            self.low * multiplier,
            self.base * multiplier,
            self.high * multiplier,
        )


@dataclass(frozen=True, slots=True)
class ConditionalLeafProfile:
    timestamp: int = 0
    dedupe: int = 0
    summary: int = 0
    fallback: int = 0

    def __post_init__(self) -> None:
        for field, value in self.canonical_value().items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DeterministicWorkContractError(
                    f"conditional {field} leaf count must be non-negative"
                )

    def canonical_value(self) -> dict[str, int]:
        return {
            "timestamp": self.timestamp,
            "dedupe": self.dedupe,
            "summary": self.summary,
            "fallback": self.fallback,
        }


@dataclass(frozen=True, slots=True)
class ConditionalLeafTokenRanges:
    timestamp: TokenEstimateRange
    dedupe: TokenEstimateRange
    summary: TokenEstimateRange
    fallback: TokenEstimateRange

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, TokenEstimateRange)
            for value in (
                self.timestamp,
                self.dedupe,
                self.summary,
                self.fallback,
            )
        ):
            raise DeterministicWorkContractError(
                "conditional leaf sensitivities must be typed token ranges"
            )

    @classmethod
    def zero(cls) -> ConditionalLeafTokenRanges:
        zero = TokenEstimateRange(0, 0, 0)
        return cls(timestamp=zero, dedupe=zero, summary=zero, fallback=zero)

    def for_profile(self, profile: ConditionalLeafProfile) -> TokenEstimateRange:
        total = TokenEstimateRange(0, 0, 0)
        for field, count in profile.canonical_value().items():
            total = total.plus(getattr(self, field).times(count))
        return total

    def canonical_value(self) -> dict[str, dict[str, int]]:
        return {
            field: getattr(self, field).canonical_value()
            for field in ("timestamp", "dedupe", "summary", "fallback")
        }


class EffectiveRevisionTokenOutcome(StrEnum):
    TERMINAL_SUCCESS_WITH_PROPOSALS = "TERMINAL_SUCCESS_WITH_PROPOSALS"
    TERMINAL_SUCCESS_ZERO_PROPOSALS = "TERMINAL_SUCCESS_ZERO_PROPOSALS"
    HELD_AMBIGUITY = "HELD_AMBIGUITY"

    @property
    def terminal(self) -> bool:
        return self is not EffectiveRevisionTokenOutcome.HELD_AMBIGUITY


@dataclass(frozen=True, slots=True)
class EffectiveRevisionTokenCase:
    """One #737-grain case with aggregate tokens for its primary leaf misses."""

    case_id: str
    outcome: EffectiveRevisionTokenOutcome
    primary_tokens: TokenEstimateRange | None
    primary_leaf_count: int | None
    current: ConditionalLeafProfile
    target: ConditionalLeafProfile
    embedding_tokens: int | None
    quality_matches_gold: bool | None
    reported_chat_tokens: int = 0
    unresolved_chat_leaves: int = 0

    def __post_init__(self) -> None:
        require_bounded_text(self.case_id, field="effective revision token case identity")
        if not isinstance(self.outcome, EffectiveRevisionTokenOutcome):
            raise DeterministicWorkContractError(
                "effective revision token outcome must be typed"
            )
        if self.primary_tokens is not None and not isinstance(
            self.primary_tokens, TokenEstimateRange
        ):
            raise DeterministicWorkContractError(
                "primary token estimate must be typed or unresolved"
            )
        if self.primary_leaf_count is not None and (
            isinstance(self.primary_leaf_count, bool)
            or not isinstance(self.primary_leaf_count, int)
            or self.primary_leaf_count < 0
        ):
            raise DeterministicWorkContractError(
                "primary leaf count must be non-negative or unresolved"
            )
        zero_primary_tokens = TokenEstimateRange(0, 0, 0)
        if self.primary_leaf_count == 0 and self.primary_tokens != zero_primary_tokens:
            raise DeterministicWorkContractError(
                "zero primary leaves require an exact zero primary token range"
            )
        if (
            self.primary_leaf_count is not None
            and self.primary_leaf_count > 0
            and self.primary_tokens == zero_primary_tokens
        ):
            raise DeterministicWorkContractError(
                "positive primary leaves require non-zero or unresolved primary tokens"
            )
        if not isinstance(self.current, ConditionalLeafProfile) or not isinstance(
            self.target, ConditionalLeafProfile
        ):
            raise DeterministicWorkContractError(
                "conditional leaf profiles must be typed"
            )
        for field, value in (
            ("embedding tokens", self.embedding_tokens),
            ("reported chat tokens", self.reported_chat_tokens),
            ("unresolved chat leaves", self.unresolved_chat_leaves),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise DeterministicWorkContractError(
                    f"{field} must be non-negative or unresolved"
                )
        if self.quality_matches_gold is not None and not isinstance(
            self.quality_matches_gold, bool
        ):
            raise DeterministicWorkContractError(
                "quality comparison must be boolean or unresolved"
            )


def _profile_expected_counts_ppm(
    cases: tuple[EffectiveRevisionTokenCase, ...],
    *,
    profile_name: str,
) -> dict[str, int]:
    denominator = len(cases)
    return {
        field: (
            sum(getattr(getattr(case, profile_name), field) for case in cases)
            * 1_000_000
            // denominator
        )
        for field in ("timestamp", "dedupe", "summary", "fallback")
    }


def _profile_prevalence_ppm(
    cases: tuple[EffectiveRevisionTokenCase, ...],
    *,
    profile_name: str,
) -> dict[str, int]:
    denominator = len(cases)
    return {
        field: (
            sum(
                getattr(getattr(case, profile_name), field) > 0 for case in cases
            )
            * 1_000_000
            // denominator
        )
        for field in ("timestamp", "dedupe", "summary", "fallback")
    }


def _average_range(
    totals: TokenEstimateRange,
    denominator: int,
) -> dict[str, int]:
    return {
        "low": totals.low // denominator,
        "base": totals.base // denominator,
        "high": totals.high // denominator,
    }


def build_token_effectiveness_report(
    cases: tuple[EffectiveRevisionTokenCase, ...],
    *,
    sensitivity: ConditionalLeafTokenRanges,
    distribution_measured: bool = True,
) -> dict[str, Any]:
    """Report provider and zero-token work without turning unknown usage into zero."""

    if (
        not isinstance(cases, tuple)
        or not cases
        or any(not isinstance(case, EffectiveRevisionTokenCase) for case in cases)
    ):
        raise DeterministicWorkContractError(
            "token effectiveness requires typed effective revision cases"
        )
    if not isinstance(sensitivity, ConditionalLeafTokenRanges):
        raise DeterministicWorkContractError(
            "token effectiveness requires typed sensitivity ranges"
        )
    if not isinstance(distribution_measured, bool):
        raise DeterministicWorkContractError(
            "distribution measurement state must be boolean"
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise DeterministicWorkContractError(
            "effective revision token case identities must be unique"
        )
    terminal = tuple(case for case in cases if case.outcome.terminal)
    if not terminal:
        raise DeterministicWorkContractError(
            "average token model requires a terminal effective revision"
        )
    current_total = TokenEstimateRange(0, 0, 0)
    target_total = TokenEstimateRange(0, 0, 0)
    usage_unresolved = any(
        case.primary_tokens is None
        or case.embedding_tokens is None
        or case.unresolved_chat_leaves > 0
        or case.reported_chat_tokens > 0
        for case in cases
    )
    for case in terminal:
        if (
            case.primary_tokens is None
            or case.embedding_tokens is None
            or case.unresolved_chat_leaves > 0
            or case.reported_chat_tokens > 0
        ):
            continue
        embedding = TokenEstimateRange(
            case.embedding_tokens,
            case.embedding_tokens,
            case.embedding_tokens,
        )
        current_total = current_total.plus(case.primary_tokens).plus(
            sensitivity.for_profile(case.current)
        ).plus(embedding)
        target_total = target_total.plus(case.primary_tokens).plus(
            sensitivity.for_profile(case.target)
        ).plus(embedding)
    explicit_unresolved_chat_leaves = sum(
        case.unresolved_chat_leaves for case in cases
    )
    unresolved_primary_leaf_count_unknown = any(
        case.primary_tokens is None and case.primary_leaf_count is None
        for case in cases
    )
    unresolved_primary_leaves = sum(
        case.primary_leaf_count or 0
        for case in cases
        if case.primary_tokens is None
    )
    if unresolved_primary_leaf_count_unknown:
        unresolved_leaf_count: object = "UNRESOLVED"
        chat_usage_unresolved = True
    else:
        unresolved_leaf_count = (
            explicit_unresolved_chat_leaves + unresolved_primary_leaves
        )
        chat_usage_unresolved = unresolved_leaf_count > 0
    embedding_unresolved = any(case.embedding_tokens is None for case in cases)
    current_expected_counts: object = "UNRESOLVED"
    target_expected_counts: object = "UNRESOLVED"
    current_prevalence: object = "UNRESOLVED"
    target_prevalence: object = "UNRESOLVED"
    primary_leaves_per_revision: object = "UNRESOLVED"
    primary_leaf_counts_resolved = False
    if distribution_measured:
        current_expected_counts = _profile_expected_counts_ppm(
            cases, profile_name="current"
        )
        target_expected_counts = _profile_expected_counts_ppm(
            cases, profile_name="target"
        )
        current_prevalence = _profile_prevalence_ppm(cases, profile_name="current")
        target_prevalence = _profile_prevalence_ppm(cases, profile_name="target")
        if all(case.primary_leaf_count is not None for case in cases):
            total_primary_leaves = sum(
                case.primary_leaf_count or 0 for case in cases
            )
            primary_leaves_per_revision = {
                "basis": "MEASURED_EFFECTIVE_REVISION_CASES",
                "expected_count_ppm": (
                    total_primary_leaves * 1_000_000 // len(cases)
                ),
                "revision_count": len(cases),
                "total_leaf_count": total_primary_leaves,
            }
            primary_leaf_counts_resolved = True
    quality_matches = all(case.quality_matches_gold is True for case in cases)
    if not distribution_measured:
        averages: object = "UNRESOLVED"
        recommendation = "HOLD_UNMEASURED_EFFECTIVE_REVISION_DISTRIBUTION"
    elif usage_unresolved or not primary_leaf_counts_resolved:
        averages: object = "UNRESOLVED"
        recommendation = "HOLD_UNRESOLVED_USAGE"
    else:
        current_average = _average_range(current_total, len(terminal))
        target_average = _average_range(target_total, len(terminal))
        averages = {"current": current_average, "target": target_average}
        strict_improvement = all(
            target_average[scenario] < current_average[scenario]
            for scenario in ("low", "base", "high")
        )
        assert isinstance(current_expected_counts, dict)
        assert isinstance(target_expected_counts, dict)
        expected_counts_non_increasing = all(
            target_expected_counts[field] <= current_expected_counts[field]
            for field in ("timestamp", "dedupe", "summary", "fallback")
        )
        avoidable_expected_count_falls = any(
            target_expected_counts[field] < current_expected_counts[field]
            for field in ("dedupe", "summary", "fallback")
        )
        if not quality_matches:
            recommendation = "HOLD_QUALITY_REGRESSION"
        elif (
            strict_improvement
            and expected_counts_non_increasing
            and avoidable_expected_count_falls
            and target_expected_counts["timestamp"] == 0
        ):
            recommendation = "ADOPT_IN_731_IMPLEMENTATION_ATOM"
        else:
            recommendation = "HOLD_NO_MEASURED_IMPROVEMENT"
    estimated_primary = TokenEstimateRange(0, 0, 0)
    for case in cases:
        if case.primary_tokens is not None:
            estimated_primary = estimated_primary.plus(case.primary_tokens)
    return {
        "schema_version": "newsroom.graphiti-token-effectiveness-report.v2",
        "effective_revision_count": len(cases),
        "mandatory_primary_leaves_per_revision": primary_leaves_per_revision,
        "conditional_leaf_expected_counts_ppm": {
            "current": current_expected_counts,
            "target": target_expected_counts,
        },
        "conditional_leaf_prevalence_ppm": {
            "current": current_prevalence,
            "target": target_prevalence,
        },
        "chat_tokens": {
            "reported": sum(case.reported_chat_tokens for case in cases),
            "estimated_primary": (
                "UNRESOLVED"
                if any(case.primary_tokens is None for case in cases)
                else estimated_primary.canonical_value()
            ),
            "unresolved": "UNRESOLVED" if chat_usage_unresolved else 0,
            "unresolved_leaf_count": unresolved_leaf_count,
        },
        "embedding_tokens": (
            "UNRESOLVED"
            if embedding_unresolved
            else {
                "total": sum(
                    case.embedding_tokens or 0 for case in cases
                ),
                "basis": "ESTIMATED_SOURCE_SAFE_WHITESPACE_TOKEN_PROXY",
            }
        ),
        "terminal_outcomes": {
            "terminal_success_with_proposals": sum(
                case.outcome
                is EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
                for case in cases
            ),
            "terminal_success_zero_proposals": sum(
                case.outcome
                is EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
                for case in cases
            ),
            "held_ambiguity": sum(
                case.outcome is EffectiveRevisionTokenOutcome.HELD_AMBIGUITY
                for case in cases
            ),
        },
        "quality": {
            "gold_match_count": sum(
                case.quality_matches_gold is True for case in cases
            ),
            "regression_count": sum(
                case.quality_matches_gold is False for case in cases
            ),
            "unresolved_count": sum(
                case.quality_matches_gold is None for case in cases
            ),
        },
        "sensitivity_tokens_per_conditional_leaf": sensitivity.canonical_value(),
        "average_total_tokens_per_terminal_effective_revision": averages,
        "recommendation": recommendation,
    }


__all__ = [
    "ConditionalLeafProfile",
    "ConditionalLeafTokenRanges",
    "EffectiveRevisionTokenCase",
    "EffectiveRevisionTokenOutcome",
    "TokenEstimateRange",
    "build_token_effectiveness_report",
]
