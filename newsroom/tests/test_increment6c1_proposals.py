from __future__ import annotations

import json
from copy import deepcopy

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5.retrieval_context import RETRIEVAL_CONTEXT_CONTRACT_DIGEST
from newsroom.increment6.proposals import (
    PROPOSAL_CONTENT_IDENTITY,
    PROPOSAL_NO_AUTHORITY_BOUNDARY,
    PROPOSAL_SCHEMA_VERSION,
    TRIAGE_PROPOSAL,
    ProposalContractError,
    ProposalRoute,
    TriageProposal,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
LEAD_A = "11111111-1111-4111-8111-111111111111"
LEAD_B = "22222222-2222-4222-8222-222222222222"
LEAD_C = "33333333-3333-4333-8333-333333333333"


def _citation(citation_id: str, source_kind: str, source_id: str) -> dict[str, object]:
    return {
        "citation_id": citation_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_digest": DIGEST_B,
        "field_path": "lead.summary",
        "byte_start": 0,
        "byte_end": 18,
        "quote_digest": DIGEST_D,
        "target_hypothesis_id": None,
    }


def _recommendation(lead_id: str = LEAD_A) -> dict[str, object]:
    return {
        "decision_lead_id": lead_id,
        "route": "NEW_EVENT_CANDIDATE",
        "confidence": {"decimal": "0.750000", "millionths": 750_000},
        "uncertainty": {"decimal": "0.125000", "millionths": 125_000},
        "input_citations": [
            _citation("citation:001", "DECISION_LEAD", lead_id),
            _citation("citation:002", "RETRIEVAL_MATCH", "passage:001"),
        ],
        "likely_new_information": "A material new state may have occurred.",
        "materiality_basis": "The possible change may affect readers.",
        "missing_context": ["Confirmation from the primary organisation"],
        "retrieval_incompleteness": ["One prior event was unavailable"],
        "hypothesis": {
            "proposal_local_id": "hypothesis:001",
            "summary": "The lead may describe a distinct new event.",
            "relationship_kind": "NO_ADEQUATE_PRIOR_MATCH",
            "target_hypothesis_id": None,
        },
        "watch_action": None,
        "supplemental_action": None,
        "operational_action": None,
        "candidate_manifest": {
            "manifest_kind": "NEW_EVENT",
            "contributing_lead_ids": [lead_id],
            "proposed_geography": "GB",
            "proposed_category": "UK_NEWS",
            "urgency": "ROUTINE",
            "likely_new_information": "A material new state may have occurred.",
            "reader_utility_basis": "Readers may need the changed state explained.",
            "uncertainties": ["The event remains unverified"],
            "evidence_objectives": ["Confirm the changed state independently"],
            "governing_versions": ["candidate-policy-v1", "rights-policy-v1"],
        },
    }


def _proposal_value(*, worker_kind: str = "FAKE") -> dict[str, object]:
    proposal: dict[str, object] = {
        "proposal_id": "84d0ae8c-1378-4b76-8792-1bb805ab6a91",
        "work_item_binding": {
            "work_item_id": "4d3b1b83-205e-4f77-a46b-ffbf5509d254",
            "work_item_version_id": "c37c30fd-cfab-4a57-ab69-a72515ebaa31",
            "work_item_version_digest": DIGEST_D,
        },
        "retrieval_context_binding": {
            "context_id": "3d2f3791-c365-47f6-b543-65ecfd6b0eba",
            "context_digest": DIGEST_A,
            "contract_digest": RETRIEVAL_CONTEXT_CONTRACT_DIGEST,
        },
        "worker_attempt_binding": {
            "attempt_id": "attempt:fixture:0001",
            "attempt_digest": DIGEST_C,
            "worker_kind": worker_kind,
            "worker_version": "fixture-worker-v1",
            "input_digest": DIGEST_B,
            "work_item_version_digest": DIGEST_D,
            "retrieval_context_digest": DIGEST_A,
        },
        "decision_lead_ids": [LEAD_A],
        "context_lead_ids": [LEAD_B],
        "recommendations": [_recommendation()],
        "rationale": "The replay inputs support a bounded triage recommendation.",
        "authority": {
            "effect": "NONE",
            "creates_hypothesis": False,
            "creates_candidate": False,
            "mutates_editorial_state": False,
            "publication_authority": False,
            "evidence_authority": False,
            "operational_authority": False,
        },
    }
    identity_value = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "proposal": proposal,
    }
    return {
        **identity_value,
        "content_identity": digest_bytes(canonical_json_bytes(identity_value)),
    }


