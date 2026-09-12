import json
import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.admission import DeterministicWriteAdmission
from newsroom.control_plane.evidence import (
    bounded_named_entities,
    evidence_package_value,
    validate_governed_evidence_records,
)
from newsroom.control_plane.native_assessor import (
    AutonomousNativeEvidenceAssessor,
    CONFIG_IDENTITY,
    CONTEXT_IDENTITY,
    CONTEXT_MANIFEST_SCHEMA_VERSION,
    NativeAssessmentExecution,
    NativeAssessmentUsage,
    REASSESSABLE_HOLDS,
    SCHEMA,
    SCHEMA_DIGEST,
    SYSTEM,
    VERSION,
    _MAX_RETAINED_RESULT_BYTES,
)
from newsroom.control_plane.native_evidence import (
    NativeEvidenceController,
    NativeEvidenceError,
    NativeEvidenceHold,
)
from newsroom.control_plane.model_usage import (
    InvocationEfficiencyPolicy,
    ModelUsageIntegrityError,
    ModelUsageService,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.control_plane.store import connect
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
                }
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
    named["package"]["governed_claims"][0]["named_entities"] = []
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
    invalid_semantic = _model_package_value(assessed)
    invalid_semantic["governed_claims"][0]["semantic_relation"].update({
        "source_modality": "ALLOWS",
        "rendered_modality": "ALLOWS",
        "relation": "EQUIVALENT",
    })
    with pytest.raises(ValidationError):
        validator.validate({"package": invalid_semantic})
    invalid_category = _model_package_value(assessed)
    invalid_category["categories"] = ["immigration"]
    with pytest.raises(ValidationError):
        validator.validate({"package": invalid_category})
    invalid_geography = _model_package_value(assessed)
    invalid_geography["geography"] = ["Britain"]
    with pytest.raises(ValidationError):
        validator.validate({"package": invalid_geography})
    assert VERSION == "newsroom.native-evidence-assessor.v8"
    assert "ASSESSOR_CLAIM_BINDING_HOLD" in REASSESSABLE_HOLDS
    assert "whitespace, newlines and country labels exactly" in SYSTEM
    assert "unfamiliar official source-bound literal" in SYSTEM
    assert "calendar months as months without converting them" in SYSTEM
    connection.close()


