from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 final evidence-binding anchor differs for {relative_path}: "
            f"count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_regex_once(
    relative_path: str,
    pattern: str,
    replacement: str,
) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(
            f"5B2 final evidence-binding regex differs for {relative_path}: "
            f"count={count}"
        )
    path.write_text(updated, encoding="utf-8")


def write_new(relative_path: str, content: str) -> None:
    path = ROOT / relative_path
    if path.exists():
        raise SystemExit(f"5B2 final evidence-binding path already exists: {relative_path}")
    path.write_text(content, encoding="utf-8")


def main() -> None:
    write_new(
        "newsroom/increment5/fulltext_snapshot_policy.py",
        """\"\"\"Shared deterministic snapshot policy for the Increment 5B2 branch.\"\"\"

from __future__ import annotations

from newsroom.increment5.branch_contracts import BranchOutcome
from newsroom.projection.models import ProjectionGenerationState
from newsroom.projection.neo4j.models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
)

from .fulltext_contracts import (
    FULLTEXT_ANALYZER,
    FULLTEXT_PROVIDER,
    FullTextBranchRequest,
    FullTextContractError,
    FullTextIndexState,
    FullTextProjectionSnapshot,
)


def fulltext_snapshot_failure(
    request: FullTextBranchRequest,
    snapshot: FullTextProjectionSnapshot,
) -> tuple[BranchOutcome, str] | None:
    \"\"\"Return the exact fail-closed outcome for one retained projection snapshot.\"\"\"

    if not isinstance(request, FullTextBranchRequest):
        raise FullTextContractError("full-text snapshot policy request must be typed")
    if not isinstance(snapshot, FullTextProjectionSnapshot):
        raise FullTextContractError("full-text snapshot policy value must be typed")
    if snapshot.generation_state is not ProjectionGenerationState.ACTIVE:
        return BranchOutcome.STALE, "GENERATION_NOT_ACTIVE"
    if snapshot.generation_id != request.expected_generation_id:
        return BranchOutcome.STALE, "GENERATION_MISMATCH"
    if (
        snapshot.generation_identity_digest
        != request.expected_generation_identity_digest
    ):
        return BranchOutcome.STALE, "GENERATION_IDENTITY_MISMATCH"
    if (
        snapshot.fulltext_component_digest
        != request.fulltext_component_digest
        or snapshot.normalization_component_digest
        != request.normalization_component_digest
    ):
        return BranchOutcome.STALE, "GENERATION_COMPONENT_MISMATCH"
    if snapshot.rights_manifest_digest != request.expected_rights_manifest_digest:
        return BranchOutcome.STALE, "RIGHTS_MANIFEST_MISMATCH"
    if snapshot.contiguous_ledger_seq < request.minimum_watermark:
        return BranchOutcome.STALE, "PROJECTION_WATERMARK_STALE"
    if snapshot.open_gap_count:
        return BranchOutcome.INCOMPLETE, "PROJECTION_GAPS_OPEN"
    if snapshot.dead_letter_count:
        return BranchOutcome.INCOMPLETE, "PROJECTION_DEAD_LETTERS_PRESENT"
    if snapshot.validation_recorded_at.value > request.serving_time.value:
        return BranchOutcome.INCOMPLETE, "PROJECTION_TIME_INVALID"
    age_seconds = (
        request.serving_time.value - snapshot.validation_recorded_at.value
    ).total_seconds()
    if (
        request.serving_time.value > snapshot.freshness_deadline.value
        or age_seconds > request.max_projection_age_seconds
    ):
        return BranchOutcome.STALE, "PROJECTION_FRESHNESS_STALE"
    if snapshot.index_state is FullTextIndexState.POPULATING:
        return BranchOutcome.INCOMPLETE, "FULLTEXT_INDEX_POPULATING"
    if snapshot.index_state in {
        FullTextIndexState.FAILED,
        FullTextIndexState.MISSING,
    }:
        return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_UNAVAILABLE"
    if (
        snapshot.provider != FULLTEXT_PROVIDER
        or snapshot.analyzer != FULLTEXT_ANALYZER
        or snapshot.server_version != NEO4J_B2_SERVER_VERSION
        or snapshot.driver_version != NEO4J_B2_DRIVER_VERSION
    ):
        return BranchOutcome.UNAVAILABLE, "COMPONENT_INCOMPATIBLE"
    return None


__all__ = ["fulltext_snapshot_failure"]
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """from .fulltext_journal import FullTextJournalResult, FullTextReceiptJournal
from .fulltext_normalizer import BilingualSearchNormalizer
from .fulltext_receipts import FullTextBranchReceipt
""",
        """from .fulltext_journal import FullTextJournalResult, FullTextReceiptJournal
from .fulltext_normalizer import BilingualSearchNormalizer
from .fulltext_receipts import FullTextBranchReceipt
from .fulltext_snapshot_policy import fulltext_snapshot_failure
""",
    )

    replace_regex_once(
        "newsroom/increment5/fulltext_retriever.py",
        r"""
    @staticmethod
    def _snapshot_failure\(
        request: FullTextBranchRequest,
        view: FullTextAuthorityView,
    \) -> tuple\[BranchOutcome, str\] \| None:
.*?
    @staticmethod
    def _require_compatibility""",
        """
    @staticmethod
    def _snapshot_failure(
        request: FullTextBranchRequest,
        view: FullTextAuthorityView,
    ) -> tuple[BranchOutcome, str] | None:
        return fulltext_snapshot_failure(request, view.snapshot)

    @staticmethod
    def _require_compatibility""",
    )

    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """from .fulltext_normalizer import BilingualSearchNormalizer
from .fulltext_receipts import FullTextBranchReceipt
""",
        """from .fulltext_normalizer import BilingualSearchNormalizer
from .fulltext_receipts import FullTextBranchReceipt
from .fulltext_snapshot_policy import fulltext_snapshot_failure
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """        if receipt.normalized_query is not None:
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
        """        if receipt.snapshot is not None:
            snapshot_failure = fulltext_snapshot_failure(
                request,
                receipt.snapshot,
            )
            if snapshot_failure is not None:
                expected_outcome, expected_reason = snapshot_failure
                if (
                    receipt.outcome is not expected_outcome
                    or receipt.reason_code != expected_reason
                    or receipt.normalized_query is not None
                    or receipt.neo4j_read_count != 0
                    or receipt.hits
                    or receipt.exclusions
                ):
                    raise FullTextReceiptJournalError(
                        "stored full-text receipt request binding differs"
                    )
                return
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
        "newsroom/increment5/fulltext_normalizer.py",
        """def _bounded_sorted(values: set[str], *, field: str) -> tuple[str, ...]:
    if len(values) > FULLTEXT_MAX_TERMS:
        raise FullTextContractError(f"{field} exceeds the reviewed term bound")
    return tuple(sorted(values))


def _normalization_core(
""",
        """def _bounded_sorted(values: set[str], *, field: str) -> tuple[str, ...]:
    if len(values) > FULLTEXT_MAX_TERMS:
        raise FullTextContractError(f"{field} exceeds the reviewed term bound")
    return tuple(sorted(values))


def _ascii_word_edge(character: str) -> bool:
    return character.isascii() and character.isalnum()


def _alias_is_mentioned(
    normalized_text: str,
    normalized_alias: str,
) -> bool:
    left = r"(?<![a-z0-9])" if _ascii_word_edge(normalized_alias[0]) else ""
    right = r"(?![a-z0-9])" if _ascii_word_edge(normalized_alias[-1]) else ""
    return re.search(
        f"{left}{re.escape(normalized_alias)}{right}",
        normalized_text,
    ) is not None


def _normalization_core(
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_normalizer.py",
        """        if bool(query.authority_alias_terms) != bool(
            query.authority_alias_ids
        ) or any(
            item not in normalized for item in query.authority_alias_terms
        ):
""",
        """        if bool(query.authority_alias_terms) != bool(
            query.authority_alias_ids
        ) or any(
            not _alias_is_mentioned(normalized, item)
            for item in query.authority_alias_terms
        ):
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_normalizer.py",
        """            if normalized_alias in normalized:
                alias_pairs.append((alias.alias_id, normalized_alias))
""",
        """            if _alias_is_mentioned(normalized, normalized_alias):
                alias_pairs.append((alias.alias_id, normalized_alias))
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_normalizer.py",
        """def test_normalizer_deduplicates_multiple_authority_ids_for_one_term() -> None:
""",
        """def test_normalizer_requires_ascii_alias_term_boundaries() -> None:
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
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("language_mode", "EN_GB"),
""",
        """@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("generation_state", "RETIRED"),
        (
            "generation_id",
            "00000000-0000-4000-8000-000000005299",
        ),
        (
            "generation_identity_digest",
            digest("another-generation-identity"),
        ),
        (
            "fulltext_component_digest",
            digest("another-snapshot-fulltext-component"),
        ),
        (
            "normalization_component_digest",
            digest("another-snapshot-normalization-component"),
        ),
        (
            "rights_manifest_digest",
            digest("another-rights-manifest"),
        ),
        ("contiguous_ledger_seq", 41),
        ("open_gap_count", 1),
        ("dead_letter_count", 1),
        (
            "freshness_deadline",
            "2042-03-12T11:45:00.000000Z",
        ),
        ("index_state", "FAILED"),
    ],
)
def test_journal_rejects_snapshot_rebound_from_request(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    assert value["snapshot"] is not None
    value["snapshot"][field] = replacement
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
    ("field", "replacement"),
    [
        ("language_mode", "EN_GB"),
""",
    )


if __name__ == "__main__":
    main()
