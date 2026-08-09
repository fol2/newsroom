from __future__ import annotations

import itertools
import json
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5.retrieval_context import RETRIEVAL_CONTEXT_CONTRACT_DIGEST
from newsroom.increment6.dispositions import (
    DISPOSITION_AUTHORITY,
    MAX_DISPOSITION_CANONICAL_BYTES,
    PROPOSAL_DISPOSITION,
    PROPOSAL_DISPOSITION_SCHEMA_VERSION,
    PROPOSAL_VALIDATION_FINDING,
    PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION,
    VALIDATED_PROPOSAL_LEAD_DISPOSITION_BINDING,
    DispositionAuthority,
    DispositionContractError,
    DispositionJudgement,
    LeadDispositionHeadBinding,
    ProposalDisposition,
    ProposalValidationFinding,
    ValidatorInputBinding,
    build_pending_dispositions,
    validate_proposal,
)
from newsroom.increment6.outcomes import (
    CanonicalNextAction,
    CanonicalOutcome,
    DecisionTerminality,
    NextAction,
    ReasonBasisClass,
    ReasonCode,
    ReasonReference,
    StructuredReason,
    OutcomeSelection,
)
from newsroom.increment6.proposals import (
    PROPOSAL_SCHEMA_VERSION,
    ProposalRoute,
    TriageProposal,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
LEAD_A = "11111111-1111-4111-8111-111111111111"
LEAD_B = "22222222-2222-4222-8222-222222222222"


def _recommendation(lead_id: str, route: str = "NEW_EVENT_CANDIDATE") -> dict[str, object]:
    value: dict[str, object] = {
        "decision_lead_id": lead_id,
        "route": route,
        "confidence": {"decimal": "0.750000", "millionths": 750_000},
        "uncertainty": {"decimal": "0.125000", "millionths": 125_000},
        "input_citations": [{
            "citation_id": f"citation:{lead_id[:4]}", "source_kind": "DECISION_LEAD",
            "source_id": lead_id, "source_digest": DIGEST_B, "field_path": "lead.summary",
            "byte_start": 0, "byte_end": 18, "quote_digest": DIGEST_D,
            "target_hypothesis_id": None,
        }, {
            "citation_id": f"retrieval:{lead_id[:4]}", "source_kind": "RETRIEVAL_MATCH",
            "source_id": f"passage:{lead_id[:4]}", "source_digest": DIGEST_C,
            "field_path": "passage.text", "byte_start": 0, "byte_end": 18,
            "quote_digest": DIGEST_D, "target_hypothesis_id": None,
        }],
        "likely_new_information": "A material new state may have occurred.",
        "materiality_basis": "The possible change may affect readers.",
        "missing_context": [], "retrieval_incompleteness": [],
        "hypothesis": None, "watch_action": None, "supplemental_action": None,
        "operational_action": None, "candidate_manifest": None,
    }
    if route == "WATCH_DEFER":
        value["watch_action"] = {"condition_kind": "SOURCE_UPDATE", "condition": "Resume when the named source changes.", "next_action": "REENTER_DISCOVERY"}
    elif route == "SUPPLEMENTAL_DISCOVERY":
        value["supplemental_action"] = {"action_kind": "CHECK_NAMED_SOURCE", "scope": "The primary organisation newsroom", "maximum_attempts": 1, "requires_approval": True}
    elif route == "OPERATIONAL_HOLD":
        value["operational_action"] = {"action_kind": "RETRY_RETRIEVAL", "owner_id": None, "dependency": None, "retry_condition": "Retry after service recovery.", "review_condition": None, "expiry_condition": None}
    elif route == "ASSOCIATE_WITHOUT_CANDIDATE":
        target = "44444444-4444-4444-8444-444444444444"
        value["hypothesis"] = {"proposal_local_id": f"hypothesis:{lead_id[:4]}", "summary": "The lead concerns a prior state.", "relationship_kind": "SAME_STATE", "target_hypothesis_id": target}
        value["input_citations"][1]["target_hypothesis_id"] = target
    elif route.endswith("_CANDIDATE"):
        kind, relationship, target = {
            "NEW_EVENT_CANDIDATE": ("NEW_EVENT", "NO_ADEQUATE_PRIOR_MATCH", None),
            "DEVELOPMENT_CANDIDATE": ("DEVELOPMENT", "DEVELOPMENT_OF", "44444444-4444-4444-8444-444444444444"),
            "CORRECTION_CANDIDATE": ("CORRECTION", "CORRECTION_REVERSAL_OF", "44444444-4444-4444-8444-444444444444"),
        }[route]
        value["hypothesis"] = {"proposal_local_id": f"hypothesis:{lead_id[:4]}", "summary": "A proposed event relationship.", "relationship_kind": relationship, "target_hypothesis_id": target}
        if target is not None:
            value["input_citations"][1]["target_hypothesis_id"] = target
        value["candidate_manifest"] = {"manifest_kind": kind, "contributing_lead_ids": [lead_id], "proposed_geography": "GB", "proposed_category": "UK_NEWS", "urgency": "ROUTINE", "likely_new_information": value["likely_new_information"], "reader_utility_basis": "Readers need the change.", "uncertainties": ["Unverified"], "evidence_objectives": ["Confirm independently"], "governing_versions": ["candidate-policy-v1"]}
    return value


def _proposal_bytes(routes: tuple[str, ...] = ("NEW_EVENT_CANDIDATE",)) -> bytes:
    available_leads = (
        (LEAD_A, LEAD_B)
        if len(routes) <= 2
        else tuple(
            f"00000000-0000-4000-8000-{index:012d}"
            for index in range(1, 33)
        )
    )
    leads = available_leads[:len(routes)]
    proposal: dict[str, object] = {
        "proposal_id": "84d0ae8c-1378-4b76-8792-1bb805ab6a91",
        "work_item_binding": {"work_item_id": "4d3b1b83-205e-4f77-a46b-ffbf5509d254", "work_item_version_id": "c37c30fd-cfab-4a57-ab69-a72515ebaa31", "work_item_version_digest": DIGEST_D},
        "retrieval_context_binding": {"context_id": "3d2f3791-c365-47f6-b543-65ecfd6b0eba", "context_digest": DIGEST_A, "contract_digest": RETRIEVAL_CONTEXT_CONTRACT_DIGEST},
        "worker_attempt_binding": {"attempt_id": "attempt:fixture:0001", "attempt_digest": DIGEST_C, "worker_kind": "FAKE", "worker_version": "fixture-worker-v1", "input_digest": DIGEST_B, "work_item_version_digest": DIGEST_D, "retrieval_context_digest": DIGEST_A},
        "decision_lead_ids": list(leads), "context_lead_ids": [],
        "recommendations": [_recommendation(lead, route) for lead, route in zip(leads, routes, strict=True)],
        "rationale": "A bounded triage recommendation.",
        "authority": {"effect": "NONE", "creates_hypothesis": False, "creates_candidate": False, "mutates_editorial_state": False, "publication_authority": False, "evidence_authority": False, "operational_authority": False},
    }
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": proposal}
    return canonical_json_bytes({**identity, "content_identity": digest_bytes(canonical_json_bytes(identity))})


def _resign(document: dict[str, object]) -> bytes:
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": document["proposal"]}
    document["content_identity"] = digest_bytes(canonical_json_bytes(identity))
    return canonical_json_bytes(document)


def _reviewed_large_producer_payload() -> bytes:
    """Reproduce the reviewed legal eight-Lead #356 payload's exact size."""

    raw = _proposal_bytes(("EDITORIAL_REJECT",) * 8)
    document = json.loads(raw)
    recommendations = document["proposal"]["recommendations"]
    for recommendation in recommendations:
        lead_id = recommendation["decision_lead_id"]
        recommendation["input_citations"] = [
            {
                "citation_id": f"citation:{index:03d}:" + "c" * 230,
                "source_kind": "DECISION_LEAD" if index == 0 else "RETRIEVAL_MATCH",
                "source_id": lead_id if index == 0 else f"passage:{index:03d}:" + "p" * 230,
                "source_digest": DIGEST_B,
                "field_path": f"passage:{index:03d}." + "f" * 230,
                "byte_start": index * 20,
                "byte_end": index * 20 + 18,
                "quote_digest": DIGEST_D,
                "target_hypothesis_id": None,
            }
            for index in range(64)
        ]
        recommendation["likely_new_information"] = "n" * 1_024
        recommendation["materiality_basis"] = "m" * 1_024
        recommendation["missing_context"] = [
            f"{index:02d}:" + "x" * 1_020 for index in range(32)
        ]
        recommendation["retrieval_incompleteness"] = [
            f"{index:02d}:" + "y" * 1_020 for index in range(32)
        ]
    document["proposal"]["rationale"] = "r" * 4_096

    target_size = 1_103_922
    deficit = target_size - len(_resign(document))
    for recommendation in recommendations:
        for citation in recommendation["input_citations"]:
            for field, fill in (("field_path", "f"), ("citation_id", "c"), ("source_id", "p")):
                if field == "source_id" and citation["source_kind"] == "DECISION_LEAD":
                    continue
                available = 256 - len(citation[field].encode("utf-8"))
                addition = min(deficit, available)
                citation[field] += fill * addition
                deficit -= addition
                if deficit == 0:
                    raw = _resign(document)
                    assert len(raw) == target_size
                    return raw
    raise AssertionError("reviewed producer payload could not reach its exact size")


def _maximal_escaped_producer_payload() -> bytes:
    """Exercise every dominant #356 text/list/citation bound across 32 Leads."""

    document = json.loads(_proposal_bytes(("NEW_EVENT_CANDIDATE",) * 32))
    bounded_text = "\x01" * 1_024

    def unique_text(index: int) -> str:
        return f"{index:02d}:" + "\x01" * 1_021

    def full_token(prefix: str, fill: str = "x") -> str:
        return prefix + fill * (256 - len(prefix))

    for recommendation in document["proposal"]["recommendations"]:
        lead_id = recommendation["decision_lead_id"]
        recommendation["input_citations"] = [
            {
                "citation_id": full_token(f"citation:{index:03d}:", "c"),
                "source_kind": "DECISION_LEAD" if index == 0 else "RETRIEVAL_MATCH",
                "source_id": lead_id if index == 0 else full_token(f"passage:{index:03d}:", "p"),
                "source_digest": DIGEST_B,
                "field_path": "\x01" * 256,
                "byte_start": index * 20,
                "byte_end": index * 20 + 18,
                "quote_digest": DIGEST_D,
                "target_hypothesis_id": None,
            }
            for index in range(64)
        ]
        recommendation["likely_new_information"] = bounded_text
        recommendation["materiality_basis"] = bounded_text
        recommendation["missing_context"] = [unique_text(index) for index in range(32)]
        recommendation["retrieval_incompleteness"] = [
            f"{index:02d};" + "\x01" * 1_021 for index in range(32)
        ]
        recommendation["hypothesis"].update({
            "proposal_local_id": full_token(f"hypothesis:{lead_id[:8]}:"),
            "summary": bounded_text,
        })
        recommendation["candidate_manifest"].update({
            "proposed_geography": full_token("geography:"),
            "proposed_category": full_token("category:"),
            "urgency": full_token("urgency:"),
            "likely_new_information": bounded_text,
            "reader_utility_basis": bounded_text,
            "uncertainties": [unique_text(index) for index in range(32)],
            "evidence_objectives": [
                f"{index:02d};" + "\x01" * 1_021 for index in range(32)
            ],
            "governing_versions": [
                full_token(f"version:{index:02d}:", "v") for index in range(32)
            ],
        })
    document["proposal"]["rationale"] = "\x01" * 4_096
    return _resign(document)


def _validator(raw: bytes | None = None) -> ValidatorInputBinding:
    return ValidatorInputBinding.for_proposal(
        proposal_bytes=_proposal_bytes() if raw is None else raw,
        validator_id="validator:fixture", validator_version="1",
        authenticated_context_identity=DIGEST_A,
        retrieval_request_id="request:001", retrieval_request_digest=DIGEST_B,
        retrieval_receipt_id="receipt:001", retrieval_receipt_digest=DIGEST_C,
        ruleset_id="triage-rules", ruleset_version="1", ruleset_digest=DIGEST_D,
    )


def _selection(outcome: CanonicalOutcome, action: CanonicalNextAction, reason: ReasonCode, terminality: DecisionTerminality = DecisionTerminality.TERMINAL_EXACT_VERSION) -> OutcomeSelection:
    return OutcomeSelection(
        outcome=outcome, terminality=terminality,
        primary_reason=StructuredReason(code=reason, basis=ReasonBasisClass.DETERMINISTIC_POLICY, references=(ReasonReference("proposal", "proposal:1", DIGEST_A),), explanation="Exact proposal route policy."),
        supporting_reasons=(),
        next_action=NextAction(action.kind, action, "condition:1" if action.kind.value in {"RETRY", "REVIEW", "WAIT_DEPENDENCY", "RESUME_ON_WATCH", "REQUEST_SUPPLEMENTAL_DISCOVERY"} else None),
    )


def test_public_allocation_and_no_authority_are_exact() -> None:
    assert PROPOSAL_VALIDATION_FINDING == PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION == "newsroom.increment6.triage-proposal-finding.v1"
    assert PROPOSAL_DISPOSITION == PROPOSAL_DISPOSITION_SCHEMA_VERSION == "newsroom.increment6.triage-proposal-disposition.v1"
    assert DISPOSITION_AUTHORITY is DispositionAuthority
    assert VALIDATED_PROPOSAL_LEAD_DISPOSITION_BINDING == "EXACT_PROPOSAL_FINDING_SET_AND_CURRENT_LEAD_HEAD"
    assert set(DispositionAuthority) == {DispositionAuthority.NONE, DispositionAuthority.PENDING}


def test_validation_findings_are_canonical_deterministic_and_permutation_invariant() -> None:
    raw = _proposal_bytes(("NEW_EVENT_CANDIDATE", "NEW_EVENT_CANDIDATE"))
    first = validate_proposal(raw, _validator(raw))
    second = validate_proposal(raw, _validator(raw))
    assert first.canonical_bytes == second.canonical_bytes
    assert first.finding_set_digest == second.finding_set_digest
    assert len(first.findings) == 2
    assert tuple(item.finding_id for item in first.findings) == tuple(sorted(item.finding_id for item in first.findings))
    parsed = ProposalValidationFinding.from_canonical_bytes(first.findings[0].canonical_bytes)
    assert parsed == first.findings[0]
    assert parsed.authority is DispositionAuthority.NONE
    assert parsed.authorises_persistence is False


@pytest.mark.parametrize("mutation", ["unknown", "tamper", "duplicate", "depth", "size"])
def test_validation_input_fails_closed_for_noncanonical_or_unbounded_json(mutation: str) -> None:
    raw = _proposal_bytes()
    if mutation == "unknown":
        value = json.loads(raw); value["unknown"] = True; raw = canonical_json_bytes(value)
    elif mutation == "tamper":
        value = json.loads(raw); value["proposal"]["rationale"] = "Changed"; raw = canonical_json_bytes(value)
    elif mutation == "duplicate":
        raw = raw[:-1] + b',"schema_version":"newsroom.increment6.triage-proposal.v1"}'
    elif mutation == "depth":
        raw = b'[' * 70 + b'0' + b']' * 70
    else:
        raw = b" " * 1_100_000
    with pytest.raises(DispositionContractError, match="integrity"):
        validate_proposal(raw, _validator())


def test_validator_identity_ruleset_receipt_and_input_are_all_bound() -> None:
    result = validate_proposal(_proposal_bytes(), _validator())
    value = result.findings[0].canonical_value()["finding"]
    assert value["validator_input_binding"] == _validator().canonical_value()
    assert _validator().authority is DispositionAuthority.PENDING
    assert _validator().authorises_persistence is False
    for field in ("authenticated_context_identity", "ruleset_digest", "input_digest", "retrieval_receipt_digest"):
        with pytest.raises(DispositionContractError):
            replace(_validator(), **{field: "forged"})
    mismatched = replace(_validator(), input_digest=DIGEST_B)
    with pytest.raises(DispositionContractError, match="validation envelope"):
        validate_proposal(_proposal_bytes(), mismatched)


ROUTE_MATRIX = {
    ProposalRoute.EDITORIAL_REJECT: (DispositionJudgement.REJECT, CanonicalOutcome.LEAD_EDITORIAL_REJECT, CanonicalNextAction.CLOSE_DECISION, ReasonCode.NOVELTY_EXACT_DUPLICATE, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.WATCH_DEFER: (DispositionJudgement.HOLD, CanonicalOutcome.LEAD_WATCH_DEFER, CanonicalNextAction.AWAIT_WATCH_CONDITION, ReasonCode.TIME_WATCH_REVIEW, DecisionTerminality.PENDING_CONDITION),
    ProposalRoute.ASSOCIATE_WITHOUT_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE, CanonicalNextAction.CLOSE_DECISION, ReasonCode.REL_SAME_STATE, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.SUPPLEMENTAL_DISCOVERY: (DispositionJudgement.ESCALATE, CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY, CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY, ReasonCode.SEARCH_PARTIAL_RESULTS, DecisionTerminality.PENDING_CONDITION),
    ProposalRoute.OPERATIONAL_HOLD: (DispositionJudgement.HOLD, CanonicalOutcome.LEAD_OPERATIONAL_HOLD, CanonicalNextAction.WAIT_FOR_DEPENDENCY, ReasonCode.OPS_RETRIEVAL, DecisionTerminality.PENDING_CONDITION),
    ProposalRoute.NEW_EVENT_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.NOVELTY_LIKELY_NEW_EVENT, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.DEVELOPMENT_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_DEVELOPMENT_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.NOVELTY_LIKELY_DEVELOPMENT, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.CORRECTION_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_CORRECTION_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.REL_CORRECTION_REVERSAL, DecisionTerminality.TERMINAL_EXACT_VERSION),
}


def test_exact_route_outcome_reason_action_matrix_and_cross_route_rejection() -> None:
    assert set(ROUTE_MATRIX) == set(ProposalRoute)
    # Proposal parsing already proves all route-specific action seams; exercise the
    # disposition matrix on the minimal new-event fixture and inspect all policies.
    result = validate_proposal(_proposal_bytes(), _validator())
    for route, (_, outcome, action, reason, terminality) in ROUTE_MATRIX.items():
        route_raw = _proposal_bytes((route.value,))
        route_result = validate_proposal(route_raw, _validator(route_raw))
        assert route_result.proposal.recommendations[0].route is route
        ProposalDisposition.validate_route_selection(route, _selection(outcome, action, reason, terminality))
        other_route = next(item for item in ProposalRoute if item is not route)
        _, wrong_outcome, wrong_action, wrong_reason, wrong_terminality = ROUTE_MATRIX[other_route]
        with pytest.raises(DispositionContractError, match="route matrix"):
            ProposalDisposition.validate_route_selection(route, _selection(wrong_outcome, wrong_action, wrong_reason, wrong_terminality))
    assert result.findings


def test_multi_lead_manifest_is_complete_and_dispositions_remain_pending() -> None:
    raw = _proposal_bytes(("NEW_EVENT_CANDIDATE", "NEW_EVENT_CANDIDATE"))
    validation = validate_proposal(raw, _validator(raw))
    heads = {
        LEAD_A: LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A),
        LEAD_B: LeadDispositionHeadBinding(LEAD_B, DIGEST_B, "head:b", DIGEST_B),
    }
    selections = {lead: _selection(CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.NOVELTY_LIKELY_NEW_EVENT) for lead in heads}
    dispositions = build_pending_dispositions(validation, heads, selections)
    assert tuple(item.decision_lead_id for item in dispositions) == (LEAD_A, LEAD_B)
    assert all(item.authority is DispositionAuthority.NONE for item in dispositions)
    assert all(not item.authorises_persistence and not item.authorises_external_effect for item in dispositions)
    assert ProposalDisposition.from_canonical_bytes(dispositions[0].canonical_bytes) == dispositions[0]
    canonical = dispositions[0].canonical_bytes
    unknown = json.loads(canonical)
    unknown["unknown"] = True
    tampered = json.loads(canonical)
    tampered["disposition"]["proposal_content_identity"] = DIGEST_B
    malformed = (
        canonical[:-1]
        + b',"schema_version":"newsroom.increment6.triage-proposal-disposition.v1"}'
    )
    for invalid in (
        canonical_json_bytes(unknown),
        canonical_json_bytes(tampered),
        malformed,
        b"[" * 70 + b"0" + b"]" * 70,
        b" " * 1_100_000,
    ):
        with pytest.raises(DispositionContractError):
            ProposalDisposition.from_canonical_bytes(invalid)
    with pytest.raises(DispositionContractError, match="complete"):
        build_pending_dispositions(validation, {LEAD_A: heads[LEAD_A]}, {LEAD_A: selections[LEAD_A]})


