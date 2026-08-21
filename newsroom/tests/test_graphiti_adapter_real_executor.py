from __future__ import annotations

import asyncio
import inspect
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority._graphiti_adapter_boundary import _GraphitiAdapterBoundary
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import UtcTimestamp
from newsroom.extraction.types import (
    ExtractionFailureCode,
    ExtractionOutcome,
    VersionedExtractionComponent,
)
from newsroom.extraction.models import ExtractorContractRequest
from newsroom.graphiti_adapter import (
    DeterministicFakeGraphitiAdapter,
    GraphitiAdapterConfiguration,
    GraphitiAdapterConfigurationId,
    GraphitiAdapterContractError,
    GraphitiAttemptId,
    GraphitiAttemptRequest,
    GraphitiCleanupReceiptId,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiInputManifest,
    GraphitiInputManifestId,
    GraphitiRuntimeMode,
    GraphitiRuntimeNotAuthorized,
    GraphitiWorkspaceId,
    GraphitiWorkspacePolicy,
    GraphitiWorkspacePolicyId,
    REAL_GRAPHITI_RUNTIME_ENABLED,
    RealGraphitiRuntimeAuthority,
)
from newsroom.graphiti_adapter.contracts import (
    GRAPHITI_ADAPTER_CODE_COMPONENT,
    GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
    GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
    GRAPHITI_ADAPTER_POLICY_COMPONENT,
    GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
    GRAPHITI_PROMPT_COMPONENT,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    EVALUATION_GRAPHITI_PACKET,
    EVALUATION_WORKSPACE_POLICY,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_WORKSPACE_GROUP,
)
from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
from newsroom.graphiti_adapter.real import RealGraphitiAdapter
from newsroom.graphiti_adapter.recovery_vocabulary import (
    GraphitiRecoveryClassification,
)
from newsroom.graphiti_adapter.neo4j_guard import GuardMarker, GuardState
from newsroom.graphiti_adapter.temporal_vocabulary import TemporalBasis

from .extraction_4a_helpers import contract_request, run_request, seed_extraction_fixture
from .graphiti_adapter_4d_helpers import FAKE_CONFIGURATION_ID

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_CONFIGURATION_ID = GraphitiAdapterConfigurationId.parse(
    "00000000-0000-4000-8000-000000004930"
)
EVALUATION_MANIFEST_ID = GraphitiInputManifestId.parse(
    "00000000-0000-4000-8000-000000004931"
)
EVALUATION_WORKSPACE_ID = GraphitiWorkspaceId.parse(
    "00000000-0000-4000-8000-000000004932"
)
EVALUATION_CLEANUP_ID = GraphitiCleanupReceiptId.parse(
    "00000000-0000-4000-8000-000000004933"
)
EVALUATION_ATTEMPT_ID = GraphitiAttemptId.parse(
    "00000000-0000-4000-8000-000000004934"
)


def _digest(label: str) -> str:
    return digest_canonical({"contract": label})


def _placeholder_authority() -> RealGraphitiRuntimeAuthority:
    return RealGraphitiRuntimeAuthority(
        authority_decision_digest=_digest("owner-decision"),
        framework_release="graphiti-placeholder-release",
        model_release="model-placeholder-release",
        embedding_release="embedding-placeholder-release",
        destination_contract_digest=_digest("destination"),
        data_processing_terms_digest=_digest("terms"),
        prompt_contract_digest=_digest("prompt"),
        output_schema_contract_digest=_digest("output"),
        permitted_expression_digest=_digest("expression"),
        rights_privacy_retention_digest=_digest("rights"),
        workspace_security_digest=_digest("workspace"),
        egress_credential_digest=_digest("egress"),
        budget_digest=_digest("budget"),
        evaluation_plan_digest=_digest("evaluation"),
        rollback_digest=_digest("rollback"),
    )


def _real_configuration(
    contract: ExtractorContractRequest,
    *,
    execution_profile: GraphitiExecutionProfile = GraphitiExecutionProfile.EVALUATION,
    authority: RealGraphitiRuntimeAuthority | None = None,
    workspace_policy: GraphitiWorkspacePolicy | None = None,
    framework_version: str = GRAPHITI_CORE_RELEASE,
    model_version: str = GRAPHITI_CHAT_MODEL,
    embedding_version: str = GRAPHITI_EMBEDDING_MODEL,
) -> GraphitiAdapterConfiguration:
    digest = _digest("evaluation-component")
    return GraphitiAdapterConfiguration(
        configuration_id=EVALUATION_CONFIGURATION_ID,
        runtime_mode=GraphitiRuntimeMode.REAL_GRAPHITI,
        execution_profile=execution_profile,
        framework=VersionedExtractionComponent(
            "graphiti.framework", framework_version, digest
        ),
        model=VersionedExtractionComponent("graphiti.model", model_version, digest),
        embedding=VersionedExtractionComponent(
            "graphiti.embedding", embedding_version, digest
        ),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=workspace_policy or EVALUATION_WORKSPACE_POLICY,
        fixture_case=None,
        real_runtime_authority=authority or EVALUATION_GRAPHITI_PACKET,
        idempotency_key="evaluation-real-adapter-v1",
    )


def _real_attempt(
    tmp_path: Path,
    *,
    execution_profile: GraphitiExecutionProfile = GraphitiExecutionProfile.EVALUATION,
    authority: RealGraphitiRuntimeAuthority | None = None,
    workspace_policy: GraphitiWorkspacePolicy | None = None,
) -> GraphitiAttemptRequest:
    state = seed_extraction_fixture(tmp_path / "authority")
    contract = contract_request()
    request = run_request(state, contract_id=contract.contract_id)
    configuration = _real_configuration(
        contract,
        execution_profile=execution_profile,
        authority=authority,
        workspace_policy=workspace_policy,
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=EVALUATION_MANIFEST_ID,
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=EVALUATION_ATTEMPT_ID,
        attempt_number=1,
        expected_previous_attempt_id=None,
        configuration=configuration,
        workspace_id=EVALUATION_WORKSPACE_ID,
        cleanup_receipt_id=EVALUATION_CLEANUP_ID,
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=None,
        idempotency_key="evaluation-real-attempt-v1",
    )


