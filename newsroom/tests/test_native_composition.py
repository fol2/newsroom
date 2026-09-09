from __future__ import annotations

import sqlite3
import os
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

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


def test_native_cursor_credential_loads_only_provisioned_key_and_restores_environment(
    tmp_path, monkeypatch,
):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    path = tmp_path / "Coding/newsroom/.env"
    path.parent.mkdir(parents=True)
    path.write_text("CURSOR_API_KEY='fixture-sdk-key'\nUNRELATED_SECRET=not-loaded\n")
    path.chmod(0o600)
    with native_composition._native_cursor_credential():
        assert os.environ["CURSOR_API_KEY"] == "fixture-sdk-key"
        assert "UNRELATED_SECRET" not in os.environ
    assert "CURSOR_API_KEY" not in os.environ
    path.write_text("CURSOR_API_KEY=\n")
    with pytest.raises(ValueError, match="credential is absent"):
        with native_composition._native_cursor_credential():
            pytest.fail("empty credential entered")
    monkeypatch.setenv("CURSOR_API_KEY", "already-provisioned")
    with native_composition._native_cursor_credential():
        assert os.environ["CURSOR_API_KEY"] == "already-provisioned"
    assert os.environ["CURSOR_API_KEY"] == "already-provisioned"


@pytest.mark.parametrize("cli_version", ["different", "1.0.8"])
def test_deployed_startup_rejects_unqualified_identity_before_credentials_or_io(
    tmp_path, monkeypatch, cli_version,
):
    from newsroom.control_plane import broker, cycle, paths, writer

    root = tmp_path / "native"
    root.mkdir()
    for name in ("evidence-intake", "private-serving", "retrieval"):
        (root / f"{name}.sqlite3").touch()
    for constant, name in (
        ("CANONICAL_INCREMENT4_AUTHORITY_STORE", "authority.sqlite3"),
        ("CANONICAL_UNPUBLISHED_STORE", "private.sqlite3"),
        ("CANONICAL_PROVING_STORE", "proving.sqlite3"),
    ):
        path = tmp_path / name
        path.touch()
        monkeypatch.setattr(paths, constant, path)
    monkeypatch.setattr(paths, "CANONICAL_OBJECT_CAS_ROOT", tmp_path)
    monkeypatch.setattr(paths, "HOST_CONTROL_PLANE_STATE_ROOT", tmp_path)
    monkeypatch.setattr(cycle, "assert_no_owner_emergency_stop", lambda _: None)
    monkeypatch.setattr(writer, "cont_writer_implementation_identity", lambda: ("1" * 40, True))
    monkeypatch.setattr(writer, "read_grok_command_semantic_version", lambda: cli_version)
    monkeypatch.setattr(native_composition.subprocess, "check_output", lambda *_a, **_k: "2" * 40)
    policies = {
        WorkloadClass.NATIVE_RETRIEVAL_EMBEDDING: _embedding_policy(),
        WorkloadClass.NATIVE_EVIDENCE_ASSESSOR: _assessment_policy(),
    }
    monkeypatch.setattr(native_composition, "ModelUsageService", lambda _: SimpleNamespace(
        qualified_policy=lambda **request: policies[request["workload_class"]],
    ))

    def unexpected(*_args, **_kwargs):
        raise AssertionError("unqualified startup reached credentials or source/provider I/O")

    monkeypatch.setattr(broker, "neo4j_projector_config", unexpected)
    monkeypatch.setattr(broker, "openrouter_api_key", unexpected)
    monkeypatch.setattr(native_composition, "open_native_pipeline", unexpected)
    service = native_composition.deployed_native_service(SimpleNamespace(
        ledger=str(paths.CANONICAL_UNPUBLISHED_STORE), lock=str(root / "hermes.lock"),
        once=False, interval=300, failure_backoff=60,
    ))
    with pytest.raises(ValueError, match="CLI differs|qualification.*absent"):
        service.run()


def test_native_deployment_identity_binds_store_instance_not_changing_contents(tmp_path):
    store = tmp_path / "authority.sqlite3"
    store.write_bytes(b"first retained state")
    arguments = dict(
        revision="1" * 40, tree="2" * 40, paths={"authority": store},
        embedding_policy=_embedding_policy(), assessment_policy=_assessment_policy(),
    )
    identity = native_composition._deployment_identity(**arguments)
    store.write_bytes(b"next retained state")
    assert native_composition._deployment_identity(**arguments) == identity
    assert native_composition._deployment_identity(**{**arguments, "revision": "3" * 40}) != identity
    replacement = tmp_path / "replacement.sqlite3"
    replacement.write_bytes(store.read_bytes())
    replacement.replace(store)
    assert native_composition._deployment_identity(**arguments) != identity


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