@pytest.mark.parametrize(
    ("route", "outcome", "action", "reason"),
    (
        (ProposalRoute.WATCH_DEFER, CanonicalOutcome.LEAD_WATCH_DEFER, CanonicalNextAction.AWAIT_WATCH_CONDITION, ReasonCode.TIME_WATCH_REVIEW),
        (ProposalRoute.SUPPLEMENTAL_DISCOVERY, CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY, CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY, ReasonCode.SEARCH_PARTIAL_RESULTS),
        (ProposalRoute.OPERATIONAL_HOLD, CanonicalOutcome.LEAD_OPERATIONAL_HOLD, CanonicalNextAction.RETRY_SAME_REQUEST, ReasonCode.OPS_RETRIEVAL),
    ),
)
def test_conditional_routes_bind_the_exact_proposal_action_seam(
    route: ProposalRoute,
    outcome: CanonicalOutcome,
    action: CanonicalNextAction,
    reason: ReasonCode,
) -> None:
    raw = _proposal_bytes((route.value,))
    validation = validate_proposal(raw, _validator(raw))
    recommendation = validation.proposal.recommendations[0]
    route_digest = digest_bytes(canonical_json_bytes(recommendation.canonical_value()))
    terminality = DecisionTerminality.PENDING_CONDITION
    selection = _selection(outcome, action, reason, terminality)
    assert selection.next_action is not None
    exact = replace(
        selection,
        next_action=replace(selection.next_action, condition_reference=route_digest),
    )
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    assert build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: exact})
    with pytest.raises(DispositionContractError, match="exact route-specific"):
        build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})


