from __future__ import annotations

from datetime import UTC, datetime

import pytest

from newsroom.authority._extraction_facade import GovernedExtractionRecords
from newsroom.authority._graphiti_adapter_facade import (
    GovernedGraphitiProposalAdapter,
)
from newsroom.authority.auth import AuthenticationProof, AuthorizationDenied
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.graphiti import (
    EvaluationGraphitiRunner,
    GraphitiPreProviderAuthorizationDenied,
    GraphitiResultStageError,
)
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.extraction.models import (
    ExtractionOutputView,
    ExtractionRawOutput,
    ExtractionRunMetadata,
    ProposalDraft,
    ProposalEnvelope,
)
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionFailureCode,
    ExtractionOutputId,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionProposalKind,
    ExtractionUsage,
    ProposalEnvelopeId,
    ProposalSetId,
)
from newsroom.graphiti_adapter import (
    GraphitiAdapterOutcome,
    GraphitiAttemptRecord,
    GraphitiCleanupReason,
    GraphitiCleanupReceipt,
    GraphitiWorkspaceState,
)
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_WORKSPACE_GROUP
from newsroom.graphiti_adapter.identity import typed_id


def _unit() -> CorpusIngestUnit:
    revision = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key="item",
        revision_digest=digest_canonical({"revision": "one"}),
        first_observed_at="2026-08-20T00:00:00.000000Z",
    )
    return CorpusIngestUnit(
        source_id="UK-01",
        item_key="item",
        headline="Headline",
        body="Body",
        canonical_url="https://example.test/item",
        observation_digest=digest_canonical({"observation": "one"}),
        observed_at="2026-08-20T00:00:00.000000Z",
        proving_run_id="run-1",
        effective_revision=revision,
        published_at="2026-08-19T00:00:00.000000Z",
    )


