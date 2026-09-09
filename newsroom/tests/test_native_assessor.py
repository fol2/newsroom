import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.control_plane.evidence import evidence_package_value
from newsroom.control_plane.native_assessor import (
    AutonomousNativeEvidenceAssessor,
    CONFIG_IDENTITY,
    CONTEXT_IDENTITY,
    CONTEXT_MANIFEST_SCHEMA_VERSION,
    NativeAssessmentExecution,
    NativeAssessmentUsage,
    SCHEMA,
    SCHEMA_DIGEST,
    VERSION,
)
from newsroom.control_plane.native_evidence import NativeEvidenceError, NativeEvidenceHold
from newsroom.control_plane.model_usage import (
    InvocationEfficiencyPolicy,
    ModelUsageIntegrityError,
    ModelUsageService,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.increment10.evidence import EvidencePackageError, _base_package
from newsroom.control_plane.writer import (
    CONT_DISABLED_CAPABILITIES,
    CONT_PRIMARY_COMMAND_FLAGS,
)
from newsroom.tests.test_increment10_editorial import _ready_package
from newsroom.tests.test_increment10_ingress import _candidate


REVISION = "1" * 40


def _model_package_value(package):
    value = evidence_package_value(package)
    return {
        "substantive_new_information": value["substantive_new_information"],
        "governed_claims": [
            {
                key: item[key]
                for key in (
                    "claim_id", "claim", "passage_index", "supporting_excerpt",
                    "source_ids", "status",
                    "rendered_assertion_zh_hant_hk", "claim_role",
                    "localised_factual_expressions", "quotations", "certainty",
                    "originality_basis", "originality_policy_version",
                    "admitted_use", "policy_version",
                )
            } | {
                "semantic_relation": {
                    "source_modality": "ASSERTED",
                    "rendered_modality": "ASSERTED",
                    "source_polarity": "AFFIRMED",
                    "rendered_polarity": "AFFIRMED",
                    "relation": "SEMANTICALLY_EQUIVALENT",
                },
                "named_entities": [
                    {"source_text": entity[0], "entity_type": entity[1]}
                    for entity in item["named_entity_evidence"]
                ]
            }
            for item in value["governed_claims"]
        ],
        "qualification_evidence": [
            {
                key: item[key]
                for key in (
                    "test", "governed_claim_id", "policy_version"
                )
            } | {"test_evidence": dict(item["test_evidence"])}
            for item in value["qualification_evidence"]
        ],
        "selection_rationale": value["selection_rationale"],
        "geography": value["geography"],
        "categories": value["categories"],
        "explicit_exclusions": value["explicit_exclusions"],
    }


def test_native_assessor_schema_is_closed_and_accepts_the_exact_package_shape(tmp_path) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    assessed = _ready_package(candidate)[1]
    validator = Draft202012Validator(SCHEMA)
    validator.validate({"package": _model_package_value(base)})
    model_value = _model_package_value(assessed)
    validator.validate({"package": model_value})
    assert "source_authority_decision_ids" not in model_value["governed_claims"][0]
    assert "semantic_relation_evidence_id" not in model_value["governed_claims"][0]
    assert "qualification_record_id" not in model_value["qualification_evidence"][0]
    named = json.loads(canonical_json_bytes({"package": model_value}))
    named["package"]["governed_claims"][0]["named_entities"] = [{
        "source_text": "Home Office", "entity_type": "ORGANISATION",
    }]
    validator.validate(named)
    named["package"]["governed_claims"][0]["named_entities"][0][
        "rendered_text"
    ] = "英國內政部"
    with pytest.raises(ValidationError):
        validator.validate(named)
    invalid_qualification = json.loads(canonical_json_bytes({"package": model_value}))
    invalid_qualification["package"]["qualification_evidence"][0][
        "test_evidence"
    ]["invented"] = "value"
    with pytest.raises(ValidationError):
        validator.validate(invalid_qualification)
    invalid = _model_package_value(base)
    invalid["invented"] = True
    with pytest.raises(ValidationError):
        validator.validate({"package": invalid})
    connection.close()


def test_native_assessor_retains_precise_qualification_contract_hold(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    package = _model_package_value(base)
    package["qualification_evidence"] = [{
        "test": "OFFICIAL_ACTION_OR_DEADLINE",
        "governed_claim_id": "missing-claim",
        "test_evidence": {
            "action_class": "OFFICIAL_DEADLINE",
            "event_polarity": "AFFIRMED",
            "action_relation": "NEW_OR_CHANGED_OFFICIAL_ACTION",
            "material_relation_span": "deadline",
            "reader_action": "check deadline",
        },
        "policy_version": "newsroom.evid-012.v7",
    }]
    _service, usage = _usage(tmp_path, monkeypatch)

    with pytest.raises(
        NativeEvidenceHold, match="ASSESSOR_QUALIFICATION_CONTRACT_HOLD"
    ):
        AutonomousNativeEvidenceAssessor(
            lambda _prompt: NativeAssessmentExecution(
                canonical_json_bytes({"package": package}).decode(),
                {
                    "usage_basis": "PROVIDER_REPORTED",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cached_read_tokens": 0,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": 0,
                    "context_tokens": 1,
                    "total_tokens": 2,
                },
            ),
            usage=usage,
            dispatch_fence=nullcontext,
        )(candidate, base, (), ())
    connection.close()


def _usage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "newsroom.control_plane.native_assessor.read_grok_command_semantic_version",
        lambda: "1.0.8",
    )
    monkeypatch.setattr(
        "newsroom.control_plane.native_assessor.cont_writer_implementation_identity",
        lambda: (REVISION, True),
    )
    service = ModelUsageService(str(tmp_path / "usage.sqlite3"))
    policy = InvocationEfficiencyPolicy.create(
        policy_id="native-assessor-policy",
        version="v1",
        workload_class=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
        provider="grok-build-cli",
        route="NATIVE_EVIDENCE_ASSESSOR",
        model="grok-4.6",
        reasoning="low",
        one_turn=True,
        exact_input=True,
        skills_enabled=False,
        tools_enabled=False,
        mcp_enabled=False,
        prior_message_count=0,
        command_semantic_version="1.0.8",
        command_flags=CONT_PRIMARY_COMMAND_FLAGS,
        context_manifest_schema_version=CONTEXT_MANIFEST_SCHEMA_VERSION,
        disabled_capabilities=CONT_DISABLED_CAPABILITIES,
        implementation_revision=REVISION,
        max_prompt_bytes=1_000_000,
        max_context_tokens=100_000,
        max_output_tokens=10_000,
        max_total_tokens=100_000,
        prompt_contract_version=VERSION,
        output_schema_digest=SCHEMA_DIGEST,
        allowed_context_identities=(CONTEXT_IDENTITY,),
        allowed_config_identities=(CONFIG_IDENTITY,),
        hard_estimate_ceiling_tokens=100_000,
        evidence_digest="sha256:" + "a" * 64,
        qualified=True,
    )
    return service, NativeAssessmentUsage(
        service, policy, clock=lambda: datetime(2026, 9, 8, tzinfo=UTC)
    )


def test_native_assessor_uses_exact_candidate_and_base_without_ambient_context(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    calls = []
    fence_active = False
    usage_service, usage = _usage(tmp_path, monkeypatch)

    def dispatch(prompt):
        assert fence_active
        with sqlite3.connect(usage_service.path) as retained:
            assert retained.execute(
                "SELECT state FROM model_transport_observations"
            ).fetchall() == [("DISPATCH_STARTED",)]
        calls.append(prompt)
        return NativeAssessmentExecution(
            canonical_json_bytes(
                {"package": _model_package_value(base)}
            ).decode(),
            {
                "usage_basis": "PROVIDER_REPORTED",
                "input_tokens": 1,
                "output_tokens": 1,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "reasoning_tokens": 0,
                "context_tokens": 1,
                "total_tokens": 2,
            },
        )

    @contextmanager
    def fence():
        nonlocal fence_active
        fence_active = True
        try:
            yield
        finally:
            fence_active = False

    result = AutonomousNativeEvidenceAssessor(
        dispatch, usage=usage, dispatch_fence=fence
    )(
        candidate, base, (), ()
    )
    assert fence_active is False
    request = json.loads(calls[0])
    assert (
        request["candidate_version"]["version"]["version_id"]
        == candidate.version_id
    )
    assert request["base_package"] == evidence_package_value(base)
    assert request["output_schema_digest"] == SCHEMA_DIGEST
    assert result.governed_claims == ()
    with sqlite3.connect(usage_service.path) as retained:
        assert retained.execute(
            "SELECT outcome FROM model_invocation_terminals"
        ).fetchall() == [("ASSESSOR_ACCEPTED",)]

    bad = AutonomousNativeEvidenceAssessor(
        lambda _: NativeAssessmentExecution('{"package": {}}', {})
    )
    with pytest.raises(EvidencePackageError):
        bad(candidate, base, (), ())
    connection.close()


@pytest.mark.parametrize(
    ("dispatch", "outcome"),
    (
        (lambda _: (_ for _ in ()).throw(RuntimeError("provider broke")),
         "ASSESSOR_PROVIDER_FAILED"),
        (lambda _: NativeAssessmentExecution(
            '{"package":{}}', {
            "usage_basis": "PROVIDER_REPORTED",
            "input_tokens": 1,
            "output_tokens": 1,
            "cached_read_tokens": 0,
            "cached_write_tokens": 0,
            "reasoning_tokens": 0,
            "context_tokens": 1,
            "total_tokens": 2,
        }),
         "ASSESSOR_VALIDATION_FAILED"),
    ),
)
def test_native_assessor_retains_post_dispatch_failures(
    tmp_path, monkeypatch, dispatch, outcome,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)

    with pytest.raises((RuntimeError, NativeEvidenceError)) as caught:
        AutonomousNativeEvidenceAssessor(
            dispatch, usage=usage, dispatch_fence=nullcontext
        )(
            candidate, base, (), ()
        )
    if outcome == "ASSESSOR_VALIDATION_FAILED":
        assert isinstance(caught.value, NativeEvidenceHold)
        assert caught.value.reason_code == "ASSESSOR_OUTPUT_CONTRACT_HOLD"

    with sqlite3.connect(service.path) as retained:
        terminal = json.loads(retained.execute(
            "SELECT record_json FROM model_invocation_terminals"
        ).fetchone()[0])
        assert terminal["outcome"] == outcome
        assert terminal["pre_dispatch_zero_proved"] is False
        assert terminal["dispatch_at"] is not None
        assert retained.execute(
            "SELECT state FROM model_transport_observations"
        ).fetchall() == [("DISPATCH_STARTED",)]
    proof = usage.retained_output_contract_failure(candidate)
    if outcome == "ASSESSOR_VALIDATION_FAILED":
        assert proof is not None
        assert proof.invocation_id == terminal["invocation_id"]
        assert proof.terminal_digest == terminal["terminal_digest"]
        monkeypatch.setattr(
            "newsroom.control_plane.native_assessor.SCHEMA_DIGEST",
            "sha256:" + "9" * 64,
        )
        assert usage.retained_output_contract_failure(candidate) is not None
        wrong_candidate = SimpleNamespace(
            candidate_id="wrong-candidate",
            version_id=candidate.version_id,
            governing_manifest=candidate.governing_manifest,
        )
        assert usage.retained_output_contract_failure(wrong_candidate) is None
        with sqlite3.connect(service.path) as retained:
            retained.execute(
                "UPDATE model_invocation_policies SET qualified=0"
            )
        assert usage.retained_output_contract_failure(candidate) is None
        with sqlite3.connect(service.path) as retained:
            retained.execute(
                "UPDATE model_invocation_policies SET qualified=1"
            )
        assert usage.retained_output_contract_failure(candidate) is not None
        with sqlite3.connect(service.path) as retained:
            original_policy = retained.execute(
                "SELECT record_json FROM model_invocation_policies"
            ).fetchone()[0]
            changed_policy = json.loads(original_policy)
            changed_policy["max_total_tokens"] += 1
            retained.execute(
                "UPDATE model_invocation_policies SET record_json=?",
                (json.dumps(changed_policy),),
            )
        assert usage.retained_output_contract_failure(candidate) is None
        with sqlite3.connect(service.path) as retained:
            retained.execute(
                "UPDATE model_invocation_policies SET record_json=?",
                (original_policy,),
            )
        assert usage.retained_output_contract_failure(candidate) is not None
        with sqlite3.connect(service.path) as retained:
            coerced_policy = json.loads(original_policy)
            coerced_policy["qualified"] = 1
            retained.execute(
                "UPDATE model_invocation_policies SET record_json=?",
                (json.dumps(coerced_policy),),
            )
        assert usage.retained_output_contract_failure(candidate) is None
        with sqlite3.connect(service.path) as retained:
            retained.execute(
                "UPDATE model_invocation_policies SET record_json=?",
                (original_policy,),
            )
        assert usage.retained_output_contract_failure(candidate) is not None
        with sqlite3.connect(service.path) as retained:
            retained.execute(
                "UPDATE model_provider_telemetry "
                "SET provider_telemetry_digest=?",
                ("sha256:" + "f" * 64,),
            )
        assert usage.retained_output_contract_failure(candidate) is None
    else:
        assert proof is None
    connection.close()


def test_native_work_envelopes_reject_unrelated_authority_ids() -> None:
    common = {
        "cycle_id": "cycle-1",
        "admitted_at": datetime(2026, 9, 8, tzinfo=UTC),
        "admission_decision_id": None,
        "candidate_id": None,
        "hypothesis_digest": None,
        "evidence_package_digest": None,
        "ingest_id": "passage-1",
        "graphiti_attempt_id": "not-a-native-graphiti-attempt",
    }
    with pytest.raises(ModelUsageIntegrityError):
        WorkEnvelope.create(
            workload_class=WorkloadClass.NATIVE_RETRIEVAL_EMBEDDING,
            **common,
        )
    with pytest.raises(ModelUsageIntegrityError):
        WorkEnvelope.create(
            workload_class=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
            **{
                **common,
                "admission_decision_id": "not-an-assessor-admission",
                "candidate_id": "candidate-1",
                "hypothesis_digest": "sha256:" + "a" * 64,
                "evidence_package_digest": "sha256:" + "b" * 64,
                "ingest_id": None,
                "graphiti_attempt_id": None,
            },
        )


def test_inflight_native_assessor_is_not_a_retained_contract_failure(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    _service, usage = _usage(tmp_path, monkeypatch)

    usage.begin(candidate, base, "in-flight assessor request")

    assert usage.retained_output_contract_failure(candidate) is None
    connection.close()