def _bytes(*, worker_kind: str = "FAKE") -> bytes:
    return canonical_json_bytes(_proposal_value(worker_kind=worker_kind))


def _resign(value: dict[str, object]) -> bytes:
    identity_value = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "proposal": value["proposal"],
    }
    value["content_identity"] = digest_bytes(canonical_json_bytes(identity_value))
    return canonical_json_bytes(value)


def _proposal(document: dict[str, object]) -> dict[str, object]:
    proposal = document["proposal"]
    assert isinstance(proposal, dict)
    return proposal


def _recommendation_value(document: dict[str, object]) -> dict[str, object]:
    recommendations = _proposal(document)["recommendations"]
    assert isinstance(recommendations, list)
    recommendation = recommendations[0]
    assert isinstance(recommendation, dict)
    return recommendation


def test_public_contract_names_match_the_accepted_6r_allocation() -> None:
    assert TRIAGE_PROPOSAL == PROPOSAL_SCHEMA_VERSION
    assert PROPOSAL_CONTENT_IDENTITY == "SHA256_CANONICAL_SCHEMA_AND_PROPOSAL"
    assert PROPOSAL_NO_AUTHORITY_BOUNDARY == (
        "NO_HYPOTHESIS_OR_CANDIDATE_MUTATION;"
        "NO_PUBLICATION_EVIDENCE_OR_OPERATIONAL_AUTHORITY"
    )


def test_fake_and_replay_proposals_round_trip_byte_identically() -> None:
    for worker_kind in ("FAKE", "REPLAY"):
        raw = _bytes(worker_kind=worker_kind)
        parsed = TriageProposal.from_canonical_bytes(raw)

        assert parsed.canonical_bytes == raw
        assert parsed.content_identity == _proposal_value(
            worker_kind=worker_kind
        )["content_identity"]
        assert parsed.worker_attempt.worker_kind.value == worker_kind
        assert parsed.recommendations[0].route is ProposalRoute.NEW_EVENT_CANDIDATE
        assert parsed.recommendations[0].confidence.millionths == 750_000
        assert parsed.grants_authority is False
        assert parsed.creates_hypothesis is False
        assert parsed.creates_candidate is False


def test_exact_work_item_context_attempt_and_input_citation_binding() -> None:
    parsed = TriageProposal.from_canonical_bytes(_bytes())

    assert parsed.worker_attempt.work_item_version_digest == (
        parsed.work_item.work_item_version_digest
    )
    assert parsed.worker_attempt.retrieval_context_digest == (
        parsed.retrieval_context.context_digest
    )
    assert parsed.recommendations[0].input_citations[0].source_id == LEAD_A

    for worker_field, binding_field, message in (
        ("work_item_version_digest", "work_item_version_digest", "work item"),
        ("retrieval_context_digest", "context_digest", "retrieval context"),
    ):
        mismatched = _proposal_value()
        proposal = _proposal(mismatched)
        worker = proposal["worker_attempt_binding"]
        assert isinstance(worker, dict)
        worker[worker_field] = DIGEST_C
        binding_name = (
            "work_item_binding"
            if binding_field == "work_item_version_digest"
            else "retrieval_context_binding"
        )
        binding = proposal[binding_name]
        assert isinstance(binding, dict)
        binding[binding_field] = DIGEST_D
        with pytest.raises(ProposalContractError, match=message):
            TriageProposal.from_canonical_bytes(_resign(mismatched))