def _governed_dependencies(
    *,
    malformed_raw_proposal: bool = False,
    deny_registration: bool = False,
):
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="fixture")
    retained: dict[str, object] = {}
    calls: list[str] = []

    def register(configuration, _proof):
        calls.append("register")
        if deny_registration:
            denied = AuthorizationDenied.__new__(AuthorizationDenied)
            PermissionError.__init__(denied, "scope missing")
            raise denied
        retained["configuration"] = configuration
        return object()

    def execute(attempt, _proof, **controls):
        calls.append("execute")
        retained["execution_controls"] = controls
        passage = attempt.extraction_request.input_binding.passages[0]
        evidence = EvidenceRange(
            passage_id=passage.passage_id,
            start_byte=0,
            end_byte=1,
            evidence_text_digest=digest_bytes(
                passage.require_text().encode("utf-8")[:1]
            ),
        )
        draft = ProposalDraft(
            local_id="entity.0001",
            kind=ExtractionProposalKind.ENTITY_MENTION,
            subject_placeholder=passage.require_text()[:1],
            object_placeholder=None,
            predicate_hint=None,
            confidence_basis_points=None,
            uncertainty_codes=(),
            rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
            evidence=(evidence,),
        )
        raw_proposal = draft.canonical_value()
        if malformed_raw_proposal:
            raw_proposal = {**raw_proposal, "subject_placeholder": "different"}
        raw = {
            "workspace_group": GRAPHITI_WORKSPACE_GROUP,
            "generation_id": attempt.generation_id,
            "episode_uuid": str(attempt.episode_uuid),
            "attempt_number": attempt.attempt_number,
            "provider_attempt_number": 1,
            "predecessor_episode_uuid": attempt.predecessor_episode_uuid,
            "temporal_basis": attempt.temporal_basis,
            "reference_time": attempt.reference_time.to_text(),
            "proposals": [raw_proposal],
            "entities": [{"local_id": "entity.0001", "name": "H"}],
            "relations": [],
            "passages": [item.canonical_value() for item in attempt.manifest.passages],
            "chat_invocations": [],
            "embedding_usage": {"usage_basis": "NO_EMBEDDING_CALL"},
            "usage_basis": "NO_EMBEDDING_CALL",
        }
        raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
        raw_bytes = canonical_json_bytes(raw)
        output_id = typed_id(ExtractionOutputId, "output", str(attempt.attempt_id))
        recorded_at = UtcTimestamp(datetime(2026, 8, 20, 0, 0, 1, tzinfo=UTC))
        output = ExtractionOutputView(
            output_id=output_id,
            run_id=attempt.extraction_request.run_id,
            run_version_id=attempt.extraction_request.run_version_id,
            validation=ExtractionOutputValidation.VALID,
            schema_contract_digest=(
                attempt.extraction_contract.output_schema.contract_digest
            ),
            byte_length=len(raw_bytes),
            canonical_digest=digest_bytes(raw_bytes),
            retained_at=recorded_at,
        )
        proposal_set_id = typed_id(
            ProposalSetId, "proposal-set", str(attempt.attempt_id)
        )
        proposal_id = typed_id(
            ProposalEnvelopeId, "proposal", str(attempt.attempt_id)
        )
        envelope_value = {
            "proposal_id": str(proposal_id),
            "proposal_set_id": str(proposal_set_id),
            "output_id": str(output_id),
            "run_id": str(attempt.extraction_request.run_id),
            "run_version_id": str(attempt.extraction_request.run_version_id),
            "draft": draft.canonical_value(),
            "producer_contract_digest": attempt.extraction_contract.digest,
        }
        envelope = ProposalEnvelope(
            proposal_id=proposal_id,
            proposal_set_id=proposal_set_id,
            output_id=output_id,
            run_id=attempt.extraction_request.run_id,
            run_version_id=attempt.extraction_request.run_version_id,
            local_id=draft.local_id,
            kind=draft.kind,
            subject_placeholder=draft.subject_placeholder,
            object_placeholder=draft.object_placeholder,
            predicate_hint=draft.predicate_hint,
            confidence_basis_points=draft.confidence_basis_points,
            uncertainty_codes=draft.uncertainty_codes,
            rationale_codes=draft.rationale_codes,
            evidence=draft.evidence,
            producer_contract_digest=attempt.extraction_contract.digest,
            canonical_digest=digest_canonical(envelope_value),
            retained_at=recorded_at,
        )
        usage = ExtractionUsage(
            elapsed_ms=0,
            input_bytes=attempt.extraction_request.input_binding.input_bytes,
            output_bytes=len(raw_bytes),
            proposal_count=1,
            evidence_range_count=1,
        )
        metadata = ExtractionRunMetadata(
            run_id=attempt.extraction_request.run_id,
            run_version_id=attempt.extraction_request.run_version_id,
            version_number=attempt.extraction_request.version_number,
            contract_id=attempt.extraction_request.contract_id,
            input_binding_digest=attempt.extraction_request.input_binding.digest,
            outcome=ExtractionOutcome.SUCCESS,
            failure_code=ExtractionFailureCode.NONE,
            started_at=recorded_at,
            ended_at=recorded_at,
            recorded_at=recorded_at,
            usage=usage,
            output=output,
            proposal_count=1,
            terminal=True,
        )
        record = GraphitiAttemptRecord(
            attempt_id=attempt.attempt_id,
            run_id=attempt.extraction_request.run_id,
            run_version_id=attempt.extraction_request.run_version_id,
            attempt_number=attempt.attempt_number,
            previous_attempt_id=attempt.expected_previous_attempt_id,
            configuration_id=attempt.configuration.configuration_id,
            configuration_digest=attempt.configuration.canonical_digest,
            workspace_id=attempt.workspace_id,
            manifest_id=attempt.manifest.manifest_id,
            outcome=GraphitiAdapterOutcome.COMPLETE,
            failure_code="NONE",
            started_at=recorded_at,
            ended_at=recorded_at,
            usage=usage,
            output_id=output_id,
            proposal_set_id=proposal_set_id,
            cleanup_receipt=GraphitiCleanupReceipt(
                receipt_id=attempt.cleanup_receipt_id,
                workspace_id=attempt.workspace_id,
                final_state=GraphitiWorkspaceState.CLEANED,
                reason=GraphitiCleanupReason.NORMAL,
                private_node_count=1,
                private_relation_count=0,
                file_count=0,
                byte_count=0,
                workspace_absent=True,
                recorded_at=recorded_at,
            ),
            authority_event_id=EventId.new(),
            recorded_at=recorded_at,
        )
        retained.update(
            raw=ExtractionRawOutput(view=output, canonical_bytes=raw_bytes),
            metadata=metadata,
            proposals=(envelope,),
        )
        return record

    adapter = GovernedGraphitiProposalAdapter(
        register_configuration=register,
        execute_attempt=execute,
        approve_replay=lambda *_args: None,
        configuration=lambda *_args: None,
        attempt=lambda *_args: None,
        attempt_history=lambda *_args: (),
        manifest_for_attempt=lambda *_args: None,
        replay_source=lambda *_args: None,
    )
    extraction = GovernedExtractionRecords(
        register_contract=lambda *_args: None,
        execute=lambda *_args: None,
        contract=lambda *_args: None,
        metadata=lambda *_args: retained["metadata"],
        run_history=lambda *_args: (),
        proposals=lambda *_args: retained["proposals"],
        raw_output=lambda *_args: retained["raw"],
    )
    return adapter, extraction, proof, calls, retained