def test_validator_rechecks_cross_lead_and_retrieval_citation_coherence() -> None:
    cross_lead = json.loads(_proposal_bytes(("NEW_EVENT_CANDIDATE", "NEW_EVENT_CANDIDATE")))
    first_manifest = cross_lead["proposal"]["recommendations"][0]["candidate_manifest"]
    first_manifest["contributing_lead_ids"] = [LEAD_A, LEAD_B]
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": cross_lead["proposal"]}
    cross_lead["content_identity"] = digest_bytes(canonical_json_bytes(identity))
    raw_cross = canonical_json_bytes(cross_lead)
    with pytest.raises(DispositionContractError, match="integrity"):
        validate_proposal(raw_cross, _validator(raw_cross))

    citation = json.loads(_proposal_bytes(("DEVELOPMENT_CANDIDATE",)))
    citation["proposal"]["recommendations"][0]["input_citations"][1]["target_hypothesis_id"] = "55555555-5555-4555-8555-555555555555"
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": citation["proposal"]}
    citation["content_identity"] = digest_bytes(canonical_json_bytes(identity))
    raw_citation = canonical_json_bytes(citation)
    with pytest.raises(DispositionContractError, match="integrity"):
        validate_proposal(raw_citation, _validator(raw_citation))


def test_operational_owner_mapping_and_ambiguous_action_are_inspectable() -> None:
    owner_only = json.loads(_proposal_bytes(("OPERATIONAL_HOLD",)))
    action = owner_only["proposal"]["recommendations"][0]["operational_action"]
    action.update({
        "action_kind": "REQUEST_REVIEW",
        "owner_id": "owner:newsroom",
        "dependency": None,
        "retry_condition": None,
        "review_condition": None,
    })
    raw_owner = _resign(owner_only)
    validation = validate_proposal(raw_owner, _validator(raw_owner))
    assert validation.findings[0].severity.value == "INFO"
    recommendation = validation.proposal.recommendations[0]
    route_digest = digest_bytes(canonical_json_bytes(recommendation.canonical_value()))
    selection = _selection(
        CanonicalOutcome.LEAD_OPERATIONAL_HOLD,
        CanonicalNextAction.REQUEST_REVIEW,
        ReasonCode.OPS_PARTIAL,
        DecisionTerminality.PENDING_CONDITION,
    )
    assert selection.next_action is not None
    selection = replace(selection, next_action=replace(selection.next_action, condition_reference=route_digest))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    assert build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})

    unsupported = json.loads(_proposal_bytes(("OPERATIONAL_HOLD",)))
    unsupported["proposal"]["recommendations"][0]["operational_action"].update({
        "action_kind": "DO_SOMETHING",
        "review_condition": "Review this condition.",
    })
    raw_unsupported = _resign(unsupported)
    invalid = validate_proposal(raw_unsupported, _validator(raw_unsupported))
    assert invalid.findings[0].code.value == "OPERATIONAL_ACTION_UNSUPPORTED"
    assert invalid.findings[0].severity.value == "ERROR"
    with pytest.raises(DispositionContractError, match="validation errors"):
        build_pending_dispositions(invalid, {LEAD_A: head}, {LEAD_A: selection})
    editorial_reject = _selection(
        CanonicalOutcome.LEAD_EDITORIAL_REJECT,
        CanonicalNextAction.CLOSE_DECISION,
        ReasonCode.NOVELTY_EXACT_DUPLICATE,
    )
    with pytest.raises(DispositionContractError, match="validation errors"):
        build_pending_dispositions(
            invalid, {LEAD_A: head}, {LEAD_A: editorial_reject}
        )


