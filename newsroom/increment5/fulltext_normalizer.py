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


class BilingualSearchNormalizer:
    """NFKC bilingual normalization with no transliteration or script conversion."""

    implementation_version = "bilingual-search-normalizer-v1"
    component_digest = NORMALIZATION_COMPONENT_DIGEST

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

        collapsed = _collapse_nfkc(surface_text)
        normalized = _casefold_latin(collapsed)

        formal_tokens = {
            match.group(0).casefold()
            for match in _FORMAL_TOKEN.finditer(normalized)
        }
        latin_terms = {
            match.group(0).casefold()
            for match in _LATIN_TERM.finditer(normalized)
            if any("a" <= character <= "z" for character in match.group(0).casefold())
        }
        han_bigrams: set[str] = set()
        for match in _HAN_SEQUENCE.finditer(normalized):
            sequence = match.group(0)
            han_bigrams.update(
                sequence[index : index + 2]
                for index in range(max(0, len(sequence) - 1))
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

        latin = _bounded_sorted(latin_terms, field="latin_terms")
        han = _bounded_sorted(han_bigrams, field="han_bigrams")
        formal = _bounded_sorted(formal_tokens, field="formal_tokens")

        clauses = {_field_clause("retrieval_text", normalized)}
        clauses.update(_field_clause("latin_terms", item) for item in latin)
        clauses.update(_field_clause("han_bigrams", item) for item in han)
        clauses.update(_field_clause("formal_tokens", item) for item in formal)
        clauses.update(
            _field_clause("authority_aliases", item)
            for item in authority_alias_terms
        )
        lucene_query = " OR ".join(sorted(clauses))

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
