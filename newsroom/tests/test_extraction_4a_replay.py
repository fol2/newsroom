from __future__ import annotations

from contextlib import closing
import dataclasses
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import IdempotencyIdentityConflict
from newsroom.extraction import (
    DeterministicFixtureExtractor,
    ExtractionIdentifierReuse,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractionSemanticCollision,
    ExtractorContractId,
)

from .extraction_4a_helpers import (
    RUN_VERSION_1_ID,
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)


def _id(value: int, *, kind):
    return kind.parse(f"00000000-0000-4000-8000-{value:012d}")


def test_exact_replay_never_invokes_the_producer_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    request = run_request(state)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        first = system.extraction.execute(request, proof=extraction_proof())

        def forbidden(*_args, **_kwargs):
            raise AssertionError("exact replay invoked the producer")

        monkeypatch.setattr(DeterministicFixtureExtractor, "produce", forbidden)
        replay = system.extraction.execute(request, proof=extraction_proof())

    assert replay.replayed is True
    assert replay.event_id == first.event_id
    assert replay.output == first.output
    assert replay.proposal_set == first.proposal_set


def test_idempotency_key_cannot_be_rebound_to_new_contract_or_run_semantics(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        original_contract = contract_request(key="fixed-contract-key")
        system.extraction.register_contract(
            original_contract, proof=extraction_proof()
        )
        changed_contract = dataclasses.replace(
            original_contract,
            contract_id=_id(5101, kind=ExtractorContractId),
        )
        with pytest.raises(IdempotencyIdentityConflict):
            system.extraction.register_contract(
                changed_contract, proof=extraction_proof()
            )

        original_run = run_request(state, key="fixed-run-key")
        system.extraction.execute(original_run, proof=extraction_proof())
        changed_run = dataclasses.replace(
            original_run,
            run_id=_id(5102, kind=ExtractionRunId),
            run_version_id=_id(5103, kind=ExtractionRunVersionId),
        )
        with pytest.raises(IdempotencyIdentityConflict):
            system.extraction.execute(
                changed_run, proof=extraction_proof()
            )

    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM extractor_contracts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] == 1


def test_semantic_duplicate_run_and_identifier_reuse_fail_closed(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    original = run_request(state)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        retained = system.extraction.execute(
            original, proof=extraction_proof()
        )

        semantic_duplicate = dataclasses.replace(
            original,
            run_id=_id(5111, kind=ExtractionRunId),
            run_version_id=_id(5112, kind=ExtractionRunVersionId),
            idempotency_key="semantic-duplicate-run",
        )
        with pytest.raises(ExtractionSemanticCollision):
            system.extraction.execute(
                semantic_duplicate, proof=extraction_proof()
            )

        reused_version_identity = dataclasses.replace(
            original,
            run_id=_id(5113, kind=ExtractionRunId),
            idempotency_key="reused-run-version-identity",
        )
        # The stable semantic digest intentionally excludes the stable identity.
        # Reusing the already-retained Run Version identity must nevertheless fail
        # before a second stable Run can be allocated.
        with pytest.raises(ExtractionIdentifierReuse):
            system.extraction.execute(
                reused_version_identity, proof=extraction_proof()
            )

        metadata = system.extraction.metadata(
            RUN_VERSION_1_ID, proof=extraction_proof()
        )
        assert metadata.run_version_id == retained.request.run_version_id
        assert metadata.outcome == retained.outcome

    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] == 1
