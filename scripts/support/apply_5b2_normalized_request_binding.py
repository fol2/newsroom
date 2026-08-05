from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 normalized-request anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_normalizer.py",
        """def _bounded_sorted(values: set[str], *, field: str) -> tuple[str, ...]:
    if len(values) > FULLTEXT_MAX_TERMS:
        raise FullTextContractError(f"{field} exceeds the reviewed term bound")
    return tuple(sorted(values))


class BilingualSearchNormalizer:
""",
        """def _bounded_sorted(values: set[str], *, field: str) -> tuple[str, ...]:
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
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_normalizer.py",
        """    component_digest = NORMALIZATION_COMPONENT_DIGEST

    def normalize(
""",
        """    component_digest = NORMALIZATION_COMPONENT_DIGEST

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
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_normalizer.py",
        """        collapsed = _collapse_nfkc(surface_text)
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
""",
        """        collapsed, normalized, latin, han, formal = (
            _normalization_core(surface_text)
        )
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_normalizer.py",
        """        latin = _bounded_sorted(latin_terms, field="latin_terms")
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
""",
        """        lucene_query = _build_lucene_query(
            normalized_text=normalized,
            latin_terms=latin,
            han_bigrams=han,
            formal_tokens=formal,
            authority_alias_terms=authority_alias_terms,
        )
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """from .fulltext_contracts import FullTextBranchRequest, FullTextContractError
from .fulltext_receipts import FullTextBranchReceipt
""",
        """from .fulltext_contracts import FullTextBranchRequest, FullTextContractError
from .fulltext_normalizer import BilingualSearchNormalizer
from .fulltext_receipts import FullTextBranchReceipt
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """        if (
            receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
            or receipt.contract_digest != request.contract_digest
            or receipt.policy_id != request.policy_id
            or receipt.fulltext_component_digest
            != request.fulltext_component_digest
            or receipt.normalization_component_digest
            != request.normalization_component_digest
            or receipt.started_at != request.serving_time
            or receipt.completed_at != request.serving_time
        ):
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )
""",
        """        if (
            receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
            or receipt.contract_digest != request.contract_digest
            or receipt.policy_id != request.policy_id
            or receipt.fulltext_component_digest
            != request.fulltext_component_digest
            or receipt.normalization_component_digest
            != request.normalization_component_digest
            or receipt.started_at != request.serving_time
            or receipt.completed_at != request.serving_time
        ):
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )
        if receipt.normalized_query is not None:
            try:
                BilingualSearchNormalizer().validate_request_binding(
                    receipt.normalized_query,
                    surface_text=request.query_text,
                    language_mode=request.language_mode,
                )
            except FullTextContractError as exc:
                raise FullTextReceiptJournalError(
                    "stored full-text receipt request binding differs"
                ) from exc
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """@pytest.mark.parametrize(
    "changes",
    [
        {"contract_digest": digest("another-contract")},
""",
        """@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("language_mode", "en-GB"),
        ("lucene_query", 'retrieval_text:"another"'),
        ("implementation_version", "another-normalizer-version"),
        ("component_digest", digest("another-normalizer-component")),
    ],
)
def test_journal_rejects_normalized_query_rebound_from_request(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    assert value["normalized_query"] is not None
    value["normalized_query"][field] = replacement
    rebound_digest = digest_bytes(
        canonical_json_bytes(value["normalized_query"])
    )
    for hit in value["hits"]:
        hit["query_digest"] = rebound_digest
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    before_calls = list(driver.calls)
    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="request binding differs",
    ):
        restarted.retrieve(request())
    assert driver.calls == before_calls


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_digest": digest("another-contract")},
""",
    )


if __name__ == "__main__":
    main()
