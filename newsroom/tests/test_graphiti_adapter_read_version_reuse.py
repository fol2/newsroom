"""Current Graphiti reads share only their freshly validated Extraction version."""
from __future__ import annotations

import pytest

from newsroom.authority._extraction_store_read import _ExtractionReadMixin
from newsroom.authority._graphiti_adapter_store_read import _GraphitiAdapterReadMixin

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    fake_attempt, open_graphiti_system, seed_graphiti_authority_fixture,
)


@pytest.mark.parametrize("surface", ("attempt", "attempt_history", "manifest_for_attempt"))
def test_current_attempt_read_decodes_its_version_once_per_independent_call(
    tmp_path, monkeypatch, surface,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    with open_graphiti_system(state, workspace_root=(tmp_path / "workspace").resolve()) as system:
        system.graphiti.register_configuration(request.configuration, proof=extraction_proof())
        retained = system.graphiti.execute_attempt(request, proof=extraction_proof())
        decoded, statements = [], []
        decode = _ExtractionReadMixin._run_version_from_row
        method_name = "graphiti_" + surface
        read = getattr(_GraphitiAdapterReadMixin, method_name)

        def counted_decode(self, connection, row, *, replayed):
            decoded.append(row["run_version_id"])
            return decode(self, connection, row, replayed=replayed)

        def traced_read(self, *args, **kwargs):
            self._connection.set_trace_callback(statements.append)
            try:
                return read(self, *args, **kwargs)
            finally:
                self._connection.set_trace_callback(None)

        monkeypatch.setattr(_ExtractionReadMixin, "_run_version_from_row", counted_decode)
        monkeypatch.setattr(_GraphitiAdapterReadMixin, method_name, traced_read)
        for _ in range(2):
            decoded.clear()
            statements.clear()
            if surface == "attempt_history":
                result = system.graphiti.attempt_history(
                    retained.run_id, limit=10, proof=extraction_proof(),
                )
                assert result == (retained,)
            else:
                result = getattr(system.graphiti, surface)(retained.attempt_id, proof=extraction_proof())
                assert result == (request.manifest if surface == "manifest_for_attempt" else retained)
            assert decoded == [str(retained.run_version_id)]
            assert sum(statement.startswith(
                "SELECT * FROM extraction_run_versions WHERE run_version_id="
            ) for statement in statements) == 1


def test_selected_version_binding_and_standalone_revalidation_remain_exact(tmp_path, monkeypatch) -> None:
    from dataclasses import replace

    from newsroom.authority._graphiti_adapter_store_common import _GraphitiAdapterStoreSupport
    from newsroom.authority.persistence import AuthorityPersistenceError
    from newsroom.extraction.types import ExtractionOutputId, ExtractionRunId, ExtractionRunVersionId, ProposalSetId
    from newsroom.graphiti_adapter import GraphitiAdapterOutcome
    from .test_graphiti_adapter_4d_integrity import _disable_trigger, _expect_reopen_failure

    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace) as system:
        system.graphiti.register_configuration(request.configuration, proof=extraction_proof())
        retained = system.graphiti.execute_attempt(request, proof=extraction_proof())
        original = _GraphitiAdapterStoreSupport._require_graphiti_attempt_current
        selected = []

        def capture(self, connection, attempt, *, selected_version=None):
            selected.append((self, connection, selected_version))
            return original(self, connection, attempt, selected_version=selected_version)

        monkeypatch.setattr(_GraphitiAdapterStoreSupport, "_require_graphiti_attempt_current", capture)
        assert system.graphiti.attempt(retained.attempt_id, proof=extraction_proof()) == retained
        store, connection, version = selected.pop()
        assert version is not None
        changes = {
            "run_version_id": ExtractionRunVersionId.new(),
            "run_id": ExtractionRunId.new(),
            "outcome": GraphitiAdapterOutcome.PARTIAL,
            "failure_code": "DIFFERENT_FAILURE",
            "usage": replace(retained.usage, request_tokens=retained.usage.request_tokens + 1),
            "output_id": ExtractionOutputId.new(),
            "proposal_set_id": ProposalSetId.new(),
        }
        for field, value in changes.items():
            with pytest.raises(AuthorityPersistenceError, match="differs from retained Extraction Run authority"):
                store._validate_graphiti_attempt_lineage(
                    connection, replace(retained, **{field: value}), selected_version=version,
                )
        # The default remains a fresh independent lookup, not the last selected
        # version from a previous call. A same-row-count mutation must fail.
        trigger = _disable_trigger(connection, "immutable_extraction_run_version_update")
        connection.execute(
            "UPDATE extraction_run_versions SET canonical_digest=? WHERE run_version_id=?",
            ("sha256:" + "f" * 64, str(retained.run_version_id)),
        )
        connection.execute(trigger)
        with pytest.raises(AuthorityPersistenceError, match="normalized columns"):
            store._validate_graphiti_attempt_lineage(connection, retained)
    _expect_reopen_failure(state, workspace, "normalized columns")