def test_flag_is_true_for_evaluation_and_graphiti_core_is_an_optional_extra() -> None:
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True
    pyproject = (_REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "graphiti-core==0.29.3" in pyproject
    assert "[project.optional-dependencies]" in pyproject
    lock = (_REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "graphiti-core"' in lock
    assert 'version = "0.29.3"' in lock


def test_cli_llm_client_is_wired_for_graphiti_chat() -> None:
    from newsroom.graphiti_adapter.evaluation_packet import (
        CURSOR_AGENT_MODEL_ID,
        GRAPHITI_CHAT_FALLBACK,
        GRAPHITI_CHAT_MODEL,
        GROK_CHAT_REASONING,
    )
    from newsroom.graphiti_adapter.real import _add_episode, _ensure_episode

    source = inspect.getsource(_add_episode)
    assert "build_cli_llm_client" in source
    assert "OpenAIGenericClient" not in source
    assert "reference_time or started_at" not in inspect.getsource(
        RealGraphitiAdapter._produce
    )
    assert GRAPHITI_CHAT_MODEL == "cursor-agent-cli:composer-2.5"
    assert GRAPHITI_CHAT_FALLBACK == "grok-build-cli:grok-4.6-medium"
    assert CURSOR_AGENT_MODEL_ID == "composer-2.5"
    assert GROK_CHAT_REASONING == "medium"
    assert "uuid=episode_id" in source
    assert "EpisodicNode.get_by_uuid" in inspect.getsource(_ensure_episode)
    assert "EpisodicNode(" in inspect.getsource(_ensure_episode)
    assert "GRAPHITI_EXTRACTION_INSTRUCTIONS" in source


def test_guarded_graphiti_never_invalidates_or_reuses_existing_edges(
) -> None:
    from newsroom.graphiti_adapter.edge_guard import guard_extracted_edges

    proposed = SimpleNamespace(
        source_node_uuid="source",
        target_node_uuid="target",
        fact="same fact as a pre-existing edge",
    )
    calls: list[str] = []

    def resolve(values: list[object], _uuid_map: dict[str, str]) -> list[object]:
        calls.append("resolve")
        return values

    async def embed(_embedder: object, values: list[object]) -> None:
        assert values == [proposed]
        calls.append("embed")

    new_edges, invalidated, episode_edges = asyncio.run(
        guard_extracted_edges(
            extracted_edges=[proposed],
            uuid_map={},
            embedder=object(),
            resolve_pointers=resolve,
            create_embeddings=embed,
        )
    )
    assert calls == ["resolve", "embed"]
    assert new_edges == [proposed]
    assert invalidated == []
    assert episode_edges == [proposed]


def test_cursor_malformed_json_executes_grok_fallback_and_records_both_calls() -> None:
    from newsroom.graphiti_adapter.cli_client import run_cli_chain

    calls: list[str] = []

    def cursor(_prompt: str) -> str:
        calls.append("cursor")
        return "not-json"

    def grok(_prompt: str, _schema: str | None) -> str:
        calls.append("grok")
        return '{"value":"fallback"}'

    invocations: list[dict[str, object]] = []
    result = asyncio.run(
        run_cli_chain(
            prompt="prompt",
            schema='{"type":"object"}',
            cursor_runner=cursor,
            grok_runner=grok,
            invocations=invocations,
        )
    )
    assert result == {"value": "fallback"}
    assert calls == ["cursor", "grok"]
    assert [item["provider"] for item in invocations] == [
        "cursor-agent-cli",
        "grok-build-cli",
    ]
    assert [item["model"] for item in invocations] == ["composer-2.5", "grok-4.6"]
    assert [item["outcome"] for item in invocations] == [
        "MALFORMED_OUTPUT",
        "COMPLETE",
    ]
    assert [item["usage"]["usage_basis"] for item in invocations] == [
        "UNREPORTED",
        "UNREPORTED",
    ]


def test_both_cli_malformed_json_results_fail_after_recording_both_calls() -> None:
    from newsroom.graphiti_adapter.cli_client import CliResponseError, run_cli_chain

    invocations: list[dict[str, object]] = []
    with pytest.raises(CliResponseError, match="JSON was not an object"):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=lambda _prompt: "[]",
                grok_runner=lambda _prompt, _schema: "also malformed",
                invocations=invocations,
            )
        )
    assert [item["outcome"] for item in invocations] == [
        "MALFORMED_OUTPUT",
        "MALFORMED_OUTPUT",
    ]


def test_non_utf8_cursor_is_recorded_before_grok_fallback() -> None:
    from newsroom.graphiti_adapter.cli_client import run_cli_async, run_cli_chain

    async def invalid_cursor(_prompt: str) -> str:
        return await run_cli_async(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'\\xff')",
            ),
            timeout=5,
        )

    invocations: list[dict[str, object]] = []
    result = asyncio.run(
        run_cli_chain(
            prompt="prompt",
            schema=None,
            cursor_runner=invalid_cursor,
            grok_runner=lambda _prompt, _schema: '{"value":"fallback"}',
            invocations=invocations,
        )
    )
    assert result == {"value": "fallback"}
    assert [item["outcome"] for item in invocations] == ["FAILED", "COMPLETE"]
    assert invocations[0]["failure"] == "CliOutputDecodeError"


def test_non_utf8_grok_is_recorded_before_chain_failure() -> None:
    from newsroom.graphiti_adapter.cli_client import (
        CliResponseError,
        run_cli_async,
        run_cli_chain,
    )

    async def invalid_grok(_prompt: str, _schema: str | None) -> str:
        return await run_cli_async(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'\\xff')",
            ),
            timeout=5,
        )

    invocations: list[dict[str, object]] = []
    with pytest.raises(CliResponseError, match="fallback CLI failed"):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=lambda _prompt: "not-json",
                grok_runner=invalid_grok,
                invocations=invocations,
            )
        )
    assert [item["outcome"] for item in invocations] == [
        "MALFORMED_OUTPUT",
        "FAILED",
    ]
    assert invocations[1]["failure"] == "CliOutputDecodeError"


def test_sync_cli_rejects_non_utf8_output_with_typed_failure() -> None:
    from newsroom.graphiti_adapter.cli_client import (
        CliOutputDecodeError,
        run_cli,
    )

    with pytest.raises(CliOutputDecodeError, match="malformed UTF-8"):
        run_cli(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'\\xff')",
            ),
            timeout=5,
        )


