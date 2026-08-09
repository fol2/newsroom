from __future__ import annotations

import json
from copy import deepcopy

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment6.proposals import (
    PROPOSAL_SCHEMA_VERSION,
    ProposalContractError,
    ProposalRoute,
    TriageProposal,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def _proposal_value(*, worker_kind: str = "FAKE") -> dict[str, object]:
    proposal: dict[str, object] = {
        "proposal_id": "84d0ae8c-1378-4b76-8792-1bb805ab6a91",
        "retrieval_context_binding": {
            "context_id": "3d2f3791-c365-47f6-b543-65ecfd6b0eba",
            "context_digest": DIGEST_A,
            "contract_digest": DIGEST_B,
        },
        "worker_attempt_binding": {
            "attempt_id": "attempt:fixture:0001",
            "attempt_digest": DIGEST_C,
            "worker_kind": worker_kind,
            "worker_version": "fixture-worker-v1",
            "input_digest": DIGEST_D,
            "retrieval_context_digest": DIGEST_A,
        },
        "route": "CREATE_HYPOTHESIS",
        "confidence": {"decimal": "0.750000", "millionths": 750_000},
        "uncertainty": {"decimal": "0.125000", "millionths": 125_000},
        "evidence_references": [
            {
                "citation_id": "citation:001",
                "context_item_digest": DIGEST_B,
                "passage_id": "passage:001",
                "passage_text_digest": DIGEST_C,
                "byte_start": 0,
                "byte_end": 18,
                "quote_digest": DIGEST_D,
            }
        ],
        "rationale": "The replay evidence supports a bounded triage route.",
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
    proposal = value["proposal"]
    identity_value = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "proposal": proposal,
    }
    value["content_identity"] = digest_bytes(canonical_json_bytes(identity_value))
    return canonical_json_bytes(value)


def test_fake_and_replay_proposals_round_trip_byte_identically() -> None:
    fake_raw = _bytes()
    fake = TriageProposal.from_canonical_bytes(fake_raw)

    assert fake.canonical_bytes == fake_raw
    assert fake.content_identity == _proposal_value()["content_identity"]
    assert fake.route is ProposalRoute.CREATE_HYPOTHESIS
    assert fake.confidence.millionths == 750_000
    assert fake.confidence.decimal == "0.750000"
    assert fake.uncertainty.millionths == 125_000
    assert fake.grants_authority is False
    assert fake.creates_hypothesis is False
    assert fake.creates_candidate is False

    replay_raw = _bytes(worker_kind="REPLAY")
    replay = TriageProposal.from_canonical_bytes(replay_raw)
    assert replay.canonical_bytes == replay_raw
    assert replay.worker_attempt.worker_kind.value == "REPLAY"


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
    proposal = document["proposal"]
    assert isinstance(proposal, dict)
    proposal[field] = value

    with pytest.raises(ProposalContractError, match=field):
        TriageProposal.from_canonical_bytes(_resign(document))


def test_context_worker_attempt_and_citations_are_exactly_bound() -> None:
    parsed = TriageProposal.from_canonical_bytes(_bytes())

    assert parsed.worker_attempt.retrieval_context_digest == (
        parsed.retrieval_context.context_digest
    )
    assert parsed.evidence_references[0].passage_id == "passage:001"
    assert parsed.evidence_references[0].byte_range == (0, 18)

    mismatched = _proposal_value()
    proposal = mismatched["proposal"]
    assert isinstance(proposal, dict)
    worker = proposal["worker_attempt_binding"]
    assert isinstance(worker, dict)
    worker["retrieval_context_digest"] = DIGEST_D
    with pytest.raises(ProposalContractError, match="retrieval context digest"):
        TriageProposal.from_canonical_bytes(_resign(mismatched))


def test_evidence_references_are_non_empty_sorted_unique_and_bounded() -> None:
    duplicate = _proposal_value()
    proposal = duplicate["proposal"]
    assert isinstance(proposal, dict)
    references = proposal["evidence_references"]
    assert isinstance(references, list)
    references.append(deepcopy(references[0]))
    with pytest.raises(ProposalContractError, match="sorted and unique"):
        TriageProposal.from_canonical_bytes(_resign(duplicate))

    malformed_range = _proposal_value()
    proposal = malformed_range["proposal"]
    assert isinstance(proposal, dict)
    reference = proposal["evidence_references"][0]  # type: ignore[index]
    assert isinstance(reference, dict)
    reference["byte_end"] = 0
    with pytest.raises(ProposalContractError, match="byte range"):
        TriageProposal.from_canonical_bytes(_resign(malformed_range))


def test_unknown_duplicate_malformed_and_cross_version_output_fail_closed() -> None:
    unknown = _proposal_value()
    proposal = unknown["proposal"]
    assert isinstance(proposal, dict)
    proposal["surprise"] = True
    with pytest.raises(ProposalContractError, match="proposal keys are not exact"):
        TriageProposal.from_canonical_bytes(_resign(unknown))

    malformed_digest = _proposal_value()
    proposal = malformed_digest["proposal"]
    assert isinstance(proposal, dict)
    context = proposal["retrieval_context_binding"]
    assert isinstance(context, dict)
    context["context_digest"] = 7
    with pytest.raises(ProposalContractError, match="context_digest"):
        TriageProposal.from_canonical_bytes(_resign(malformed_digest))

    raw = _bytes()
    duplicate = raw.decode("utf-8").replace(
        f'"schema_version":"{PROPOSAL_SCHEMA_VERSION}"',
        f'"schema_version":"{PROPOSAL_SCHEMA_VERSION}",'
        f'"schema_version":"{PROPOSAL_SCHEMA_VERSION}"',
        1,
    )
    with pytest.raises(ProposalContractError, match="duplicate object name"):
        TriageProposal.from_canonical_bytes(duplicate.encode("utf-8"))

    pretty = json.dumps(_proposal_value(), indent=2).encode("utf-8")
    with pytest.raises(ProposalContractError, match="canonical JSON"):
        TriageProposal.from_canonical_bytes(pretty)

    wrong_version = _proposal_value()
    wrong_version["schema_version"] = "newsroom.increment6.triage-proposal.v2"
    with pytest.raises(ProposalContractError, match="schema version"):
        TriageProposal.from_canonical_bytes(canonical_json_bytes(wrong_version))


def test_content_identity_detects_mutation_and_is_not_authority() -> None:
    mutated = _proposal_value()
    proposal = mutated["proposal"]
    assert isinstance(proposal, dict)
    proposal["rationale"] = "Changed after identity was assigned."
    with pytest.raises(ProposalContractError, match="content identity differs"):
        TriageProposal.from_canonical_bytes(canonical_json_bytes(mutated))

    authority = _proposal_value()
    proposal = authority["proposal"]
    assert isinstance(proposal, dict)
    effects = proposal["authority"]
    assert isinstance(effects, dict)
    effects["publication_authority"] = True
    with pytest.raises(ProposalContractError, match="grants no authority"):
        TriageProposal.from_canonical_bytes(_resign(authority))


def test_real_or_provider_backed_worker_output_is_outside_the_contract() -> None:
    for worker_kind in ("MODEL", "PROVIDER", "LIVE"):
        with pytest.raises(ProposalContractError, match="worker_kind"):
            TriageProposal.from_canonical_bytes(_bytes(worker_kind=worker_kind))