def test_integrity_failures_are_not_editorial_rejections_and_no_effect_type_is_reachable() -> None:
    with pytest.raises(DispositionContractError) as caught:
        validate_proposal(b"not-json", _validator())
    assert "EDITORIAL_REJECT" not in str(caught.value)
    assert "REJECT" not in str(caught.value)
    assert not hasattr(caught.value, "outcome")
    assert all(member.value in {"NONE", "PENDING"} for member in DispositionAuthority)


def test_lead_digest_mismatch_and_oversized_constructed_disposition_fail_closed() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    wrong_head = LeadDispositionHeadBinding(LEAD_A, DIGEST_C, "head:a", DIGEST_A)
    with pytest.raises(DispositionContractError, match="Lead head digest"):
        build_pending_dispositions(
            validation, {LEAD_A: wrong_head}, {LEAD_A: selection}
        )

    reasons = tuple(
        sorted(
            (
                StructuredReason(
                    code=ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
                    basis=ReasonBasisClass.DETERMINISTIC_OBSERVATION,
                    references=(ReasonReference("evidence", f"evidence:{index:04d}", DIGEST_A),),
                    explanation="\n" * 1_000,
                )
                for index in range(30_000)
            ),
            key=lambda item: item.canonical_bytes,
        )
    )
    oversized = replace(selection, supporting_reasons=reasons)
    exact_head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    with pytest.raises(DispositionContractError, match="canonical byte bound"):
        build_pending_dispositions(
            validation, {LEAD_A: exact_head}, {LEAD_A: oversized}
        )