def test_native_assessor_derives_entities_from_constructed_uk03_output(
    tmp_path,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    package = _model_package_value(_ready_package(candidate)[1])
    claim = package["governed_claims"][0]
    claim_text = "The Home Office published changes"
    excerpt = "The Home Office published changes to the Skilled Worker Visa."
    claim.update({
        "claim": claim_text,
        "supporting_excerpt": excerpt,
        "rendered_assertion_zh_hant_hk": (
            "Home Office 已公布 Skilled Worker Visa 的修訂。"
        ),
    })
    package.update({
        "substantive_new_information": [claim_text],
        "governed_claims": [claim],
        "qualification_evidence": [],
    })
    role = SimpleNamespace(
        role=SimpleNamespace(value="ORIGINATING_AUTHORITY"),
        purpose="Own immigration rules",
        canonical_value=lambda: {
            "role": "ORIGINATING_AUTHORITY", "purpose": "Own immigration rules",
        },
    )
    source = SimpleNamespace(
        unit=SimpleNamespace(
            source_id="source-1",
            authority=SimpleNamespace(definition_id="definition-1"),
        ),
        source_version=SimpleNamespace(
            canonical_digest="sha256:" + "a" * 64,
            request=SimpleNamespace(roles=(role,)),
        ),
        rights=SimpleNamespace(
            record_id="rights-1",
            decision="PERMITTED",
            permitted_use="PUBLICATION_EVIDENCE",
        ),
        dependency=SimpleNamespace(
            record_id="dependency-1",
            dependency_status="RESOLVED",
            evidential_origin_id="origin-1",
            originating_report_id="report-1",
        ),
    )
    body = excerpt.encode()
    acquired = SimpleNamespace(
        receipt_digest="sha256:" + "b" * 64,
        canonical_url="https://www.gov.uk/example",
        publisher="Home Office",
        responsible_body="Home Office",
        source_type="PRIMARY_OFFICIAL",
        publication_time="2026-09-09T12:00:00.000000Z",
        retrieval_time="2026-09-09T12:01:00.000000Z",
        source_updated_time="2026-09-09T12:00:00.000000Z",
        transport_evidence_digest="sha256:" + "c" * 64,
        geography="UK",
        language="en-GB",
        body=body,
        body_digest=digest_bytes(body),
    )

    invalid_semantic = json.loads(canonical_json_bytes({"package": package}))
    invalid_semantic["package"]["governed_claims"][0][
        "semantic_relation"
    ].update({
        "source_modality": "ALLOWS",
        "rendered_modality": "ALLOWS",
        "relation": "EQUIVALENT",
    })
    with pytest.raises(EvidencePackageError, match="semantic relation"):
        AutonomousNativeEvidenceAssessor._validated_execution(
            NativeAssessmentExecution(
                canonical_json_bytes(invalid_semantic).decode(), {}
            ),
            candidate,
            base,
            (source,),
            (acquired,),
        )

    result = AutonomousNativeEvidenceAssessor._validated_execution(
        NativeAssessmentExecution(
            canonical_json_bytes({"package": package}).decode(), {}
        ),
        candidate,
        base,
        (source,),
        (acquired,),
    )

    assert result.governed_claims[0].named_entities == (
        "Home Office", "Skilled Worker Visa",
    )
    assert result.governed_claims[0].rendered_named_entities == (
        "Home Office", "Skilled Worker Visa",
    )
    governed = replace(
        base,
        substantive_new_information=result.substantive_new_information,
        governed_claims=result.governed_claims,
        qualification_evidence=result.qualification_evidence,
        selection_rationale=result.selection_rationale,
        geography=result.geography,
        categories=result.categories,
        explicit_exclusions=result.explicit_exclusions,
    )
    records = NativeEvidenceController._records(
        base, governed, (source,), (acquired,), result
    )
    retained_rows = tuple(
        (
            record["record_id"],
            record["record_type"],
            canonical_json_bytes(record).decode(),
            digest_bytes(canonical_json_bytes(record)),
        )
        for record in records
    )
    assert validate_governed_evidence_records(
        candidate_id=candidate.candidate_id,
        source_inventory=(("source-1", acquired.canonical_url),),
        base_package_digest=base.digest,
        package=governed,
        retained_records=retained_rows,
    ) is not None
    def decide(assessment, passage, information):
        admitted_package = replace(
            _ready_package(candidate)[1],
            passages=(passage,),
            substantive_new_information=(information,),
            governed_claims=assessment.governed_claims,
            qualification_evidence=(),
            resolved_evidence_records=tuple(
                (
                    record["record_id"],
                    digest_bytes(canonical_json_bytes(record)),
                )
                for record in assessment.assessment_records
            ),
        )
        return DeterministicWriteAdmission().decide_candidate_identity(
            candidate_id=admitted_package.candidate_id,
            hypothesis_id=admitted_package.hypothesis_id,
            package=admitted_package,
            decided_at="2026-09-09T12:02:00.000000Z",
        )

    decision = decide(result, excerpt, claim_text)
    assert "INVALID_GOVERNED_CLAIM_EVIDENCE" not in decision.stable_reason_codes

    for exact_claim, rendered, names in (
        (
            "The applicant must be in the UK.", "申請人必須身在UK。",
            ("UK",),
        ),
        (
            "John Smith said services would resume.",
            "John Smith表示服務將恢復。", ("John Smith",),
        ),
        (
            "Appendix Victim of Domestic Abuse applies.",
            "適用Appendix Victim of Domestic Abuse。",
            ("Appendix Victim of Domestic Abuse",),
        ),
        (
            "General Grounds for Refusal applies.",
            "適用General Grounds for Refusal。",
            ("General Grounds for Refusal",),
        ),
        (
            "AR(EU)1.1 applies.", "適用AR(EU)1.1。", ("AR(EU)1.1",),
        ),
        (
            "Appendix O applies.", "適用Appendix O。", ("Appendix O",),
        ),
        (
            "This route is for ECAA workers, business persons and their family "
            "members who are in the UK and already hold permission in that capacity "
            "and are seeking an extension of their permission.",
            "ECAA工作者、商務人士及其家屬如身在UK並已持有相關許可，"
            "可申請延長許可。",
            ("ECAA", "UK"),
        ),
    ):
        current = json.loads(canonical_json_bytes(package))
        current["governed_claims"][0].update({
            "claim": exact_claim, "supporting_excerpt": exact_claim,
            "rendered_assertion_zh_hant_hk": rendered,
        })
        current["substantive_new_information"] = [exact_claim]
        current_acquired = SimpleNamespace(**{
            **vars(acquired), "body": exact_claim.encode(),
        })
        assessment = AutonomousNativeEvidenceAssessor._validated_execution(
            NativeAssessmentExecution(canonical_json_bytes({"package": current}).decode(), {}),
            candidate, base, (source,), (current_acquired,),
        )
        assert assessment.governed_claims[0].named_entities == names
        assert "INVALID_GOVERNED_CLAIM_EVIDENCE" not in decide(
            assessment, exact_claim, exact_claim
        ).stable_reason_codes

        current["governed_claims"][0]["rendered_assertion_zh_hant_hk"] += " unsupported prose"
        with pytest.raises(NativeEvidenceHold, match="ASSESSOR_RENDERING_CONTRACT_HOLD"):
            AutonomousNativeEvidenceAssessor._validated_execution(
                NativeAssessmentExecution(canonical_json_bytes({"package": current}).decode(), {}),
                candidate, base, (source,), (current_acquired,),
            )

    combined_claim = (
        "From 11 November 2025 all references to General Grounds for Refusal are "
        "to be read as Part Suitability."
    )
    combined = json.loads(canonical_json_bytes(package))
    combined["governed_claims"][0].update({
        "claim": combined_claim,
        "supporting_excerpt": combined_claim,
        "rendered_assertion_zh_hant_hk": (
            "由2025年11月11日起，所有對General Grounds for Refusal的提述須"
            "理解為Part Suitability。"
        ),
        "localised_factual_expressions": [
            ["11 November 2025", "2025年11月11日"]
        ],
    })
    combined["substantive_new_information"] = [combined_claim]
    combined_acquired = SimpleNamespace(**{
        **vars(acquired), "body": combined_claim.encode(),
    })
    combined_assessment = AutonomousNativeEvidenceAssessor._validated_execution(
        NativeAssessmentExecution(
            canonical_json_bytes({"package": combined}).decode(), {}
        ),
        candidate, base, (source,), (combined_acquired,),
    )
    assert combined_assessment.governed_claims[0].named_entities == (
        "General Grounds for Refusal", "Part Suitability",
    )
    assert "INVALID_GOVERNED_CLAIM_EVIDENCE" not in decide(
        combined_assessment, combined_claim, combined_claim
    ).stable_reason_codes

    month_claim = (
        "If the applicant meets the ECAA business person requirement, they will be "
        "granted permission to stay for up to 36 months."
    )
    month = json.loads(canonical_json_bytes(package))
    month["governed_claims"][0].update({
        "claim": month_claim,
        "supporting_excerpt": month_claim,
        "rendered_assertion_zh_hant_hk": (
            "申請人如符合ECAA商務人士要求，可獲准逗留最多36個月。"
        ),
        "localised_factual_expressions": [["36 months", "36個月"]],
    })
    month["substantive_new_information"] = [month_claim]
    month_acquired = SimpleNamespace(**{
        **vars(acquired), "body": month_claim.encode(),
    })
    month_assessment = AutonomousNativeEvidenceAssessor._validated_execution(
        NativeAssessmentExecution(
            canonical_json_bytes({"package": month}).decode(), {}
        ),
        candidate, base, (source,), (month_acquired,),
    )
    assert month_assessment.governed_claims[0].localised_factual_expressions == (
        ("36 months", "36個月"),
    )
    assert "INVALID_GOVERNED_CLAIM_EVIDENCE" not in decide(
        month_assessment, month_claim, month_claim
    ).stable_reason_codes

    boundary_claim = "Changes were published by the Home Office"
    boundary_excerpt = "Home Office announced changes."
    boundary_body = f"{boundary_claim}. {boundary_excerpt}"
    boundary_package = _model_package_value(_ready_package(candidate)[1])
    boundary_package["governed_claims"][0].update({
        "claim": boundary_claim,
        "supporting_excerpt": boundary_excerpt,
        "rendered_assertion_zh_hant_hk": "Home Office 已公布有關修訂。",
    })
    boundary_package.update({
        "substantive_new_information": [boundary_claim],
        "governed_claims": [boundary_package["governed_claims"][0]],
        "qualification_evidence": [],
    })
    boundary_acquired = SimpleNamespace(**{
        **vars(acquired), "body": boundary_body.encode(),
    })
    assert bounded_named_entities(f"{boundary_claim}\n{boundary_excerpt}") != (
        bounded_named_entities(boundary_claim)
        | bounded_named_entities(boundary_excerpt)
    )
    boundary_result = AutonomousNativeEvidenceAssessor._validated_execution(
        NativeAssessmentExecution(
            canonical_json_bytes({"package": boundary_package}).decode(), {}
        ),
        candidate, base, (source,), (boundary_acquired,),
    )
    boundary_decision = decide(boundary_result, boundary_body, boundary_claim)
    assert (
        "INVALID_GOVERNED_CLAIM_EVIDENCE"
        not in boundary_decision.stable_reason_codes
    )
    paraphrased = json.loads(canonical_json_bytes({"package": package}))
    paraphrased["package"]["governed_claims"][0]["claim"] = (
        "The Home Office changed the immigration system"
    )
    with pytest.raises(NativeEvidenceHold, match="ASSESSOR_CLAIM_BINDING_HOLD"):
        AutonomousNativeEvidenceAssessor._validated_execution(
            NativeAssessmentExecution(
                canonical_json_bytes(paraphrased).decode(), {}
            ),
            candidate, base, (source,), (acquired,),
        )
    unsupported = json.loads(canonical_json_bytes({"package": package}))
    unsupported["package"]["governed_claims"][0][
        "supporting_excerpt"
    ] = "published changes to the Skilled Worker Visa."
    with pytest.raises(EvidencePackageError, match="source evidence"):
        AutonomousNativeEvidenceAssessor._validated_execution(
            NativeAssessmentExecution(canonical_json_bytes(unsupported).decode(), {}),
            candidate, base, (source,), (acquired,),
        )
    changed = json.loads(canonical_json_bytes({"package": package}))
    changed["package"]["governed_claims"][0][
        "rendered_assertion_zh_hant_hk"
    ] = "Home Office 已公布修訂。"
    with pytest.raises(EvidencePackageError, match="rendered named entities"):
        AutonomousNativeEvidenceAssessor._validated_execution(
            NativeAssessmentExecution(canonical_json_bytes(changed).decode(), {}),
            candidate, base, (source,), (acquired,),
        )
    invented = json.loads(canonical_json_bytes({"package": package}))
    invented["package"]["governed_claims"][0][
        "rendered_assertion_zh_hant_hk"
    ] += " NHS England"
    with pytest.raises(EvidencePackageError, match="rendered named entities"):
        AutonomousNativeEvidenceAssessor._validated_execution(
            NativeAssessmentExecution(canonical_json_bytes(invented).decode(), {}),
            candidate, base, (source,), (acquired,),
        )

    for source_claim, altered_span in (
        (
            "Immigration Rules part 4: work experience\n\n“Au pair” placements "
            "DELETED Working holidaymakers DELETED",
            "Immigration Rules part 4: work experience “Au pair” placements "
            "DELETED Working holidaymakers DELETED",
        ),
        (
            "for travel to the UK on or after 8 January 2025: Antigua and Barbuda "
            "Argentina Australia Barbados Belize Brazil Brunei Canada Chile Costa "
            "Rica Grenada Guatemala Guyana Hong Kong Special Administrative Region",
            "for travel to the UK on or after 8 January 2025: Hong Kong Special "
            "Administrative Region",
        ),
    ):
        for field in ("claim", "supporting_excerpt"):
            altered = json.loads(canonical_json_bytes({"package": package}))
            altered_claim = altered["package"]["governed_claims"][0]
            altered_claim.update({
                "claim": source_claim,
                "supporting_excerpt": source_claim,
                "rendered_assertion_zh_hant_hk": (
                    "UK及Hong Kong內容。" if "Hong Kong" in source_claim else "內容。"
                ),
            })
            altered_claim[field] = altered_span
            altered["package"]["substantive_new_information"] = [
                altered_claim["claim"]
            ]
            altered_acquired = SimpleNamespace(**{
                **vars(acquired), "body": source_claim.encode(),
            })
            with pytest.raises(
                NativeEvidenceHold, match="ASSESSOR_CLAIM_BINDING_HOLD"
            ):
                AutonomousNativeEvidenceAssessor._validated_execution(
                    NativeAssessmentExecution(
                        canonical_json_bytes(altered).decode(), {}
                    ),
                    candidate, base, (source,), (altered_acquired,),
                )
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
        lambda **_kwargs: "1.0.8",
    )
    monkeypatch.setattr(
        "newsroom.control_plane.native_assessor.cont_writer_implementation_identity",
        lambda: (REVISION, True),
    )
    service = ModelUsageService(str(tmp_path / "usage.sqlite3"))
    connect(service.path).close()
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

    boundaries = []

    def before_dispatch():
        with sqlite3.connect(usage_service.path) as retained:
            assert retained.execute(
                "SELECT COUNT(*) FROM model_invocation_allocations"
            ).fetchone() == (1,)
            assert retained.execute(
                "SELECT COUNT(*) FROM model_transport_observations"
            ).fetchone() == (0,)
        boundaries.append("ASSESSMENT_STARTED")

    result = AutonomousNativeEvidenceAssessor(
        dispatch, usage=usage, dispatch_fence=fence
    ).assess_with_boundary(
        candidate, base, (), (), before_dispatch=before_dispatch
    )
    assert fence_active is False
    assert boundaries == ["ASSESSMENT_STARTED"]
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


