from __future__ import annotations

from contextlib import closing
import dataclasses
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import HydrationRequest
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.extraction import (
    DeterministicFixtureExtractor,
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionRightsDenied,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractionSemanticCollision,
    ExtractionVersionConflict,
    ExtractorContractId,
    FixtureExtractionCase,
    VersionedExtractionComponent,
    merge_extraction_authority_registries,
)

from .authority_a2b_helpers import open_object_system
from .extraction_4a_helpers import (
    CONTRACT_ID,
    RUN_ID,
    RUN_VERSION_1_ID,
    RUN_VERSION_2_ID,
    contract_request,
    extraction_proof,
    extraction_scopes,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)
from .source_3a_helpers import SOURCE_NOW, proof


def _uuid(identifier: int, *, kind):
    return kind.parse(f"00000000-0000-4000-8000-{identifier:012d}")


def test_extraction_fixture_clones_are_isolated_and_preserve_blob_modes(
    tmp_path: Path,
) -> None:
    first = seed_extraction_fixture(tmp_path / "first")
    second = seed_extraction_fixture(tmp_path / "second")

    assert first.database != second.database
    assert first.object_root != second.object_root
    assert first.input_binding == second.input_binding
    assert first.database.stat().st_mode & 0o777 == 0o600
    assert second.database.stat().st_mode & 0o777 == 0o600

    first_blobs = tuple(
        sorted(path for path in first.object_root.rglob("*") if path.is_file())
    )
    second_blobs = tuple(
        sorted(path for path in second.object_root.rglob("*") if path.is_file())
    )
    assert len(first_blobs) == len(second_blobs) == 2
    retained_blob_bytes = tuple(path.read_bytes() for path in second_blobs)
    for first_blob, second_blob in zip(first_blobs, second_blobs, strict=True):
        assert first_blob.read_bytes() == second_blob.read_bytes()
        assert first_blob.stat().st_mode & 0o777 == 0o400
        assert second_blob.stat().st_mode & 0o777 == 0o400
        assert (first_blob.stat().st_dev, first_blob.stat().st_ino) != (
            second_blob.stat().st_dev,
            second_blob.stat().st_ino,
        )

    with closing(sqlite3.connect(first.database)) as connection:
        connection.execute("CREATE TABLE clone_isolation_probe(value TEXT)")
        connection.execute("INSERT INTO clone_isolation_probe VALUES ('first')")
        connection.commit()
    first_blobs[0].chmod(0o600)
    first_blobs[0].write_bytes(b"isolated object tamper")

    third = seed_extraction_fixture(tmp_path / "third")
    third_blobs = tuple(
        sorted(path for path in third.object_root.rglob("*") if path.is_file())
    )
    for untouched in (second, third):
        with closing(sqlite3.connect(untouched.database)) as connection:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE name='clone_isolation_probe'"
                ).fetchone()
                is None
            )
    assert tuple(path.read_bytes() for path in second_blobs) == retained_blob_bytes
    assert tuple(path.read_bytes() for path in third_blobs) == retained_blob_bytes
    assert all(path.stat().st_mode & 0o777 == 0o400 for path in third_blobs)
    with pytest.raises(ValueError, match="destination must be empty"):
        seed_extraction_fixture(tmp_path / "second")


def test_extraction_authority_commits_reads_replays_and_reopens(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        contract = system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        replayed_contract = system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        assert replayed_contract.replayed is True
        assert replayed_contract.event_id == contract.event_id

        result = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
        assert result.outcome is ExtractionOutcome.SUCCESS
        assert result.output is not None
        assert result.output.validation is ExtractionOutputValidation.VALID
        assert result.proposal_set is not None
        assert len(result.proposal_set.proposals) == 4
        assert all(
            proposal.run_version_id == RUN_VERSION_1_ID
            for proposal in result.proposal_set.proposals
        )
        assert result.usage.cost_microunits == 0
        assert result.usage.request_tokens == 0
        assert result.usage.response_tokens == 0

        replay = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
        assert replay.replayed is True
        assert replay.event_id == result.event_id
        assert replay.output == result.output
        assert replay.proposal_set == result.proposal_set

        metadata = system.extraction.metadata(
            RUN_VERSION_1_ID, proof=extraction_proof()
        )
        assert metadata.outcome is ExtractionOutcome.SUCCESS
        assert metadata.proposal_count == 4
        history = system.extraction.run_history(
            RUN_ID, limit=10, proof=extraction_proof()
        )
        assert history == (metadata,)
        proposals = system.extraction.proposals(
            RUN_VERSION_1_ID, proof=extraction_proof()
        )
        assert proposals == result.proposal_set.proposals
        raw = system.extraction.raw_output(
            result.output.output_id, proof=extraction_proof()
        )
        assert raw.view == result.output
        assert b"Hong Kong Transport Department" in raw.canonical_bytes
        assert "Hong Kong Transport Department" not in repr(raw)

    with open_extraction_system(state) as reopened:
        metadata = reopened.extraction.metadata(
            RUN_VERSION_1_ID, proof=extraction_proof()
        )
        assert metadata.outcome is ExtractionOutcome.SUCCESS
        proposals = reopened.extraction.proposals(
            RUN_VERSION_1_ID, proof=extraction_proof()
        )
        assert len(proposals) == 4

    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_outputs"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_proposal_sets"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_proposals"
        ).fetchone()[0] == 4


