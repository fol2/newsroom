"""Independent Increment 5B2 full-text retriever over a bounded authority port."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import math
import time
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    validate_sha256_digest,
)
from newsroom.authority.neo4j_fulltext_reader import (
    Neo4jFullTextReadError,
    Neo4jFullTextReadRequest,
    Neo4jFullTextReadTimeout,
    Neo4jFullTextReader,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5.branch_contracts import (
    BRANCH_TIMEOUT_MS,
    BranchExclusion,
    BranchOutcome,
    BranchReceiptId,
)
from newsroom.projection.models import ProjectionGenerationState
from newsroom.projection.neo4j.models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
)
from newsroom.retrieval.models import (
    RetrievalBranch,
    RetrievalBranchHit,
    canonical_score,
)

from .fulltext_contracts import (
    FULLTEXT_ANALYZER,
    FULLTEXT_COMPONENT_DIGEST,
    FULLTEXT_INDEXED_FIELDS,
    FULLTEXT_POLICY_ID,
    FULLTEXT_PROVIDER,
    INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
    NORMALIZATION_COMPONENT_DIGEST,
    FullTextAuthorityView,
    FullTextBranchRequest,
    FullTextContractError,
    FullTextIndexState,
    NormalizedFullTextQuery,
)
from .fulltext_journal import FullTextJournalResult, FullTextReceiptJournal
from .fulltext_normalizer import BilingualSearchNormalizer
from .fulltext_receipts import FullTextBranchReceipt


_QUERY_ID = "increment5.fulltext.v1"


class FullTextRetrieverError(RuntimeError):
    """The independent full-text branch cannot safely execute."""


class FullTextRetriever:
    """Execute one fixed, read-only, generation-scoped full-text branch."""

    def __init__(
        self,
        *,
        graph_reader: Neo4jFullTextReader,
        journal: FullTextReceiptJournal,
        authority_view_provider: Callable[
            [FullTextBranchRequest], FullTextAuthorityView
        ],
        receipt_id_factory: Callable[[], BranchReceiptId] = BranchReceiptId.new,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        normalizer: BilingualSearchNormalizer | None = None,
    ) -> None:
        if not isinstance(graph_reader, Neo4jFullTextReader):
            raise TypeError("full-text graph reader must be typed")
        if not isinstance(journal, FullTextReceiptJournal):
            raise TypeError("full-text receipt journal must be typed")
        if not callable(authority_view_provider):
            raise TypeError("full-text authority view provider must be callable")
        if not callable(receipt_id_factory) or not callable(monotonic_ns):
            raise TypeError("full-text factories must be callable")
        if normalizer is not None and not isinstance(
            normalizer, BilingualSearchNormalizer
        ):
            raise TypeError("full-text normalizer must be typed")

        self._graph_reader = graph_reader
        self._journal = journal
        self._authority_view_provider = authority_view_provider
        self._receipt_id_factory = receipt_id_factory
        self._monotonic_ns = monotonic_ns
        self._normalizer = normalizer or BilingualSearchNormalizer()

    def retrieve(
        self, request: FullTextBranchRequest
    ) -> FullTextJournalResult:
        if not isinstance(request, FullTextBranchRequest):
            raise TypeError("full-text retrieval request must be typed")
        return self._journal.execute(
            request,
            lambda: self._execute(request),
        )

    def _execute(
        self, request: FullTextBranchRequest
    ) -> FullTextBranchReceipt:
        start_ns = self._monotonic_ns()
        if request.contract_digest != INCREMENT5_RETRIEVAL_CONTRACT_DIGEST:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="CONTRACT_MISMATCH",
            )
        if request.policy_id != FULLTEXT_POLICY_ID:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="POLICY_MISMATCH",
            )
        if (
            request.fulltext_component_digest != FULLTEXT_COMPONENT_DIGEST
            or request.normalization_component_digest
            != NORMALIZATION_COMPONENT_DIGEST
        ):
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="COMPONENT_MISMATCH",
            )
        if request.query_valid_time.value > request.serving_time.value:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="QUERY_VALID_TIME_IN_FUTURE",
            )
        if self._graph_reader.driver_version != NEO4J_B2_DRIVER_VERSION:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="DRIVER_INCOMPATIBLE",
            )

        authority_read_count = 0
        try:
            view = self._authority_view_provider(request)
            if not isinstance(view, FullTextAuthorityView):
                raise FullTextContractError(
                    "authority provider returned an untyped full-text view"
                )
            authority_read_count = 1
        except Exception:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_VIEW_UNAVAILABLE",
                authority_read_count=authority_read_count,
            )

        snapshot = view.snapshot
        view_digest = view.view_digest
        snapshot_failure = self._snapshot_failure(request, view)
        if snapshot_failure is not None:
            outcome, reason = snapshot_failure
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=outcome,
                reason_code=reason,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                authority_read_count=1,
            )

        try:
            normalized = self._normalizer.normalize(
                surface_text=request.query_text,
                language_mode=request.language_mode,
                query_valid_time=request.query_valid_time,
                authority_aliases=view.authority_aliases,
            )
        except FullTextContractError:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="QUERY_NORMALIZATION_REJECTED",
                snapshot=snapshot,
                authority_view_digest=view_digest,
                authority_read_count=1,
            )

        neo4j_reads = 0
        deadline_ns = start_ns + request.timeout_ms * 1_000_000
        try:
            component_result = self._graph_reader.read(
                Neo4jFullTextReadRequest.component(
                    timeout_ns=self._remaining_timeout_ns(
                        start_ns=start_ns,
                        deadline_ns=deadline_ns,
                    )
                )
            )
            neo4j_reads += component_result.read_count
            self._require_compatibility(component_result.component, snapshot)

            index_result = self._graph_reader.read(
                Neo4jFullTextReadRequest.index(
                    index_name=snapshot.index_name,
                    timeout_ns=self._remaining_timeout_ns(
                        start_ns=start_ns,
                        deadline_ns=deadline_ns,
                    ),
                )
            )
            neo4j_reads += index_result.read_count
            index_failure = self._index_failure(
                list(index_result.indexes),
                snapshot,
            )
            if index_failure is not None:
                outcome, reason = index_failure
                return self._receipt(
                    request,
                    start_ns=start_ns,
                    outcome=outcome,
                    reason_code=reason,
                    authority_read_count=1,
                    neo4j_read_count=neo4j_reads,
                    snapshot=snapshot,
                    authority_view_digest=view_digest,
                    normalized_query=normalized,
                )

            query_result = self._graph_reader.read(
                Neo4jFullTextReadRequest.query(
                    index_name=snapshot.index_name,
                    lucene_expression=normalized.lucene_query,
                    generation_id=snapshot.generation_id,
                    limit=request.result_limit + 1,
                    timeout_ns=self._remaining_timeout_ns(
                        start_ns=start_ns,
                        deadline_ns=deadline_ns,
                    ),
                )
            )
            neo4j_reads += query_result.read_count
            rows = list(query_result.rows)
        except Neo4jFullTextReadTimeout:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.INCOMPLETE,
                reason_code="QUERY_TIMEOUT",
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
            )
        except Neo4jFullTextReadError:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="NEO4J_READ_UNAVAILABLE",
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
            )
        except FullTextRetrieverError as exc:
            reason = str(exc)
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code=reason,
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
            )
        if len(rows) > request.result_limit:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.INCOMPLETE,
                reason_code="RESULT_BOUND_EXCEEDED",
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
            )

        try:
            hits, exclusions = self._parse_hits(
                rows,
                request=request,
                view=view,
                normalized=normalized,
            )
        except FullTextContractError:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="PROJECTION_INTEGRITY_ERROR",
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
            )

        if not hits and exclusions:
            reason = (
                "RIGHTS_BLOCKED"
                if any(
                    item.reason.value == "RIGHTS_NOT_CURRENT"
                    for item in exclusions
                )
                else "AUTHORITY_STATE_BLOCKED"
            )
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code=reason,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
                exclusions=exclusions,
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
            )

        return self._receipt(
            request,
            start_ns=start_ns,
            outcome=BranchOutcome.COMPLETE,
            reason_code=(
                "NO_MATCH"
                if not hits
                else "OK_WITH_EXCLUSIONS"
                if exclusions
                else "OK"
            ),
            snapshot=snapshot,
            authority_view_digest=view_digest,
            normalized_query=normalized,
            hits=hits,
            exclusions=exclusions,
            authority_read_count=1,
            neo4j_read_count=neo4j_reads,
        )

    def _remaining_timeout_ns(
        self,
        *,
        start_ns: int,
        deadline_ns: int,
    ) -> int:
        current_ns = self._monotonic_ns()
        if (
            isinstance(current_ns, bool)
            or not isinstance(current_ns, int)
            or current_ns < start_ns
        ):
            raise FullTextRetrieverError(
                "full-text monotonic clock moved backwards"
            )
        remaining_ns = deadline_ns - current_ns
        if remaining_ns <= 0:
            raise Neo4jFullTextReadTimeout(
                "full-text branch deadline is exhausted"
            )
        return remaining_ns

    @staticmethod
    def _snapshot_failure(
        request: FullTextBranchRequest,
        view: FullTextAuthorityView,
    ) -> tuple[BranchOutcome, str] | None:
        snapshot = view.snapshot
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
        if (
            snapshot.rights_manifest_digest
            != request.expected_rights_manifest_digest
        ):
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
            request.serving_time.value
            - snapshot.validation_recorded_at.value
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

    @staticmethod
    def _require_compatibility(
        record: Any,
        snapshot: Any,
    ) -> None:
        if record is None:
            raise FullTextRetrieverError("NEO4J_INCOMPATIBLE")
        try:
            version = str(record["version"])
            edition = str(record["edition"]).lower()
        except Exception:
            raise FullTextRetrieverError("NEO4J_INCOMPATIBLE") from None
        if (
            version != NEO4J_B2_SERVER_VERSION
            or version != snapshot.server_version
            or edition != "community"
        ):
            raise FullTextRetrieverError("NEO4J_INCOMPATIBLE")

    @staticmethod
    def _index_failure(
        rows: Any,
        snapshot: Any,
    ) -> tuple[BranchOutcome, str] | None:
        if not isinstance(rows, list):
            return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_MALFORMED"
        if not rows:
            return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_MISSING"
        if len(rows) != 1:
            return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_AMBIGUOUS"
        row = rows[0]
        if not isinstance(row, Mapping):
            try:
                row = dict(row)
            except Exception:
                return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_MALFORMED"
        try:
            name = str(row["name"])
            index_type = str(row["type"]).upper()
            state = str(row["state"]).upper()
            entity_type = str(row["entityType"]).upper()
            labels = tuple(str(item) for item in row["labelsOrTypes"])
            properties = tuple(str(item) for item in row["properties"])
            provider = str(row["indexProvider"])
            options = row["options"]
            if not isinstance(options, Mapping):
                options = dict(options)
            index_config = options["indexConfig"]
            if not isinstance(index_config, Mapping):
                index_config = dict(index_config)
            analyzer = str(index_config["fulltext.analyzer"])
            eventually_consistent = index_config[
                "fulltext.eventually_consistent"
            ]
        except Exception:
            return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_MALFORMED"
        if (
            name != snapshot.index_name
            or index_type != "FULLTEXT"
            or entity_type != "NODE"
            or labels != (snapshot.document_label,)
            or tuple(sorted(properties)) != FULLTEXT_INDEXED_FIELDS
            or provider != FULLTEXT_PROVIDER
            or analyzer != FULLTEXT_ANALYZER
            or eventually_consistent is not False
        ):
            return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_INCOMPATIBLE"
        if state == "POPULATING":
            return BranchOutcome.INCOMPLETE, "FULLTEXT_INDEX_POPULATING"
        if state != "ONLINE":
            return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_UNAVAILABLE"
        return None

    @staticmethod
    def _parse_hits(
        rows: list[Any],
        *,
        request: FullTextBranchRequest,
        view: FullTextAuthorityView,
        normalized: NormalizedFullTextQuery,
    ) -> tuple[
        tuple[RetrievalBranchHit, ...],
        tuple[BranchExclusion, ...],
    ]:
        parsed: list[
            tuple[str, str, str, float]
        ] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                try:
                    raw = dict(raw)
                except Exception:
                    raise FullTextContractError(
                        "full-text result row is malformed"
                    ) from None
            if set(raw) != {
                "generation_id",
                "passage_id",
                "document_digest",
                "language",
                "score",
            }:
                raise FullTextContractError(
                    "full-text result row differs from the fixed contract"
                )
            generation_id = str(raw["generation_id"])
            passage_id = str(raw["passage_id"])
            document_digest = str(raw["document_digest"])
            language = str(raw["language"])
            score_value = raw["score"]
            if generation_id != str(view.snapshot.generation_id):
                raise FullTextContractError(
                    "full-text result belongs to another generation"
                )
            if not passage_id or len(passage_id.encode("utf-8")) > 256:
                raise FullTextContractError(
                    "full-text result passage identity is invalid"
                )
            try:
                validate_sha256_digest(
                    document_digest,
                    field="fulltext_result_document_digest",
                )
            except CanonicalizationError:
                raise FullTextContractError(
                    "full-text result document digest is invalid"
                ) from None
            if language not in {"en-GB", "zh-HK"}:
                raise FullTextContractError(
                    "full-text result language is invalid"
                )
            if (
                isinstance(score_value, bool)
                or not isinstance(score_value, (int, float))
                or not math.isfinite(float(score_value))
                or float(score_value) < 0.0
            ):
                raise FullTextContractError(
                    "full-text result score is invalid"
                )
            parsed.append(
                (
                    passage_id,
                    document_digest,
                    language,
                    float(score_value),
                )
            )
        if len({item[0] for item in parsed}) != len(parsed):
            raise FullTextContractError(
                "full-text result passage identities are duplicated"
            )
        if parsed != sorted(
            parsed,
            key=lambda item: (-item[3], item[0]),
        ):
            raise FullTextContractError(
                "full-text results differ from deterministic ordering"
            )

        bindings = view.binding_by_passage_id
        hits: list[RetrievalBranchHit] = []
        exclusions: list[BranchExclusion] = []
        for passage_id, document_digest, language, score in parsed:
            binding = bindings.get(passage_id)
            if binding is None:
                raise FullTextContractError(
                    "full-text result lacks an authoritative document binding"
                )
            if (
                binding.provenance_digest != document_digest
                or binding.language != language
            ):
                raise FullTextContractError(
                    "full-text projection result differs from authority binding"
                )
            exclusion = binding.exclusion_at(request.query_valid_time)
            if exclusion is not None:
                exclusions.append(
                    BranchExclusion(
                        authority_kind="PASSAGE",
                        authority_id=passage_id,
                        reason=exclusion,
                    )
                )
                continue
            hits.append(
                RetrievalBranchHit(
                    branch=RetrievalBranch.FULL_TEXT,
                    query_id=_QUERY_ID,
                    query_digest=normalized.query_digest,
                    rank=len(hits) + 1,
                    raw_score=canonical_score(score),
                    result_key=f"FULL_TEXT:{passage_id}",
                    dependency_root_id=binding.dependency_root_id,
                    passage_id=passage_id,
                    trust_scope=binding.trust_scope,
                    source_kind="GOVERNED_PASSAGE",
                    source_identity=binding.source_identity,
                )
            )
        return tuple(hits), tuple(exclusions)

    def _receipt(
        self,
        request: FullTextBranchRequest,
        *,
        start_ns: int,
        outcome: BranchOutcome,
        reason_code: str,
        snapshot: Any | None = None,
        authority_view_digest: str | None = None,
        normalized_query: NormalizedFullTextQuery | None = None,
        hits: tuple[RetrievalBranchHit, ...] = (),
        exclusions: tuple[BranchExclusion, ...] = (),
        authority_read_count: int = 0,
        neo4j_read_count: int = 0,
    ) -> FullTextBranchReceipt:
        completed_ns = self._monotonic_ns()
        if completed_ns < start_ns:
            raise FullTextRetrieverError(
                "full-text monotonic clock moved backwards"
            )
        elapsed_ns = completed_ns - start_ns
        timed_out = elapsed_ns > BRANCH_TIMEOUT_MS * 1_000_000
        if timed_out:
            outcome = BranchOutcome.INCOMPLETE
            reason_code = "QUERY_TIMEOUT"
            hits = ()
            exclusions = ()
        elapsed_ms = min(
            BRANCH_TIMEOUT_MS,
            elapsed_ns // 1_000_000,
        )
        return FullTextBranchReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            request_digest=request.request_digest,
            contract_digest=request.contract_digest,
            policy_id=request.policy_id,
            fulltext_component_digest=request.fulltext_component_digest,
            normalization_component_digest=(
                request.normalization_component_digest
            ),
            outcome=outcome,
            reason_code=reason_code,
            started_at=request.serving_time,
            completed_at=request.serving_time,
            elapsed_ms=elapsed_ms,
            snapshot=snapshot,
            authority_view_digest=authority_view_digest,
            normalized_query=normalized_query,
            hits=hits,
            exclusions=exclusions,
            authority_read_count=authority_read_count,
            neo4j_read_count=neo4j_read_count,
        )


__all__ = [
    "FullTextRetriever",
    "FullTextRetrieverError",
]