def test_native_assessor_command_version_is_observed_without_becoming_a_gate(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "newsroom.control_plane.native_assessor.read_grok_command_semantic_version",
        lambda: "1.0.9",
    )
    allocation = usage.begin(candidate, base, "retained assessor prompt")
    with sqlite3.connect(service.path) as retained:
        assert retained.execute(
            "SELECT count(*) FROM model_work_envelopes"
        ).fetchone() == (1,)
        assert retained.execute(
            "SELECT count(*) FROM model_invocation_allocations"
        ).fetchone() == (1,)
        assert retained.execute(
            "SELECT count(*) FROM model_transport_observations"
        ).fetchone() == (0,)
        manifest = json.loads(retained.execute(
            "SELECT record_json FROM model_invocation_context_manifests "
            "WHERE context_manifest_digest=?",
            (allocation.context_manifest_digest,),
        ).fetchone()[0])
        assert manifest["command_semantic_version"] == "1.0.9"
    connection.close()


def test_native_assessor_pre_dispatch_recovery_requires_zero_exact_envelopes(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    _service, usage = _usage(tmp_path, monkeypatch)

    proof = usage.retained_pre_dispatch_failure(candidate)
    assert proof is not None
    assert proof.candidate_id == candidate.candidate_id
    assert proof.candidate_version_id == candidate.version_id
    allocation = usage.begin(candidate, base, "retained assessor prompt")
    assert usage.retained_pre_dispatch_failure(candidate) is None
    other = SimpleNamespace(
        candidate_id="other-candidate",
        version_id="other-version",
        governing_manifest=SimpleNamespace(
            canonical_digest=candidate.governing_manifest.canonical_digest
        ),
    )
    assert usage.retained_pre_dispatch_failure(other) is not None
    with sqlite3.connect(_service.path) as usage_connection:
        usage_connection.execute(
            "UPDATE model_invocation_allocations SET envelope_id='orphan'"
        )
    assert usage.retained_pre_dispatch_failure(other) is None
    with sqlite3.connect(_service.path) as usage_connection:
        usage_connection.execute(
            "UPDATE model_invocation_allocations SET envelope_id=?",
            (allocation.envelope_id,),
        )
    assert usage.retained_pre_dispatch_failure(other) is not None
    dispatch_at = usage.mark_dispatch(allocation)
    with sqlite3.connect(_service.path) as usage_connection:
        usage_connection.execute(
            "UPDATE model_transport_observations SET invocation_id='orphan'"
        )
    assert usage.retained_pre_dispatch_failure(other) is None
    with sqlite3.connect(_service.path) as usage_connection:
        usage_connection.execute(
            "UPDATE model_transport_observations SET invocation_id=?",
            (allocation.invocation_id,),
        )
    usage.complete(
        allocation,
        outcome="ASSESSOR_PROVIDER_FAILED",
        execution=NativeAssessmentExecution(
            "provider response",
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
        provider_dispatched=True,
        dispatch_at=dispatch_at,
        failure_class="SYSTEMIC",
    )
    assert usage.retained_pre_dispatch_failure(other) is not None
    with sqlite3.connect(_service.path) as usage_connection:
        usage_connection.execute("PRAGMA foreign_keys=OFF")
        usage_connection.execute("DELETE FROM model_transport_observations")
        usage_connection.execute("DELETE FROM model_invocation_allocations")
        usage_connection.execute("DELETE FROM model_work_envelopes")
        assert usage_connection.execute(
            "SELECT COUNT(*) FROM model_invocation_terminals"
        ).fetchone() == (1,)
    assert usage.retained_pre_dispatch_failure(other) is None
    connection.close()


@pytest.mark.parametrize(
    ("output", "outcome"),
    (
        (None, "ASSESSOR_PROVIDER_FAILED"),
        ('{"package":{}}', "ASSESSOR_VALIDATION_FAILED"),
        ('{', "ASSESSOR_VALIDATION_FAILED"),
        ('{"package":{},"package":{}}', "ASSESSOR_VALIDATION_FAILED"),
    ),
)
def test_native_assessor_retains_post_dispatch_failures(
    tmp_path,
    monkeypatch,
    output,
    outcome,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)
    dispatches = 0

    def dispatch(_request):
        nonlocal dispatches
        dispatches += 1
        if output is None:
            raise RuntimeError("provider broke")
        return NativeAssessmentExecution(
            output,
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

    with pytest.raises((RuntimeError, NativeEvidenceError)) as caught:
        AutonomousNativeEvidenceAssessor(
            dispatch, usage=usage, dispatch_fence=nullcontext
        )(
            candidate, base, (), ()
        )
    if outcome == "ASSESSOR_VALIDATION_FAILED":
        assert isinstance(caught.value, NativeEvidenceHold)
        assert caught.value.reason_code == "ASSESSOR_OUTPUT_CONTRACT_HOLD"
    assert dispatches == 1

    with sqlite3.connect(service.path) as retained:
        terminal = json.loads(retained.execute(
            "SELECT record_json FROM model_invocation_terminals"
        ).fetchone()[0])
        assert terminal["outcome"] == outcome
        assert terminal["pre_dispatch_zero_proved"] is False
        assert terminal["dispatch_at"] is not None
        assert retained.execute(
            "SELECT state FROM model_transport_observations ORDER BY state"
        ).fetchall() == [("DISPATCH_STARTED",)]
        result_rows = retained.execute(
            "SELECT payload_json FROM ledger WHERE kind='NATIVE_ASSESSMENT_RESULT'"
        ).fetchall()
        assert len(result_rows) == (0 if output is None else 1)
        if output is not None:
            diagnostic = json.loads(result_rows[0][0])
            assert diagnostic["result_text"] == output
            assert diagnostic["result_bytes"] == len(output.encode())
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


def test_native_assessor_result_diagnostic_is_bounded_and_replay_safe(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)
    allocation = usage.begin(candidate, base, "exact request")
    dispatch_at = usage.mark_dispatch(allocation)
    execution = NativeAssessmentExecution('{"malformed":true}', {})

    assert usage.retain_result(
        allocation, execution, dispatch_at=dispatch_at
    ) is True
    assert usage.retain_result(
        allocation, execution, dispatch_at=dispatch_at
    ) is True
    with pytest.raises(
        NativeEvidenceError, match="conflicting native assessment result replay"
    ):
        usage.retain_result(
            allocation,
            NativeAssessmentExecution('{"different":true}', {}),
            dispatch_at=dispatch_at,
        )
    with sqlite3.connect(service.path) as retained:
        result = json.loads(retained.execute(
            "SELECT payload_json FROM ledger WHERE kind='NATIVE_ASSESSMENT_RESULT'"
        ).fetchone()[0])
        assert result["result_text"] == execution.text
        assert result["result_digest"] == digest_bytes(execution.text.encode())
        assert result["retention_outcome"] == "RETAINED"
        assert retained.execute(
            "SELECT COUNT(*) FROM ledger WHERE kind='NATIVE_ASSESSMENT_RESULT'"
        ).fetchone()[0] == 1
        assert retained.execute(
            "SELECT COUNT(*) FROM model_invocation_terminals"
        ).fetchone()[0] == 0
    connection.close()


def test_native_assessor_result_diagnostic_rejects_oversized_output(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)
    allocation = usage.begin(candidate, base, "exact request")
    dispatch_at = usage.mark_dispatch(allocation)
    text = "x" * (_MAX_RETAINED_RESULT_BYTES + 1)

    assert usage.retain_result(
        allocation, NativeAssessmentExecution(text, {}), dispatch_at=dispatch_at
    ) is False
    with sqlite3.connect(service.path) as retained:
        result = json.loads(retained.execute(
            "SELECT payload_json FROM ledger WHERE kind='NATIVE_ASSESSMENT_RESULT'"
        ).fetchone()[0])
    assert result["result_text"] is None
    assert result["result_bytes"] == len(text)
    assert result["result_digest"] == digest_bytes(text.encode())
    assert result["retention_outcome"] == "OVERSIZED"
    connection.close()


def test_native_assessor_oversized_result_becomes_accounted_contract_hold(
    tmp_path, monkeypatch,
) -> None:
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)
    output = "x" * (_MAX_RETAINED_RESULT_BYTES + 1)
    provider_usage = {
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": 1,
        "output_tokens": 1,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "reasoning_tokens": 0,
        "context_tokens": 1,
        "total_tokens": 2,
    }

    with pytest.raises(
        NativeEvidenceHold, match="ASSESSOR_OUTPUT_CONTRACT_HOLD"
    ):
        AutonomousNativeEvidenceAssessor(
            lambda _request: NativeAssessmentExecution(output, provider_usage),
            usage=usage,
            dispatch_fence=nullcontext,
        )(candidate, base, (), ())

    with sqlite3.connect(service.path) as retained:
        assert retained.execute(
            "SELECT outcome FROM model_invocation_terminals"
        ).fetchall() == [("ASSESSOR_VALIDATION_FAILED",)]
        result = json.loads(retained.execute(
            "SELECT payload_json FROM ledger WHERE kind='NATIVE_ASSESSMENT_RESULT'"
        ).fetchone()[0])
        assert result["retention_outcome"] == "OVERSIZED"
        assert result["result_text"] is None
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


@pytest.mark.parametrize("new_contract", (False, True))
def test_retained_assessment_revalidation_reuses_output_without_provider(tmp_path, monkeypatch, new_contract):
    import newsroom.control_plane.native_assessor as module

    if new_contract:
        monkeypatch.setattr(module, "VERSION", "newsroom.native-evidence-assessor.v7")
        monkeypatch.setattr(__import__(__name__, fromlist=["VERSION"]), "VERSION", module.VERSION)
    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    service, usage = _usage(tmp_path, monkeypatch)
    calls = []

    def dispatch(_prompt):
        calls.append("provider")
        return NativeAssessmentExecution(
            canonical_json_bytes({"package": _model_package_value(base)}).decode(),
            {"usage_basis": "PROVIDER_REPORTED", "input_tokens": 1,
             "output_tokens": 1, "cached_read_tokens": 0, "cached_write_tokens": 0,
             "reasoning_tokens": 0, "context_tokens": 1, "total_tokens": 2},
        )

    assessor = AutonomousNativeEvidenceAssessor(dispatch, usage=usage, dispatch_fence=nullcontext)
    first = assessor(candidate, base, (), ())
    if new_contract:
        monkeypatch.setattr(module, "VERSION", "newsroom.native-evidence-assessor.v8")
        monkeypatch.setattr(__import__(__name__, fromlist=["VERSION"]), "VERSION", module.VERSION)
        _, usage = _usage(tmp_path, monkeypatch)
        assessor = AutonomousNativeEvidenceAssessor(dispatch, usage=usage, dispatch_fence=nullcontext)
    assert assessor(candidate, base, (), ()) == first
    assert calls == ["provider"]
    with sqlite3.connect(service.path) as retained:
        assert retained.execute("SELECT COUNT(*) FROM model_invocation_allocations").fetchone() == (1,)
        original_digest = retained.execute("SELECT payload_digest FROM ledger WHERE kind='NATIVE_ASSESSMENT_RESULT'").fetchone()[0]
        retained.execute("UPDATE ledger SET payload_digest='corrupt' WHERE kind='NATIVE_ASSESSMENT_RESULT'")
    with pytest.raises(NativeEvidenceHold, match="ASSESSOR_REVALIDATION_UNRESOLVED_HOLD"):
        assessor(candidate, base, (), ())
    assert calls == ["provider"]
    with sqlite3.connect(service.path) as retained:
        retained.execute("UPDATE ledger SET payload_digest=? WHERE kind='NATIVE_ASSESSMENT_RESULT'", (original_digest,))
        retained.execute("UPDATE model_work_envelopes SET record_json=json_set(record_json,'$.candidate_id','hidden')")
    with pytest.raises(NativeEvidenceHold, match="ASSESSOR_REVALIDATION_UNRESOLVED_HOLD"):
        assessor(candidate, base, (), ())
    assert calls == ["provider"]
    connection.close()


@pytest.mark.parametrize("settled", (True, False))
def test_superseded_assessor_allows_one_new_contract_attempt_only_after_settlement(tmp_path, monkeypatch, settled):
    import newsroom.control_plane.native_assessor as module

    connection, _port, candidate = _candidate(tmp_path)
    base = _base_package(_ready_package(candidate)[1])
    monkeypatch.setattr(module, "VERSION", "newsroom.native-evidence-assessor.v7")
    monkeypatch.setattr(__import__(__name__, fromlist=["VERSION"]), "VERSION", module.VERSION)
    service, old_usage = _usage(tmp_path, monkeypatch)
    execution = NativeAssessmentExecution(
        "not JSON",
        {"usage_basis": "PROVIDER_REPORTED", "input_tokens": 1,
         "output_tokens": 1, "cached_read_tokens": 0, "cached_write_tokens": 0,
         "reasoning_tokens": 0, "context_tokens": 1, "total_tokens": 2},
    )
    if settled:
        with pytest.raises(NativeEvidenceHold):
            AutonomousNativeEvidenceAssessor(
                lambda _: execution, usage=old_usage, dispatch_fence=nullcontext,
            )(candidate, base, (), ())
    else:
        old_usage.begin(candidate, base, "unknown prior attempt")
    monkeypatch.setattr(module, "VERSION", "newsroom.native-evidence-assessor.v8")
    monkeypatch.setattr(__import__(__name__, fromlist=["VERSION"]), "VERSION", module.VERSION)
    _, new_usage = _usage(tmp_path, monkeypatch)
    calls = []

    def dispatch(_prompt):
        calls.append("provider")
        return execution

    assessor = AutonomousNativeEvidenceAssessor(dispatch, usage=new_usage, dispatch_fence=nullcontext)
    for _ in range(2):
        with pytest.raises(NativeEvidenceHold):
            assessor(candidate, base, (), ())
    assert calls == (["provider"] if settled else [])
    with sqlite3.connect(service.path) as retained:
        assert retained.execute("SELECT COUNT(*) FROM model_invocation_allocations").fetchone() == (2 if settled else 1,)
    connection.close()