@pytest.mark.parametrize("cancelled_provider", ["cursor", "grok"])
def test_cli_deadline_cancellation_is_recorded(cancelled_provider: str) -> None:
    from newsroom.graphiti_adapter.cli_client import run_cli_chain

    async def cancelled_cursor(_prompt: str) -> str:
        raise asyncio.CancelledError

    async def malformed_cursor(_prompt: str) -> str:
        return "not-json"

    async def cancelled_grok(_prompt: str, _schema: str | None) -> str:
        raise asyncio.CancelledError

    invocations: list[dict[str, object]] = []
    cursor = cancelled_cursor if cancelled_provider == "cursor" else malformed_cursor
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=cursor,
                grok_runner=cancelled_grok,
                invocations=invocations,
            )
        )

    expected_provider = (
        "cursor-agent-cli" if cancelled_provider == "cursor" else "grok-build-cli"
    )
    assert invocations[-1]["provider"] == expected_provider
    assert invocations[-1]["outcome"] == "CANCELLED"
    assert invocations[-1]["failure"] == "CancelledError"
    expected_outcomes = (
        ["CANCELLED"]
        if cancelled_provider == "cursor"
        else ["MALFORMED_OUTPUT", "CANCELLED"]
    )
    assert [item["outcome"] for item in invocations] == expected_outcomes


def test_deterministic_episode_creation_rejects_unmarked_retained_identity() -> None:
    from newsroom.graphiti_adapter.real import _ensure_episode

    class Missing(Exception):
        pass

    retained: dict[str, object] = {}
    saves: list[str] = []

    class Episode:
        def __init__(self, **values: object) -> None:
            for key, value in values.items():
                setattr(self, key, value)

        @classmethod
        async def get_by_uuid(cls, _driver: object, uuid: str) -> object:
            if uuid not in retained:
                raise Missing(uuid)
            return retained[uuid]

        async def save(self, _driver: object) -> None:
            retained[str(self.uuid)] = self
            saves.append(str(self.uuid))

    runtime = SimpleNamespace(
        EpisodicNode=Episode,
        NodeNotFoundError=Missing,
        EpisodeType=SimpleNamespace(text="text"),
    )
    graphiti = SimpleNamespace(driver=object())
    reference = datetime(2026, 8, 20, tzinfo=UTC)
    arguments = {
        "graphiti": graphiti,
        "runtime": runtime,
        "episode_id": "deterministic-id",
        "name": "deterministic-id",
        "body": "retained body",
        "reference_time": reference,
    }
    _episode, first_state = asyncio.run(_ensure_episode(**arguments))
    _episode, retained_state = asyncio.run(_ensure_episode(**arguments))
    assert first_state == "CREATED"
    assert retained_state == "RETAINED"
    assert saves == ["deterministic-id"]
    assert tuple(retained) == ("deterministic-id",)


def test_durable_guard_marker_restores_original_provider_metering() -> None:
    from newsroom.graphiti_adapter.real import (
        _EpisodeTelemetry,
        _restore_marker_telemetry,
    )
    from newsroom.graphiti_adapter.neo4j_guard import GuardMarker, GuardState

    telemetry = _EpisodeTelemetry()
    marker = GuardMarker(
        state=GuardState.COMPLETE,
        attempt_number=1,
        input_digest="sha256:" + "0" * 64,
        chat_invocations=({"provider": "cursor-agent-cli"},),
        embedding_usage={
            "usage_basis": "PROVIDER_REPORTED",
            "request_count": 1,
            "cost_usd_microunits": 17,
        },
    )
    _restore_marker_telemetry(telemetry, marker)
    assert telemetry.provider_attempt_number == 1
    assert telemetry.embedding_usage["cost_usd_microunits"] == 17
    assert telemetry.chat_invocations == [{"provider": "cursor-agent-cli"}]


def test_episode_uses_default_database_and_validates_before_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    class Missing(Exception):
        pass

    retained: dict[str, object] = {}
    saves: list[str] = []
    guard_events: list[str] = []

    class Episode:
        def __init__(self, **values: object) -> None:
            for key, value in values.items():
                setattr(self, key, value)
            self.entity_edges = []

        @classmethod
        async def get_by_uuid(cls, _driver: object, episode_id: str) -> object:
            if episode_id not in retained:
                raise Missing(episode_id)
            return retained[episode_id]

        async def save(self, _driver: object) -> None:
            retained[str(self.uuid)] = self
            saves.append(str(self.uuid))

    class Driver:
        _database = "neo4j"

        def clone(self, **_values: object) -> object:
            raise AssertionError("group_id must not replace the configured database")

    class Graphiti:
        def __init__(self, *_args: object, **_values: object) -> None:
            self.driver = Driver()
            self.clients = SimpleNamespace(driver=self.driver)

        async def retrieve_episodes(
            self, *_args: object, **_values: object
        ) -> list[object]:
            raise AssertionError(
                "ambient episodes have no current rights proof and must not be reused"
            )

        async def add_episode(self, **values: object) -> object:
            assert values["group_id"] == GRAPHITI_WORKSPACE_GROUP
            assert values["previous_episode_uuids"] == []
            return SimpleNamespace(
                episode=retained[str(values["uuid"])],
                nodes=(),
                edges=(),
            )

        async def close(self) -> None:
            return None

    class Guard:
        async def begin(self) -> object:
            guard_events.append("begin")
            return real.GuardMarker(
                state=real.GuardState.CREATED,
                attempt_number=1,
                input_digest="sha256:" + "0" * 64,
            )

        async def record_pending_telemetry(self, **_values: object) -> None:
            guard_events.append("metered")

        async def restore_preexisting(self) -> None:
            guard_events.append("restored")

        async def complete(self, raw: dict[str, object]) -> None:
            assert raw == {"provider_attempt_number": 1}
            guard_events.append("complete")

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
        IdentityCrossEncoder=lambda: object(),
        EpisodeType=SimpleNamespace(text="text"),
        EpisodicNode=Episode,
        NodeNotFoundError=Missing,
        MutationGuard=lambda *_args, **_values: Guard(),
    )
    monkeypatch.setattr(real, "_load_graphiti", lambda: runtime)
    monkeypatch.setattr(
        real,
        "build_cli_llm_client",
        lambda: SimpleNamespace(invocations=[]),
    )
    telemetry = real._EpisodeTelemetry()
    validation_states: list[str] = []

    def validate(_result: object, _telemetry: object) -> dict[str, object]:
        validation_states.append(guard_events[-1])
        return {"provider_attempt_number": 1}

    result = asyncio.run(
        real._add_episode(
            api_key="key",
            password="password",
            body="Body",
            name="episode-id",
            episode_id="episode-id",
            reference_time=datetime(2026, 8, 20, tzinfo=UTC),
            telemetry=telemetry,
            attempt_number=1,
            validate_result=validate,
            restore_result=lambda _raw, _telemetry: None,
        )
    )
    assert result.episode.uuid == "episode-id"
    assert validation_states == ["restored"]
    assert guard_events == ["begin", "metered", "restored", "complete"]
    assert saves == ["episode-id"]


