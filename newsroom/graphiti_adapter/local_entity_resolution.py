"""Provider-free local Canonical Entity resolution policy (#748)."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import digest_canonical
from newsroom.graphiti_adapter.deterministic_contract import (
    DeterministicWorkContractError,
    require_bounded_text,
    require_ppm,
    require_text_tuple,
)


class LocalEntityResolutionOutcome(StrEnum):
    DETERMINISTIC_EXISTING_NODE = "DETERMINISTIC_EXISTING_NODE"
    DETERMINISTIC_NEW_NODE = "DETERMINISTIC_NEW_NODE"
    AMBIGUOUS_HOLD = "AMBIGUOUS_HOLD"


class LocalEntityResolutionBasis(StrEnum):
    EXACT_NAME_AND_TYPE = "EXACT_NAME_AND_TYPE"
    GOVERNED_ALIAS_OR_IDENTIFIER = "GOVERNED_ALIAS_OR_IDENTIFIER"
    NORMALISED_NAME_AND_TYPE = "NORMALISED_NAME_AND_TYPE"
    MULTIPLE_EXACT_OR_GOVERNED_MATCHES = "MULTIPLE_EXACT_OR_GOVERNED_MATCHES"
    MULTIPLE_NORMALISED_MATCHES = "MULTIPLE_NORMALISED_MATCHES"
    NO_TYPE_COMPATIBLE_CANDIDATE = "NO_TYPE_COMPATIBLE_CANDIDATE"
    NO_SOURCE_SAFE_CANDIDATE = "NO_SOURCE_SAFE_CANDIDATE"
    BELOW_NEW_CANONICAL_ENTITY_CEILING = "BELOW_NEW_CANONICAL_ENTITY_CEILING"
    SOURCE_CONSTRAINED_EMBEDDING = "SOURCE_CONSTRAINED_EMBEDDING"
    LOW_CONFIDENCE_OR_MARGIN = "LOW_CONFIDENCE_OR_MARGIN"


@dataclass(frozen=True, slots=True)
class EntityMentionInput:
    name: str
    entity_type: str
    source_id: str
    governed_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_bounded_text(self.name, field="entity mention name")
        require_bounded_text(self.entity_type, field="entity mention type", maximum_bytes=128)
        require_bounded_text(self.source_id, field="entity mention source", maximum_bytes=512)
        require_text_tuple(
            self.governed_identifiers,
            field="entity mention governed identifiers",
        )


@dataclass(frozen=True, slots=True)
class CanonicalEntityCandidate:
    canonical_entity_id: str
    canonical_name: str
    entity_type: str
    governed_aliases: tuple[str, ...]
    governed_identifiers: tuple[str, ...]
    embedding_similarity_ppm: int
    permitted_source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_bounded_text(
            self.canonical_entity_id,
            field="candidate Canonical Entity identity",
        )
        require_bounded_text(self.canonical_name, field="candidate canonical name")
        require_bounded_text(self.entity_type, field="candidate entity type", maximum_bytes=128)
        require_text_tuple(self.governed_aliases, field="candidate governed aliases")
        require_text_tuple(
            self.governed_identifiers,
            field="candidate governed identifiers",
        )
        require_ppm(self.embedding_similarity_ppm, field="embedding similarity")
        require_text_tuple(
            self.permitted_source_ids,
            field="candidate permitted sources",
            allow_empty=False,
        )


@dataclass(frozen=True, slots=True)
class LocalEntityResolutionPolicy:
    existing_canonical_entity_threshold_ppm: int = 900_000
    existing_canonical_entity_margin_ppm: int = 50_000
    new_canonical_entity_ceiling_ppm: int = 800_000

    def __post_init__(self) -> None:
        require_ppm(self.existing_canonical_entity_threshold_ppm, field="existing Canonical Entity threshold")
        require_ppm(self.existing_canonical_entity_margin_ppm, field="existing Canonical Entity margin")
        require_ppm(self.new_canonical_entity_ceiling_ppm, field="new Canonical Entity ceiling")
        if self.new_canonical_entity_ceiling_ppm >= self.existing_canonical_entity_threshold_ppm:
            raise DeterministicWorkContractError(
                "new Canonical Entity ceiling must stay below existing Canonical Entity threshold"
            )


DEFAULT_LOCAL_ENTITY_RESOLUTION_POLICY = LocalEntityResolutionPolicy()


@dataclass(frozen=True, slots=True)
class LocalEntityResolution:
    outcome: LocalEntityResolutionOutcome
    selected_canonical_entity_id: str | None
    basis: LocalEntityResolutionBasis
    considered_canonical_entity_ids: tuple[str, ...]
    provider_leaf_count: int = 0

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "schema_version": "newsroom.graphiti-local-entity-resolution.v1",
                "outcome": self.outcome.value,
                "selected_canonical_entity_id": self.selected_canonical_entity_id,
                "basis": self.basis.value,
                "considered_canonical_entity_ids": list(self.considered_canonical_entity_ids),
                "provider_leaf_count": self.provider_leaf_count,
            }
        )


def _normalise_name(value: str) -> str:
    normalised = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalised
        if not unicodedata.category(character).startswith(("P", "Z"))
    )


def _resolution(
    outcome: LocalEntityResolutionOutcome,
    *,
    selected: str | None,
    basis: LocalEntityResolutionBasis,
    candidates: tuple[CanonicalEntityCandidate, ...],
) -> LocalEntityResolution:
    return LocalEntityResolution(
        outcome=outcome,
        selected_canonical_entity_id=selected,
        basis=basis,
        considered_canonical_entity_ids=tuple(
            candidate.canonical_entity_id for candidate in candidates
        ),
    )


def _resolve_ranked(
    candidates: tuple[CanonicalEntityCandidate, ...],
    scores: dict[str, int],
    *,
    policy: LocalEntityResolutionPolicy,
    basis: LocalEntityResolutionBasis,
) -> LocalEntityResolution:
    ranked = sorted(
        (
            (scores[candidate.canonical_entity_id], candidate)
            for candidate in candidates
        ),
        key=lambda item: (-item[0], item[1].canonical_entity_id),
    )
    top_score, top = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if (
        top_score >= policy.existing_canonical_entity_threshold_ppm
        and top_score - second_score >= policy.existing_canonical_entity_margin_ppm
    ):
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE,
            selected=top.canonical_entity_id,
            basis=basis,
            candidates=candidates,
        )
    return _resolution(
        LocalEntityResolutionOutcome.AMBIGUOUS_HOLD,
        selected=None,
        basis=LocalEntityResolutionBasis.LOW_CONFIDENCE_OR_MARGIN,
        candidates=candidates,
    )


def resolve_entity_locally(
    mention: EntityMentionInput,
    candidates: tuple[CanonicalEntityCandidate, ...],
    *,
    policy: LocalEntityResolutionPolicy = DEFAULT_LOCAL_ENTITY_RESOLUTION_POLICY,
) -> LocalEntityResolution:
    """Resolve common identities locally and hold rather than guess."""

    if not isinstance(mention, EntityMentionInput):
        raise DeterministicWorkContractError(
            "local resolution requires a typed entity mention"
        )
    if not isinstance(candidates, tuple) or any(
        not isinstance(candidate, CanonicalEntityCandidate) for candidate in candidates
    ):
        raise DeterministicWorkContractError(
            "local resolution requires typed Canonical Entity candidates"
        )
    if not isinstance(policy, LocalEntityResolutionPolicy):
        raise DeterministicWorkContractError(
            "local resolution requires a typed policy"
        )
    typed = tuple(
        candidate for candidate in candidates if candidate.entity_type == mention.entity_type
    )
    if not typed:
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_NEW_NODE,
            selected=None,
            basis=LocalEntityResolutionBasis.NO_TYPE_COMPATIBLE_CANDIDATE,
            candidates=candidates,
        )
    exact = tuple(
        candidate for candidate in typed if candidate.canonical_name == mention.name
    )
    if len(exact) == 1:
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE,
            selected=exact[0].canonical_entity_id,
            basis=LocalEntityResolutionBasis.EXACT_NAME_AND_TYPE,
            candidates=typed,
        )
    mention_identifiers = set(mention.governed_identifiers)
    governed = tuple(
        candidate
        for candidate in typed
        if mention.name in candidate.governed_aliases
        or bool(mention_identifiers.intersection(candidate.governed_identifiers))
    )
    if len(governed) == 1:
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE,
            selected=governed[0].canonical_entity_id,
            basis=LocalEntityResolutionBasis.GOVERNED_ALIAS_OR_IDENTIFIER,
            candidates=typed,
        )
    if len(exact) > 1 or len(governed) > 1:
        return _resolution(
            LocalEntityResolutionOutcome.AMBIGUOUS_HOLD,
            selected=None,
            basis=LocalEntityResolutionBasis.MULTIPLE_EXACT_OR_GOVERNED_MATCHES,
            candidates=typed,
        )
    normalised_name = _normalise_name(mention.name)
    normalised = tuple(
        candidate
        for candidate in typed
        if _normalise_name(candidate.canonical_name) == normalised_name
        or any(
            _normalise_name(alias) == normalised_name
            for alias in candidate.governed_aliases
        )
    )
    if len(normalised) == 1:
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE,
            selected=normalised[0].canonical_entity_id,
            basis=LocalEntityResolutionBasis.NORMALISED_NAME_AND_TYPE,
            candidates=typed,
        )
    if len(normalised) > 1:
        return _resolution(
            LocalEntityResolutionOutcome.AMBIGUOUS_HOLD,
            selected=None,
            basis=LocalEntityResolutionBasis.MULTIPLE_NORMALISED_MATCHES,
            candidates=typed,
        )
    constrained = tuple(
        candidate
        for candidate in typed
        if mention.source_id in candidate.permitted_source_ids
    )
    if not constrained:
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_NEW_NODE,
            selected=None,
            basis=LocalEntityResolutionBasis.NO_SOURCE_SAFE_CANDIDATE,
            candidates=typed,
        )
    scores = {
        candidate.canonical_entity_id: candidate.embedding_similarity_ppm
        for candidate in constrained
    }
    top_similarity = max(scores.values())
    if top_similarity <= policy.new_canonical_entity_ceiling_ppm:
        return _resolution(
            LocalEntityResolutionOutcome.DETERMINISTIC_NEW_NODE,
            selected=None,
            basis=LocalEntityResolutionBasis.BELOW_NEW_CANONICAL_ENTITY_CEILING,
            candidates=constrained,
        )
    embedding_result = _resolve_ranked(
        constrained,
        scores,
        policy=policy,
        basis=LocalEntityResolutionBasis.SOURCE_CONSTRAINED_EMBEDDING,
    )
    if (
        embedding_result.outcome
        is LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE
    ):
        return embedding_result
    return embedding_result


__all__ = [
    "DEFAULT_LOCAL_ENTITY_RESOLUTION_POLICY",
    "CanonicalEntityCandidate",
    "EntityMentionInput",
    "LocalEntityResolution",
    "LocalEntityResolutionBasis",
    "LocalEntityResolutionOutcome",
    "LocalEntityResolutionPolicy",
    "resolve_entity_locally",
]
