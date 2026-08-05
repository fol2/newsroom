from __future__ import annotations

import pytest

from newsroom.increment5.fulltext_contracts import (
    FullTextContractError,
    FullTextLanguageMode,
)
from newsroom.increment5.fulltext_normalizer import BilingualSearchNormalizer

from .increment5b2_helpers import NOW, aliases


def test_normalizer_canonicalizes_english_without_caller_lucene_syntax() -> None:
    normalizer = BilingualSearchNormalizer()
    result = normalizer.normalize(
        surface_text='  SYNTHETIC\r\nAuthority (deadline): "27/03/2042"  ',
        language_mode=FullTextLanguageMode.EN_GB,
        query_valid_time=NOW,
        authority_aliases=aliases(),
    )

    assert result.normalized_text == (
        'synthetic authority (deadline): "27/03/2042"'
    )
    assert result.latin_terms == (
        "authority",
        "deadline",
        "synthetic",
    )
    assert "27/03/2042" in result.formal_tokens
    assert result.authority_alias_ids == ("alias-synthetic-authority",)
    assert result.authority_alias_terms == ("synthetic authority",)
    assert 'retrieval_text:"synthetic authority \\(deadline\\)\\: ' in result.lucene_query
    assert "\\/" in result.lucene_query
    assert "\\(" in result.lucene_query
    assert '\\"' in result.lucene_query
    assert result.lucene_query == " OR ".join(
        sorted(result.lucene_query.split(" OR "))
    )


def test_normalizer_preserves_traditional_han_and_emits_exact_bigrams() -> None:
    result = BilingualSearchNormalizer().normalize(
        surface_text="合成網上平台 截止日期 二〇四二年三月二十七日",
        language_mode=FullTextLanguageMode.ZH_HANT_HK,
        query_valid_time=NOW,
    )

    assert "網上" in result.han_bigrams
    assert "平台" in result.han_bigrams
    assert "截止" in result.han_bigrams
    assert "合成網上平台" in result.normalized_text
    assert "网上" not in result.normalized_text
    assert not result.authority_alias_ids


def test_normalizer_mixed_language_is_deterministic_and_nfkc() -> None:
    normalizer = BilingualSearchNormalizer()
    first = normalizer.normalize(
        surface_text="ＡＢＣ １２-３４ 合成網上平台",
        language_mode=FullTextLanguageMode.MIXED_EN_GB_ZH_HANT_HK,
        query_valid_time=NOW,
    )
    second = normalizer.normalize(
        surface_text="ABC 12-34 合成網上平台",
        language_mode=FullTextLanguageMode.MIXED_EN_GB_ZH_HANT_HK,
        query_valid_time=NOW,
    )

    assert first.normalized_text == "abc 12-34 合成網上平台"
    assert first.query_digest == second.query_digest
    assert first.formal_tokens == ("12-34",)
    assert first.latin_terms == ("abc",)


def test_normalizer_uses_only_current_typed_authority_aliases() -> None:
    result = BilingualSearchNormalizer().normalize(
        surface_text="Synthetic Authority and Expired Authority",
        language_mode=FullTextLanguageMode.EN_GB,
        query_valid_time=NOW,
        authority_aliases=aliases(),
    )

    assert result.authority_alias_ids == ("alias-synthetic-authority",)
    assert result.authority_alias_terms == ("synthetic authority",)
    assert "expired authority" not in result.authority_alias_terms


def test_normalizer_requires_ascii_alias_term_boundaries() -> None:
    base = aliases()[1]
    ai_alias = type(base)(
        alias_id="alias-ai",
        surface_text="AI",
        normalized_text="ai",
        valid_from=base.valid_from,
        valid_until=base.valid_until,
        rights_current=True,
        lifecycle="ACTIVE",
    )

    false_positive = BilingualSearchNormalizer().normalize(
        surface_text="Paid leave policy",
        language_mode=FullTextLanguageMode.EN_GB,
        query_valid_time=NOW,
        authority_aliases=(ai_alias,),
    )
    exact_mention = BilingualSearchNormalizer().normalize(
        surface_text="AI policy",
        language_mode=FullTextLanguageMode.EN_GB,
        query_valid_time=NOW,
        authority_aliases=(ai_alias,),
    )

    assert false_positive.authority_alias_ids == ()
    assert false_positive.authority_alias_terms == ()
    assert 'authority_aliases:"ai"' not in false_positive.lucene_query
    assert exact_mention.authority_alias_ids == ("alias-ai",)
    assert exact_mention.authority_alias_terms == ("ai",)
    assert 'authority_aliases:"ai"' in exact_mention.lucene_query


def test_normalizer_deduplicates_multiple_authority_ids_for_one_term() -> None:
    base = aliases()[1]
    duplicate = type(base)(
        alias_id="alias-synthetic-authority-2",
        surface_text=base.surface_text,
        normalized_text=base.normalized_text,
        valid_from=base.valid_from,
        valid_until=base.valid_until,
        rights_current=base.rights_current,
        lifecycle=base.lifecycle,
    )
    result = BilingualSearchNormalizer().normalize(
        surface_text="Synthetic Authority",
        language_mode=FullTextLanguageMode.EN_GB,
        query_valid_time=NOW,
        authority_aliases=tuple(sorted((base, duplicate), key=lambda item: item.alias_id)),
    )

    assert result.authority_alias_ids == (
        "alias-synthetic-authority",
        "alias-synthetic-authority-2",
    )
    assert result.authority_alias_terms == ("synthetic authority",)


@pytest.mark.parametrize(
    "surface",
    (
        "",
        " ",
        "\r\n\t",
        "x" * 16_385,
    ),
)
def test_normalizer_rejects_empty_or_oversized_query(surface: str) -> None:
    with pytest.raises(FullTextContractError):
        BilingualSearchNormalizer().normalize(
            surface_text=surface,
            language_mode=FullTextLanguageMode.EN_GB,
            query_valid_time=NOW,
        )


def test_normalizer_rejects_alias_bytes_from_another_normalizer() -> None:
    alias = aliases()[1]
    mismatched = type(alias)(
        alias_id=alias.alias_id,
        surface_text=alias.surface_text,
        normalized_text="another normalized value",
        valid_from=alias.valid_from,
        valid_until=alias.valid_until,
        rights_current=True,
        lifecycle="ACTIVE",
    )
    with pytest.raises(
        FullTextContractError,
        match="differs from reviewed normalizer",
    ):
        BilingualSearchNormalizer().normalize(
            surface_text="Synthetic Authority",
            language_mode=FullTextLanguageMode.EN_GB,
            query_valid_time=NOW,
            authority_aliases=(mismatched,),
        )
