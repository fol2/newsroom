from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import sqlite3

import pytest

from newsroom.authority._graphiti_adapter_store_commit import (
    _GraphitiAdapterCommitMixin,
)
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.extraction.types import ExtractionFailureCode
from newsroom.graphiti_adapter import (
    DeterministicFakeGraphitiAdapter,
    GraphitiAdapterOutcome,
    GraphitiAdapterRightsDenied,
    GraphitiCleanupReason,
)
from newsroom.graphiti_adapter.policy import (
    merge_graphiti_adapter_authority_registries,
)
from newsroom.sources import (
    SourceDefinitionVersionId,
    open_governed_source_registry_authority_system,
)

from .authority_a2b_helpers import open_object_system
from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    fake_attempt,
    open_graphiti_system,
    retry_fake_attempt,
    seed_graphiti_authority_fixture,
)
from .source_3a_helpers import (
    SOURCE_NOW,
    VERSION_2_ID,
    authenticator,
    authorizer,
    proof,
    read_policy,
    version_request,
)


def _combined_registries(state):
    commands, schemas = merge_graphiti_adapter_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    return merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )


def _count(conn: sqlite3.Connection, table: str, where: str, value: str) -> int:
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}=?", (value,)
        ).fetchone()[0]
    )


def test_extraction_persists_before_attempt_inside_one_atomic_transaction(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    original = _GraphitiAdapterCommitMixin._persist_graphiti_attempt_after_extraction
    observed: dict[str, int] = {}

    def inspect_then_persist(self, conn, **kwargs):
        result = kwargs["result"]
        observed["versions"] = _count(
            conn,
            "extraction_run_versions",
            "run_version_id",
            str(result.request.run_version_id),
        )
        observed["outputs"] = _count(
            conn,
            "extraction_outputs",
            "run_version_id",
            str(result.request.run_version_id),
        )
        observed["proposal_sets"] = _count(
            conn,
            "extraction_proposal_sets",
            "run_version_id",
            str(result.request.run_version_id),
        )
        observed["attempts_before"] = _count(
            conn,
            "graphiti_adapter_attempts",
            "attempt_id",
            str(attempt.attempt_id),
        )
        return original(self, conn, **kwargs)

    monkeypatch.setattr(
        _GraphitiAdapterCommitMixin,
        "_persist_graphiti_attempt_after_extraction",
        inspect_then_persist,
    )
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            attempt, proof=extraction_proof()
        )

    assert retained.outcome is GraphitiAdapterOutcome.COMPLETE
    assert observed == {
        "versions": 1,
        "outputs": 1,
        "proposal_sets": 1,
        "attempts_before": 0,
    }


