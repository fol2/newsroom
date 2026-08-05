from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 contract-domain anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_contracts.py",
        "from newsroom.authority.canonical import (\n    canonical_json_bytes,\n",
        "from newsroom.authority.canonical import (\n    MAX_SAFE_INTEGER,\n    canonical_json_bytes,\n",
    )
    replace_once(
        "newsroom/increment5/fulltext_contracts.py",
        """def _non_negative(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FullTextContractError(f"{field} must be a non-negative integer")
    return value
""",
        """def _non_negative(value: int, *, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_SAFE_INTEGER
    ):
        raise FullTextContractError(
            f"{field} must be a canonical non-negative integer"
        )
    return value
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_contracts.py",
        """        if self.lifecycle in {"TOMBSTONED", "RETIRED", "REJECTED", "REVOKED"}:
            return BranchExclusionReason.TOMBSTONED
        if (
""",
        """        if self.lifecycle in {
            "TOMBSTONED",
            "RETIRED",
            "REJECTED",
            "REVOKED",
            "MERGED",
            "SPLIT",
            "REVERSED",
        }:
            return BranchExclusionReason.TOMBSTONED
        if self.lifecycle != "ACTIVE":
            return BranchExclusionReason.STALE_SOURCE_VERSION
        if (
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        "from newsroom.authority.canonical import (\n    canonical_json_bytes,\n",
        "from newsroom.authority.canonical import (\n    CanonicalizationError,\n    canonical_json_bytes,\n",
    )
    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        "from newsroom.retrieval.models import RetrievalBranch, RetrievalBranchHit\n",
        "from newsroom.retrieval.models import (\n"
        "    RetrievalBranch,\n"
        "    RetrievalBranchHit,\n"
        "    RetrievalContractError,\n"
        ")\n",
    )
    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        """        if self.authority_read_count == 1 and (
            self.snapshot is None or self.authority_view_digest is None
        ):
            raise FullTextContractError(
                "full-text authority read requires snapshot and view identity"
            )
""",
        """        if self.authority_read_count == 1 and (
            self.snapshot is None or self.authority_view_digest is None
        ):
            raise FullTextContractError(
                "full-text authority read requires snapshot and view identity"
            )
        if self.neo4j_read_count and (
            self.authority_read_count != 1 or self.normalized_query is None
        ):
            raise FullTextContractError(
                "full-text Neo4j evidence requires canonical authority and query evidence"
            )
        if self.exclusions and self.neo4j_read_count != 3:
            raise FullTextContractError(
                "full-text exclusions require a completed graph query"
            )
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        """        snapshot_value = value["snapshot"]
        normalized_value = value["normalized_query"]
        hits = tuple(
            RetrievalBranchHit(
                branch=RetrievalBranch(str(item["branch"])),
                query_id=str(item["query_id"]),
                query_digest=str(item["query_digest"]),
                rank=int(item["rank"]),
                raw_score=str(item["raw_score"]),
                result_key=str(item["result_key"]),
                dependency_root_id=str(item["dependency_root_id"]),
                passage_id=(
                    None
                    if item["passage_id"] is None
                    else str(item["passage_id"])
                ),
                trust_scope=TrustScope(str(item["trust_scope"])),
                source_kind=str(item["source_kind"]),
                source_identity=str(item["source_identity"]),
            )
            for item in value["hits"]
        )
        exclusions = tuple(
            BranchExclusion(
                authority_kind=str(item["authority_kind"]),
                authority_id=str(item["authority_id"]),
                reason=BranchExclusionReason(str(item["reason"])),
            )
            for item in value["exclusions"]
        )
        receipt = cls(
            receipt_id=BranchReceiptId.parse(str(value["receipt_id"])),
            request_id=BranchRequestId.parse(str(value["request_id"])),
            request_digest=str(value["request_digest"]),
            contract_digest=str(value["contract_digest"]),
            policy_id=str(value["policy_id"]),
            fulltext_component_digest=str(
                value["fulltext_component_digest"]
            ),
            normalization_component_digest=str(
                value["normalization_component_digest"]
            ),
            implementation_version=str(value["implementation_version"]),
            outcome=BranchOutcome(str(value["outcome"])),
            reason_code=str(value["reason_code"]),
            started_at=UtcTimestamp.parse(str(value["started_at"])),
            completed_at=UtcTimestamp.parse(str(value["completed_at"])),
            elapsed_ms=int(value["elapsed_ms"]),
            snapshot=(
                None
                if snapshot_value is None
                else FullTextProjectionSnapshot.from_canonical_value(
                    snapshot_value
                )
            ),
            authority_view_digest=(
                None
                if value["authority_view_digest"] is None
                else str(value["authority_view_digest"])
            ),
            normalized_query=(
                None
                if normalized_value is None
                else NormalizedFullTextQuery.from_canonical_value(
                    normalized_value
                )
            ),
            hits=hits,
            exclusions=exclusions,
            authority_read_count=int(value["authority_read_count"]),
            neo4j_read_count=int(value["neo4j_read_count"]),
            external_call_count=int(value["external_call_count"]),
            gross_cost_microunits=int(value["gross_cost_microunits"]),
            authority_effect=str(value["authority_effect"]),
            hybrid_result_claimed=bool(value["hybrid_result_claimed"]),
            projection_text_factual_use_allowed=bool(
                value["projection_text_factual_use_allowed"]
            ),
        )
        if receipt.canonical_bytes != raw:
            raise FullTextContractError(
                "stored full-text receipt is not canonical"
            )
        return receipt
""",
        """        try:
            snapshot_value = value["snapshot"]
            normalized_value = value["normalized_query"]
            hits = tuple(
                RetrievalBranchHit(
                    branch=RetrievalBranch(str(item["branch"])),
                    query_id=str(item["query_id"]),
                    query_digest=str(item["query_digest"]),
                    rank=int(item["rank"]),
                    raw_score=str(item["raw_score"]),
                    result_key=str(item["result_key"]),
                    dependency_root_id=str(item["dependency_root_id"]),
                    passage_id=(
                        None
                        if item["passage_id"] is None
                        else str(item["passage_id"])
                    ),
                    trust_scope=TrustScope(str(item["trust_scope"])),
                    source_kind=str(item["source_kind"]),
                    source_identity=str(item["source_identity"]),
                )
                for item in value["hits"]
            )
            exclusions = tuple(
                BranchExclusion(
                    authority_kind=str(item["authority_kind"]),
                    authority_id=str(item["authority_id"]),
                    reason=BranchExclusionReason(str(item["reason"])),
                )
                for item in value["exclusions"]
            )
            receipt = cls(
                receipt_id=BranchReceiptId.parse(str(value["receipt_id"])),
                request_id=BranchRequestId.parse(str(value["request_id"])),
                request_digest=str(value["request_digest"]),
                contract_digest=str(value["contract_digest"]),
                policy_id=str(value["policy_id"]),
                fulltext_component_digest=str(
                    value["fulltext_component_digest"]
                ),
                normalization_component_digest=str(
                    value["normalization_component_digest"]
                ),
                implementation_version=str(value["implementation_version"]),
                outcome=BranchOutcome(str(value["outcome"])),
                reason_code=str(value["reason_code"]),
                started_at=UtcTimestamp.parse(str(value["started_at"])),
                completed_at=UtcTimestamp.parse(str(value["completed_at"])),
                elapsed_ms=int(value["elapsed_ms"]),
                snapshot=(
                    None
                    if snapshot_value is None
                    else FullTextProjectionSnapshot.from_canonical_value(
                        snapshot_value
                    )
                ),
                authority_view_digest=(
                    None
                    if value["authority_view_digest"] is None
                    else str(value["authority_view_digest"])
                ),
                normalized_query=(
                    None
                    if normalized_value is None
                    else NormalizedFullTextQuery.from_canonical_value(
                        normalized_value
                    )
                ),
                hits=hits,
                exclusions=exclusions,
                authority_read_count=int(value["authority_read_count"]),
                neo4j_read_count=int(value["neo4j_read_count"]),
                external_call_count=int(value["external_call_count"]),
                gross_cost_microunits=int(value["gross_cost_microunits"]),
                authority_effect=str(value["authority_effect"]),
                hybrid_result_claimed=bool(value["hybrid_result_claimed"]),
                projection_text_factual_use_allowed=bool(
                    value["projection_text_factual_use_allowed"]
                ),
            )
            if receipt.canonical_bytes != raw:
                raise FullTextContractError(
                    "stored full-text receipt is not canonical"
                )
            return receipt
        except FullTextContractError:
            raise
        except (
            CanonicalizationError,
            RetrievalContractError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise FullTextContractError(
                "stored full-text receipt fields differ from the canonical contract"
            ) from exc
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        """    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise FullTextContractError(
            "stored full-text receipt must use canonical JSON"
        )
""",
        """    try:
        canonical = canonical_json_bytes(value)
    except CanonicalizationError as exc:
        raise FullTextContractError(
            "stored full-text receipt is outside canonical JSON"
        ) from exc
    if not isinstance(value, dict) or canonical != raw:
        raise FullTextContractError(
            "stored full-text receipt must use canonical JSON"
        )
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        "from newsroom.authority.canonical import digest_bytes\n",
        "from newsroom.authority.canonical import digest_bytes\n"
        "from newsroom.increment5.branch_contracts import BranchRequestId\n",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """                        expected_request_digest=request.request_digest,
                        expected_request_bytes=request.canonical_bytes,
""",
        """                        expected_request_id=request.request_id,
                        expected_request_digest=request.request_digest,
                        expected_request_bytes=request.canonical_bytes,
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """            receipt = self._verified_receipt(
                row,
                expected_request_digest=request.request_digest,
                expected_request_bytes=request.canonical_bytes,
            )
""",
        """            receipt = self._verified_receipt(
                row,
                expected_request_id=request.request_id,
                expected_request_digest=request.request_digest,
                expected_request_bytes=request.canonical_bytes,
            )
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """        *,
        expected_request_digest: str,
        expected_request_bytes: bytes,
""",
        """        *,
        expected_request_id: BranchRequestId,
        expected_request_digest: str,
        expected_request_bytes: bytes,
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """        if receipt.request_digest != expected_request_digest:
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )
""",
        """        if (
            receipt.request_id != expected_request_id
            or receipt.request_digest != expected_request_digest
        ):
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        "import pytest\n\n",
        "import pytest\n\n"
        "from newsroom.authority.canonical import canonical_json_bytes, digest_bytes\n",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    noncanonical_view = authority_view(
        projection_snapshot=replace(
            snapshot(),
            contiguous_ledger_seq=9_007_199_254_740_992,
        )
    )
""",
        """    corrupt_snapshot = snapshot()
    object.__setattr__(
        corrupt_snapshot,
        "contiguous_ledger_seq",
        9_007_199_254_740_992,
    )
    noncanonical_view = authority_view(
        projection_snapshot=corrupt_snapshot
    )
""",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_current_rights_and_lifecycle_exclusions_are_explicit(
""",
        """@pytest.mark.parametrize(
    ("lifecycle", "reason"),
    [
        ("HELD", BranchExclusionReason.STALE_SOURCE_VERSION),
        ("UNRESOLVED", BranchExclusionReason.STALE_SOURCE_VERSION),
        ("PROPOSED", BranchExclusionReason.STALE_SOURCE_VERSION),
        ("MERGED", BranchExclusionReason.TOMBSTONED),
        ("SPLIT", BranchExclusionReason.TOMBSTONED),
        ("REVERSED", BranchExclusionReason.TOMBSTONED),
    ],
)
def test_every_nonactive_passage_lifecycle_is_excluded(
    lifecycle: str,
    reason: BranchExclusionReason,
) -> None:
    binding = replace(bindings()[1], lifecycle=lifecycle)
    assert binding.exclusion_at(NOW) is reason


def test_current_rights_and_lifecycle_exclusions_are_explicit(
""",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    with pytest.raises(FullTextContractError, match="response byte limit"):
        request(response_byte_limit=262_145)
""",
        """    with pytest.raises(FullTextContractError, match="response byte limit"):
        request(response_byte_limit=262_145)
    with pytest.raises(FullTextContractError, match="canonical non-negative"):
        request(minimum_watermark=9_007_199_254_740_992)
    with pytest.raises(FullTextContractError, match="canonical non-negative"):
        snapshot(index_document_count=9_007_199_254_740_992)
""",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_request_rejects_oversized_and_unbounded_controls() -> None:
""",
        """def test_journal_rejects_rebound_request_identity(tmp_path: Path) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    value["request_id"] = "00000000-0000-4000-8000-000000005299"
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


def test_journal_translates_canonical_malformed_receipt_fields(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    value["fulltext_component_digest"] = "not-a-digest"
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

    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="unavailable or inconsistent",
    ):
        restarted.retrieve(request())


def test_request_rejects_oversized_and_unbounded_controls() -> None:
""",
    )


if __name__ == "__main__":
    main()
