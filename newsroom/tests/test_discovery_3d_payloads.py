from __future__ import annotations

from copy import deepcopy

import pytest

from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.discovery.payloads import (
    discovery_signal_payload,
    gate_decision_payload,
    lead_disposition_payload,
    news_lead_payload,
    watch_condition_payload,
)

from .discovery_3d_helpers import (
    disposition_request,
    gate_request,
    lead_request,
    signal_request,
    watch_request,
)


_CASES = (
    (discovery_signal_payload, signal_request()),
    (gate_decision_payload, gate_request()),
    (news_lead_payload, lead_request()),
    (watch_condition_payload, watch_request()),
    (lead_disposition_payload, disposition_request()),
)


@pytest.mark.parametrize(("canonicalizer", "typed_request"), _CASES)
def test_payload_canonicalizer_round_trips_exact_typed_request(
    canonicalizer,
    typed_request,
) -> None:
    assert canonicalizer(typed_request.canonical_value()) == typed_request.canonical_bytes


@pytest.mark.parametrize(("canonicalizer", "typed_request"), _CASES)
def test_payload_canonicalizer_rejects_unknown_fields(
    canonicalizer,
    typed_request,
) -> None:
    value = deepcopy(typed_request.canonical_value())
    value["unexpected"] = True
    with pytest.raises(PayloadSchemaValidationError, match="fields differ"):
        canonicalizer(value)


def test_gate_payload_rejects_derived_outcome_shape_drift() -> None:
    value = deepcopy(gate_request().canonical_value())
    value["basis"]["observable_newness"] = "PARSER_ONLY"
    with pytest.raises(PayloadSchemaValidationError, match="Gate Decision is invalid"):
        gate_decision_payload(value)


def test_lead_payload_rejects_noncanonical_source_role_order() -> None:
    value = deepcopy(lead_request().canonical_value())
    value["source_roles"].insert(
        0,
        {
            "role": "RESPONSIBLE_OPERATOR",
            "purpose": "Second role deliberately appended out of order.",
            "limitations": [],
        }
    )
    with pytest.raises(PayloadSchemaValidationError, match="News Lead is invalid"):
        news_lead_payload(value)


def test_watch_payload_rejects_indefinite_condition() -> None:
    value = deepcopy(watch_request().canonical_value())
    value.update(
        {
            "resume_transition_kinds": [],
            "expected_occurrence": None,
            "corroborating_lead_id": None,
            "review_at": None,
            "expires_at": None,
            "operator_review_condition": None,
        }
    )
    with pytest.raises(PayloadSchemaValidationError, match="Watch Condition is invalid"):
        watch_condition_payload(value)


def test_disposition_payload_rejects_candidate_authority() -> None:
    value = deepcopy(disposition_request().canonical_value())
    value["outcome"] = "LEAD_ADMIT_NEW_CANDIDATE"
    with pytest.raises(
        PayloadSchemaValidationError,
        match="Lead Disposition Decision is invalid",
    ):
        lead_disposition_payload(value)