def test_current_history_rejects_corruption_in_the_last_selected_attempt(tmp_path, monkeypatch) -> None:
    import sqlite3

    from newsroom.authority.persistence import AuthorityPersistenceError
    from newsroom.extraction.types import FixtureExtractionCase
    from .graphiti_adapter_4d_authority_helpers import approval_from_authority, replay_attempt_for_next_version
    from .test_graphiti_adapter_4d_integrity import _disable_trigger

    state = seed_graphiti_authority_fixture(
        tmp_path / "authority", fixture_case=FixtureExtractionCase.BILINGUAL_PARTIAL,
    )
    request = fake_attempt(state, fixture_case=FixtureExtractionCase.BILINGUAL_PARTIAL)
    workspace = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace) as system:
        system.graphiti.register_configuration(request.configuration, proof=extraction_proof())
        first = system.graphiti.execute_attempt(request, proof=extraction_proof())
    approval_request = approval_from_authority(state, first)
    with open_graphiti_system(state, workspace_root=workspace) as system:
        approval = system.graphiti.approve_replay(approval_request, proof=extraction_proof())
        second_request = replay_attempt_for_next_version(state, first, approval.source)
        system.graphiti.register_configuration(second_request.configuration, proof=extraction_proof())
        second = system.graphiti.execute_attempt(second_request, proof=extraction_proof())
        assert system.graphiti.attempt_history(first.run_id, limit=10, proof=extraction_proof()) == (second, first)
        # The newest row is valid. Only the final older row is corrupt.
        with sqlite3.connect(state.database) as connection:
            trigger = _disable_trigger(connection, "immutable_extraction_run_version_update")
            connection.execute(
                "UPDATE extraction_run_versions SET canonical_digest=? WHERE run_version_id=?",
                ("sha256:" + "f" * 64, str(first.run_version_id)),
            )
            connection.execute(trigger)
        decoded = []
        decode = _ExtractionReadMixin._run_version_from_row

        def counted_decode(self, connection, row, *, replayed):
            decoded.append(row["run_version_id"])
            return decode(self, connection, row, replayed=replayed)

        monkeypatch.setattr(_ExtractionReadMixin, "_run_version_from_row", counted_decode)
        with pytest.raises(AuthorityPersistenceError, match="normalized columns"):
            system.graphiti.attempt_history(first.run_id, limit=10, proof=extraction_proof())
        assert decoded == [str(second.run_version_id), str(first.run_version_id)]


def test_same_opened_history_rechecks_real_expiring_passage_rights(tmp_path, monkeypatch) -> None:
    from datetime import timedelta
    from dataclasses import replace

    from newsroom.graphiti_adapter import GraphitiAdapterRightsDenied
    from . import extraction_4a_helpers as fixtures
    from .source_3a_helpers import SOURCE_NOW

    # Reuse the existing builder and its real thirty-second rights policy,
    # rather than changing retained rights rows or faking a currentness result.
    admit = fixtures.admit
    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "admit", lambda system, **kwargs: admit(
            system, admission_type="source.short", **kwargs,
        ))
        state = fixtures._build_extraction_fixture(tmp_path / "short-authority")
    request = fake_attempt(state)
    with fixtures.open_extraction_system(state) as extraction:
        extraction.extraction.register_contract(request.extraction_contract, proof=extraction_proof())
    current = [SOURCE_NOW]
    with open_graphiti_system(
        state, workspace_root=(tmp_path / "workspace").resolve(), clock=lambda: current[0],
    ) as system:
        system.graphiti.register_configuration(request.configuration, proof=extraction_proof())
        retained = system.graphiti.execute_attempt(request, proof=extraction_proof())
        assert system.graphiti.attempt_history(retained.run_id, limit=10, proof=extraction_proof()) == (retained,)
        current[0] = replace(SOURCE_NOW, value=SOURCE_NOW.value + timedelta(seconds=30))
        with pytest.raises(GraphitiAdapterRightsDenied, match="rights have expired"):
            system.graphiti.attempt_history(retained.run_id, limit=10, proof=extraction_proof())
