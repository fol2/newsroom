"""#790 Step 16 P1: canonical final receipt binds projection_receipt."""

from __future__ import annotations

import copy
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.extraction.types import ExtractionOutcome
from newsroom.graphiti_adapter.combined_temporal_contract import SourceRevisionInput
from newsroom.graphiti_adapter.combined_temporal_evidence import segment_source
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
    extract_combined_temporal,
)
from newsroom.graphiti_adapter.combined_temporal_projection import (
    PROJECTION_POLICY_DIGEST,
    PROJECTION_POLICY_VERSION,
    PROJECTION_RECEIPT_SCHEMA_VERSION,
    project_governed_proposals,
    validate_projection_receipt,
)
from newsroom.graphiti_adapter.combined_temporal_types import CombinedTemporalError
from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for_body
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_CORE_RELEASE
from newsroom.graphiti_adapter.real import RealGraphitiAdapter
from newsroom.graphiti_adapter.result_snapshot import restore_validated_snapshot
from newsroom.graphiti_adapter.temporal_vocabulary import TemporalBasis
from newsroom.graphiti_adapter.types import GraphitiAdapterContractError
from newsroom.tests.test_graphiti_adapter_real_executor import (
    _provider_free_pipeline,
    _real_attempt,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "issue_790_step13_15_raw"


def _load_step(step: int) -> dict:
    return json.loads((_FIXTURES / f"step{step}.json").read_text(encoding="utf-8"))


def _projection_for_step(step: int):
    fix = _load_step(step)
    return project_governed_proposals(
        fix["raw"],
        segment_source(fix["source_body"]),
        UtcTimestamp.parse(fix["reference_time"]).value,
        raw_provider_digest=fix["provider_raw_digest"],
    )


def _attempt_for_step(fix: dict):
    return evaluation_attempt_for_body(
        episode_body=fix["source_body"],
        ingest_id=fix["ingest_id"],
        proving_run_id="issue-790-step16-receipt-binding",
        source_id="issue-790-step16",
        item_key=f"step-{fix['step']}",
        observation_digest=fix["provider_raw_digest"],
        published_at=fix["reference_time"],
        updated_at=None,
        effective_revision=EffectiveRevisionIdentity(
            source_id="issue-790-step16",
            item_key=f"step-{fix['step']}",
            revision_digest=fix["provider_raw_digest"],
            first_observed_at=fix["reference_time"],
        ),
    )


def _install_provider_free_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fixture_raw: dict,
    guard_completed: dict[str, object],
) -> None:
    import newsroom.graphiti_adapter.real as real

    class Episode:
        def __init__(self, **values: object) -> None:
            self.__dict__.update(values)
            self.entity_edges: list[object] = []

        @classmethod
        async def get_by_uuid(cls, _driver: object, episode_id: str) -> object:
            raise Missing(episode_id)

        async def save(self, *_args: object, **_values: object) -> None:
            return None

    class Missing(Exception):
        pass

    class Driver:
        _database = "neo4j"

        def clone(self, **_values: object) -> object:
            raise AssertionError("group_id must not replace the configured database")

    class Graphiti:
        def __init__(self, *_args: object, **values: object) -> None:
            self.driver = Driver()
            self.clients = SimpleNamespace(
                driver=self.driver,
                llm_client=values["llm_client"],
                embedder=values["embedder"],
            )

        async def retrieve_episodes(
            self, *_args: object, **_values: object
        ) -> list[object]:
            return []

        async def close(self) -> None:
            return None

    class Guard:
        async def begin(self) -> object:
            return real.GuardMarker(
                state=real.GuardState.CREATED,
                attempt_number=1,
                input_digest="sha256:" + "0" * 64,
            )

        async def record_pending_telemetry(self, **_values: object) -> None:
            return None

        async def restore_preexisting(self) -> None:
            return None

        @asynccontextmanager
        async def fenced_graph_mutation(self):
            yield

        async def complete(self, raw: dict[str, object]) -> None:
            guard_completed.clear()
            guard_completed["_raw"] = raw
            guard_completed["_id"] = id(raw)

        async def rollback_pending(self, **_values: object) -> bool:
            return True

    class LlmClient:
        invocations: list[dict[str, object]] = []

        async def _generate_response(self, *_args: object, **_values: object) -> object:
            self.invocations.append(
                {
                    "model": "composer-2.5",
                    "usage": {"usage_basis": "PROVIDER_REPORTED", "output_tokens": 32},
                    "outcome": "SUCCESS",
                }
            )
            return fixture_raw

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=SimpleNamespace()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    runtime = SimpleNamespace(
        Graphiti=Graphiti,
        OpenAIEmbedder=lambda **_values: delegate,
        OpenAIEmbedderConfig=lambda **values: SimpleNamespace(**values),
        MeteredOpenAIEmbedder=real.MeteredOpenAIEmbedder,
        IdentityCrossEncoder=lambda: object(),
        EpisodeType=SimpleNamespace(text="text"),
        EpisodicNode=Episode,
        NodeNotFoundError=Missing,
        MutationGuard=lambda *_args, **_values: Guard(),
    )
    monkeypatch.setattr(real, "_load_graphiti", lambda: runtime)
    monkeypatch.setattr(real, "build_cli_llm_client", LlmClient)
    monkeypatch.setattr(real, "combined_temporal_pipeline_for", _provider_free_pipeline)
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "password")


