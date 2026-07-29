from __future__ import annotations

from contextlib import closing
import dataclasses
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.extraction import (
    DeterministicFixtureExtractor,
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionUsage,
    ProducedExtraction,
    VersionedExtractionComponent,
)
from newsroom.extraction.output_schema import (
    normalize_fixture_production,
    validate_fixture_production,
)

from .extraction_4a_helpers import (
    RUN_VERSION_2_ID,
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)


def _with_raw(
    production,
    raw,
    *,
    proposal_count: int | None = None,
    evidence_count: int | None = None,
):
    return dataclasses.replace(
        production,
        raw_output_value=raw,
        usage=dataclasses.replace(
            production.usage,
            output_bytes=len(canonical_json_bytes(raw)),
            proposal_count=(
                production.usage.proposal_count
                if proposal_count is None
                else proposal_count
            ),
            evidence_range_count=(
                production.usage.evidence_range_count
                if evidence_count is None
                else evidence_count
            ),
        ),
    )


def test_independent_output_validator_rejects_schema_and_proposal_drift(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)
    produced = DeterministicFixtureExtractor().produce(
        contract=contract, request=request
    )
    validate_fixture_production(
        contract=contract, request=request, production=produced
    )

    extra_property = dict(produced.raw_output_value)
    extra_property["unapproved"] = True
    malformed = _with_raw(produced, extra_property)
    with pytest.raises(ExtractionContractError, match="violates"):
        validate_fixture_production(
            contract=contract, request=request, production=malformed
        )

    proposal_drift = dataclasses.replace(
        produced,
        proposals=produced.proposals[:-1],
        usage=dataclasses.replace(
            produced.usage,
            proposal_count=len(produced.proposals) - 1,
            evidence_range_count=sum(
                len(item.evidence) for item in produced.proposals[:-1]
            ),
        ),
    )
    with pytest.raises(ExtractionContractError, match="differs"):
        validate_fixture_production(
            contract=contract, request=request, production=proposal_drift
        )

    semantically_invalid = dataclasses.replace(
        produced,
        outcome=ExtractionOutcome.INVALID_OUTPUT,
        failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
        validation=ExtractionOutputValidation.INVALID,
        proposals=(),
        usage=dataclasses.replace(
            produced.usage,
            proposal_count=0,
            evidence_range_count=0,
        ),
    )
    # The JSON schema still matches, but the retained raw value no longer has
    # any corresponding proposal envelopes. That is honest INVALID output.
    validate_fixture_production(
        contract=contract, request=request, production=semantically_invalid
    )


def test_invalid_proposal_evidence_normalises_to_invalid_output(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)
    produced = DeterministicFixtureExtractor().produce(
        contract=contract, request=request
    )
    first = produced.proposals[0]
    bad_evidence = dataclasses.replace(
        first.evidence[0],
        evidence_text_digest="sha256:" + "0" * 64,
    )
    bad_first = dataclasses.replace(first, evidence=(bad_evidence,))
    malformed = dataclasses.replace(
        produced,
        proposals=tuple(
            sorted(
                (bad_first, *produced.proposals[1:]),
                key=lambda item: item.local_id,
            )
        ),
    )

    normalized = normalize_fixture_production(
        contract=contract, request=request, production=malformed
    )
    assert normalized.outcome is ExtractionOutcome.INVALID_OUTPUT
    assert normalized.failure_code is ExtractionFailureCode.OUTPUT_SCHEMA_INVALID
    assert normalized.validation is ExtractionOutputValidation.INVALID
    assert normalized.raw_output_value == produced.raw_output_value
    assert normalized.proposals == ()


def test_malformed_valid_output_is_retained_as_invalid_without_proposals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)
    produced = DeterministicFixtureExtractor().produce(
        contract=contract, request=request
    )
    raw = dict(produced.raw_output_value)
    raw["unapproved"] = {"tool": "write_governed_graph"}
    malformed = _with_raw(produced, raw)

    with open_extraction_system(state) as system:
        system.extraction.register_contract(contract, proof=extraction_proof())
        monkeypatch.setattr(
            DeterministicFixtureExtractor,
            "produce",
            lambda *_args, **_kwargs: malformed,
        )
        result = system.extraction.execute(request, proof=extraction_proof())
        assert result.outcome is ExtractionOutcome.INVALID_OUTPUT
        assert result.failure_code is ExtractionFailureCode.OUTPUT_SCHEMA_INVALID
        assert result.output is not None
        assert result.output.validation is ExtractionOutputValidation.INVALID
        assert result.proposal_set is None
        retained_raw = system.extraction.raw_output(
            result.output.output_id, proof=extraction_proof()
        )
        assert retained_raw.canonical_bytes == canonical_json_bytes(raw)

    with closing(sqlite3.connect(state.database)) as conn:
        expected = {
            "extraction_runs": 1,
            "extraction_run_passages": 2,
            "extraction_run_versions": 1,
            "extraction_outputs": 1,
            "extraction_proposal_sets": 0,
            "extraction_proposals": 0,
            "extraction_proposal_evidence": 0,
        }
        for table, count in expected.items():
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count
        assert conn.execute(
            "SELECT COUNT(*) FROM ledger_events "
            "WHERE event_type='extraction.run.executed'"
        ).fetchone()[0] == 1