@pytest.mark.parametrize(
    ("state", "expected_event"),
    [
        ("COMPLETE", "restore_complete"),
        ("PENDING", "rollback_pending"),
    ],
)
def test_process_recovery_uses_durable_guard_before_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    expected_event: str,
) -> None:
    import newsroom.graphiti_adapter.real as real

    events: list[str] = []

    class Graphiti:
        def __init__(self, *_args: object, **_values: object) -> None:
            self.driver = object()

        async def add_episode(self, **_values: object) -> object:
            raise AssertionError("recovery must happen before provider dispatch")

        async def close(self) -> None:
            events.append("close")

    class Guard:
        async def begin(self) -> object:
            return real.GuardMarker(
                state=real.GuardState(state),
                attempt_number=1,
                input_digest="sha256:" + "0" * 64,
                embedding_usage={
                    "usage_basis": "PROVIDER_REPORTED",
                    "request_count": 1,
                    "cost_usd_microunits": 7,
                },
            )

        async def completed_raw(self) -> dict[str, object]:
            return {"immutable": True}

        async def rollback_pending(self, **_values: object) -> None:
            events.append("rollback_pending")

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=SimpleNamespace()),
        config=SimpleNamespace(embedding_model="model", embedding_dim=2),
    )
    runtime = SimpleNamespace(
        Graphiti=Graphiti,
        OpenAIEmbedder=lambda **_values: delegate,
        OpenAIEmbedderConfig=lambda **values: SimpleNamespace(**values),
        IdentityCrossEncoder=lambda: object(),
        MutationGuard=lambda *_args, **_values: Guard(),
    )
    monkeypatch.setattr(real, "_load_graphiti", lambda: runtime)
    monkeypatch.setattr(
        real, "build_cli_llm_client", lambda: SimpleNamespace(invocations=[])
    )

    def restore(raw: dict[str, object], _telemetry: object) -> None:
        assert raw == {"immutable": True}
        events.append("restore_complete")

    call = real._add_episode(
        api_key="key",
        password="password",
        body="Body",
        name="episode-id",
        episode_id="episode-id",
        reference_time=datetime(2026, 8, 20, tzinfo=UTC),
        telemetry=real._EpisodeTelemetry(),
        attempt_number=1,
        validate_result=lambda _result, _telemetry: {},
        restore_result=restore,
    )
    if state == "PENDING":
        with pytest.raises(real.AmbiguousEpisodeEffect, match="process ended"):
            asyncio.run(call)
    else:
        asyncio.run(call)
    assert events == [expected_event, "close"]


@pytest.mark.parametrize("slow_cleanup", (False, True))
def test_cancelled_episode_cleanup_is_ordered_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    slow_cleanup: bool,
) -> None:
    import newsroom.graphiti_adapter.real as real

    events: list[str] = []

    class Graphiti:
        def __init__(self, *_args: object, **_values: object) -> None:
            self.driver = object()

        async def add_episode(self, **_values: object) -> SimpleNamespace:
            events.append("provider-start")
            await asyncio.Event().wait()
            raise AssertionError("cancelled provider unexpectedly resumed")

        async def close(self) -> None:
            events.append("close")
            if slow_cleanup:
                await asyncio.Event().wait()

    class Guard:
        async def begin(self) -> GuardMarker:
            return GuardMarker(
                state=GuardState.CREATED,
                attempt_number=1,
                input_digest="sha256:" + "0" * 64,
            )

        async def record_pending_telemetry(self, **_values: object) -> None:
            events.append("telemetry")

        async def rollback_pending(self, **_values: object) -> None:
            events.append("rollback")
            if slow_cleanup:
                await asyncio.Event().wait()

    async def created_episode(**_values: object) -> tuple[SimpleNamespace, str]:
        return SimpleNamespace(uuid="episode-id"), "CREATED"

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=SimpleNamespace()),
        config=SimpleNamespace(embedding_model="model", embedding_dim=2),
    )
    runtime = SimpleNamespace(
        Graphiti=Graphiti,
        OpenAIEmbedder=lambda **_values: delegate,
        OpenAIEmbedderConfig=lambda **values: SimpleNamespace(**values),
        IdentityCrossEncoder=lambda: object(),
        EpisodeType=SimpleNamespace(text="text"),
        MutationGuard=lambda *_args, **_values: Guard(),
    )
    monkeypatch.setattr(real, "_load_graphiti", lambda: runtime)
    monkeypatch.setattr(real, "_ensure_episode", created_episode)
    monkeypatch.setattr(
        real, "build_cli_llm_client", lambda: SimpleNamespace(invocations=[])
    )
    if slow_cleanup:
        monkeypatch.setattr(real, "GRAPHITI_CLEANUP_TIMEOUT_MS", 10)

    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            asyncio.wait_for(
                real._add_episode(
                    api_key="key",
                    password="password",
                    body="Body",
                    name="episode-id",
                    episode_id="episode-id",
                    reference_time=datetime(2026, 8, 20, tzinfo=UTC),
                    telemetry=real._EpisodeTelemetry(),
                    attempt_number=1,
                    validate_result=lambda _result, _telemetry: {},
                    restore_result=lambda _raw, _telemetry: None,
                ),
                timeout=0.01,
            )
        )
    elapsed = time.monotonic() - started
    assert events == ["provider-start", "telemetry", "rollback", "close"]
    if slow_cleanup:
        assert elapsed < 0.2