def test_validate_projection_receipt_accepts_exact_step13_receipt() -> None:
    receipt = _projection_for_step(13).receipt
    assert validate_projection_receipt(receipt)["projection_receipt_digest"] == (
        receipt["projection_receipt_digest"]
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda r: r.pop("schema_version", None) or r,
        lambda r: r.pop("projection_receipt_digest", None) or r,
        lambda r: r.__setitem__(
            "projection_receipt_digest", "sha256:" + "0" * 64
        )
        or r,
        lambda r: r.__setitem__(
            "raw_provider_output_digest", "sha256:" + "1" * 64
        )
        or r,
        lambda r: r.__setitem__(
            "accepted_payload_digest", "sha256:" + "2" * 64
        )
        or r,
        lambda r: r.__setitem__(
            "reference_time_digest", "sha256:" + "3" * 64
        )
        or r,
        lambda r: r.__setitem__("accepted_count", 99) or r,
        lambda r: r.__setitem__("rejected_count", 99) or r,
    ],
)
def test_validate_projection_receipt_tamper_matrix_fails_closed(mutator) -> None:
    receipt = dict(_projection_for_step(13).receipt)
    mutator(receipt)
    with pytest.raises(CombinedTemporalError):
        validate_projection_receipt(receipt)


def test_real_success_seals_one_canonical_receipt_with_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fix = _load_step(14)
    projected = _projection_for_step(14)
    assert projected.receipt["accepted_count"] > 0
    guard_completed: dict[str, object] = {}
    _install_provider_free_runtime(
        monkeypatch, fixture_raw=fix["raw"], guard_completed=guard_completed
    )

    produced = RealGraphitiAdapter()._produce(
        _attempt_for_step(fix),
        UtcTimestamp.parse(fix["reference_time"]),
    )

    assert produced.outcome is ExtractionOutcome.SUCCESS
    raw = produced.raw_output_value
    assert isinstance(raw, dict)
    assert guard_completed["_id"] == id(raw)
    assert guard_completed["_raw"] is raw
    combined = raw["combined_temporal_receipt"]
    assert isinstance(combined, dict)
    assert combined["projection_receipt"] == projected.receipt
    validate_projection_receipt(combined["projection_receipt"])
    unsigned = dict(raw)
    unsigned.pop("raw_output_digest")
    assert raw["raw_output_digest"] == digest_bytes(canonical_json_bytes(unsigned))