def test_every_decision_lead_is_recommended_once_and_context_leads_are_isolated() -> None:
    duplicate = _proposal_value()
    proposal = _proposal(duplicate)
    proposal["recommendations"] = [
        _recommendation(LEAD_A),
        _recommendation(LEAD_A),
    ]
    with pytest.raises(ProposalContractError, match="exactly once"):
        TriageProposal.from_canonical_bytes(_resign(duplicate))

    omitted = _proposal_value()
    proposal = _proposal(omitted)
    proposal["decision_lead_ids"] = [LEAD_A, LEAD_C]
    with pytest.raises(ProposalContractError, match="exactly once"):
        TriageProposal.from_canonical_bytes(_resign(omitted))

    context_routed = _proposal_value()
    _recommendation_value(context_routed)["decision_lead_id"] = LEAD_B
    with pytest.raises(ProposalContractError, match="exactly once"):
        TriageProposal.from_canonical_bytes(_resign(context_routed))

    bad_citation = _proposal_value()
    citations = _recommendation_value(bad_citation)["input_citations"]
    assert isinstance(citations, list)
    citation = citations[0]
    assert isinstance(citation, dict)
    citation["source_kind"] = "CONTEXT_LEAD"
    with pytest.raises(ProposalContractError, match="context Lead manifest"):
        TriageProposal.from_canonical_bytes(_resign(bad_citation))

    missing_own_citation = _proposal_value()
    citations = _recommendation_value(missing_own_citation)["input_citations"]
    assert isinstance(citations, list)
    citations.pop(0)
    with pytest.raises(ProposalContractError, match="exact decision Lead input"):
        TriageProposal.from_canonical_bytes(_resign(missing_own_citation))


@pytest.mark.parametrize(
    "route",
    [
        "EDITORIAL_REJECT",
        "WATCH_DEFER",
        "ASSOCIATE_WITHOUT_CANDIDATE",
        "SUPPLEMENTAL_DISCOVERY",
        "OPERATIONAL_HOLD",
        "NEW_EVENT_CANDIDATE",
        "DEVELOPMENT_CANDIDATE",
        "CORRECTION_CANDIDATE",
    ],
)
def test_only_normative_routes_are_admitted(route: str) -> None:
    document = _proposal_value()
    recommendation = _recommendation_value(document)
    recommendation["route"] = route
    recommendation["hypothesis"] = None
    recommendation["candidate_manifest"] = None

    if route == "WATCH_DEFER":
        recommendation["watch_action"] = {
            "condition_kind": "SOURCE_UPDATE",
            "condition": "Resume when the named source publishes an update.",
            "next_action": "REENTER_DISCOVERY",
        }
    elif route == "SUPPLEMENTAL_DISCOVERY":
        recommendation["supplemental_action"] = {
            "action_kind": "CHECK_NAMED_SOURCE",
            "scope": "The primary organisation newsroom",
            "maximum_attempts": 1,
            "requires_approval": True,
        }
    elif route == "OPERATIONAL_HOLD":
        recommendation["operational_action"] = {
            "action_kind": "RETRY_RETRIEVAL",
            "owner_id": "owner:newsroom",
            "dependency": "retrieval-service",
            "retry_condition": "Retry after the retrieval service is healthy.",
            "review_condition": None,
            "expiry_condition": None,
        }
    elif route == "ASSOCIATE_WITHOUT_CANDIDATE":
        recommendation["hypothesis"] = {
            "proposal_local_id": "hypothesis:001",
            "summary": "The lead may concern the prior state.",
            "relationship_kind": "SAME_STATE",
            "target_hypothesis_id": "44444444-4444-4444-8444-444444444444",
        }
        citations = recommendation["input_citations"]
        assert isinstance(citations, list)
        retrieval_citation = citations[1]
        assert isinstance(retrieval_citation, dict)
        retrieval_citation["target_hypothesis_id"] = (
            "44444444-4444-4444-8444-444444444444"
        )
    elif route.endswith("_CANDIDATE"):
        kind, relationship, target = {
            "NEW_EVENT_CANDIDATE": ("NEW_EVENT", "NO_ADEQUATE_PRIOR_MATCH", None),
            "DEVELOPMENT_CANDIDATE": (
                "DEVELOPMENT",
                "DEVELOPMENT_OF",
                "44444444-4444-4444-8444-444444444444",
            ),
            "CORRECTION_CANDIDATE": (
                "CORRECTION",
                "CORRECTION_REVERSAL_OF",
                "44444444-4444-4444-8444-444444444444",
            ),
        }[route]
        recommendation["hypothesis"] = {
            "proposal_local_id": "hypothesis:001",
            "summary": "The lead may represent the proposed relationship.",
            "relationship_kind": relationship,
            "target_hypothesis_id": target,
        }
        if target is not None:
            citations = recommendation["input_citations"]
            assert isinstance(citations, list)
            retrieval_citation = citations[1]
            assert isinstance(retrieval_citation, dict)
            retrieval_citation["target_hypothesis_id"] = target
        manifest = deepcopy(_recommendation()["candidate_manifest"])
        assert isinstance(manifest, dict)
        manifest["manifest_kind"] = kind
        recommendation["candidate_manifest"] = manifest

    parsed = TriageProposal.from_canonical_bytes(_resign(document))
    assert parsed.recommendations[0].route.value == route