def test_pending_guard_recovery_uses_retained_attempt_snapshot() -> None:
    from newsroom.graphiti_adapter.neo4j_guard import Neo4jMutationGuard

    snapshot_ids: list[str] = []
    marker = {
        "state": "PENDING",
        "group_id": GRAPHITI_WORKSPACE_GROUP,
        "attempt_number": 1,
        "input_digest": "sha256:" + "0" * 64,
        "snapshot_id": "episode-id:1",
        "chat_invocations_json": "[]",
        "embedding_usage_json": "null",
    }

    class Driver:
        async def execute_query(
            self,
            query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            assert routing_ == "w"
            snapshot_id = params.get("snapshot_id")
            if isinstance(snapshot_id, str):
                snapshot_ids.append(snapshot_id)
            if "RETURN properties(m) AS marker" in query:
                return ([{"marker": marker}], None, None)
            if "SET m.state = 'ROLLING_BACK'" in query:
                marker["state"] = "ROLLING_BACK"
                return ([{"state": "ROLLING_BACK"}], None, None)
            if "SET m.state = 'RECOVERED_AMBIGUOUS'" in query:
                marker["state"] = "RECOVERED_AMBIGUOUS"
                return ([{"state": "RECOVERED_AMBIGUOUS"}], None, None)
            return ([], None, None)

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=2,
        input_digest="sha256:" + "0" * 64,
    )
    retained = asyncio.run(guard.begin())
    assert retained.attempt_number == 1
    assert asyncio.run(
        guard.rollback_pending(
            chat_invocations=[],
            embedding_usage={"usage_basis": "NO_EMBEDDING_CALL"},
            reason="RECOVERED_PENDING_PROCESS_DEATH",
        )
    )
    assert snapshot_ids
    assert set(snapshot_ids) == {"episode-id:1"}


@pytest.mark.parametrize("state", ["SNAPSHOTTING", "RECOVERED_AMBIGUOUS"])
def test_guard_retry_resets_snapshot_after_retained_attempt_cleanup(
    state: str,
) -> None:
    from newsroom.graphiti_adapter.neo4j_guard import Neo4jMutationGuard

    marker: dict[str, object] | None = {
        "state": state,
        "group_id": GRAPHITI_WORKSPACE_GROUP,
        "attempt_number": 1,
        "input_digest": "sha256:" + "0" * 64,
        "snapshot_id": "episode-id:1",
        "chat_invocations_json": "[]",
        "embedding_usage_json": "null",
    }
    deleted_snapshots: list[str] = []
    created_snapshots: list[str] = []

    class Driver:
        async def execute_query(
            self,
            query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            nonlocal marker
            assert routing_ == "w"
            if "RETURN properties(m) AS marker" in query:
                return ([] if marker is None else [{"marker": marker}], None, None)
            if "NewsroomSnapshot" in query and "DELETE s" in query:
                deleted_snapshots.append(str(params["snapshot_id"]))
            if "MATCH (m:NewsroomIngestMarker" in query and "DELETE m" in query:
                marker = None
            if "CREATE (m:NewsroomIngestMarker" in query:
                created_snapshots.append(str(params["snapshot_id"]))
            return ([], None, None)

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=2,
        input_digest="sha256:" + "0" * 64,
    )
    created = asyncio.run(guard.begin())
    assert created.attempt_number == 2
    assert created_snapshots == ["episode-id:2"]
    assert deleted_snapshots == ["episode-id:1"]