def test_every_legal_producer_envelope_fits_the_public_consumer_bound() -> None:
    reviewed = _reviewed_large_producer_payload()
    assert len(reviewed) == 1_103_922
    assert TriageProposal.from_canonical_bytes(reviewed).canonical_bytes == reviewed
    reviewed_validation = validate_proposal(reviewed, _validator(reviewed))
    assert len(reviewed_validation.findings) == 8

    maximal = _maximal_escaped_producer_payload()
    assert len(maximal) > 16_777_216
    assert len(maximal) < MAX_DISPOSITION_CANONICAL_BYTES
    assert TriageProposal.from_canonical_bytes(maximal).canonical_bytes == maximal
    maximal_validation = validate_proposal(maximal, _validator(maximal))
    assert len(maximal_validation.findings) == 32
    assert maximal_validation.proposal.canonical_bytes == maximal

    oversized = b" " * (MAX_DISPOSITION_CANONICAL_BYTES + 1)
    with pytest.raises(DispositionContractError, match="bounded bytes"):
        ValidatorInputBinding.for_proposal(
            proposal_bytes=oversized,
            validator_id="validator:fixture",
            validator_version="1",
            authenticated_context_identity=DIGEST_A,
            retrieval_request_id="request:001",
            retrieval_request_digest=DIGEST_B,
            retrieval_receipt_id="receipt:001",
            retrieval_receipt_digest=DIGEST_C,
            ruleset_id="triage-rules",
            ruleset_version="1",
            ruleset_digest=DIGEST_D,
        )