def test_operational_hold_requires_an_inspectable_action_boundary() -> None:
    missing = _proposal_value()
    recommendation = _recommendation_value(missing)
    recommendation["route"] = "OPERATIONAL_HOLD"
    recommendation["hypothesis"] = None
    recommendation["candidate_manifest"] = None
    with pytest.raises(ProposalContractError, match="operational action"):
        TriageProposal.from_canonical_bytes(_resign(missing))

    uninspectable = deepcopy(missing)
    recommendation = _recommendation_value(uninspectable)
    recommendation["operational_action"] = {
        "action_kind": None,
        "owner_id": None,
        "dependency": None,
        "retry_condition": None,
        "review_condition": None,
        "expiry_condition": None,
    }
    with pytest.raises(ProposalContractError, match="inspectable"):
        TriageProposal.from_canonical_bytes(_resign(uninspectable))


@pytest.mark.parametrize(
    "route",
    [
        "ASSOCIATE_WITHOUT_CANDIDATE",
        "DEVELOPMENT_CANDIDATE",
        "CORRECTION_CANDIDATE",
    ],
)
def test_relationship_target_requires_exact_retrieval_context_citation(
    route: str,
) -> None:
    target = "44444444-4444-4444-8444-444444444444"
    document = _proposal_value()
    recommendation = _recommendation_value(document)
    recommendation["route"] = route
    recommendation["hypothesis"] = {
        "proposal_local_id": "hypothesis:targeted",
        "summary": "The Lead may relate to one exact retrieved Hypothesis.",
        "relationship_kind": {
            "ASSOCIATE_WITHOUT_CANDIDATE": "SAME_STATE",
            "DEVELOPMENT_CANDIDATE": "DEVELOPMENT_OF",
            "CORRECTION_CANDIDATE": "CORRECTION_REVERSAL_OF",
        }[route],
        "target_hypothesis_id": target,
    }
    if route == "ASSOCIATE_WITHOUT_CANDIDATE":
        recommendation["candidate_manifest"] = None
    else:
        manifest = recommendation["candidate_manifest"]
        assert isinstance(manifest, dict)
        manifest["manifest_kind"] = {
            "DEVELOPMENT_CANDIDATE": "DEVELOPMENT",
            "CORRECTION_CANDIDATE": "CORRECTION",
        }[route]

    citations = recommendation["input_citations"]
    assert isinstance(citations, list)
    citations.pop(1)
    with pytest.raises(ProposalContractError, match="Retrieval Context citation"):
        TriageProposal.from_canonical_bytes(_resign(document))

    mismatched = deepcopy(document)
    citations = _recommendation_value(mismatched)["input_citations"]
    assert isinstance(citations, list)
    citations.append(_citation("citation:002", "RETRIEVAL_MATCH", "passage:001"))
    citation = citations[1]
    assert isinstance(citation, dict)
    citation["target_hypothesis_id"] = (
        "55555555-5555-4555-8555-555555555555"
    )
    with pytest.raises(ProposalContractError, match="Retrieval Context citation"):
        TriageProposal.from_canonical_bytes(_resign(mismatched))


