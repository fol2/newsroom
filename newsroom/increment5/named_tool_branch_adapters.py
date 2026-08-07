"""Closed typed adapters from Increment 5C named tools to the four 5B branches.

Each port translates one accepted named-tool request into one fixed reviewed 5B
request, invokes exactly one typed retriever and returns the complete canonical
upstream receipt with independently attributable component identities.  Request
content never selects a backend, query language, predicate, callable or write
surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.projection.models import ProjectionGenerationId

from .admitted_graph_retriever import (
    GRAPH_ACTOR_ID,
    GRAPH_MAX_DEPTH,
    GRAPH_MAX_FANOUT,
    GRAPH_POLICY_ID,
    GRAPH_PROFILE_ID,
    GRAPH_PURPOSE,
    GRAPH_QUERY_COMPONENT_DIGEST,
    GRAPH_RELATION_CONTRACT_DIGEST,
    GRAPH_RESPONSE_LIMIT_BYTES,
    GRAPH_RESULT_LIMIT,
    GRAPH_TEMPORAL_WINDOW_SECONDS,
    GRAPH_TIMEOUT_MS,
    RETRIEVAL_CONTRACT_DIGEST as GRAPH_RETRIEVAL_CONTRACT_DIGEST,
    AdmittedGraphReceipt,
    AdmittedGraphRequest,
    AdmittedGraphRetriever,
)
from .branch_contracts import (
    BRANCH_RESULT_LIMIT,
    BRANCH_TIMEOUT_MS,
    EXACT_BRANCH_ACTOR_ID,
    EXACT_BRANCH_POLICY_ID,
    EXACT_BRANCH_PURPOSE,
    BranchOutcome,
    BranchRequestId,
    ExactBranchRequest,
    ExactLookupKind as BranchExactLookupKind,
)
from .branch_receipts import ExactBranchReceipt
from .decision import INCREMENT_5A_CONTRACT_DIGEST
from .exact_retriever import SQLiteExactRetriever
from .fulltext_contracts import (
    FULLTEXT_ACTOR_ID,
    FULLTEXT_COMPONENT_DIGEST,
    FULLTEXT_MAX_PROJECTION_AGE_SECONDS,
    FULLTEXT_POLICY_ID,
    FULLTEXT_PURPOSE,
    FULLTEXT_RESPONSE_BYTE_LIMIT,
    INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
    NORMALIZATION_COMPONENT_DIGEST,
    FullTextBranchRequest,
    FullTextLanguageMode,
)
from .fulltext_receipts import FullTextBranchReceipt
from .fulltext_retriever import FullTextRetriever
from .named_tool_branch_execution import (
    AttributedBranchResult,
    BranchComponentIdentity,
    BranchReceiptAttribution,
    NamedBranchMode,
    NamedBranchOutcome,
    NamedBranchPolicyBlockedError,
)
from .named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    NAMED_TOOL_TIMEOUT_LIMIT_MS,
    AdmittedGraphTraversalToolRequest,
    ExactAuthorityLookupToolRequest,
    ExactLookupKind,
    FixedPointVectorRetrievalToolRequest,
    FullTextRetrievalToolRequest,
    NamedToolId,
    NamedToolLanguage,
    NamedToolRequest,
)
from .vector_retriever import (
    EMBEDDING_COMPONENT_DIGEST,
    RETRIEVAL_CONTRACT_DIGEST as VECTOR_RETRIEVAL_CONTRACT_DIGEST,
    VECTOR_ACTOR_ID,
    VECTOR_COMPONENT_DIGEST,
    VECTOR_POLICY_ID,
    VECTOR_PURPOSE,
    VECTOR_RESPONSE_LIMIT_BYTES,
    VECTOR_RESULT_LIMIT,
    VECTOR_TIMEOUT_MS,
    VectorBranchReceipt,
    VectorBranchRequest,
    VectorFixtureRetriever,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded canonical token")
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _config_digest(schema_version: str, values: dict[str, object]) -> str:
    return digest_bytes(
        canonical_json_bytes({"schema_version": schema_version, **values})
    )


NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST = digest_bytes(
    canonical_json_bytes(
        {
            "schema_version": "newsroom.increment5.named-tool-branch-adapters.v1",
            "ports": [
                {
                    "tool_id": NamedToolId.EXACT_AUTHORITY_LOOKUP.value,
                    "branch_mode": NamedBranchMode.EXACT.value,
                    "branch_contract": INCREMENT_5A_CONTRACT_DIGEST,
                },
                {
                    "tool_id": NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL.value,
                    "branch_mode": NamedBranchMode.FULL_TEXT.value,
                    "branch_contract": INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
                },
                {
                    "tool_id": NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL.value,
                    "branch_mode": NamedBranchMode.VECTOR.value,
                    "branch_contract": VECTOR_RETRIEVAL_CONTRACT_DIGEST,
                },
                {
                    "tool_id": NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL.value,
                    "branch_mode": NamedBranchMode.ADMITTED_GRAPH.value,
                    "branch_contract": GRAPH_RETRIEVAL_CONTRACT_DIGEST,
                },
            ],
            "named_tool_contract": NAMED_TOOL_CONTRACT_DIGEST,
            "policy_id": NAMED_TOOL_POLICY_ID,
            "profile_id": NAMED_TOOL_PROFILE_ID,
            "timeout_ms": NAMED_TOOL_TIMEOUT_LIMIT_MS,
            "absolute_receipt_bytes": NAMED_TOOL_RESPONSE_LIMIT_BYTES,
            "authority_effect": "NONE",
        }
    )
)


@dataclass(frozen=True, slots=True)
class ExactNamedToolAdapterConfig:
    source_authority_scope_id: str
    minimum_ledger_seq: int = 0

    def __post_init__(self) -> None:
        _require_token(
            self.source_authority_scope_id,
            field="exact_adapter_source_authority_scope_id",
        )
        _require_non_negative_int(
            self.minimum_ledger_seq,
            field="exact_adapter_minimum_ledger_seq",
        )

    @property
    def config_digest(self) -> str:
        return _config_digest(
            "newsroom.increment5.named-exact-adapter-config.v1",
            {
                "source_authority_scope_id": self.source_authority_scope_id,
                "minimum_ledger_seq": self.minimum_ledger_seq,
            },
        )


@dataclass(frozen=True, slots=True)
class FullTextNamedToolAdapterConfig:
    expected_generation_id: str
    expected_generation_identity_digest: str
    expected_rights_manifest_digest: str
    minimum_watermark: int = 0

    def __post_init__(self) -> None:
        ProjectionGenerationId.parse(self.expected_generation_id)
        validate_sha256_digest(
            self.expected_generation_identity_digest,
            field="fulltext_adapter_generation_identity_digest",
        )
        validate_sha256_digest(
            self.expected_rights_manifest_digest,
            field="fulltext_adapter_rights_manifest_digest",
        )
        _require_non_negative_int(
            self.minimum_watermark,
            field="fulltext_adapter_minimum_watermark",
        )

    @property
    def config_digest(self) -> str:
        return _config_digest(
            "newsroom.increment5.named-fulltext-adapter-config.v1",
            {
                "expected_generation_id": self.expected_generation_id,
                "expected_generation_identity_digest": (
                    self.expected_generation_identity_digest
                ),
                "expected_rights_manifest_digest": (
                    self.expected_rights_manifest_digest
                ),
                "minimum_watermark": self.minimum_watermark,
            },
        )


@dataclass(frozen=True, slots=True)
class VectorNamedToolAdapterConfig:
    minimum_watermark_seq: int = 0

    def __post_init__(self) -> None:
        _require_non_negative_int(
            self.minimum_watermark_seq,
            field="vector_adapter_minimum_watermark_seq",
        )

    @property
    def config_digest(self) -> str:
        return _config_digest(
            "newsroom.increment5.named-vector-adapter-config.v1",
            {"minimum_watermark_seq": self.minimum_watermark_seq},
        )


@dataclass(frozen=True, slots=True)
class AdmittedGraphNamedToolAdapterConfig:
    minimum_watermark_seq: int = 0

    def __post_init__(self) -> None:
        _require_non_negative_int(
            self.minimum_watermark_seq,
            field="graph_adapter_minimum_watermark_seq",
        )

    @property
    def config_digest(self) -> str:
        return _config_digest(
            "newsroom.increment5.named-admitted-graph-adapter-config.v1",
            {"minimum_watermark_seq": self.minimum_watermark_seq},
        )


def _preflight(request: NamedToolRequest, expected_tool: NamedToolId) -> None:
    envelope = request.envelope
    if envelope.tool_id is not expected_tool:
        raise NamedBranchPolicyBlockedError("named request does not match adapter tool")
    if (
        envelope.policy_id != NAMED_TOOL_POLICY_ID
        or envelope.contract_digest != NAMED_TOOL_CONTRACT_DIGEST
        or envelope.profile_id != NAMED_TOOL_PROFILE_ID
    ):
        raise NamedBranchPolicyBlockedError(
            "named request does not use the accepted policy, contract and profile"
        )
    if envelope.timeout_ms != NAMED_TOOL_TIMEOUT_LIMIT_MS:
        raise NamedBranchPolicyBlockedError(
            "the reviewed branch cannot safely honour a narrower timeout"
        )


def _components(values: Iterable[tuple[str, str]]) -> tuple[BranchComponentIdentity, ...]:
    return tuple(
        BranchComponentIdentity(name=name, digest=digest)
        for name, digest in sorted(values)
    )


def _normalized_outcome(outcome: BranchOutcome) -> NamedBranchOutcome:
    return NamedBranchOutcome(outcome.value)


def _attribution(
    *,
    tool_request_digest: str,
    tool_id: NamedToolId,
    branch_mode: NamedBranchMode,
    branch_schema_version: str,
    branch_request_digest: str,
    raw_receipt: bytes,
    branch_profile_id: str,
    branch_generation_id: str | None,
    branch_generation_digest: str | None,
    components: tuple[BranchComponentIdentity, ...],
    query_valid_time: str,
    serving_time: str,
    outcome: BranchOutcome,
    upstream_reason: str | None,
    result_count: int,
) -> AttributedBranchResult:
    normalized = _normalized_outcome(outcome)
    if normalized is NamedBranchOutcome.COMPLETE:
        no_match = result_count == 0
        reason = "NO_MATCH" if no_match else None
    else:
        no_match = False
        reason = upstream_reason or "BRANCH_NON_COMPLETE"
    attribution = BranchReceiptAttribution(
        tool_request_digest=tool_request_digest,
        tool_id=tool_id,
        branch_mode=branch_mode,
        branch_schema_version=branch_schema_version,
        branch_request_digest=branch_request_digest,
        branch_receipt_digest=digest_bytes(raw_receipt),
        branch_profile_id=branch_profile_id,
        branch_generation_id=branch_generation_id,
        branch_generation_digest=branch_generation_digest,
        component_identities=components,
        query_valid_time=query_valid_time,
        serving_time=serving_time,
        outcome=normalized,
        reason=reason,
        result_count=result_count,
        no_match=no_match,
        branch_receipt_bytes=len(raw_receipt),
    )
    return AttributedBranchResult(
        attribution=attribution,
        branch_receipt_bytes=raw_receipt,
    )


_EXACT_KIND_MAP = {
    ExactLookupKind.SOURCE_NATIVE_ID: BranchExactLookupKind.SOURCE_NATIVE_ID,
    ExactLookupKind.REVISION_ID: BranchExactLookupKind.SOURCE_REVISION_ID,
    ExactLookupKind.REPRESENTATION_ID: BranchExactLookupKind.REPRESENTATION_ID,
    ExactLookupKind.CANONICAL_ENTITY_ID: BranchExactLookupKind.CANONICAL_ENTITY_ID,
    ExactLookupKind.AUTHORITY_ALIAS: BranchExactLookupKind.AUTHORITY_ALIAS,
    ExactLookupKind.FORMAL_PROCESS_ID: BranchExactLookupKind.FORMAL_PROCESS_ID,
}


class ExactNamedToolPort:
    port_id = "increment5.named.exact.v1"
    tool_id = NamedToolId.EXACT_AUTHORITY_LOOKUP
    branch_mode = NamedBranchMode.EXACT

    def __init__(
        self,
        *,
        retriever: SQLiteExactRetriever,
        config: ExactNamedToolAdapterConfig,
    ) -> None:
        if not isinstance(retriever, SQLiteExactRetriever):
            raise TypeError("exact named-tool port requires the typed exact retriever")
        if not isinstance(config, ExactNamedToolAdapterConfig):
            raise TypeError("exact named-tool port requires typed adapter configuration")
        self.retriever = retriever
        self.config = config

    def execute(self, request: NamedToolRequest) -> AttributedBranchResult:
        if not isinstance(request, ExactAuthorityLookupToolRequest):
            raise NamedBranchPolicyBlockedError("exact adapter requires an exact request")
        _preflight(request, self.tool_id)
        kind = _EXACT_KIND_MAP[request.lookup_kind]
        branch_request = ExactBranchRequest(
            request_id=BranchRequestId.parse(request.envelope.request_id),
            idempotency_key=request.envelope.idempotency_key,
            actor_id=EXACT_BRANCH_ACTOR_ID,
            purpose=EXACT_BRANCH_PURPOSE,
            policy_id=EXACT_BRANCH_POLICY_ID,
            contract_digest=INCREMENT_5A_CONTRACT_DIGEST,
            lookup_kind=kind,
            lookup_value=request.lookup_value,
            authority_scope_id=(
                self.config.source_authority_scope_id
                if kind is BranchExactLookupKind.SOURCE_NATIVE_ID
                else None
            ),
            query_valid_time=UtcTimestamp.parse(request.envelope.query_valid_time),
            serving_time=UtcTimestamp.parse(request.envelope.serving_time),
            minimum_ledger_seq=self.config.minimum_ledger_seq,
            result_limit=BRANCH_RESULT_LIMIT,
            timeout_ms=BRANCH_TIMEOUT_MS,
        )
        journal_result = self.retriever.retrieve(branch_request)
        receipt = journal_result.receipt
        if not isinstance(receipt, ExactBranchReceipt):
            raise RuntimeError("exact retriever returned the wrong receipt type")
        raw = receipt.canonical_bytes
        components = _components(
            (
                ("adapter_config", self.config.config_digest),
                ("adapter_contract", NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST),
                ("branch_contract", INCREMENT_5A_CONTRACT_DIGEST),
                (
                    "exact_implementation",
                    digest_bytes(
                        canonical_json_bytes(
                            {
                                "implementation_version": receipt.implementation_version,
                                "source_generation": receipt.source_generation,
                            }
                        )
                    ),
                ),
                ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
            )
        )
        return _attribution(
            tool_request_digest=request.request_digest,
            tool_id=self.tool_id,
            branch_mode=self.branch_mode,
            branch_schema_version="newsroom.increment5.exact-branch-receipt.v1",
            branch_request_digest=branch_request.request_digest,
            raw_receipt=raw,
            branch_profile_id=receipt.implementation_version,
            branch_generation_id=None,
            branch_generation_digest=None,
            components=components,
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            outcome=receipt.outcome,
            upstream_reason=receipt.reason_code,
            result_count=len(receipt.hits),
        )


def _language_mode(languages: tuple[NamedToolLanguage, ...]) -> FullTextLanguageMode:
    selected = frozenset(languages)
    if selected == {NamedToolLanguage.EN_GB}:
        return FullTextLanguageMode.EN_GB
    if selected == {NamedToolLanguage.ZH_HANT_HK}:
        return FullTextLanguageMode.ZH_HANT_HK
    return FullTextLanguageMode.MIXED_EN_GB_ZH_HANT_HK


class FullTextNamedToolPort:
    port_id = "increment5.named.fulltext.v1"
    tool_id = NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL
    branch_mode = NamedBranchMode.FULL_TEXT

    def __init__(
        self,
        *,
        retriever: FullTextRetriever,
        config: FullTextNamedToolAdapterConfig,
    ) -> None:
        if not isinstance(retriever, FullTextRetriever):
            raise TypeError("full-text named-tool port requires the typed retriever")
        if not isinstance(config, FullTextNamedToolAdapterConfig):
            raise TypeError("full-text named-tool port requires typed configuration")
        self.retriever = retriever
        self.config = config

    def execute(self, request: NamedToolRequest) -> AttributedBranchResult:
        if not isinstance(request, FullTextRetrievalToolRequest):
            raise NamedBranchPolicyBlockedError("full-text adapter requires its typed request")
        _preflight(request, self.tool_id)
        if request.envelope.generation_id != self.config.expected_generation_id:
            raise NamedBranchPolicyBlockedError(
                "full-text request generation is outside the reviewed adapter configuration"
            )
        branch_request = FullTextBranchRequest(
            request_id=BranchRequestId.parse(request.envelope.request_id),
            idempotency_key=request.envelope.idempotency_key,
            actor_id=FULLTEXT_ACTOR_ID,
            purpose=FULLTEXT_PURPOSE,
            policy_id=FULLTEXT_POLICY_ID,
            contract_digest=INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
            fulltext_component_digest=FULLTEXT_COMPONENT_DIGEST,
            normalization_component_digest=NORMALIZATION_COMPONENT_DIGEST,
            expected_generation_id=ProjectionGenerationId.parse(
                self.config.expected_generation_id
            ),
            expected_generation_identity_digest=(
                self.config.expected_generation_identity_digest
            ),
            expected_rights_manifest_digest=(
                self.config.expected_rights_manifest_digest
            ),
            query_text=request.query_text,
            language_mode=_language_mode(request.languages),
            source_ids=request.source_ids,
            query_valid_time=UtcTimestamp.parse(request.envelope.query_valid_time),
            serving_time=UtcTimestamp.parse(request.envelope.serving_time),
            minimum_watermark=self.config.minimum_watermark,
            result_limit=BRANCH_RESULT_LIMIT,
            timeout_ms=BRANCH_TIMEOUT_MS,
            response_byte_limit=FULLTEXT_RESPONSE_BYTE_LIMIT,
            max_projection_age_seconds=FULLTEXT_MAX_PROJECTION_AGE_SECONDS,
        )
        receipt = self.retriever.retrieve(branch_request).receipt
        if not isinstance(receipt, FullTextBranchReceipt):
            raise RuntimeError("full-text retriever returned the wrong receipt type")
        snapshot = receipt.snapshot
        generation_id = None if snapshot is None else str(snapshot.generation_id)
        generation_digest = (
            None if snapshot is None else snapshot.generation_identity_digest
        )
        branch_profile = (
            FULLTEXT_POLICY_ID if snapshot is None else snapshot.profile.value
        )
        components_list: list[tuple[str, str]] = [
            ("adapter_config", self.config.config_digest),
            ("adapter_contract", NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST),
            ("branch_contract", INCREMENT5_RETRIEVAL_CONTRACT_DIGEST),
            ("fulltext_component", FULLTEXT_COMPONENT_DIGEST),
            ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
            ("normalization_component", NORMALIZATION_COMPONENT_DIGEST),
            ("rights_manifest", self.config.expected_rights_manifest_digest),
        ]
        if snapshot is not None:
            components_list.append(
                (
                    "generation_identity",
                    snapshot.generation_identity_digest,
                )
            )
        return _attribution(
            tool_request_digest=request.request_digest,
            tool_id=self.tool_id,
            branch_mode=self.branch_mode,
            branch_schema_version="newsroom.increment5.fulltext-branch-receipt.v1",
            branch_request_digest=branch_request.request_digest,
            raw_receipt=receipt.canonical_bytes,
            branch_profile_id=branch_profile,
            branch_generation_id=generation_id,
            branch_generation_digest=generation_digest,
            components=_components(components_list),
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            outcome=receipt.outcome,
            upstream_reason=receipt.reason_code,
            result_count=len(receipt.hits),
        )


class VectorNamedToolPort:
    port_id = "increment5.named.vector.v1"
    tool_id = NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL
    branch_mode = NamedBranchMode.VECTOR

    def __init__(
        self,
        *,
        retriever: VectorFixtureRetriever,
        config: VectorNamedToolAdapterConfig,
    ) -> None:
        if not isinstance(retriever, VectorFixtureRetriever):
            raise TypeError("vector named-tool port requires the typed fixture retriever")
        if not isinstance(config, VectorNamedToolAdapterConfig):
            raise TypeError("vector named-tool port requires typed configuration")
        self.retriever = retriever
        self.config = config

    def execute(self, request: NamedToolRequest) -> AttributedBranchResult:
        if not isinstance(request, FixedPointVectorRetrievalToolRequest):
            raise NamedBranchPolicyBlockedError("vector adapter requires its typed request")
        _preflight(request, self.tool_id)
        catalog = self.retriever.catalog
        branch_request = VectorBranchRequest(
            request_id=request.envelope.request_id,
            idempotency_key=request.envelope.idempotency_key,
            actor_id=VECTOR_ACTOR_ID,
            purpose=VECTOR_PURPOSE,
            policy_id=VECTOR_POLICY_ID,
            contract_digest=VECTOR_RETRIEVAL_CONTRACT_DIGEST,
            catalog_digest=catalog.catalog_digest,
            profile_id=catalog.profile_id,
            vector_component_digest=VECTOR_COMPONENT_DIGEST,
            embedding_component_digest=EMBEDDING_COMPONENT_DIGEST,
            query_id=request.fixture_query_id,
            query_digest=request.fixture_query_digest,
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            minimum_watermark_seq=self.config.minimum_watermark_seq,
            result_limit=VECTOR_RESULT_LIMIT,
            timeout_ms=VECTOR_TIMEOUT_MS,
            response_limit_bytes=VECTOR_RESPONSE_LIMIT_BYTES,
        )
        receipt = self.retriever.retrieve(branch_request)
        if not isinstance(receipt, VectorBranchReceipt):
            raise RuntimeError("vector retriever returned the wrong receipt type")
        components_list: list[tuple[str, str]] = [
            ("adapter_config", self.config.config_digest),
            ("adapter_contract", NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST),
            ("branch_contract", VECTOR_RETRIEVAL_CONTRACT_DIGEST),
            ("embedding_component", EMBEDDING_COMPONENT_DIGEST),
            ("fixture_catalog", catalog.catalog_digest),
            ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
            ("vector_component", VECTOR_COMPONENT_DIGEST),
        ]
        if receipt.rights_manifest_digest is not None:
            components_list.append(
                ("rights_manifest", receipt.rights_manifest_digest)
            )
        return _attribution(
            tool_request_digest=request.request_digest,
            tool_id=self.tool_id,
            branch_mode=self.branch_mode,
            branch_schema_version="newsroom.increment5.vector-branch-receipt.v1",
            branch_request_digest=branch_request.request_digest,
            raw_receipt=receipt.canonical_bytes,
            branch_profile_id=receipt.profile_id,
            branch_generation_id=receipt.generation_id,
            branch_generation_digest=receipt.generation_digest,
            components=_components(components_list),
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            outcome=receipt.outcome,
            upstream_reason=(None if receipt.reason is None else receipt.reason.value),
            result_count=len(receipt.hits),
        )


class AdmittedGraphNamedToolPort:
    port_id = "increment5.named.admitted-graph.v1"
    tool_id = NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL
    branch_mode = NamedBranchMode.ADMITTED_GRAPH

    def __init__(
        self,
        *,
        retriever: AdmittedGraphRetriever,
        config: AdmittedGraphNamedToolAdapterConfig,
    ) -> None:
        if not isinstance(retriever, AdmittedGraphRetriever):
            raise TypeError("graph named-tool port requires the typed graph retriever")
        if not isinstance(config, AdmittedGraphNamedToolAdapterConfig):
            raise TypeError("graph named-tool port requires typed configuration")
        self.retriever = retriever
        self.config = config

    def execute(self, request: NamedToolRequest) -> AttributedBranchResult:
        if not isinstance(request, AdmittedGraphTraversalToolRequest):
            raise NamedBranchPolicyBlockedError("graph adapter requires its typed request")
        _preflight(request, self.tool_id)
        if (
            request.maximum_depth != GRAPH_MAX_DEPTH
            or request.maximum_fanout != GRAPH_MAX_FANOUT
            or request.temporal_window_seconds != GRAPH_TEMPORAL_WINDOW_SECONDS
        ):
            raise NamedBranchPolicyBlockedError(
                "the accepted graph branch cannot silently widen a narrower request"
            )
        branch_request = AdmittedGraphRequest(
            request_id=request.envelope.request_id,
            idempotency_key=request.envelope.idempotency_key,
            actor_id=GRAPH_ACTOR_ID,
            purpose=GRAPH_PURPOSE,
            policy_id=GRAPH_POLICY_ID,
            contract_digest=GRAPH_RETRIEVAL_CONTRACT_DIGEST,
            profile_id=GRAPH_PROFILE_ID,
            graph_component_digest=GRAPH_QUERY_COMPONENT_DIGEST,
            relation_contract_digest=GRAPH_RELATION_CONTRACT_DIGEST,
            root_id=request.root_id,
            root_identity_digest=request.root_identity_digest,
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            minimum_watermark_seq=self.config.minimum_watermark_seq,
            maximum_depth=GRAPH_MAX_DEPTH,
            maximum_fanout=GRAPH_MAX_FANOUT,
            temporal_window_seconds=GRAPH_TEMPORAL_WINDOW_SECONDS,
            result_limit=GRAPH_RESULT_LIMIT,
            timeout_ms=GRAPH_TIMEOUT_MS,
            response_limit_bytes=GRAPH_RESPONSE_LIMIT_BYTES,
        )
        receipt = self.retriever.retrieve(branch_request)
        if not isinstance(receipt, AdmittedGraphReceipt):
            raise RuntimeError("graph retriever returned the wrong receipt type")
        components_list: list[tuple[str, str]] = [
            ("adapter_config", self.config.config_digest),
            ("adapter_contract", NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST),
            ("branch_contract", GRAPH_RETRIEVAL_CONTRACT_DIGEST),
            ("graph_component", GRAPH_QUERY_COMPONENT_DIGEST),
            ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
            ("relation_contract", GRAPH_RELATION_CONTRACT_DIGEST),
        ]
        if receipt.rights_manifest_digest is not None:
            components_list.append(
                ("rights_manifest", receipt.rights_manifest_digest)
            )
        return _attribution(
            tool_request_digest=request.request_digest,
            tool_id=self.tool_id,
            branch_mode=self.branch_mode,
            branch_schema_version="newsroom.increment5.admitted-graph-receipt.v1",
            branch_request_digest=branch_request.request_digest,
            raw_receipt=receipt.canonical_bytes,
            branch_profile_id=receipt.profile_id,
            branch_generation_id=receipt.generation_id,
            branch_generation_digest=receipt.generation_digest,
            components=_components(components_list),
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            outcome=receipt.outcome,
            upstream_reason=(None if receipt.reason is None else receipt.reason.value),
            result_count=len(receipt.hits),
        )


__all__ = [
    "NAMED_TOOL_BRANCH_ADAPTER_CONTRACT_DIGEST",
    "AdmittedGraphNamedToolAdapterConfig",
    "AdmittedGraphNamedToolPort",
    "ExactNamedToolAdapterConfig",
    "ExactNamedToolPort",
    "FullTextNamedToolAdapterConfig",
    "FullTextNamedToolPort",
    "VectorNamedToolAdapterConfig",
    "VectorNamedToolPort",
]