def test_zero_proposal_terminal_retains_projection_and_no_redispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fix = _load_step(13)
    projected = _projection_for_step(13)
    assert projected.payload == {"entities": [], "facts": []}
    guard_completed: dict[str, object] = {}
    _install_provider_free_runtime(
        monkeypatch, fixture_raw=fix["raw"], guard_completed=guard_completed
    )
    llm_calls = {"n": 0}
    import newsroom.graphiti_adapter.real as real

    class CountingLlm:
        invocations: list[dict[str, object]] = []

        async def _generate_response(self, *_args: object, **_values: object) -> object:
            llm_calls["n"] += 1
            self.invocations.append(
                {
                    "model": "composer-2.5",
                    "usage": {"usage_basis": "PROVIDER_REPORTED", "output_tokens": 8},
                    "outcome": "SUCCESS",
                }
            )
            return fix["raw"]

    monkeypatch.setattr(real, "build_cli_llm_client", CountingLlm)

    produced = RealGraphitiAdapter()._produce(
        _attempt_for_step(fix),
        UtcTimestamp.parse(fix["reference_time"]),
    )

    assert llm_calls["n"] == 1
    assert produced.outcome is ExtractionOutcome.SUCCESS
    raw = produced.raw_output_value
    assert isinstance(raw, dict)
    assert guard_completed["_raw"] is raw
    combined = raw["combined_temporal_receipt"]
    assert isinstance(combined, dict)
    assert combined["projection_receipt"] == projected.receipt
    embedding = raw.get("embedding_usage")
    assert isinstance(embedding, dict)
    assert embedding.get("request_count", 0) in {0, None}
    # No second provider dispatch after terminal zero-proposal success.
    assert llm_calls["n"] == 1


def test_leaf_zero_proposal_also_retains_rejection_evidence() -> None:
    fix = _load_step(13)
    transport_calls = {"n": 0}

    class Transport:
        def generate_response(self, **kwargs: object) -> CombinedTemporalTransportResult:
            del kwargs
            transport_calls["n"] += 1
            return CombinedTemporalTransportResult(
                raw=fix["raw"],
                framework_version=GRAPHITI_CORE_RELEASE,
                model_version="composer-2.5",
                token_usage={"basis": "PROVIDER_REPORTED", "output_tokens": 8},
                provider_cost=None,
            )

    class Pipeline:
        def prepare_attempt(self) -> None:
            return None

        def complete_failure(self, terminal: dict[str, object]) -> dict[str, object]:
            return dict(terminal)

        def execute(self, **kwargs: object) -> SimpleNamespace:
            receipt = dict(kwargs["receipt"])
            validate_projection_receipt(receipt["projection_receipt"])
            return SimpleNamespace(
                nodes=(),
                edges=(),
                guarded_edges=(),
                node_resolutions=(),
                graph_effect_attempted=False,
                embedding_skipped=True,
                journal_skipped=True,
                rollback_skipped=True,
                completed_receipt=receipt,
            )

    revision = SourceRevisionInput(
        body=fix["source_body"],
        revision_id="rev",
        source_id="src",
        item_key="item",
        representation_digest="sha256:" + "ab" * 32,
        published_at=fix["reference_time"],
        updated_at=None,
        observed_at=fix["reference_time"],
        ingested_at=fix["reference_time"],
    )
    leaf = extract_combined_temporal(
        revision, transport=Transport(), pipeline=Pipeline()
    )
    assert transport_calls["n"] == 1
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
    assert leaf.graph_effect_attempted is False
    assert leaf.embedding_skipped is True
    assert leaf.payload == {"entities": [], "facts": []}


def test_guard_completed_immutable_replay_restores_projection(
    tmp_path: Path,
) -> None:
    from newsroom.graphiti_adapter.real import _EpisodeTelemetry, _raw_receipt

    fix = _load_step(14)
    projected = _projection_for_step(14)
    instant = UtcTimestamp.parse(fix["reference_time"])
    attempt = replace(
        _real_attempt(tmp_path),
        reference_time=instant,
        temporal_basis=TemporalBasis.SOURCE_PUBLISHED,
        episode_uuid="episode-replay",
    )
    raw = _raw_receipt(
        attempt,
        started_at=instant,
        telemetry=_EpisodeTelemetry(provider_attempt_number=1),
        result=None,
        proposals=(),
    )
    raw.pop("raw_output_digest", None)
    raw["combined_temporal_receipt"] = {
        "projection_receipt": projected.receipt,
        "raw_output_digest": fix["provider_raw_digest"],
    }
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))

    restored = restore_validated_snapshot(raw=raw, attempt=attempt)
    assert restored.produced.outcome is ExtractionOutcome.SUCCESS
    assert restored.produced.raw_output_value == raw
    combined = restored.produced.raw_output_value["combined_temporal_receipt"]
    assert combined["projection_receipt"] == projected.receipt

    absent_combined = copy.deepcopy(raw)
    absent_combined.pop("combined_temporal_receipt")
    absent_combined.pop("raw_output_digest")
    absent_combined["raw_output_digest"] = digest_bytes(
        canonical_json_bytes(absent_combined)
    )
    with pytest.raises(
        GraphitiAdapterContractError, match="lacks combined_temporal_receipt"
    ):
        restore_validated_snapshot(raw=absent_combined, attempt=attempt)

    missing = copy.deepcopy(raw)
    missing["combined_temporal_receipt"] = {
        "raw_output_digest": fix["provider_raw_digest"]
    }
    missing.pop("raw_output_digest")
    missing["raw_output_digest"] = digest_bytes(canonical_json_bytes(missing))
    with pytest.raises(GraphitiAdapterContractError, match="lacks projection_receipt"):
        restore_validated_snapshot(raw=missing, attempt=attempt)

    tampered = copy.deepcopy(raw)
    tampered["combined_temporal_receipt"]["projection_receipt"] = dict(
        projected.receipt
    )
    tampered["combined_temporal_receipt"]["projection_receipt"][
        "projection_receipt_digest"
    ] = "sha256:" + "a" * 64
    tampered.pop("raw_output_digest")
    tampered["raw_output_digest"] = digest_bytes(canonical_json_bytes(tampered))
    with pytest.raises(GraphitiAdapterContractError, match="projection receipt"):
        restore_validated_snapshot(raw=tampered, attempt=attempt)