def test_attempt_persistence_failure_rolls_back_extraction_and_adapter_authority(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    observed = {"extraction_visible": False}

    def fail_after_extraction(self, conn, **kwargs):
        result = kwargs["result"]
        observed["extraction_visible"] = bool(
            _count(
                conn,
                "extraction_run_versions",
                "run_version_id",
                str(result.request.run_version_id),
            )
        )
        raise RuntimeError("forced coupled authority failure")

    monkeypatch.setattr(
        _GraphitiAdapterCommitMixin,
        "_persist_graphiti_attempt_after_extraction",
        fail_after_extraction,
    )
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        with pytest.raises(RuntimeError, match="forced coupled authority failure"):
            system.graphiti.execute_attempt(attempt, proof=extraction_proof())

    assert observed["extraction_visible"] is True
    assert not any(workspace_root.glob("*"))
    with closing(sqlite3.connect(state.database)) as conn:
        assert _count(
            conn,
            "extraction_runs",
            "run_id",
            str(attempt.extraction_request.run_id),
        ) == 0
        assert _count(
            conn,
            "extraction_run_versions",
            "run_version_id",
            str(attempt.extraction_request.run_version_id),
        ) == 0
        assert _count(
            conn,
            "extraction_outputs",
            "run_version_id",
            str(attempt.extraction_request.run_version_id),
        ) == 0
        assert _count(
            conn,
            "extraction_proposal_sets",
            "run_version_id",
            str(attempt.extraction_request.run_version_id),
        ) == 0
        assert _count(
            conn,
            "graphiti_adapter_attempts",
            "attempt_id",
            str(attempt.attempt_id),
        ) == 0
        assert _count(
            conn,
            "graphiti_workspaces",
            "workspace_id",
            str(attempt.workspace_id),
        ) == 0
        assert _count(
            conn,
            "graphiti_input_manifests",
            "manifest_id",
            str(attempt.manifest.manifest_id),
        ) == 0
        assert _count(
            conn,
            "graphiti_cleanup_receipts",
            "receipt_id",
            str(attempt.cleanup_receipt_id),
        ) == 0
        for key in (
            attempt.extraction_request.idempotency_key,
            attempt.idempotency_key,
        ):
            assert _count(conn, "authority_commands", "idempotency_key", key) == 0


def test_authority_measured_timeout_discards_output_replays_and_can_retry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state, timeout_ms=10)
    workspace_root = (tmp_path / "workspace").resolve()
    original_execute = DeterministicFakeGraphitiAdapter.execute
    current = [SOURCE_NOW]

    def slow_execute(self, *, attempt, workspace_root):
        execution = original_execute(
            self, attempt=attempt, workspace_root=workspace_root
        )
        ended_at = replace(
            execution.ended_at,
            value=execution.ended_at.value + timedelta(milliseconds=11),
        )
        current[0] = ended_at
        return replace(
            execution,
            ended_at=ended_at,
            cleanup_receipt=replace(
                execution.cleanup_receipt, recorded_at=ended_at
            ),
        )

    monkeypatch.setattr(
        DeterministicFakeGraphitiAdapter, "execute", slow_execute
    )
    with open_graphiti_system(
        state, workspace_root=workspace_root, clock=lambda: current[0]
    ) as system:
        system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        timed_out = system.graphiti.execute_attempt(
            attempt, proof=extraction_proof()
        )

    assert timed_out.outcome is GraphitiAdapterOutcome.TIMEOUT
    assert timed_out.failure_code == ExtractionFailureCode.EXECUTION_TIMEOUT.value
    assert timed_out.usage.elapsed_ms == 11
    assert timed_out.output_id is None
    assert timed_out.proposal_set_id is None
    assert timed_out.cleanup_receipt.reason is GraphitiCleanupReason.TIMEOUT

    def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("exact adapter replay reran the workspace")

    monkeypatch.setattr(
        DeterministicFakeGraphitiAdapter, "execute", forbidden_execute
    )
    with open_graphiti_system(
        state, workspace_root=workspace_root, clock=lambda: current[0]
    ) as system:
        replay = system.graphiti.execute_attempt(
            attempt, proof=extraction_proof()
        )
        assert replay == replace(timed_out, replayed=True)

    monkeypatch.setattr(
        DeterministicFakeGraphitiAdapter, "execute", original_execute
    )
    retry = retry_fake_attempt(state, timed_out, timeout_ms=10)
    with open_graphiti_system(
        state, workspace_root=workspace_root, clock=lambda: current[0]
    ) as system:
        completed = system.graphiti.execute_attempt(
            retry, proof=extraction_proof()
        )
        history = system.graphiti.attempt_history(
            attempt.extraction_request.run_id,
            limit=10,
            proof=extraction_proof(),
        )
    assert completed.outcome is GraphitiAdapterOutcome.COMPLETE
    assert [item.outcome for item in history] == [
        GraphitiAdapterOutcome.COMPLETE,
        GraphitiAdapterOutcome.TIMEOUT,
    ]


def test_tombstone_blocks_attempt_replay_and_reads_without_deleting_history(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            attempt, proof=extraction_proof()
        )

    passage = state.input_binding.passages[0]
    commands, schemas = _combined_registries(state)
    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="GRAPHITI_DELETE_REQUESTED",
            idempotency_key="increment-4d-delete-request",
            proof=proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="GRAPHITI_TOMBSTONED",
            idempotency_key="increment-4d-tombstone",
            proof=proof(),
        )

    with open_graphiti_system(state, workspace_root=workspace_root) as reopened:
        with pytest.raises(GraphitiAdapterRightsDenied):
            reopened.graphiti.attempt(
                retained.attempt_id, proof=extraction_proof()
            )
        with pytest.raises(GraphitiAdapterRightsDenied):
            reopened.graphiti.execute_attempt(
                attempt, proof=extraction_proof()
            )

    with closing(sqlite3.connect(state.database)) as conn:
        assert _count(
            conn,
            "graphiti_adapter_attempts",
            "attempt_id",
            str(retained.attempt_id),
        ) == 1
        assert _count(
            conn,
            "extraction_run_versions",
            "run_version_id",
            str(retained.run_version_id),
        ) == 1


def test_new_source_definition_version_blocks_retained_attempt_use(tmp_path) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            attempt, proof=extraction_proof()
        )

    commands, schemas = _combined_registries(state)
    version_3 = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000004981"
    )
    with open_governed_source_registry_authority_system(
        path=state.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=authenticator(),
        authorizer=authorizer(),
        read_policy=read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as sources:
        sources.sources.record_definition_version(
            version_request(
                version_id=version_3,
                version_number=3,
                previous_version_id=VERSION_2_ID,
                locator="fixture://increment-4d/source-v3",
                key="increment-4d-source-version-v3",
            ),
            proof=proof(),
        )

    with open_graphiti_system(state, workspace_root=workspace_root) as reopened:
        with pytest.raises(GraphitiAdapterRightsDenied, match="no longer current"):
            reopened.graphiti.attempt(
                retained.attempt_id, proof=extraction_proof()
            )
        with pytest.raises(GraphitiAdapterRightsDenied, match="no longer current"):
            reopened.graphiti.attempt_history(
                retained.run_id,
                limit=10,
                proof=extraction_proof(),
            )
