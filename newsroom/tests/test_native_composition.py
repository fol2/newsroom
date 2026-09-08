from __future__ import annotations

import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from newsroom.authority import AuthorityCommands, AuthorityEvents, ObjectAdmissionRequest
from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.control_plane import native_assessor, native_composition, native_embeddings
from newsroom.control_plane import govuk_rights
from newsroom.control_plane.govuk_rights import GovUkLicenceEvidence, POLICY_DIGEST
from newsroom.control_plane.model_usage import InvocationEfficiencyPolicy, WorkloadClass
from newsroom.control_plane.native_collision import NativeCollisionAuthority
from newsroom.control_plane.native_pipeline import NativePipeline
from newsroom.control_plane.native_retrieval import NativeRetrievalContinuation
from newsroom.control_plane.writer import CONT_DISABLED_CAPABILITIES, CONT_PRIMARY_COMMAND_FLAGS
from newsroom.increment5.native_retrieval import NativeRetrievalDocuments, NativeRetrievalHold
from newsroom.tests.increment5b2_helpers import config
from newsroom.tests.projection_b2_helpers import MemoryNeo4jAdapter


NOW = datetime(2026, 9, 8, 14, tzinfo=UTC)


def _embedding_policy() -> InvocationEfficiencyPolicy:
    return InvocationEfficiencyPolicy.create(
        policy_id="native-composition-embedding", version="v1",
        workload_class=WorkloadClass.NATIVE_RETRIEVAL_EMBEDDING,
        provider="openrouter", route=native_embeddings.ROUTE,
        model=native_embeddings.OPENROUTER_EMBEDDING_SLUG, reasoning="none",
        one_turn=True, exact_input=True, skills_enabled=False, tools_enabled=False,
        mcp_enabled=False, prior_message_count=0,
        command_semantic_version=native_embeddings.VERSION,
        command_flags=("POST=/embeddings",),
        context_manifest_schema_version=native_embeddings.VERSION,
        disabled_capabilities=("tools",),
        implementation_revision=native_embeddings.implementation_digest(),
        max_prompt_bytes=20_000, max_context_tokens=8_000,
        max_output_tokens=1, max_total_tokens=8_000,
        prompt_contract_version=native_embeddings.VERSION,
        output_schema_digest=native_embeddings.SCHEMA_DIGEST,
        allowed_context_identities=(native_embeddings.VERSION,),
        allowed_config_identities=(native_embeddings.VERSION,),
        hard_estimate_ceiling_tokens=None,
        evidence_digest=digest_canonical({"test": "native composition embedding"}),
        qualified=True,
    )


def _assessment_policy() -> InvocationEfficiencyPolicy:
    return InvocationEfficiencyPolicy.create(
        policy_id="native-composition-assessment", version="v1",
        workload_class=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
        provider="grok-build-cli", route=native_assessor.ROUTE,
        model="grok-4.6", reasoning="low", one_turn=True, exact_input=True,
        skills_enabled=False, tools_enabled=False, mcp_enabled=False,
        prior_message_count=0, command_semantic_version="1.0.8",
        command_flags=CONT_PRIMARY_COMMAND_FLAGS,
        context_manifest_schema_version=native_assessor.CONTEXT_MANIFEST_SCHEMA_VERSION,
        disabled_capabilities=CONT_DISABLED_CAPABILITIES,
        implementation_revision="1" * 40, max_prompt_bytes=1_000_000,
        max_context_tokens=100_000, max_output_tokens=10_000,
        max_total_tokens=100_000, prompt_contract_version=native_assessor.VERSION,
        output_schema_digest=native_assessor.SCHEMA_DIGEST,
        allowed_context_identities=(native_assessor.CONTEXT_IDENTITY,),
        allowed_config_identities=(native_assessor.CONFIG_IDENTITY,),
        hard_estimate_ceiling_tokens=100_000,
        evidence_digest=digest_canonical({"test": "native composition assessment"}),
        qualified=True,
    )


class _Driver:
    def close(self) -> None:
        return None


class _RetrievalProjection:
    bootstraps = 0

    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def bootstrap(self) -> None:
        type(self).bootstraps += 1

    def upsert(self, *_args, **_kwargs) -> None:
        raise AssertionError("test opener must not project a document")

    def retrieve(self, *_args, **_kwargs):
        raise AssertionError("test opener must not retrieve")

    def retrieve_vector(self, *_args, **_kwargs):
        raise AssertionError("test opener must not retrieve")


class _Reader:
    def close(self) -> None:
        return None