def test_evaluation_runner_raw_receipt_binds_identical_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control Plane EvaluationGraphitiRunner retains the sealed projection receipt."""
    from newsroom.control_plane.corpus import CorpusIngestUnit
    from newsroom.control_plane.graphiti import EvaluationGraphitiRunner

    fix = _load_step(14)
    projected = _projection_for_step(14)
    guard_completed: dict[str, object] = {}
    _install_provider_free_runtime(
        monkeypatch, fixture_raw=fix["raw"], guard_completed=guard_completed
    )
    unit = CorpusIngestUnit(
        source_id="issue-790-step16",
        item_key="step-14",
        headline="",
        body=fix["source_body"],
        canonical_url="",
        observation_digest=fix["provider_raw_digest"],
        observed_at=fix["reference_time"],
        proving_run_id="issue-790-step16-receipt-binding",
        effective_revision=EffectiveRevisionIdentity(
            source_id="issue-790-step16",
            item_key="step-14",
            revision_digest=fix["provider_raw_digest"],
            first_observed_at=fix["reference_time"],
        ),
        published_at=fix["reference_time"],
    )
    result = EvaluationGraphitiRunner(
        clock=lambda: UtcTimestamp.parse(fix["reference_time"]).value
    ).ingest(unit)
    assert result.outcome == "COMPLETE"
    assert result.raw_receipt is guard_completed["_raw"]
    assert result.raw_receipt is not None
    assert result.raw_receipt["combined_temporal_receipt"]["projection_receipt"] == (
        projected.receipt
    )
    unsigned = dict(result.raw_receipt)
    supplied = unsigned.pop("raw_output_digest")
    assert supplied == digest_bytes(canonical_json_bytes(unsigned))
    assert result.receipt_digest == supplied


def test_step13_15_fixtures_still_project() -> None:
    for step in (13, 14, 15):
        result = _projection_for_step(step)
        validate_projection_receipt(result.receipt)
        assert result.receipt["projection_policy_version"] == PROJECTION_POLICY_VERSION
        assert result.receipt["projection_policy_digest"] == PROJECTION_POLICY_DIGEST
        assert result.receipt["schema_version"] == PROJECTION_RECEIPT_SCHEMA_VERSION
    assert _projection_for_step(13).payload == {"entities": [], "facts": []}
    assert _projection_for_step(14).receipt["rejected_count"] == 0
    assert _projection_for_step(15).receipt["rejected_count"] == 0


def test_draft_keeps_owner_approval_unsatisfied() -> None:
    draft = json.loads(
        Path(
            "docs/operations/2026-08-28-issue-790-success-sequence-step-16-draft.json"
        ).read_text(encoding="utf-8")
    )
    assert draft["executable"] is False
    assert "OWNER_AUTHENTICATED_STEP_16_CANARY_APPROVAL" in draft["blocked_until"]
    assert (
        "OWNER_AUTHENTICATED_STEP_16_CANARY_APPROVAL"
        not in draft["satisfied_prerequisites"]
    )