def test_large_integer_json_errors_are_normalised_at_public_parse_boundaries() -> None:
    raw = b'{"x":' + b"9" * 5_000 + b"}"
    with pytest.raises(DispositionContractError):
        validate_proposal(raw, _validator())
    with pytest.raises(DispositionContractError):
        ProposalDisposition.from_canonical_bytes(raw)
    with pytest.raises(DispositionContractError):
        ProposalValidationFinding.from_canonical_bytes(raw)
    with pytest.raises(DispositionContractError):
        ValidatorInputBinding.for_proposal(
            proposal_bytes=raw,
            validator_id="validator:fixture",
            validator_version="1",
            authenticated_context_identity=DIGEST_A,
            retrieval_request_id="request:001",
            retrieval_request_digest=DIGEST_B,
            retrieval_receipt_id="receipt:001",
            retrieval_receipt_digest=DIGEST_C,
            ruleset_id="triage-rules",
            ruleset_version="1",
            ruleset_digest=DIGEST_D,
        )


def test_operational_action_selector_exhaustively_rejects_competing_seams() -> None:
    action_codes = {
        "RETRY_RETRIEVAL": (
            CanonicalNextAction.RETRY_SAME_REQUEST,
            ReasonCode.OPS_RETRIEVAL,
        ),
        "REQUEST_REVIEW": (
            CanonicalNextAction.REQUEST_REVIEW,
            ReasonCode.OPS_PARTIAL,
        ),
        "WAIT_FOR_DEPENDENCY": (
            CanonicalNextAction.WAIT_FOR_DEPENDENCY,
            ReasonCode.OPS_RETRIEVAL,
        ),
    }
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    for action_kind, presence in itertools.product(action_codes, itertools.product((False, True), repeat=5)):
        owner, retry, review, expiry, dependency = presence
        document = json.loads(_proposal_bytes(("OPERATIONAL_HOLD",)))
        action = document["proposal"]["recommendations"][0]["operational_action"]
        action.update({
            "action_kind": action_kind,
            "owner_id": "owner:newsroom" if owner else None,
            "retry_condition": "Retry when healthy." if retry else None,
            "review_condition": "Review with owner." if review else None,
            "expiry_condition": "Review at expiry." if expiry else None,
            "dependency": "retrieval-service" if dependency else None,
        })
        # #356 requires at least one inspectable seam. Its only all-empty case is
        # correctly a Proposal integrity failure before the 6C2 matrix.
        raw = _resign(document)
        if not any(presence):
            with pytest.raises(DispositionContractError, match="integrity"):
                validate_proposal(raw, _validator(raw))
            continue
        validation = validate_proposal(raw, _validator(raw))
        expected_valid = {
            "RETRY_RETRIEVAL": retry and not any((owner, review, expiry, dependency)),
            "REQUEST_REVIEW": (owner or review or expiry) and not any((retry, dependency)),
            "WAIT_FOR_DEPENDENCY": dependency and not any((owner, retry, review, expiry)),
        }[action_kind]
        assert (validation.findings[0].severity.value == "INFO") is expected_valid
        recommendation = validation.proposal.recommendations[0]
        route_digest = digest_bytes(canonical_json_bytes(recommendation.canonical_value()))
        action_code, reason = action_codes[action_kind]
        selection = _selection(
            CanonicalOutcome.LEAD_OPERATIONAL_HOLD,
            action_code,
            reason,
            DecisionTerminality.PENDING_CONDITION,
        )
        assert selection.next_action is not None
        selection = replace(
            selection,
            next_action=replace(selection.next_action, condition_reference=route_digest),
        )
        if expected_valid:
            assert build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})
        else:
            with pytest.raises(DispositionContractError, match="validation errors"):
                build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})
