from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from newsroom.graphiti_adapter.runtime_calibration import (
    DECISION_GATES,
    CalibrationClosed,
    CalibrationRecommendation,
    run_provider_free_runtime_calibration,
    validate_redacted_receipts,
)


def _valid_receipts() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    primary = {
        "invocation_id": "invocation-primary",
        "parent_invocation_id": None,
        "leaf_class": "PRIMARY",
        "request_digest": "sha256:" + ("1" * 64),
        "prompt_digest": "sha256:" + ("2" * 64),
        "schema_identity": "NewsroomCombinedTemporalExtractionV1",
        "schema_digest": "sha256:" + ("3" * 64),
        "model": "composer-2.5",
        "route": "GRAPHITI_CHAT_PRIMARY",
        "outcome": "MALFORMED_OUTPUT",
        "usage_status": "REPORTED",
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": 10,
        "output_tokens": 2,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 12,
        "circuit_state": "CLOSED",
        "accepted": False,
    }
    fallback = {
        **primary,
        "invocation_id": "invocation-fallback",
        "parent_invocation_id": "invocation-primary",
        "leaf_class": "FALLBACK",
        "request_digest": "sha256:" + ("4" * 64),
        "model": "grok-4.6",
        "route": "GRAPHITI_CHAT_FALLBACK",
        "outcome": "COMPLETE",
        "total_tokens": 11,
        "accepted": True,
    }
    attempts = [
        {
            "attempt_id": "attempt-1",
            "terminal_outcome": "TERMINAL_SUCCESS_WITH_PROPOSALS",
            "leaf_invocation_ids": ["invocation-primary", "invocation-fallback"],
            "rolled_back": False,
        }
    ]
    return [primary, fallback], attempts


def test_redacted_receipt_validator_accepts_bound_fallback_receipts() -> None:
    leaves, attempts = _valid_receipts()

    result = validate_redacted_receipts(leaves, attempts)

    assert result.passed is True
    assert result.reason_codes == ()
    assert result.validated_leaf_count == 2
    assert result.validated_attempt_count == 1


def test_redacted_receipt_validator_rejects_silent_zero_and_source_expression() -> None:
    leaves, attempts = _valid_receipts()
    leaves = deepcopy(leaves)
    leaves[0].update(
        {
            "usage_status": "UNREPORTED",
            "usage_basis": "UNREPORTED",
            "total_tokens": 0,
            "prompt_text": "source expression must not enter a receipt",
        }
    )

    result = validate_redacted_receipts(leaves, attempts)

    assert result.passed is False
    assert set(result.reason_codes) == {
        "MISSING_USAGE_PRESENTED_AS_ZERO",
        "SOURCE_EXPRESSION_PRESENT",
    }


def test_redacted_receipt_validator_rejects_retry_and_acceptance_breaches() -> None:
    leaves, attempts = _valid_receipts()
    leaves[0]["outcome"] = "FAILED"
    leaves[1]["request_digest"] = leaves[0]["request_digest"]
    leaves[1]["circuit_state"] = "OPEN"
    second_fallback = {
        **leaves[1],
        "invocation_id": "invocation-second-fallback",
        "request_digest": "sha256:" + ("5" * 64),
        "accepted": False,
        "circuit_state": "CLOSED",
    }
    leaves.append(second_fallback)
    attempts[0]["leaf_invocation_ids"] = [
        "invocation-primary",
        "invocation-fallback",
        "invocation-second-fallback",
    ]

    result = validate_redacted_receipts(leaves, attempts)

    assert set(result.reason_codes) == {
        "ACCEPTED_AFTER_BREACH",
        "DUPLICATE_UNCHANGED_REQUEST_DIGEST",
        "FALLBACK_WITHOUT_ELIGIBLE_PARENT",
        "MULTIPLE_FALLBACKS_PER_PRIMARY",
    }


def test_provider_free_runtime_packet_meets_every_issue_771_decision_gate() -> None:
    packet = run_provider_free_runtime_calibration()
    record = packet.as_record()

    assert DECISION_GATES == (
        "every primary cache miss uses one #747 primary leaf",
        "ordinary timestamp, dedupe and summary leaves are zero where #748 qualifies deterministic work",
        "remaining leaves are distinct, pre-receipted and outcome-linked",
        "source/evidence/temporal/rights/Entity Resolution/proposal-only/journal/rollback gold does not regress",
        "provider usage is reported or explicitly estimated/unresolved under #728 (never silent zero)",
        "low/base/high average provider tokens strictly below the retained current path",
        "no increase in held ambiguity hidden as token saving",
        "fallback improves terminal valid results without increasing unchanged retries",
        "public effects remain zero",
    )
    assert packet.recommendation is CalibrationRecommendation.ADOPT
    assert packet.reason_code is None
    assert packet.live_owner_gated_execution_authorised is False
    assert record["issue"] == 771
    assert record["parent_issue"] == 731
    assert record["provider_calls"] == 0
    assert record["public_effects"] == 0
    assert all(record["decision_gate_results"].values())
    assert record["receipt_validation"]["passed"] is True
    assert {
        item["route"]
        for item in record["receipt_validation"]["invocation_efficiency_policies"]
    } == {"GRAPHITI_CHAT_PRIMARY", "GRAPHITI_CHAT_FALLBACK"}
    assert all(
        str(item["evidence_digest"]).startswith("sha256:")
        and item["hard_estimate_ceiling_tokens"] is None
        for item in record["receipt_validation"]["invocation_efficiency_policies"]
    )
    assert record["quality_gold"]["all_passed"] is True
    assert record["quality_gold"]["held_ambiguity_outcome"] == "AMBIGUOUS_HOLD"
    assert record["terminal_outcomes"]["zero-result"] == (
        "TERMINAL_SUCCESS_ZERO_PROPOSALS"
    )
    assert record["attempt_usage"]["failed_or_rolled_back"]
    assert record["attempt_usage"]["terminal_success"]
    assert record["ineligible_runtime"] == {
        "systemic-failure": {"outcomes": ["FAILED"], "fallback_called": False},
        "timeout": {"outcomes": ["TIMEOUT"], "fallback_called": False},
        "cancellation": {"outcomes": ["CANCELLED"], "fallback_called": False},
    }
    averages = record["token_effectiveness"]["average_tokens_per_terminal_revision"]
    assert all(
        averages["target"][scenario] < averages["current"][scenario]
        for scenario in ("low", "base", "high")
    )
    assert record["deterministic_local_work"]["reported_as_provider_tokens"] is False
    fixture_ids = {item["fixture_id"] for item in record["fixture_slices"]}
    assert {
        "zero-result",
        "pair-current",
        "several-relations",
        "explicit-valid-at",
        "relative-date",
        "null-temporal",
        "same-name",
        "short-summary",
        "overlong-summary",
        "long-8192",
        "malformed-output-single-fallback",
        "systemic-failure",
        "timeout",
        "cancellation",
        "restart-immutable-usage",
        "rolled-back-attempt",
    } <= fixture_ids


def test_runtime_calibration_cli_is_dry_run_and_live_execution_is_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.graphiti_runtime_calibration import main

    assert main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["provider_calls"] == 0
    assert output["public_effects"] == 0

    with pytest.raises(CalibrationClosed, match="owner-gated live packet"):
        main(["--execute"])


def test_checked_measurements_match_the_provider_free_packet() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "2026-08-25-graphiti-runtime-calibration-measurements.json"
    )

    assert json.loads(path.read_text(encoding="utf-8")) == (
        run_provider_free_runtime_calibration().as_record()
    )