def test_cross_lead_candidate_and_hypothesis_content_must_be_coherent() -> None:
    rejected_contributor = _proposal_value()
    proposal = _proposal(rejected_contributor)
    proposal["decision_lead_ids"] = [LEAD_A, LEAD_C]
    candidate = _recommendation(LEAD_A)
    manifest = candidate["candidate_manifest"]
    assert isinstance(manifest, dict)
    manifest["contributing_lead_ids"] = [LEAD_A, LEAD_C]
    rejected = _recommendation(LEAD_C)
    rejected["route"] = "EDITORIAL_REJECT"
    rejected["hypothesis"] = None
    rejected["candidate_manifest"] = None
    proposal["recommendations"] = [candidate, rejected]
    with pytest.raises(ProposalContractError, match="Candidate contributor"):
        TriageProposal.from_canonical_bytes(_resign(rejected_contributor))

    conflicting_hypothesis = _proposal_value()
    proposal = _proposal(conflicting_hypothesis)
    proposal["decision_lead_ids"] = [LEAD_A, LEAD_C]
    first = _recommendation(LEAD_A)
    second = _recommendation(LEAD_C)
    first_manifest = first["candidate_manifest"]
    second_manifest = second["candidate_manifest"]
    assert isinstance(first_manifest, dict)
    assert isinstance(second_manifest, dict)
    first_manifest["contributing_lead_ids"] = [LEAD_A, LEAD_C]
    second_manifest["contributing_lead_ids"] = [LEAD_A, LEAD_C]
    second_hypothesis = second["hypothesis"]
    assert isinstance(second_hypothesis, dict)
    second_hypothesis["summary"] = "A conflicting summary for the same local identity."
    proposal["recommendations"] = [first, second]
    with pytest.raises(ProposalContractError, match="proposal_local_id conflicts"):
        TriageProposal.from_canonical_bytes(_resign(conflicting_hypothesis))

    coherent = _proposal_value()
    proposal = _proposal(coherent)
    proposal["decision_lead_ids"] = [LEAD_A, LEAD_C]
    first = _recommendation(LEAD_A)
    second = _recommendation(LEAD_C)
    for recommendation in (first, second):
        manifest = recommendation["candidate_manifest"]
        assert isinstance(manifest, dict)
        manifest["contributing_lead_ids"] = [LEAD_A, LEAD_C]
    proposal["recommendations"] = [first, second]

    parsed = TriageProposal.from_canonical_bytes(_resign(coherent))
    assert len(parsed.recommendations) == 2