def test_run_version_binds_proposal_set_presence_to_reported_proposals(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        result = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
        zero_usage = dataclasses.replace(
            result.usage,
            proposal_count=0,
            evidence_range_count=0,
        )
        zero_digest = digest_canonical(
            {
                "request": result.request.canonical_value(),
                "contract_canonical_digest": result.contract_canonical_digest,
                "outcome": result.outcome.value,
                "failure_code": result.failure_code.value,
                "started_at": result.started_at.to_text(),
                "ended_at": result.ended_at.to_text(),
                "usage": zero_usage.canonical_value(),
            }
        )
        empty_success = dataclasses.replace(
            result,
            usage=zero_usage,
            proposal_set=None,
            canonical_digest=zero_digest,
        )

        assert empty_success.outcome is ExtractionOutcome.SUCCESS
        assert empty_success.output is result.output
        assert empty_success.proposal_set is None
        assert empty_success.usage.proposal_count == 0

        for contradictory in (
            {"usage": zero_usage},
            {
                "proposal_set": None,
                "canonical_digest": zero_digest,
            },
        ):
            with pytest.raises(
                ExtractionContractError,
                match="run proposal state differs from outcome",
            ):
                dataclasses.replace(result, **contradictory)


def test_partial_failure_invalid_and_retry_version_semantics(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        cases = (
            (
                4201,
                FixtureExtractionCase.BILINGUAL_PARTIAL,
                ExtractionOutcome.PARTIAL,
                True,
                3,
            ),
            (
                4211,
                FixtureExtractionCase.RETRYABLE_FAILURE,
                ExtractionOutcome.RETRYABLE_FAILURE,
                False,
                0,
            ),
            (
                4221,
                FixtureExtractionCase.BLOCKING_FAILURE,
                ExtractionOutcome.BLOCKING_FAILURE,
                False,
                0,
            ),
            (
                4231,
                FixtureExtractionCase.INVALID_OUTPUT,
                ExtractionOutcome.INVALID_OUTPUT,
                True,
                0,
            ),
        )
        retained = {}
        contract_ids = {}
        for number, fixture_case, outcome, has_output, proposal_count in cases:
            contract_id = _uuid(number + 100_000, kind=ExtractorContractId)
            system.extraction.register_contract(
                contract_request(
                    contract_id=contract_id,
                    fixture_case=fixture_case,
                    key=f"contract-{number}",
                ),
                proof=extraction_proof(),
            )
            request = run_request(
                state,
                run_id=_uuid(number, kind=ExtractionRunId),
                run_version_id=_uuid(number + 1, kind=ExtractionRunVersionId),
                contract_id=contract_id,
                key=f"run-{number}-v1",
            )
            result = system.extraction.execute(
                request, proof=extraction_proof()
            )
            retained[fixture_case] = result
            contract_ids[fixture_case] = contract_id
            assert result.outcome is outcome
            assert (result.output is not None) is has_output
            assert (
                0 if result.proposal_set is None else len(result.proposal_set.proposals)
            ) == proposal_count

        invalid = retained[FixtureExtractionCase.INVALID_OUTPUT]
        assert invalid.output is not None
        assert invalid.output.validation is ExtractionOutputValidation.INVALID
        assert invalid.proposal_set is None

        retryable = retained[FixtureExtractionCase.RETRYABLE_FAILURE]
        retry_request = run_request(
            state,
            run_id=retryable.request.run_id,
            run_version_id=_uuid(4213, kind=ExtractionRunVersionId),
            version_number=2,
            previous=retryable.request.run_version_id,
            contract_id=contract_ids[FixtureExtractionCase.RETRYABLE_FAILURE],
            key="run-4211-v2",
        )
        retry_v2 = system.extraction.execute(
            retry_request, proof=extraction_proof()
        )
        assert retry_v2.request.version_number == 2
        assert retry_v2.outcome is ExtractionOutcome.RETRYABLE_FAILURE
        assert len(
            system.extraction.run_history(
                retryable.request.run_id,
                limit=10,
                proof=extraction_proof(),
            )
        ) == 2

        blocking = retained[FixtureExtractionCase.BLOCKING_FAILURE]
        with pytest.raises(ExtractionVersionConflict, match="terminal"):
            system.extraction.execute(
                run_request(
                    state,
                    run_id=blocking.request.run_id,
                    run_version_id=_uuid(4223, kind=ExtractionRunVersionId),
                    version_number=2,
                    previous=blocking.request.run_version_id,
                    contract_id=contract_ids[FixtureExtractionCase.BLOCKING_FAILURE],
                    key="run-4221-v2",
                ),
                proof=extraction_proof(),
            )


def test_contract_identity_and_contract_change_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        original = contract_request()
        system.extraction.register_contract(original, proof=extraction_proof())

        duplicate_identity = dataclasses.replace(
            original,
            contract_id=ExtractorContractId.parse(
                "00000000-0000-4000-8000-000000004301"
            ),
            idempotency_key="duplicate-semantic-contract",
        )
        with pytest.raises(ExtractionSemanticCollision):
            system.extraction.register_contract(
                duplicate_identity, proof=extraction_proof()
            )

        changed_prompt = VersionedExtractionComponent(
            component_id=original.prompt.component_id,
            component_version="fixture-prompt-v2",
            contract_digest="sha256:" + "9" * 64,
        )
        changed = dataclasses.replace(
            original,
            contract_id=ExtractorContractId.parse(
                "00000000-0000-4000-8000-000000004302"
            ),
            prompt=changed_prompt,
            idempotency_key="changed-prompt-contract",
        )
        retained_changed = system.extraction.register_contract(
            changed, proof=extraction_proof()
        )
        assert retained_changed.request.semantic_digest != original.semantic_digest

        changed_run = dataclasses.replace(
            run_request(
                state,
                run_id=ExtractionRunId.parse(
                    "00000000-0000-4000-8000-000000004303"
                ),
                run_version_id=ExtractionRunVersionId.parse(
                    "00000000-0000-4000-8000-000000004304"
                ),
                key="changed-prompt-run",
            ),
            contract_id=changed.contract_id,
        )
        def must_not_run(*_args, **_kwargs):
            raise AssertionError("incompatible contract reached the producer")

        monkeypatch.setattr(
            DeterministicFixtureExtractor,
            "produce",
            must_not_run,
        )
        blocked = system.extraction.execute(
            changed_run, proof=extraction_proof()
        )
        assert blocked.outcome is ExtractionOutcome.BLOCKING_FAILURE
        assert blocked.failure_code is ExtractionFailureCode.POLICY_BLOCKED
        assert blocked.output is None
        assert blocked.proposal_set is None

    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions "
            "WHERE run_version_id=?",
            (str(changed_run.run_version_id),),
        ).fetchone()[0] == 1


def test_read_scopes_are_distinct_and_execute_is_authorized_before_work(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    write_only = frozenset(
        {"authority.extraction.manage", "authority.extraction.execute"}
    )
    with open_extraction_system(state, granted_scopes=write_only) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        result = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
        with pytest.raises(PermissionError):
            system.extraction.metadata(
                result.request.run_version_id,
                proof=extraction_proof(),
            )

    no_execute = frozenset(
        {
            "authority.extraction.manage",
            "authority.extraction.read",
            "authority.extraction.read_proposals",
            "authority.extraction.read_raw",
        }
    )
    other_state = seed_extraction_fixture(tmp_path / "other")
    with open_extraction_system(other_state, granted_scopes=no_execute) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        with pytest.raises(PermissionError):
            system.extraction.execute(
                run_request(other_state), proof=extraction_proof()
            )
    with closing(sqlite3.connect(other_state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] == 0


def test_current_rights_revocation_blocks_replay_and_downstream_reads(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        result = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
        assert result.output is not None
        output_id = result.output.output_id

    all_commands, all_schemas = merge_extraction_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    # The object opener's merge is deliberately idempotent.
    all_commands, all_schemas = merge_authority_registries(
        command_registry=all_commands,
        payload_schemas=all_schemas,
    )
    admission_id = state.input_binding.passages[0].admission_id
    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=all_commands,
        payload_schema_registry=all_schemas,
    ) as objects:
        objects.objects.revoke(
            admission_id,
            reason_code="RIGHTS_REVOKED_FOR_TEST",
            idempotency_key="revoke-increment-4a-input",
            proof=proof(),
        )

    # Startup preserves history, but every use/replay rechecks current rights.
    with open_extraction_system(state) as reopened:
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.execute(
                run_request(state), proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.metadata(
                RUN_VERSION_1_ID, proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.proposals(
                RUN_VERSION_1_ID, proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.raw_output(
                output_id, proof=extraction_proof()
            )