def test_guard_rejects_mismatched_retained_snapshot_identity() -> None:
    from newsroom.graphiti_adapter.neo4j_guard import GuardError, Neo4jMutationGuard

    marker = {
        "state": "PENDING",
        "group_id": GRAPHITI_WORKSPACE_GROUP,
        "attempt_number": 1,
        "input_digest": "sha256:" + "0" * 64,
        "snapshot_id": "episode-id:2",
        "chat_invocations_json": "[]",
        "embedding_usage_json": "null",
    }

    class Driver:
        async def execute_query(
            self,
            _query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            assert params == {"episode_uuid": "episode-id"}
            assert routing_ == "w"
            return ([{"marker": marker}], None, None)

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=2,
        input_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(GuardError, match="snapshot identity"):
        asyncio.run(guard.begin())


def test_complete_guard_recovery_cleans_crash_window_snapshot() -> None:
    from newsroom.graphiti_adapter.neo4j_guard import Neo4jMutationGuard

    deleted_snapshots: list[str] = []
    marker = {
        "state": "COMPLETE",
        "group_id": GRAPHITI_WORKSPACE_GROUP,
        "attempt_number": 1,
        "input_digest": "sha256:" + "0" * 64,
        "snapshot_id": "episode-id:1",
        "chat_invocations_json": "[]",
        "embedding_usage_json": "null",
    }

    class Driver:
        async def execute_query(
            self,
            query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            assert routing_ == "w"
            if "RETURN properties(m) AS marker" in query:
                return ([{"marker": marker}], None, None)
            if "NewsroomSnapshot" in query and "DELETE s" in query:
                deleted_snapshots.append(str(params["snapshot_id"]))
            return ([], None, None)

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=2,
        input_digest="sha256:" + "0" * 64,
    )
    retained = asyncio.run(guard.begin())
    assert retained.state.value == "COMPLETE"
    assert deleted_snapshots == ["episode-id:1"]


def test_complete_guard_recovery_requires_byte_exact_canonical_snapshot() -> None:
    from newsroom.graphiti_adapter.neo4j_guard import (
        GuardError,
        Neo4jMutationGuard,
    )

    raw = {"provider_attempt_number": 1, "result": "fixed"}
    raw_json = canonical_json_bytes(raw).decode("utf-8")
    marker = {
        "state": "COMPLETE",
        "validated_raw_json": raw_json,
        "validated_raw_digest": digest_bytes(raw_json.encode("utf-8")),
    }

    class Driver:
        async def execute_query(
            self,
            _query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            assert params == {"episode_uuid": "episode-id"}
            assert routing_ == "w"
            return ([{"marker": marker}], None, None)

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=1,
        input_digest="sha256:" + "0" * 64,
    )
    assert asyncio.run(guard.completed_raw()) == raw
    marker["validated_raw_json"] = '{"provider_attempt_number": 1, "result": "fixed"}'
    with pytest.raises(GuardError, match="digest differs"):
        asyncio.run(guard.completed_raw())


def test_guard_completion_checks_the_committed_transition() -> None:
    from newsroom.graphiti_adapter.neo4j_guard import Neo4jMutationGuard

    queries: list[str] = []

    class Driver:
        async def execute_query(
            self,
            query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            del params, routing_
            queries.append(query)
            records = [{"state": "COMPLETE"}] if "RETURN m.state" in query else []
            return records, None, None

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=1,
        input_digest="sha256:" + "0" * 64,
    )
    asyncio.run(guard.complete({"provider_attempt_number": 1}))
    assert any("SET m.state = 'COMPLETE'" in query for query in queries)
    assert any("NewsroomSnapshot" in query and "DELETE s" in query for query in queries)


def test_complete_marker_blocks_cancellation_rollback_deletion() -> None:
    from newsroom.graphiti_adapter.neo4j_guard import Neo4jMutationGuard

    queries: list[str] = []

    class Driver:
        async def execute_query(
            self,
            query: str,
            *,
            params: dict[str, object],
            routing_: str,
        ) -> tuple[list[dict[str, object]], None, None]:
            del params, routing_
            queries.append(query)
            if "SET m.state = 'ROLLING_BACK'" in query:
                return [], None, None
            if "RETURN properties(m) AS marker" in query:
                return [{"marker": {"state": "COMPLETE"}}], None, None
            return [], None, None

    guard = Neo4jMutationGuard(
        Driver(),
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid="episode-id",
        attempt_number=1,
        input_digest="sha256:" + "0" * 64,
    )
    rolled_back = asyncio.run(
        guard.rollback_pending(
            chat_invocations=[],
            embedding_usage={"usage_basis": "NO_EMBEDDING_CALL"},
            reason="CANCELLED",
        )
    )
    assert rolled_back is False
    assert not any("DELETE r" in query or "DETACH DELETE n" in query for query in queries)


def test_immutable_completion_snapshot_restores_without_graph_rehydration(
    tmp_path: Path,
) -> None:
    from newsroom.graphiti_adapter.real import _EpisodeTelemetry, _raw_receipt
    from newsroom.graphiti_adapter.result_snapshot import restore_validated_snapshot

    instant = UtcTimestamp(datetime(2026, 8, 20, tzinfo=UTC))
    attempt = replace(
        _real_attempt(tmp_path),
        reference_time=instant,
        temporal_basis=TemporalBasis.SOURCE_PUBLISHED,
    )
    raw = _raw_receipt(
        attempt,
        started_at=instant,
        telemetry=_EpisodeTelemetry(provider_attempt_number=1),
        result=None,
        proposals=(),
    )
    restored = restore_validated_snapshot(raw=raw, attempt=attempt)
    assert restored.produced.raw_output_value == raw
    assert restored.provider_attempt_number == 1
    assert (
        restored.recovery_classification
        is GraphitiRecoveryClassification.RECOVERED_IMMUTABLE_COMPLETE
    )

    corrupted = dict(raw)
    corrupted["framework"] = "graphiti-core==mutated"
    unsigned = dict(corrupted)
    unsigned.pop("raw_output_digest")
    corrupted["raw_output_digest"] = digest_bytes(canonical_json_bytes(unsigned))
    with pytest.raises(GraphitiAdapterContractError, match="immutable attempt"):
        restore_validated_snapshot(raw=corrupted, attempt=attempt)


def test_immutable_completion_preserves_original_access_after_rights_renewal(
    tmp_path: Path,
) -> None:
    from newsroom.graphiti_adapter.real import _EpisodeTelemetry, _raw_receipt
    from newsroom.graphiti_adapter.result_snapshot import restore_validated_snapshot

    instant = UtcTimestamp(datetime(2026, 8, 20, tzinfo=UTC))
    original = replace(
        _real_attempt(tmp_path),
        reference_time=instant,
        temporal_basis=TemporalBasis.SOURCE_PUBLISHED,
    )
    raw = _raw_receipt(
        original,
        started_at=instant,
        telemetry=_EpisodeTelemetry(provider_attempt_number=1),
        result=None,
        proposals=(),
    )
    old_access = raw["passages"][0]["access_decision_id"]
    current_passages = tuple(
        replace(
            passage,
            access_decision_id=ObjectAccessDecisionId.parse(
                f"00000000-0000-4000-8000-{9_900 + index:012d}"
            ),
        )
        for index, passage in enumerate(
            original.extraction_request.input_binding.passages,
            start=1,
        )
    )
    current_binding = replace(
        original.extraction_request.input_binding,
        passages=current_passages,
    )
    current_request = replace(
        original.extraction_request,
        input_binding=current_binding,
    )
    current_manifest = GraphitiInputManifest.from_run_request(
        manifest_id=original.manifest.manifest_id,
        configuration=original.configuration,
        contract=original.extraction_contract,
        request=current_request,
    )
    renewed = replace(
        original,
        manifest=current_manifest,
        extraction_request=current_request,
    )
    restored = restore_validated_snapshot(raw=raw, attempt=renewed)
    assert restored.produced.raw_output_value["passages"][0][
        "access_decision_id"
    ] == old_access


def test_embedding_meter_retains_provider_tokens_and_native_usd_cost() -> None:
    from newsroom.graphiti_adapter.embedding_meter import MeteredOpenAIEmbedder

    class Embeddings:
        async def create(self, **_values: object) -> object:
            usage = SimpleNamespace(
                model_dump=lambda: {
                    "prompt_tokens": 19,
                    "total_tokens": 19,
                    "cost": "0.000017",
                }
            )
            return SimpleNamespace(
                id="request-1",
                usage=usage,
                data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
            )

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    meter = MeteredOpenAIEmbedder(delegate)
    assert asyncio.run(meter.create("retained text")) == [0.1, 0.2]
    assert meter.receipt() == {
        "requests": [
            {
                "provider": "openrouter",
                "model": "openai/text-embedding-3-large",
                "request_id": "request-1",
                "prompt_tokens": 19,
                "total_tokens": 19,
                "cost_usd_microunits": 17,
                "cost_reported": True,
                "outcome": "COMPLETE",
            }
        ],
        "request_count": 1,
        "embedding_tokens": 19,
        "cost_usd_microunits": 17,
        "usage_basis": "PROVIDER_REPORTED",
    }


def test_embedding_meter_retains_ambiguous_failed_provider_request() -> None:
    from newsroom.graphiti_adapter.embedding_meter import MeteredOpenAIEmbedder

    class Embeddings:
        async def create(self, **_values: object) -> object:
            raise RuntimeError("provider response was lost")

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    meter = MeteredOpenAIEmbedder(delegate)
    with pytest.raises(RuntimeError, match="response was lost"):
        asyncio.run(meter.create("retained text"))
    receipt = meter.receipt()
    assert receipt["usage_basis"] == "PROVIDER_PARTIALLY_UNREPORTED"
    assert receipt["request_count"] == 1
    assert receipt["requests"][0]["outcome"] == "UNOBSERVED"


def test_else_branch_constructs_real_adapter_instead_of_unreachable_assertion() -> None:
    source = inspect.getsource(_GraphitiAdapterBoundary._execute_attempt_locked)
    assert "unreachable real Graphiti execution path" not in source
    assert "require_execution_authorized()" in source
    assert "adapter = RealGraphitiAdapter(" in source
    assert inspect.signature(RealGraphitiAdapter.execute) == inspect.signature(
        DeterministicFakeGraphitiAdapter.execute
    )


def test_placeholder_packet_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.graphiti_adapter.real as real

    runtime_loads: list[str] = []
    monkeypatch.setattr(
        real,
        "_load_graphiti",
        lambda: runtime_loads.append("loaded"),
    )
    policy = GraphitiWorkspacePolicy(
        policy_id=GraphitiWorkspacePolicyId.parse(
            "00000000-0000-4000-8000-000000004935"
        ),
        policy_version="graphiti-disposable-workspace-v1",
        namespace_prefix="graphiti-real-evaluation",
        max_workspace_bytes=1024 * 1024,
        max_private_nodes=100,
        max_private_relations=100,
        egress_policy=GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY,
        credential_class=GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY,
    )
    attempt = _real_attempt(
        tmp_path,
        authority=_placeholder_authority(),
        workspace_policy=policy,
    )
    attempt.configuration.require_execution_authorized()
    with pytest.raises(GraphitiAdapterContractError, match="EVALUATION CLI packet pins"):
        RealGraphitiAdapter().execute(
            attempt=attempt,
            workspace_root=(tmp_path / "workspace").resolve(),
        )
    assert runtime_loads == []


def test_evaluation_packet_is_the_only_authorised_real_profile(tmp_path: Path) -> None:
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True
    production = _real_attempt(
        tmp_path, execution_profile=GraphitiExecutionProfile.PRODUCTION
    )
    with pytest.raises(GraphitiAdapterContractError, match="EVALUATION"):
        RealGraphitiAdapter().execute(
            attempt=production,
            workspace_root=(tmp_path / "workspace").resolve(),
        )
    with pytest.raises(GraphitiRuntimeNotAuthorized, match="EVALUATION"):
        production.configuration.require_execution_authorized()


def test_authorised_evaluation_attempt_does_not_import_graphiti_core() -> None:
    graphiti_was_loaded = "graphiti_core" in sys.modules
    from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
    from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_WORKSPACE_GROUP

    attempt = evaluation_attempt_for(("香港天文台發出強烈季候風信號。",))
    attempt.configuration.require_execution_authorized()
    assert attempt.configuration.workspace_policy.namespace_prefix == GRAPHITI_WORKSPACE_GROUP
    assert ("graphiti_core" in sys.modules) is graphiti_was_loaded
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True


def test_retryable_failure_returns_diagnostic_receipt_without_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    async def fail(**values: object) -> object:
        telemetry = values["telemetry"]
        telemetry.chat_invocations.append(
            {
                "provider": "cursor-agent-cli",
                "model": "composer-2.5",
                "outcome": "FAILED",
            }
        )
        telemetry.embedding_usage = {
            "usage_basis": "NO_EMBEDDING_CALL",
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "requests": [],
        }
        raise RuntimeError("chat failed")

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "password")
    monkeypatch.setattr(real, "_add_episode", fail)
    attempt = evaluation_attempt_for(("A retained source passage.",))
    produced = RealGraphitiAdapter()._produce(
        attempt,
        UtcTimestamp.parse("2026-08-20T00:00:00.000000Z"),
    )
    assert produced.outcome is ExtractionOutcome.RETRYABLE_FAILURE
    assert produced.failure_code is ExtractionFailureCode.PRODUCER_INTERNAL_ERROR
    assert produced.raw_output_value is None
    assert produced.attempt_receipt_value is not None
    assert produced.attempt_receipt_value["chat_invocation_count"] == 1
    assert produced.attempt_receipt_value["usage_basis"] == "NO_EMBEDDING_CALL"
    assert produced.attempt_receipt_value["token_usage"]["usage_basis"] == (
        "UNREPORTED"
    )
    assert produced.attempt_receipt_value["token_usage"][
        "unreported_chat_requests"
    ] == 1


