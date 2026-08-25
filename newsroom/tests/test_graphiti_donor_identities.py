"""Provider-free donor identity proofs for Graphiti issue #772."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.graphiti_adapter.combined_temporal_contract import CompactPrompt
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CombinedTemporalFailureCode,
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
    UNMEASURED,
    build_compact_prompt,
    extract_combined_temporal,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import (
    FIXTURES,
    MALFORMED_CASES,
    fixture,
)
from newsroom.graphiti_adapter.combined_temporal_pipeline import (
    CombinedTemporalPipelineResult,
)
from newsroom.graphiti_adapter.combined_temporal_runtime import (
    extract_combined_temporal_async,
)
from newsroom.graphiti_adapter.donor_identities import (
    TRACK_A_DECISION,
    ValidatedSemanticExtractionArtifactV1,
    build_embedding_request_identity,
    build_semantic_request_identity,
)
from newsroom.graphiti_adapter.donor_store import (
    InMemoryDonorStore,
    SqliteDonorStore,
)
from newsroom.graphiti_adapter.embedding_meter import MeteredOpenAIEmbedder
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_CORE_RELEASE


class _FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def generate_response(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        response_model: str,
    ) -> CombinedTemporalTransportResult:
        del prompt, schema, response_model
        self.calls += 1
        return CombinedTemporalTransportResult(
            raw=self.payload,
            framework_version=GRAPHITI_CORE_RELEASE,
            model_version=None,
            token_usage={"basis": UNMEASURED},
            provider_cost=None,
        )


class _ProviderFreePipeline:
    def prepare_attempt(self) -> None:
        return None

    def complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        return receipt

    def execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        return CombinedTemporalPipelineResult(
            nodes=nodes,
            edges=edges,
            guarded_edges=edges,
            node_resolutions=tuple("NEW" for _node in nodes),
            graph_effect_attempted=False,
            embedding_skipped=not edges,
            journal_skipped=False,
            rollback_skipped=True,
        )


class _FailedTransport:
    def generate_response(self, **_values: object) -> CombinedTemporalTransportResult:
        raise RuntimeError("transport failed")


class _FailedPipeline(_ProviderFreePipeline):
    def execute(self, **_values: object) -> CombinedTemporalPipelineResult:
        from newsroom.graphiti_adapter.combined_temporal_pipeline import (
            CombinedTemporalPipelineError,
        )

        raise CombinedTemporalPipelineError(
            "held after validation",
            graph_effect_attempted=True,
            rollback_completed=True,
        )


class _ReplayPipeline(_ProviderFreePipeline):
    def __init__(self, completed: Mapping[str, object] | None = None) -> None:
        self.completed = completed

    def prepare_attempt(self) -> Mapping[str, object] | None:
        return self.completed

    def execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        durable = dict(receipt)
        proposal = dict(durable["proposal_receipt"])
        proposal["entity_mentions"] = [
            {
                **item,
                "canonical_identity": str(node.uuid),
                "resolution": "NEW",
            }
            for item, node in zip(proposal["entity_mentions"], nodes, strict=True)
        ]
        proposal["relation_proposals"] = [
            {
                **item,
                "proposal_identity": str(edge.uuid),
                "source_identity": str(edge.source_node_uuid),
                "target_identity": str(edge.target_node_uuid),
                "fact_embedding": None,
            }
            for item, edge in zip(proposal["relation_proposals"], edges, strict=True)
        ]
        durable["proposal_receipt"] = proposal
        self.completed = durable
        return CombinedTemporalPipelineResult(
            nodes=nodes,
            edges=edges,
            guarded_edges=edges,
            node_resolutions=tuple("NEW" for _node in nodes),
            graph_effect_attempted=False,
            embedding_skipped=True,
            journal_skipped=False,
            rollback_skipped=True,
            completed_receipt=durable,
        )


class _AsyncTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    async def generate_response(
        self, **_values: object
    ) -> CombinedTemporalTransportResult:
        self.calls += 1
        return CombinedTemporalTransportResult(
            raw=self.payload,
            framework_version=GRAPHITI_CORE_RELEASE,
            model_version="fixture-model",
            token_usage={"basis": UNMEASURED},
            provider_cost=None,
        )


class _AsyncProviderFreePipeline:
    async def _prepare_attempt(self) -> None:
        return None

    async def _complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        return receipt

    async def _execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        return CombinedTemporalPipelineResult(
            nodes=nodes,
            edges=edges,
            guarded_edges=edges,
            node_resolutions=tuple("NEW" for _node in nodes),
            graph_effect_attempted=False,
            embedding_skipped=not edges,
            journal_skipped=False,
            rollback_skipped=True,
            completed_receipt=receipt,
        )

def test_revision_lineage_is_proved_controller_only_across_all_gold_fixtures() -> None:
    assert TRACK_A_DECISION == "CONTROLLER_ONLY_PROVED"
    for case in FIXTURES:
        swapped = replace(
            case.revision,
            revision_id=f"swapped-{case.revision.revision_id}",
            predecessor_revision_id="swapped-predecessor",
        )

        first = extract_combined_temporal(
            case.revision,
            transport=_FakeTransport(case.gold),
            pipeline=_ProviderFreePipeline(),
        )
        second = extract_combined_temporal(
            swapped,
            transport=_FakeTransport(case.gold),
            pipeline=_ProviderFreePipeline(),
        )

        assert first.outcome in {
            CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS,
        }
        assert second.outcome is first.outcome
        assert first.payload == second.payload
        assert first.evidence_ranges == second.evidence_ranges
        assert build_compact_prompt(case.revision).text == build_compact_prompt(
            swapped
        ).text


def test_every_new_valid_result_retains_one_request_identity_and_donor_artefact(
) -> None:
    store = InMemoryDonorStore()

    for case in FIXTURES:
        leaf = extract_combined_temporal(
            case.revision,
            transport=_FakeTransport(case.gold),
            pipeline=_ProviderFreePipeline(),
            donor_store=store,
        )

        assert leaf.request_identity_digest is not None
        assert leaf.donor_artifact_digest is not None
        assert store.semantic_request_count(leaf.request_identity_digest) == 1
        assert store.validated_artifact_count(leaf.request_identity_digest) == 1


def test_invalid_held_and_pre_validator_results_never_create_donor_artefacts() -> None:
    store = InMemoryDonorStore()
    for case in MALFORMED_CASES:
        leaf = extract_combined_temporal(
            case.revision,
            transport=_FakeTransport(case.payload),
            pipeline=_ProviderFreePipeline(),
            donor_store=store,
        )
        assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
        assert leaf.donor_artifact_digest is None

    revision = fixture("pair-current").revision
    transport_failure = extract_combined_temporal(
        revision,
        transport=_FailedTransport(),
        pipeline=_ProviderFreePipeline(),
        donor_store=store,
    )
    held = extract_combined_temporal(
        revision,
        transport=_FakeTransport(fixture("pair-current").gold),
        pipeline=_FailedPipeline(),
        donor_store=store,
    )

    assert transport_failure.failure_code is CombinedTemporalFailureCode.PIPELINE_FAILED
    assert held.failure_code is CombinedTemporalFailureCode.PIPELINE_FAILED
    assert store.validated_artifact_count() == 0
    assert store.semantic_request_count() >= 1
    ineligible_manifest = b'{"contract":"ValidatedSemanticExtractionArtifactV1"}'
    assert store.retain_validated_artifact(
        ValidatedSemanticExtractionArtifactV1(
            artifact_digest=digest_canonical(
                {"contract": "ValidatedSemanticExtractionArtifactV1"}
            ),
            identity_digest="sha256:" + "00" * 32,
            manifest_json=ineligible_manifest,
        )
    ) is False


def test_donor_artefact_manifest_contains_no_source_or_graph_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "donors.sqlite3"
    store = SqliteDonorStore(path)
    case = fixture("pair-current")

    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
        pipeline=_ProviderFreePipeline(),
        donor_store=store,
    )

    assert leaf.donor_artifact_digest is not None
    with sqlite3.connect(path) as connection:
        raw = connection.execute(
            "SELECT manifest_json FROM validated_semantic_extraction_artifacts"
        ).fetchone()[0]
    manifest = json.loads(raw)
    assert raw.encode("utf-8") == canonical_json_bytes(manifest)
    forbidden = {
        "admission",
        "canonical_entity",
        "canonical_identity",
        "completion_marker",
        "episode_uuid",
        "fact_embedding",
        "governed",
        "graph_uuids",
        "ingest_id",
        "neo4j",
        "node.uuid",
        "projection",
        "revision_id",
        "rights",
        "source_id",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert keys(manifest).isdisjoint(forbidden)
    assert manifest["payload"] == leaf.payload
    assert manifest["payload_digest"] == leaf.payload_digest


def test_semantic_identity_changes_on_every_bound_semantic_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.donor_identities as identities

    revision = fixture("pair-current").revision
    prompt = build_compact_prompt(revision)
    baseline = build_semantic_request_identity(revision, prompt).identity_digest
    body_shift = replace(revision, body=revision.body[:-1] + "!")
    first_segment = prompt.segments[0]
    segment_shift = replace(first_segment, end_byte=first_segment.end_byte + 1)
    shifted_prompt = CompactPrompt(
        prompt.text,
        prompt.schema,
        (segment_shift, *prompt.segments[1:]),
    )

    assert build_semantic_request_identity(
        body_shift, build_compact_prompt(body_shift)
    ).identity_digest != baseline
    assert (
        build_semantic_request_identity(revision, shifted_prompt).identity_digest
        != baseline
    )
    assert build_semantic_request_identity(
        replace(revision, published_at="2026-08-20T00:00:00Z"),
        build_compact_prompt(
            replace(revision, published_at="2026-08-20T00:00:00Z")
        ),
    ).identity_digest != baseline
    assert build_semantic_request_identity(
        revision,
        replace(prompt, text=prompt.text + "\nDRIFT"),
    ).identity_digest != baseline

    monkeypatch.setattr(identities, "SCHEMA_DIGEST", "sha256:" + "11" * 32)
    assert build_semantic_request_identity(revision, prompt).identity_digest != baseline
    monkeypatch.setattr(identities, "SCHEMA_DIGEST", digest_canonical(prompt.schema))
    monkeypatch.setattr(identities, "VALIDATOR_CONTRACT_VERSION", "validator-drift")
    assert build_semantic_request_identity(revision, prompt).identity_digest != baseline
    monkeypatch.setattr(
        identities, "VALIDATOR_CONTRACT_VERSION", "NewsroomCombinedTemporalNormaliseV1"
    )
    monkeypatch.setattr(identities, "GRAPHITI_CHAT_MODEL", "model-drift")
    assert build_semantic_request_identity(revision, prompt).identity_digest != baseline


def test_controller_receipts_retain_revision_lineage_after_prompt_removal() -> None:
    case = fixture("correction-revision")
    pipeline = _ReplayPipeline()
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
        pipeline=pipeline,
    )
    completed = pipeline.completed
    assert completed is not None
    assert "REVISION_ID:" not in leaf.prompt.text
    assert "PREDECESSOR_REVISION_ID:" not in leaf.prompt.text
    assert completed["source_revision_id"] == case.revision.revision_id
    assert completed["predecessor_revision_id"] == (
        case.revision.predecessor_revision_id
    )
    proposal = completed["proposal_receipt"]
    assert isinstance(proposal, dict)
    assert proposal["source_revision_id"] == case.revision.revision_id
    assert proposal["predecessor_revision_id"] == (
        case.revision.predecessor_revision_id
    )


def test_evaluation_executor_seeds_insert_only_sqlite_beside_the_workspace() -> None:
    source = Path(
        "newsroom/graphiti_adapter/real.py"
    ).read_text(encoding="utf-8")
    assert "donor_store: DonorStore | None = None" in source
    assert "donor_workspace_root: Path | None = None" in source
    assert 'donor_workspace_root / "donor_identities.sqlite3"' in source
    assert "SqliteDonorStore" in source
    assert "donor_store=donor_store" in source


def test_revision_and_predecessor_lineage_do_not_change_semantic_identity() -> None:
    revision = fixture("correction-revision").revision
    swapped = replace(
        revision,
        revision_id="other-revision",
        predecessor_revision_id="other-predecessor",
    )

    assert build_semantic_request_identity(
        revision, build_compact_prompt(revision)
    ).identity_digest == build_semantic_request_identity(
        swapped, build_compact_prompt(swapped)
    ).identity_digest


def test_matching_donor_is_telemetry_only_and_never_skips_provider_dispatch() -> None:
    store = InMemoryDonorStore()
    case = fixture("pair-current")
    planted_transport = _FakeTransport({"entities": [], "facts": []})
    planted = extract_combined_temporal(
        case.revision,
        transport=planted_transport,
        pipeline=_ProviderFreePipeline(),
        donor_store=store,
    )
    second_revision = replace(case.revision, revision_id="new-ingest-revision")
    current_transport = _FakeTransport(case.gold)

    current = extract_combined_temporal(
        second_revision,
        transport=current_transport,
        pipeline=_ProviderFreePipeline(),
        donor_store=store,
    )

    assert planted.request_identity_digest == current.request_identity_digest
    assert planted.payload_digest != current.payload_digest
    assert current.payload == case.gold
    assert current_transport.calls == 1
    assert store.semantic_opportunity_count(current.request_identity_digest) == 1
    assert store.validated_artifact_count(current.request_identity_digest) == 2


def test_concurrent_matching_extracts_make_two_provider_calls_and_one_donor_row(
    tmp_path: Path,
) -> None:
    store = SqliteDonorStore(tmp_path / "donors.sqlite3")
    case = fixture("pair-current")
    transports = (_FakeTransport(case.gold), _FakeTransport(case.gold))

    def run(transport: _FakeTransport) -> str:
        leaf = extract_combined_temporal(
            case.revision,
            transport=transport,
            pipeline=_ProviderFreePipeline(),
            donor_store=store,
        )
        assert leaf.donor_artifact_digest is not None
        return leaf.donor_artifact_digest

    with ThreadPoolExecutor(max_workers=2) as executor:
        digests = tuple(executor.map(run, transports))

    assert transports[0].calls + transports[1].calls == 2
    assert digests[0] == digests[1]
    assert store.semantic_request_count() == 1
    assert store.validated_artifact_count() == 1
    assert SqliteDonorStore(store.path).validated_artifact_count() == 1


def test_completed_marker_replay_skips_transport_and_mints_no_second_donor() -> None:
    store = InMemoryDonorStore()
    case = fixture("pair-current")
    pipeline = _ReplayPipeline()
    first_transport = _FakeTransport(case.gold)
    first = extract_combined_temporal(
        case.revision,
        transport=first_transport,
        pipeline=pipeline,
        donor_store=store,
    )
    replay_transport = _FakeTransport(RuntimeError("provider must not run"))

    replayed = extract_combined_temporal(
        case.revision,
        transport=replay_transport,
        pipeline=_ReplayPipeline(pipeline.completed),
        donor_store=store,
    )

    assert first_transport.calls == 1
    assert replay_transport.calls == 0
    assert replayed.payload == first.payload
    assert store.semantic_request_count() == 1
    assert store.validated_artifact_count() == 1
    assert store.semantic_opportunity_count(first.request_identity_digest) == 0


def test_embedding_identity_and_integrity_are_retained_without_serving_vectors(
) -> None:
    store = InMemoryDonorStore()
    provider_calls = 0

    class Embeddings:
        async def create(self, **_values: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            vector = [1.0, 2.0] if provider_calls == 1 else [3.0, 4.0]
            return SimpleNamespace(
                id=f"embedding-{provider_calls}",
                data=[SimpleNamespace(embedding=vector)],
                usage={"prompt_tokens": 1, "total_tokens": 1, "cost": "0.000001"},
            )

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    embedder = MeteredOpenAIEmbedder(delegate, donor_store=store)

    assert asyncio.run(embedder.create("exact input")) == [1.0, 2.0]
    assert asyncio.run(embedder.create("exact input")) == [3.0, 4.0]
    assert provider_calls == 2
    assert store.embedding_request_count() == 1
    assert store.embedding_integrity_count() == 2


def test_embedding_failure_retains_request_identity_without_vector_integrity() -> None:
    store = InMemoryDonorStore()

    class Embeddings:
        async def create(self, **_values: object) -> object:
            raise RuntimeError("provider failed")

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    embedder = MeteredOpenAIEmbedder(delegate, donor_store=store)

    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(embedder.create("exact input"))

    assert store.embedding_request_count() == 1
    assert store.embedding_integrity_count() == 0


def test_embedding_request_identity_binds_input_model_and_dimensions() -> None:
    baseline = build_embedding_request_identity(
        provider="openrouter",
        model="openai/text-embedding-3-large",
        dimensions=2,
        input_data="exact input",
        provider_options={},
    ).identity_digest

    assert build_embedding_request_identity(
        provider="openrouter",
        model="openai/text-embedding-3-large",
        dimensions=2,
        input_data="exact inpuu",
        provider_options={},
    ).identity_digest != baseline
    assert build_embedding_request_identity(
        provider="openrouter",
        model="other-model",
        dimensions=2,
        input_data="exact input",
        provider_options={},
    ).identity_digest != baseline
    assert build_embedding_request_identity(
        provider="openrouter",
        model="openai/text-embedding-3-large",
        dimensions=3,
        input_data="exact input",
        provider_options={},
    ).identity_digest != baseline


class _EvaluationEnvelopePipeline(_ProviderFreePipeline):
    def execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        inner = super().execute(nodes=nodes, edges=edges, receipt=receipt)
        return CombinedTemporalPipelineResult(
            nodes=inner.nodes,
            edges=inner.edges,
            guarded_edges=inner.guarded_edges,
            node_resolutions=inner.node_resolutions,
            graph_effect_attempted=inner.graph_effect_attempted,
            embedding_skipped=inner.embedding_skipped,
            journal_skipped=inner.journal_skipped,
            rollback_skipped=inner.rollback_skipped,
            completed_receipt={
                "framework": GRAPHITI_CORE_RELEASE,
                "combined_temporal_receipt": dict(receipt),
            },
        )


def test_evaluation_envelope_receipt_still_mints_a_donor_artefact() -> None:
    store = InMemoryDonorStore()
    case = fixture("pair-current")
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
        pipeline=_EvaluationEnvelopePipeline(),
        donor_store=store,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert leaf.donor_artifact_digest is not None
    assert leaf.request_identity_digest is not None
    assert store.validated_artifact_count(leaf.request_identity_digest) == 1


def test_async_extraction_retains_the_same_non_serving_donor_contract() -> None:
    store = InMemoryDonorStore()
    case = fixture("pair-current")
    transport = _AsyncTransport(case.gold)

    leaf = asyncio.run(
        extract_combined_temporal_async(
            case.revision,
            transport=transport,
            pipeline=_AsyncProviderFreePipeline(),  # type: ignore[arg-type]
            donor_store=store,
        )
    )

    assert transport.calls == 1
    assert leaf.request_identity_digest is not None
    assert leaf.donor_artifact_digest is not None
    assert store.semantic_request_count(leaf.request_identity_digest) == 1
    assert store.validated_artifact_count(leaf.request_identity_digest) == 1


def test_embedding_integrity_uses_ieee_digest_and_retains_receipt_linkage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "donors.sqlite3"
    store = SqliteDonorStore(path)

    class Embeddings:
        async def create(self, **_values: object) -> object:
            return SimpleNamespace(
                id="provider-request-1",
                data=[SimpleNamespace(embedding=[1.25, 2.5])],
                usage={"prompt_tokens": 1, "total_tokens": 1, "cost": "0.000001"},
            )

    class Observer:
        def before_embedding_invocation(self, **_values: object) -> object:
            return "allocation"

        def after_embedding_invocation(
            self, token: object, *, outcome: str, usage: dict[str, object]
        ) -> Mapping[str, str]:
            assert token == "allocation"
            assert outcome == "COMPLETE"
            assert usage["total_tokens"] == 1
            return {
                "model_work_envelope_id": "envelope-1",
                "model_invocation_id": "invocation-1",
                "model_invocation_allocation_digest": "allocation-digest-1",
                "model_invocation_terminal_digest": "terminal-digest-1",
            }

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    embedder = MeteredOpenAIEmbedder(
        delegate,
        invocation_observer=Observer(),
        donor_store=store,
    )

    assert asyncio.run(embedder.create("exact input")) == [1.25, 2.5]
    with sqlite3.connect(path) as connection:
        raw = connection.execute(
            "SELECT manifest_json FROM embedding_vector_integrity"
        ).fetchone()[0]
    manifest = json.loads(raw)
    vector = manifest["vectors"][0]
    assert vector == {
        "finite": True,
        "index": 0,
        "length": 2,
        "vector_digest": (
            "sha256:a722883996ae7168467418a173f6a3314c988e6993869f14c90e3262439355ee"
        ),
    }
    assert manifest["provider_request_id"] == "provider-request-1"
    assert manifest["receipt_linkage"]["model_invocation_id"] == "invocation-1"

    def contains_float(value: object) -> bool:
        if isinstance(value, dict):
            return any(contains_float(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_float(item) for item in value)
        return isinstance(value, float)

    assert contains_float(manifest) is False


def test_donor_telemetry_failure_cannot_change_provider_or_validated_result() -> None:
    class ExplodingStore:
        def count_semantic_opportunity(self, _identity: object) -> int:
            raise RuntimeError("telemetry unavailable")

        def retain_extraction_request(self, _identity: object) -> None:
            raise RuntimeError("storage unavailable")

        def retain_validated_artifact(self, _artifact: object) -> bool:
            raise RuntimeError("storage unavailable")

    case = fixture("pair-current")
    transport = _FakeTransport(case.gold)
    leaf = extract_combined_temporal(
        case.revision,
        transport=transport,
        pipeline=_ProviderFreePipeline(),
        donor_store=ExplodingStore(),  # type: ignore[arg-type]
    )

    assert transport.calls == 1
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert leaf.payload == case.gold
    assert leaf.graph_effect_attempted is False