def test_unexpected_producer_exception_is_redacted_retryable_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)
    secret = "secret://provider-token-do-not-retain"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    original_produce = DeterministicFixtureExtractor.produce
    with open_extraction_system(state) as system:
        system.extraction.register_contract(contract, proof=extraction_proof())
        monkeypatch.setattr(DeterministicFixtureExtractor, "produce", fail)
        result = system.extraction.execute(request, proof=extraction_proof())
        assert result.outcome is ExtractionOutcome.RETRYABLE_FAILURE
        assert result.failure_code is ExtractionFailureCode.PRODUCER_INTERNAL_ERROR
        assert result.output is None
        assert result.proposal_set is None
        replay = system.extraction.execute(request, proof=extraction_proof())
        assert replay.replayed is True
        assert replay.event_id == result.event_id
        assert replay.failure_code is ExtractionFailureCode.PRODUCER_INTERNAL_ERROR

        monkeypatch.setattr(
            DeterministicFixtureExtractor, "produce", original_produce
        )
        retry = system.extraction.execute(
            run_request(
                state,
                run_id=request.run_id,
                run_version_id=RUN_VERSION_2_ID,
                version_number=2,
                previous=request.run_version_id,
                key="producer-retry-v2",
            ),
            proof=extraction_proof(),
        )
        assert retry.outcome is ExtractionOutcome.SUCCESS
        assert len(
            system.extraction.run_history(
                request.run_id, limit=10, proof=extraction_proof()
            )
        ) == 2

    assert secret.encode("utf-8") not in state.database.read_bytes()
    assert secret not in repr(result)


def test_contract_rejection_is_redacted_blocking_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)
    secret = "secret://policy-detail-do-not-retain"

    def reject(*_args, **_kwargs):
        raise ExtractionContractError(secret)

    with open_extraction_system(state) as system:
        system.extraction.register_contract(contract, proof=extraction_proof())
        monkeypatch.setattr(DeterministicFixtureExtractor, "produce", reject)
        result = system.extraction.execute(request, proof=extraction_proof())
        assert result.outcome is ExtractionOutcome.BLOCKING_FAILURE
        assert result.failure_code is ExtractionFailureCode.POLICY_BLOCKED
        assert result.output is None
        assert result.proposal_set is None
        replay = system.extraction.execute(request, proof=extraction_proof())
        assert replay.replayed is True
        assert replay.event_id == result.event_id

    assert secret.encode("utf-8") not in state.database.read_bytes()
    assert secret not in repr(result)


def test_no_output_failure_cannot_bypass_exact_fixture_contract(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    request = run_request(state)
    contract = contract_request()
    incompatible = dataclasses.replace(
        contract,
        prompt=VersionedExtractionComponent(
            component_id=contract.prompt.component_id,
            component_version="unapproved-v2",
            contract_digest="sha256:" + "7" * 64,
        ),
    )
    retryable = ProducedExtraction(
        outcome=ExtractionOutcome.RETRYABLE_FAILURE,
        failure_code=ExtractionFailureCode.FIXTURE_RETRYABLE,
        validation=None,
        raw_output_value=None,
        proposals=(),
        usage=ExtractionUsage(
            elapsed_ms=0,
            input_bytes=request.input_binding.input_bytes,
            output_bytes=0,
            proposal_count=0,
            evidence_range_count=0,
        ),
    )

    with pytest.raises(ExtractionContractError, match="incompatible contract"):
        normalize_fixture_production(
            contract=incompatible,
            request=request,
            production=retryable,
        )


def test_untyped_producer_result_is_redacted_retryable_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)

    with open_extraction_system(state) as system:
        system.extraction.register_contract(contract, proof=extraction_proof())
        monkeypatch.setattr(
            DeterministicFixtureExtractor,
            "produce",
            lambda *_args, **_kwargs: object(),
        )
        result = system.extraction.execute(request, proof=extraction_proof())

    assert result.outcome is ExtractionOutcome.RETRYABLE_FAILURE
    assert result.failure_code is ExtractionFailureCode.PRODUCER_INTERNAL_ERROR
    assert result.output is None
    assert result.proposal_set is None


def test_unexpected_authority_normalisation_error_aborts_without_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.authority._extraction_boundary as boundary_module

    state = seed_extraction_fixture(tmp_path)
    contract = contract_request()
    request = run_request(state)

    def authority_defect(*_args, **_kwargs):
        raise RuntimeError("authority-normalisation-defect")

    with open_extraction_system(state) as system:
        system.extraction.register_contract(contract, proof=extraction_proof())
        monkeypatch.setattr(
            boundary_module,
            "normalize_fixture_production",
            authority_defect,
        )
        with pytest.raises(RuntimeError, match="authority-normalisation-defect"):
            system.extraction.execute(request, proof=extraction_proof())

    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM ledger_events "
            "WHERE event_type='extraction.run.executed'"
        ).fetchone()[0] == 0