def test_pre_dispatch_setup_failure_is_a_proved_no_call_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    def missing_runtime() -> object:
        raise GraphitiAdapterContractError("graphiti runtime is absent")

    monkeypatch.setattr(real, "_load_graphiti", missing_runtime)
    produced = RealGraphitiAdapter()._produce(
        evaluation_attempt_for(("A retained source passage.",)),
        UtcTimestamp.parse("2026-08-20T00:00:00.000000Z"),
    )

    receipt = produced.attempt_receipt_value
    assert produced.outcome is ExtractionOutcome.RETRYABLE_FAILURE
    assert receipt is not None
    assert receipt["dispatch_state"] == "NOT_DISPATCHED"
    assert receipt["setup_failure"] == "GraphitiAdapterContractError"
    assert receipt["chat_invocation_count"] == 0
    assert receipt["embedding_usage"]["request_count"] == 0
    assert receipt["embedding_usage"]["cost_usd_microunits"] == 0
    assert receipt["usage_basis"] == "NO_EMBEDDING_CALL"
    assert receipt["token_usage"]["usage_basis"] == "NO_PROVIDER_CALL"


def test_credential_time_is_deducted_from_absolute_extraction_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    class MonotonicClock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

        def advance(self) -> None:
            self.value += 100.0

    monotonic = MonotonicClock()
    provider_calls = 0

    def delayed_api_key() -> str:
        monotonic.advance()
        return "key"

    def delayed_password() -> str:
        monotonic.advance()
        return "password"

    async def must_not_dispatch(**_values: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("expired extraction deadline reached provider")

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", delayed_api_key)
    monkeypatch.setattr(real, "neo4j_community_password", delayed_password)
    monkeypatch.setattr(real, "_add_episode", must_not_dispatch)
    produced = RealGraphitiAdapter(monotonic=monotonic)._produce(
        evaluation_attempt_for(("A retained source passage.",)),
        UtcTimestamp.parse("2026-08-20T00:00:00.000000Z"),
    )

    assert provider_calls == 0
    assert produced.outcome is ExtractionOutcome.RETRYABLE_FAILURE
    assert produced.failure_code is ExtractionFailureCode.EXECUTION_TIMEOUT
    assert produced.attempt_receipt_value is not None
    assert produced.attempt_receipt_value["embedding_usage"]["request_count"] == 0


def test_public_execute_honours_expired_absolute_rights_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.graphiti_adapter.real as real

    fixed = UtcTimestamp.parse("2026-08-21T00:03:00.000000Z")
    provider_calls = 0

    async def must_not_dispatch(**_values: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("expired absolute deadline reached provider")

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "password")
    monkeypatch.setattr(real, "_add_episode", must_not_dispatch)
    execution = RealGraphitiAdapter(
        clock=lambda: fixed,
        execution_deadline=fixed.value,
    ).execute(
        attempt=evaluation_attempt_for(("A retained source passage.",)),
        workspace_root=tmp_path / "expired-workspace",
    )

    assert provider_calls == 0
    assert execution.outcome.value == "TIMEOUT"
    assert execution.produced.failure_code is ExtractionFailureCode.EXECUTION_TIMEOUT
    assert list((tmp_path / "expired-workspace").iterdir()) == []


def test_relations_without_exact_evidence_are_retained_without_proposals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    async def relation_without_evidence(**values: object) -> object:
        values["telemetry"].embedding_usage = {
            "usage_basis": "NO_EMBEDDING_CALL",
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "requests": [],
        }
        result = SimpleNamespace(
            episode=SimpleNamespace(uuid=values["episode_id"]),
            nodes=(
                SimpleNamespace(uuid="node-a", name="Absent A", summary="A"),
                SimpleNamespace(uuid="node-b", name="Absent B", summary="B"),
            ),
            edges=(
                SimpleNamespace(
                    uuid="edge-1",
                    name="ABOUT_EVENT",
                    fact="This exact fact is absent from the retained passage.",
                    source_node_uuid="node-a",
                    target_node_uuid="node-b",
                    valid_at=None,
                    invalid_at=None,
                    expired_at=None,
                ),
            ),
        )
        values["validate_result"](result, values["telemetry"])
        return result

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "password")
    monkeypatch.setattr(real, "_add_episode", relation_without_evidence)
    produced = RealGraphitiAdapter()._produce(
        evaluation_attempt_for(("A retained source passage.",)),
        UtcTimestamp.parse("2026-08-20T00:00:00.000000Z"),
    )
    assert produced.outcome is ExtractionOutcome.SUCCESS
    assert produced.proposals == ()
    assert produced.raw_output_value is not None
    assert produced.raw_output_value["relations"][0]["proposal_status"] == (
        "HELD_NO_EXACT_EVIDENCE"
    )


