"""Reviewed bilingual normalizer and fixed Lucene query builder for 5B2."""

from __future__ import annotations

import re
import unicodedata

from newsroom.authority.types import UtcTimestamp

from .fulltext_contracts import (
    AuthorityAliasTerm,
    FULLTEXT_MAX_TERMS,
    FullTextContractError,
    FullTextLanguageMode,
    NORMALIZATION_COMPONENT_DIGEST,
    NormalizedFullTextQuery,
)


_LATIN_TERM = re.compile(r"[a-z0-9]+(?:['’.-][a-z0-9]+)*", re.IGNORECASE)
_FORMAL_TOKEN = re.compile(
    r"(?<![a-z0-9])(?:[a-z]{1,16}[-/:.]?)?\d+(?:[-/:.]\d+)+(?![a-z0-9])"
    r"|(?<![a-z0-9])[a-z]{1,16}-\d+[a-z0-9./:-]*(?![a-z0-9])",
    re.IGNORECASE,
)
_HAN_SEQUENCE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_LUCENE_SPECIAL = frozenset(r'+-&|!(){}[]^"~*?:\/')


def _collapse_nfkc(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = " ".join(normalized.split())
    if not normalized:
        raise FullTextContractError("normalized full-text query is empty")
    return normalized


def _casefold_latin(value: str) -> str:
    # Unicode casefold does not convert traditional Han into another script.
    return value.casefold()


def _escape_lucene_term(value: str) -> str:
    escaped: list[str] = []
    for character in value:
        if character in _LUCENE_SPECIAL:
            escaped.append("\\")
        escaped.append(character)
    return "".join(escaped)


def _field_clause(field: str, value: str) -> str:
    if field not in {
        "authority_aliases",
        "formal_tokens",
        "han_bigrams",
        "latin_terms",
        "retrieval_text",
    }:
        raise FullTextContractError("full-text query builder field is not reviewed")
    return f'{field}:"{_escape_lucene_term(value)}"'


def _bounded_sorted(values: set[str], *, field: str) -> tuple[str, ...]:
    if len(values) > FULLTEXT_MAX_TERMS:
        raise FullTextContractError(f"{field} exceeds the reviewed term bound")
    return tuple(sorted(values))


def _normalization_core(
    surface_text: str,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    collapsed = _collapse_nfkc(surface_text)
    normalized = _casefold_latin(collapsed)
    formal_tokens = {
        match.group(0).casefold()
        for match in _FORMAL_TOKEN.finditer(normalized)
    }
    latin_terms = {
        match.group(0).casefold()
        for match in _LATIN_TERM.finditer(normalized)
        if any(
            "a" <= character <= "z"
            for character in match.group(0).casefold()
        )
    }
    han_bigrams: set[str] = set()
    for match in _HAN_SEQUENCE.finditer(normalized):
        sequence = match.group(0)
        han_bigrams.update(
            sequence[index : index + 2]
            for index in range(max(0, len(sequence) - 1))
        )
    return (
        collapsed,
        normalized,
        _bounded_sorted(latin_terms, field="latin_terms"),
        _bounded_sorted(han_bigrams, field="han_bigrams"),
        _bounded_sorted(formal_tokens, field="formal_tokens"),
    )


def _build_lucene_query(
    *,
    normalized_text: str,
    latin_terms: tuple[str, ...],
    han_bigrams: tuple[str, ...],
    formal_tokens: tuple[str, ...],
    authority_alias_terms: tuple[str, ...],
) -> str:
    clauses = {_field_clause("retrieval_text", normalized_text)}
    clauses.update(
        _field_clause("latin_terms", item) for item in latin_terms
    )
    clauses.update(
        _field_clause("han_bigrams", item) for item in han_bigrams
    )
    clauses.update(
        _field_clause("formal_tokens", item) for item in formal_tokens
    )
    clauses.update(
        _field_clause("authority_aliases", item)
        for item in authority_alias_terms
    )
    return " OR ".join(sorted(clauses))


class BilingualSearchNormalizer:
    """NFKC bilingual normalization with no transliteration or script conversion."""

    implementation_version = "bilingual-search-normalizer-v1"
    component_digest = NORMALIZATION_COMPONENT_DIGEST

    def validate_request_binding(
        self,
        query: NormalizedFullTextQuery,
        *,
        surface_text: str,
        language_mode: FullTextLanguageMode,
    ) -> None:
        if not isinstance(query, NormalizedFullTextQuery):
            raise FullTextContractError(
                "retained full-text query must be typed"
            )
        if not isinstance(language_mode, FullTextLanguageMode):
            raise FullTextContractError(
                "retained full-text language mode must be typed"
            )
        collapsed, normalized, latin, han, formal = _normalization_core(
            surface_text
        )
        if (
            query.surface_text != collapsed
            or query.normalized_text != normalized
            or query.language_mode is not language_mode
            or query.latin_terms != latin
            or query.han_bigrams != han
            or query.formal_tokens != formal
            or query.implementation_version != self.implementation_version
            or query.component_digest != self.component_digest
        ):
            raise FullTextContractError(
                "retained full-text query differs from its request core"
            )
        if bool(query.authority_alias_terms) != bool(
            query.authority_alias_ids
        ) or any(
            item not in normalized for item in query.authority_alias_terms
        ):
            raise FullTextContractError(
                "retained full-text authority aliases differ from request text"
            )
        expected_lucene = _build_lucene_query(
            normalized_text=normalized,
            latin_terms=latin,
            han_bigrams=han,
            formal_tokens=formal,
            authority_alias_terms=query.authority_alias_terms,
        )
        if query.lucene_query != expected_lucene:
            raise FullTextContractError(
                "retained full-text Lucene expression differs"
            )

    def normalize(
        self,
        *,
        surface_text: str,
        language_mode: FullTextLanguageMode,
        query_valid_time: UtcTimestamp,
        authority_aliases: tuple[AuthorityAliasTerm, ...] = (),
    ) -> NormalizedFullTextQuery:
        if not isinstance(surface_text, str) or not surface_text:
            raise FullTextContractError("full-text surface query is required")
        if not isinstance(language_mode, FullTextLanguageMode):
            raise FullTextContractError("full-text language mode must be typed")
        if not isinstance(query_valid_time, UtcTimestamp):
            raise FullTextContractError("normalizer query-valid time must be typed")
        if not isinstance(authority_aliases, tuple):
            raise FullTextContractError(
                "authority aliases must be an immutable typed tuple"
            )
        if len(authority_aliases) > 32 or any(
            not isinstance(item, AuthorityAliasTerm)
            for item in authority_aliases
        ):
            raise FullTextContractError(
                "authority aliases exceed their typed bound"
            )

        collapsed, normalized, latin, han, formal = (
            _normalization_core(surface_text)
        )

        alias_pairs: list[tuple[str, str]] = []
        for alias in authority_aliases:
            if not alias.is_eligible_at(query_valid_time):
                continue
            normalized_alias = _casefold_latin(
                _collapse_nfkc(alias.surface_text)
            )
            if normalized_alias != alias.normalized_text:
                raise FullTextContractError(
                    "authority alias normalized text differs from reviewed normalizer"
                )
            if normalized_alias in normalized:
                alias_pairs.append((alias.alias_id, normalized_alias))

        alias_pairs = sorted(set(alias_pairs))
        authority_alias_ids = tuple(sorted({item[0] for item in alias_pairs}))
        authority_alias_terms = tuple(sorted({item[1] for item in alias_pairs}))
        if len(authority_alias_ids) > 32:
            raise FullTextContractError(
                "eligible authority aliases exceed their bound"
            )

        lucene_query = _build_lucene_query(
            normalized_text=normalized,
            latin_terms=latin,
            han_bigrams=han,
            formal_tokens=formal,
            authority_alias_terms=authority_alias_terms,
        )

        return NormalizedFullTextQuery(
            surface_text=collapsed,
            normalized_text=normalized,
            language_mode=language_mode,
            latin_terms=latin,
            han_bigrams=han,
            formal_tokens=formal,
            authority_alias_terms=authority_alias_terms,
            authority_alias_ids=authority_alias_ids,
            lucene_query=lucene_query,
            implementation_version=self.implementation_version,
            component_digest=self.component_digest,
        )


__all__ = ["BilingualSearchNormalizer"]