def test_governed_runner_uses_exact_4d_and_4a_authority(monkeypatch) -> None:
    adapter, extraction, proof, calls, retained = _governed_dependencies()

    class DirectAdapter:
        def __init__(self, **_values):
            raise AssertionError("direct adapter must not be constructed")

    monkeypatch.setattr(
        EvaluationGraphitiRunner,
        "_adapter_cls",
        DirectAdapter,
        raising=False,
    )
    deadline = datetime(2026, 8, 20, 0, 1, tzinfo=UTC)
    observer = object()
    result = EvaluationGraphitiRunner(
        proposal_adapter=adapter,
        extraction_records=extraction,
        proof=proof,
        fallback_permitted=False,
    )._ingest(_unit(), deadline=deadline, invocation_observer=observer)

    raw = retained["raw"]
    assert calls == ["register", "execute"]
    assert result.receipt_digest == result.raw_receipt["raw_output_digest"]
    assert canonical_json_bytes(result.raw_receipt) == raw.canonical_bytes
    assert result.proposals == tuple(result.raw_receipt["proposals"])
    assert result.proposal_count == 1
    assert retained["execution_controls"] == {
        "execution_deadline": deadline,
        "fallback_permitted": False,
        "invocation_observer": observer,
    }


def test_governed_runner_dependencies_are_all_or_none() -> None:
    adapter, _extraction, _proof, _calls, _retained = _governed_dependencies()
    with pytest.raises(ValueError, match="supplied together"):
        EvaluationGraphitiRunner(proposal_adapter=adapter)


def test_governed_runner_types_authority_refusal_before_provider_execution() -> None:
    adapter, extraction, proof, calls, _retained = _governed_dependencies(
        deny_registration=True
    )

    with pytest.raises(GraphitiPreProviderAuthorizationDenied) as raised:
        EvaluationGraphitiRunner(
            proposal_adapter=adapter,
            extraction_records=extraction,
            proof=proof,
            fallback_permitted=False,
        )._ingest(
            _unit(),
            deadline=datetime(2026, 8, 20, 0, 1, tzinfo=UTC),
            invocation_observer=object(),
        )

    assert raised.value.stage == "ADAPTER_EXECUTION"
    assert calls == ["register"]


@pytest.mark.parametrize("bounded_call", ["deadline", "fallback"])
def test_governed_runner_fails_closed_when_runtime_controls_cannot_cross_4d(
    bounded_call: str,
) -> None:
    adapter, extraction, proof, calls, _retained = _governed_dependencies()
    runner = EvaluationGraphitiRunner(
        proposal_adapter=adapter,
        extraction_records=extraction,
        proof=proof,
        fallback_permitted=bounded_call != "fallback",
    )

    with pytest.raises(GraphitiResultStageError) as raised:
        if bounded_call == "deadline":
            runner.ingest_until(
                _unit(),
                deadline=datetime(2026, 8, 20, 0, 1, tzinfo=UTC),
            )
        else:
            runner.ingest(_unit())

    assert raised.value.stage == "ADAPTER_EXECUTION"
    assert calls == []


def test_governed_runner_rejects_raw_proposals_that_differ_from_authority() -> None:
    adapter, extraction, proof, _calls, _retained = _governed_dependencies(
        malformed_raw_proposal=True
    )
    with pytest.raises(GraphitiResultStageError) as raised:
        EvaluationGraphitiRunner(
            proposal_adapter=adapter,
            extraction_records=extraction,
            proof=proof,
            fallback_permitted=False,
        )._ingest(
            _unit(),
            deadline=datetime(2026, 8, 20, 0, 1, tzinfo=UTC),
            invocation_observer=object(),
        )
    assert raised.value.stage == "CYCLE_RESULT_CONSTRUCTION"
