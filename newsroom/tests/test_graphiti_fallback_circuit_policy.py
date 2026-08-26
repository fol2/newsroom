from __future__ import annotations

import pytest

from newsroom.control_plane.graphiti_fallback_policy import (
    FallbackEligibility,
    GraphitiFallbackClass,
    classify_graphiti_fallback,
    load_checked_graphiti_fallback_circuit_policy,
)
from newsroom.control_plane.graphiti_requests import (
    GraphitiLeafClass,
    load_checked_graphiti_call_shape_policy,
)
from newsroom.graphiti_adapter import cursor_transport


@pytest.mark.parametrize(
    ("outcome", "eligibility", "outcome_class"),
    [
        (
            "MALFORMED_OUTPUT",
            FallbackEligibility.ELIGIBLE,
            GraphitiFallbackClass.MALFORMED_OUTPUT,
        ),
        (
            "COMPLETE",
            FallbackEligibility.NOT_NEEDED,
            GraphitiFallbackClass.COMPLETE,
        ),
        (
            "EXECUTABLE_NOT_FOUND",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.EXECUTABLE,
        ),
        (
            "PREDISPATCH_REFUSED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.CONFIGURATION,
        ),
        (
            "FAILED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.SYSTEMIC_TRANSPORT,
        ),
        (
            "TIMEOUT",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.TIMEOUT,
        ),
        (
            "CANCELLED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.CANCELLATION,
        ),
        (
            "DISPATCH_FENCE_REFUSED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.DISPATCH_FENCE,
        ),
        (
            "OUTPUT_LIMIT_EXCEEDED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.CONTEXT_OUTPUT_BREACH,
        ),
        (
            "AUTHENTICATION_FAILED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.AUTHENTICATION,
        ),
        (
            "QUOTA_EXCEEDED",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.QUOTA,
        ),
        (
            "UNRECOGNISED_FAILURE",
            FallbackEligibility.INELIGIBLE,
            GraphitiFallbackClass.UNKNOWN,
        ),
    ],
)
def test_public_fallback_classifier_is_fail_closed(
    outcome: str,
    eligibility: FallbackEligibility,
    outcome_class: GraphitiFallbackClass,
) -> None:
    decision = classify_graphiti_fallback(outcome)

    assert decision.outcome == outcome
    assert decision.eligibility is eligibility
    assert decision.outcome_class is outcome_class


def test_checked_fallback_policy_is_bound_to_call_shape_and_729_release_order() -> None:
    policy = load_checked_graphiti_fallback_circuit_policy()
    call_shape = load_checked_graphiti_call_shape_policy()

    assert policy.version == "issue-790-v3"
    assert policy.call_shape_policy_digest == call_shape.canonical_digest
    assert policy.eligible_outcomes == ("MALFORMED_OUTPUT",)
    assert policy.max_fallback_leaves_per_primary == 1
    assert policy.circuit_release_preference == (
        "DETERMINISTIC_HEALTH_PROBE",
        "AUTHORISED_OPERATOR_RESET",
    )
    assert {route.route for route in call_shape.qualified_routes} == {
        "GRAPHITI_CHAT_PRIMARY",
        "GRAPHITI_CHAT_FALLBACK",
        "GRAPHITI_EMBEDDING",
    }
    primary = call_shape.route_for(GraphitiLeafClass.PRIMARY)
    assert (
        f"binary={cursor_transport.QUALIFIED_CURSOR_AGENT_BIN}"
        in primary.command_flags
    )
    assert (
        "resolved-binary="
        f"{cursor_transport.QUALIFIED_CURSOR_AGENT_RESOLVED_BIN}"
        in primary.command_flags
    )
    assert (
        f"CONTROLLER_STDOUT_CONTRACT={cursor_transport.CURSOR_STDOUT_LIMIT_IDENTITY}"
        in primary.command_flags
    )
    assert (
        f"AUTHENTICATION_BRIDGE={cursor_transport.CURSOR_AUTHENTICATION_BRIDGE}"
        in primary.command_flags
    )
    assert (
        f"AUTHENTICATION_PROBE={cursor_transport.CURSOR_AUTHENTICATION_PROBE}"
        in primary.command_flags
    )
    assert (
        f"LOCAL_CREDENTIAL_PROBE_ACCOUNT={cursor_transport.CURSOR_CREDENTIAL_ACCOUNT}"
        in primary.command_flags
    )
    assert (
        f"LOCAL_CREDENTIAL_PROBE_SEARCH={cursor_transport.CURSOR_CREDENTIAL_SEARCH}"
        in primary.command_flags
    )
    assert (
        f"CREDENTIAL_STATE={cursor_transport.CURSOR_CREDENTIAL_STATE}"
        in primary.command_flags
    )
    assert (
        f"package-digest={cursor_transport.QUALIFIED_CURSOR_AGENT_PACKAGE_DIGEST}"
        in primary.command_flags
    )
    assert (
        "control-semantics-digest="
        f"{cursor_transport.QUALIFIED_CURSOR_AGENT_CONTROL_SEMANTICS_DIGEST}"
        in primary.command_flags
    )
    assert (
        f"hidden-control-proof={cursor_transport.CURSOR_COMMAND_SURFACE_PROOF}"
        in primary.command_flags
    )