def test_true_empty_graphiti_extraction_is_a_valid_zero_proposal_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    async def empty_graph(**values: object) -> object:
        values["telemetry"].embedding_usage = {
            "usage_basis": "NO_EMBEDDING_CALL",
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "requests": [],
        }
        result = SimpleNamespace(
            episode=SimpleNamespace(uuid=values["episode_id"]),
            nodes=(),
            edges=(),
        )
        values["validate_result"](result, values["telemetry"])
        return result

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "password")
    monkeypatch.setattr(real, "_add_episode", empty_graph)
    produced = RealGraphitiAdapter()._produce(
        evaluation_attempt_for(("A retained source passage.",)),
        UtcTimestamp.parse("2026-08-20T00:00:00.000000Z"),
    )
    assert produced.outcome is ExtractionOutcome.SUCCESS
    assert produced.proposals == ()
    assert produced.raw_output_value is not None
    assert produced.raw_output_value["entity_count"] == 0
    assert produced.raw_output_value["relation_count"] == 0


def test_success_over_fixed_provider_budget_is_retained_as_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    async def over_budget(**values: object) -> object:
        values["telemetry"].embedding_usage = {
            "usage_basis": "PROVIDER_REPORTED",
            "request_count": 1,
            "embedding_tokens": 1,
            "cost_usd_microunits": 500_001,
            "requests": [],
        }
        result = SimpleNamespace(
            episode=SimpleNamespace(uuid=values["episode_id"]),
            nodes=(),
            edges=(),
        )
        values["validate_result"](result, values["telemetry"])
        return result

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "password")
    monkeypatch.setattr(real, "_add_episode", over_budget)
    produced = RealGraphitiAdapter()._produce(
        evaluation_attempt_for(("A retained source passage.",)),
        UtcTimestamp.parse("2026-08-20T00:00:00.000000Z"),
    )
    assert produced.outcome is ExtractionOutcome.INVALID_OUTPUT
    assert produced.failure_code is ExtractionFailureCode.OUTPUT_SCHEMA_INVALID
    assert produced.proposals == ()
    assert produced.raw_output_value is not None
    assert produced.raw_output_value["budget_status"] == "EXCEEDED"


def test_cursor_cli_runs_outside_repository_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.graphiti_adapter import cli_client

    observed: dict[str, object] = {}

    def capture(
        command: tuple[str, ...], *, timeout: int, cwd: str | None = None
    ) -> str:
        observed.update(command=command, timeout=timeout, cwd=cwd)
        return "{}"

    monkeypatch.setattr(cli_client, "run_cli", capture)
    cursor_execution = cli_client.run_cursor_agent_llm("untrusted source")
    assert cursor_execution.text == "{}"
    assert cursor_execution.usage["usage_basis"] == "UNREPORTED"
    cwd = observed["cwd"]
    assert isinstance(cwd, str)
    assert Path(cwd) != _REPOSITORY_ROOT
    assert "newsroom-cursor-graphiti-" in cwd
    assert observed["timeout"] == cli_client.CLI_CALL_TIMEOUT_SECONDS

    observed.clear()
    grok_execution = cli_client.run_grok_llm("untrusted source", None)
    assert grok_execution.text == "{}"
    assert grok_execution.usage["usage_basis"] == "UNREPORTED"
    grok_cwd = observed["cwd"]
    assert isinstance(grok_cwd, str)
    assert Path(grok_cwd) != _REPOSITORY_ROOT
    assert "newsroom-grok-graphiti-" in grok_cwd
    assert observed["timeout"] == cli_client.CLI_CALL_TIMEOUT_SECONDS


def test_async_cli_child_is_terminated_when_attempt_deadline_cancels() -> None:
    from newsroom.graphiti_adapter.cli_client import run_cli_async

    async def cancelled_call() -> str:
        return await asyncio.wait_for(
            run_cli_async(
                (
                    sys.executable,
                    "-c",
                    "import time; time.sleep(10)",
                ),
                timeout=5,
            ),
            timeout=0.05,
        )

    with pytest.raises(TimeoutError):
        asyncio.run(cancelled_call())