def _arguments(tmp_path):
    proving = tmp_path / "proving.sqlite3"
    sqlite3.connect(proving).close()
    return {
        "authority_path": tmp_path / "authority.sqlite3",
        "object_root": tmp_path / "objects",
        "workspace_root": tmp_path,
        "private_path": tmp_path / "private.sqlite3",
        "proving_path": proving,
        "intake_path": tmp_path / "intake.sqlite3",
        "serving_path": tmp_path / "serving.sqlite3",
        "retrieval_path": tmp_path / "retrieval.sqlite3",
        "neo4j_config": config(),
        "embedding_key": "test-key-never-dispatched",
        "embedding_policy": _embedding_policy(),
        "assessment_policy": _assessment_policy(),
        "source_definition_ids": {},
        "licence": None,
        "implementation_worktree_clean": True,
        "clock": lambda: NOW,
    }


def test_native_composition_opens_factory_once_reopens_and_has_no_pre_effect(
    tmp_path, monkeypatch,
) -> None:
    _RetrievalProjection.bootstraps = 0
    monkeypatch.setattr(native_composition, "observe_portfolio_terms", lambda **_: {})
    monkeypatch.setattr(
        "newsroom.authority._graphiti_increment4_system._open_structural_graph_adapter",
        lambda _: MemoryNeo4jAdapter(),
    )
    monkeypatch.setattr(native_composition.GraphDatabase, "driver", lambda *_a, **_k: _Driver())
    monkeypatch.setattr(native_composition, "Neo4jNativeRetrievalProjection", _RetrievalProjection)
    monkeypatch.setattr(native_composition, "_open_neo4j_adapter", lambda _: MemoryNeo4jAdapter())
    monkeypatch.setattr(
        native_composition, "_open_neo4j_fulltext_reader_with_adapter",
        lambda _adapter: _Reader(),
    )
    terms = (
        b"<html><main>Reviewed GOV.UK reuse terms.</main></html>",
        b"<html><main>Reviewed Open Government Licence terms.</main></html>",
    )
    monkeypatch.setattr(
        govuk_rights,
        "REVIEWED_TEXT",
        {
            url: govuk_rights.licence_text_digest(raw)
            for url, raw in zip(
                (govuk_rights.REUSE_URL, govuk_rights.LICENCE_URL), terms,
                strict=True,
            )
        },
    )

    def retain_licence(*, objects, proof, dispatch_fence, clock):
        dispatch_fence()
        admissions = tuple(
            objects.admit(
                ObjectAdmissionRequest(
                    "evidence.source", f"native-composition-licence:{digest_bytes(raw)}"
                ),
                raw,
                proof=proof,
            ).admission
            for raw in terms
        )
        return GovUkLicenceEvidence(
            tuple(item.admission_id for item in admissions),
            tuple(item.blob.blob_digest for item in admissions),
            NOW.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            POLICY_DIGEST,
        )

    monkeypatch.setattr(
        native_composition, "retain_current_govuk_licence", retain_licence
    )
    stops = []
    fences = []

    def stop_check() -> None:
        stops.append("checked")

    @contextmanager
    def stop_fence():
        fences.append("entered")
        yield

    arguments = {
        **_arguments(tmp_path),
        "stop_check": stop_check,
        "stop_fence": stop_fence,
    }
    for expected_bootstraps in (1, 2):
        with native_composition.open_native_pipeline(**arguments) as pipeline:
            assert type(pipeline) is NativePipeline
            assert type(pipeline._runtime.authority.commands) is AuthorityCommands
            assert type(pipeline._runtime.authority.events) is AuthorityEvents
            assert type(pipeline._retrieval_for(())) is NativeRetrievalContinuation
            assert type(pipeline._retrieval_for(())._documents) is NativeRetrievalDocuments
            assert type(pipeline._collision) is NativeCollisionAuthority
            assert pipeline._runtime.authority.collision is pipeline._collision.enforcer
            assert pipeline._runtime.ingress.receipt_count == 0
            assert pipeline._journal.units == {}
            assert _RetrievalProjection.bootstraps == expected_bootstraps
            with sqlite3.connect(arguments["serving_path"]) as serving:
                assert serving.execute(
                    "SELECT COUNT(*) FROM private_serving_payloads"
                ).fetchone()[0] == 0

    with pytest.raises(NativeRetrievalHold, match="NATIVE_EMBEDDING_POLICY_HOLD"):
        with native_composition.open_native_pipeline(
            **{
                **arguments,
                "embedding_policy": replace(
                    arguments["embedding_policy"], qualified=False
                ),
            }
        ):
            raise AssertionError("unqualified composition entered")
    assert _RetrievalProjection.bootstraps == 2
    assert stops == ["checked"] * 6
    assert fences == ["entered", "entered"]


def test_native_composition_owner_stop_precedes_store_or_provider_effects(
    tmp_path,
) -> None:
    arguments = _arguments(tmp_path)

    def stopped() -> None:
        raise RuntimeError("signed owner stop")

    arguments.update(stop_check=stopped, stop_fence=nullcontext)

    with pytest.raises(RuntimeError, match="signed owner stop"):
        with native_composition.open_native_pipeline(**arguments):
            raise AssertionError("stopped composition entered")
    assert not arguments["authority_path"].exists()
    assert not arguments["private_path"].exists()