@pytest.mark.parametrize(
    ("route", "field", "value", "message"),
    [
        ("WATCH_DEFER", "watch_action", None, "watch action"),
        (
            "EDITORIAL_REJECT",
            "watch_action",
            {
                "condition_kind": "REVIEW",
                "condition": "Review later.",
                "next_action": "REVIEW",
            },
            "watch action",
        ),
        ("SUPPLEMENTAL_DISCOVERY", "supplemental_action", None, "supplemental"),
        (
            "EDITORIAL_REJECT",
            "supplemental_action",
            {
                "action_kind": "CHECK_SOURCE",
                "scope": "source",
                "maximum_attempts": 1,
                "requires_approval": True,
            },
            "supplemental",
        ),
        ("NEW_EVENT_CANDIDATE", "candidate_manifest", None, "Candidate manifest"),
    ],
)
def test_route_specific_seams_fail_closed(
    route: str, field: str, value: object, message: str
) -> None:
    document = _proposal_value()
    recommendation = _recommendation_value(document)
    recommendation["route"] = route
    recommendation[field] = value
    if route == "WATCH_DEFER":
        recommendation["candidate_manifest"] = None
        recommendation["hypothesis"] = None
    if route == "SUPPLEMENTAL_DISCOVERY":
        recommendation["candidate_manifest"] = None
        recommendation["hypothesis"] = None
    with pytest.raises(ProposalContractError, match=message):
        TriageProposal.from_canonical_bytes(_resign(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", {"decimal": "1.000001", "millionths": 1_000_001}),
        ("confidence", {"decimal": "0.100000", "millionths": 100_001}),
        ("confidence", {"decimal": "0.1", "millionths": 100_000}),
        ("uncertainty", {"decimal": "-0.000001", "millionths": -1}),
        ("uncertainty", {"decimal": "0.500000", "millionths": True}),
    ],
)
def test_confidence_and_uncertainty_are_bounded_exact_fixed_point(
    field: str, value: object
) -> None:
    document = _proposal_value()
    _recommendation_value(document)[field] = value
    with pytest.raises(ProposalContractError, match=field):
        TriageProposal.from_canonical_bytes(_resign(document))


def test_unknown_duplicate_malformed_and_cross_version_output_fail_closed() -> None:
    unknown = _proposal_value()
    _recommendation_value(unknown)["surprise"] = True
    with pytest.raises(ProposalContractError, match="recommendation keys are not exact"):
        TriageProposal.from_canonical_bytes(_resign(unknown))

    malformed = _proposal_value()
    context = _proposal(malformed)["retrieval_context_binding"]
    assert isinstance(context, dict)
    context["context_digest"] = 7
    with pytest.raises(ProposalContractError, match="context_digest"):
        TriageProposal.from_canonical_bytes(_resign(malformed))

    raw = _bytes()
    duplicate = raw.decode("utf-8").replace(
        f'"schema_version":"{PROPOSAL_SCHEMA_VERSION}"',
        f'"schema_version":"{PROPOSAL_SCHEMA_VERSION}",'
        f'"schema_version":"{PROPOSAL_SCHEMA_VERSION}"',
        1,
    )
    with pytest.raises(ProposalContractError, match="duplicate object name"):
        TriageProposal.from_canonical_bytes(duplicate.encode("utf-8"))

    with pytest.raises(ProposalContractError, match="canonical JSON"):
        TriageProposal.from_canonical_bytes(json.dumps(_proposal_value(), indent=2).encode())

    wrong_version = _proposal_value()
    wrong_version["schema_version"] = "newsroom.increment6.triage-proposal.v2"
    with pytest.raises(ProposalContractError, match="schema version"):
        TriageProposal.from_canonical_bytes(canonical_json_bytes(wrong_version))


def test_content_identity_and_no_authority_boundary_fail_closed() -> None:
    mutated = _proposal_value()
    _proposal(mutated)["rationale"] = "Changed after identity was assigned."
    with pytest.raises(ProposalContractError, match="content identity differs"):
        TriageProposal.from_canonical_bytes(canonical_json_bytes(mutated))

    for field in (
        "creates_hypothesis",
        "creates_candidate",
        "publication_authority",
        "evidence_authority",
        "operational_authority",
    ):
        authority = _proposal_value()
        effects = _proposal(authority)["authority"]
        assert isinstance(effects, dict)
        effects[field] = True
        with pytest.raises(ProposalContractError, match="grants no authority"):
            TriageProposal.from_canonical_bytes(_resign(authority))


def test_real_or_provider_backed_worker_output_is_outside_the_contract() -> None:
    for worker_kind in ("MODEL", "PROVIDER", "LIVE"):
        with pytest.raises(ProposalContractError, match="worker_kind"):
            TriageProposal.from_canonical_bytes(_bytes(worker_kind=worker_kind))
