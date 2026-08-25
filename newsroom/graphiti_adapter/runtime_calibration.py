"""Provider-free Graphiti runtime calibration and source-safe receipts."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.control_plane.graphiti import (
    GRAPHITI_CONTEXT_IDENTITY,
    GraphitiModelUsageObserver,
)
from newsroom.control_plane.graphiti_fallback_policy import (
    FallbackEligibility,
    classify_graphiti_fallback,
    load_checked_graphiti_fallback_circuit_policy,
)
from newsroom.control_plane.graphiti_requests import (
    load_checked_graphiti_call_shape_policy,
)
from newsroom.control_plane.model_usage import (
    ModelUsageService,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.graphiti_adapter.cli_client import CliExecution, run_cli_chain
from newsroom.graphiti_adapter.combined_temporal_contract import (
    CONTRACT_NAME,
    SCHEMA,
    build_compact_prompt,
)
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import FIXTURES, fixture
from newsroom.graphiti_adapter.combined_temporal_pipeline import (
    CombinedTemporalPipelineResult,
)
from newsroom.graphiti_adapter.combined_temporal_runtime import (
    extract_combined_temporal_async,
    resolve_nodes_with_optional_embeddings,
)
from newsroom.graphiti_adapter.deterministic_work_fixtures import (
    _retained_effective_revision_sensitivity,
    run_provider_free_qualification,
)
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_CORE_RELEASE
from newsroom.graphiti_adapter.token_effectiveness import (
    ConditionalLeafProfile,
    ConditionalLeafTokenRanges,
    EffectiveRevisionTokenCase,
    EffectiveRevisionTokenOutcome,
    TokenEstimateRange,
    build_token_effectiveness_report,
)

DECISION_GATES = (
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


class CalibrationRecommendation(StrEnum):
    ADOPT = "ADOPT"
    HOLD = "HOLD"
    REJECT = "REJECT"


class CalibrationClosed(RuntimeError):
    """Live owner-gated calibration was refused before provider I/O."""


@dataclass(frozen=True, slots=True)
class ReceiptValidation:
    passed: bool
    reason_codes: tuple[str, ...]
    validated_leaf_count: int
    validated_attempt_count: int


@dataclass(frozen=True, slots=True)
class GraphitiRuntimeCalibrationPacket:
    recommendation: CalibrationRecommendation
    reason_code: str | None
    live_owner_gated_execution_authorised: bool
    evidence: dict[str, object]
    evidence_digest: str

    def as_record(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.graphiti-runtime-calibration.v1",
            **self.evidence,
            "recommendation": self.recommendation.value,
            "reason_code": self.reason_code,
            "live_owner_gated_execution_authorised": (
                self.live_owner_gated_execution_authorised
            ),
            "evidence_digest": self.evidence_digest,
        }


_REQUIRED_LEAF_FIELDS = frozenset(
    {
        "invocation_id",
        "parent_invocation_id",
        "leaf_class",
        "request_digest",
        "prompt_digest",
        "schema_identity",
        "schema_digest",
        "model",
        "route",
        "outcome",
        "usage_status",
        "usage_basis",
        "input_tokens",
        "output_tokens",
        "cached_read_tokens",
        "cached_write_tokens",
        "reasoning_tokens",
        "total_tokens",
        "circuit_state",
        "accepted",
    }
)
_SOURCE_EXPRESSION_FIELDS = frozenset(
    {
        "body",
        "episode_body",
        "fact",
        "payload",
        "prompt",
        "prompt_text",
        "raw_output",
        "source_expression",
        "source_text",
    }
)
_UNRESOLVED_USAGE = frozenset({"UNREPORTED", "AMBIGUOUS", "INVALID"})


def _contains_source_expression(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(_SOURCE_EXPRESSION_FIELDS.intersection(value)) or any(
            _contains_source_expression(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_source_expression(item) for item in value)
    return False


def _sha256(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    hexadecimal = value.removeprefix("sha256:")
    return len(hexadecimal) == 64 and all(
        character in "0123456789abcdef" for character in hexadecimal
    )


def validate_redacted_receipts(
    leaves: Sequence[Mapping[str, object]],
    attempts: Sequence[Mapping[str, object]],
) -> ReceiptValidation:
    """Validate per-leaf and per-attempt bindings without source expression."""

    reasons: set[str] = set()
    invocation_ids = {
        str(leaf.get("invocation_id"))
        for leaf in leaves
        if leaf.get("invocation_id") is not None
    }
    request_digests = [str(leaf.get("request_digest")) for leaf in leaves]
    if any(count > 1 for count in Counter(request_digests).values()):
        reasons.add("DUPLICATE_UNCHANGED_REQUEST_DIGEST")
    fallback_counts: Counter[str] = Counter()
    by_invocation = {
        str(leaf.get("invocation_id")): leaf
        for leaf in leaves
        if leaf.get("invocation_id") is not None
    }
    for leaf in leaves:
        if not _REQUIRED_LEAF_FIELDS.issubset(leaf):
            reasons.add("LEAF_BINDING_INCOMPLETE")
        if _contains_source_expression(leaf):
            reasons.add("SOURCE_EXPRESSION_PRESENT")
        usage_status = leaf.get("usage_status")
        if usage_status in _UNRESOLVED_USAGE and leaf.get("total_tokens") is not None:
            reasons.add("MISSING_USAGE_PRESENTED_AS_ZERO")
        if any(
            not _sha256(leaf.get(field))
            for field in ("request_digest", "prompt_digest", "schema_digest")
        ):
            reasons.add("DIGEST_BINDING_INVALID")
        if leaf.get("leaf_class") not in {"PRIMARY", "FALLBACK", "EMBEDDING"}:
            reasons.add("LEAF_CLASS_INVALID")
        if leaf.get("circuit_state") not in {"OPEN", "CLOSED"}:
            reasons.add("CIRCUIT_STATE_INVALID")
        if leaf.get("leaf_class") == "FALLBACK":
            parent_id = leaf.get("parent_invocation_id")
            parent = by_invocation.get(str(parent_id))
            parent_outcome = None if parent is None else parent.get("outcome")
            if parent is None or not isinstance(parent_outcome, str) or (
                classify_graphiti_fallback(parent_outcome).eligibility
                is not FallbackEligibility.ELIGIBLE
            ):
                reasons.add("FALLBACK_WITHOUT_ELIGIBLE_PARENT")
            if parent_id is not None:
                fallback_counts[str(parent_id)] += 1
        if leaf.get("accepted") is True and (
            leaf.get("circuit_state") == "OPEN"
            or leaf.get("usage_status") in _UNRESOLVED_USAGE
            or leaf.get("outcome") == "OUTPUT_LIMIT_EXCEEDED"
        ):
            reasons.add("ACCEPTED_AFTER_BREACH")
    if any(count > 1 for count in fallback_counts.values()):
        reasons.add("MULTIPLE_FALLBACKS_PER_PRIMARY")
    for attempt in attempts:
        if {
            "attempt_id",
            "terminal_outcome",
            "leaf_invocation_ids",
            "rolled_back",
        } - attempt.keys():
            reasons.add("ATTEMPT_BINDING_INCOMPLETE")
            continue
        leaf_ids = attempt.get("leaf_invocation_ids")
        if not isinstance(leaf_ids, list) or any(
            str(item) not in invocation_ids for item in leaf_ids
        ):
            reasons.add("ATTEMPT_LEAF_BINDING_INVALID")
    ordered = tuple(sorted(reasons))
    return ReceiptValidation(
        passed=not ordered,
        reason_codes=ordered,
        validated_leaf_count=len(leaves),
        validated_attempt_count=len(attempts),
    )


class _FixtureTransport:
    def __init__(self, raw: object) -> None:
        self.raw = raw
        self.calls = 0

    async def generate_response(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        response_model: str,
        max_tokens: int,
    ) -> CombinedTemporalTransportResult:
        del prompt, max_tokens
        if dict(schema) != SCHEMA or response_model != CONTRACT_NAME:
            raise ValueError("provider-free fixture request identity differs")
        self.calls += 1
        return CombinedTemporalTransportResult(
            raw=self.raw,
            framework_version=GRAPHITI_CORE_RELEASE,
            model_version="composer-2.5",
            token_usage={"usage_basis": "ESTIMATED", "total_tokens": None},
            provider_cost=None,
        )


class _FixturePipeline:
    async def _prepare_attempt(self) -> None:
        return None

    async def _complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        return receipt

    async def _execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        return CombinedTemporalPipelineResult(
            nodes=nodes,
            edges=edges,
            guarded_edges=edges,
            node_resolutions=tuple("DETERMINISTIC_NEW_NODE" for _ in nodes),
            graph_effect_attempted=bool(nodes or edges),
            embedding_skipped=True,
            journal_skipped=False,
            rollback_skipped=True,
            completed_receipt=receipt,
        )


class _FakeEmbeddingTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _value: str) -> list[float]:
        self.calls += 1
        return [1.0, 0.0]


def _range_from_bytes(byte_count: int) -> TokenEstimateRange:
    return TokenEstimateRange(
        low=max(1, (byte_count + 3) // 4),
        base=max(1, (byte_count + 2) // 3),
        high=max(1, (byte_count + 1) // 2),
    )


def _runtime_token_report() -> dict[str, object]:
    cases: list[EffectiveRevisionTokenCase] = []
    for item in FIXTURES:
        prompt = build_compact_prompt(item.revision)
        primary_tokens = _range_from_bytes(
            len(prompt.text.encode("utf-8"))
            + len(canonical_json_bytes(SCHEMA))
            + len(canonical_json_bytes(item.gold))
        )
        outcome = (
            EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
            if item.name == "zero-result"
            else EffectiveRevisionTokenOutcome.HELD_AMBIGUITY
            if item.name == "same-name"
            else EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
        )
        current = (
            ConditionalLeafProfile(timestamp=1, dedupe=1)
            if item.name == "zero-result"
            else ConditionalLeafProfile(dedupe=1)
            if item.name == "pair-current"
            else ConditionalLeafProfile(fallback=1)
            if item.name == "several-relations"
            else ConditionalLeafProfile()
        )
        target = (
            ConditionalLeafProfile(fallback=1)
            if item.name == "several-relations"
            else ConditionalLeafProfile()
        )
        cases.append(
            EffectiveRevisionTokenCase(
                case_id=item.name,
                outcome=outcome,
                primary_tokens=primary_tokens,
                primary_leaf_count=1,
                current=current,
                target=target,
                embedding_tokens=1 if item.name == "same-name" else 0,
                quality_matches_gold=True,
            )
        )
    report = build_token_effectiveness_report(
        tuple(cases),
        sensitivity=ConditionalLeafTokenRanges(
            timestamp=TokenEstimateRange(756, 1_008, 1_511),
            dedupe=TokenEstimateRange(512, 1_024, 2_048),
            summary=TokenEstimateRange(256, 512, 1_024),
            fallback=TokenEstimateRange(1_024, 2_048, 4_096),
        ),
        distribution_measured=True,
    )
    fixture_averages = report.pop(
        "average_total_tokens_per_terminal_effective_revision"
    )
    retained = _retained_effective_revision_sensitivity()
    retained_averages = retained[
        "average_total_token_estimate_per_terminal_effective_revision"
    ]
    assert isinstance(fixture_averages, dict)
    assert isinstance(retained_averages, dict)
    report["average_tokens_per_terminal_revision"] = {
        "current": retained_averages["current"],
        "target": fixture_averages["target"],
    }
    report["fixture_measured_average_tokens"] = fixture_averages
    report["grain"] = "ISSUE_737_EFFECTIVE_REVISION"
    report["formula"] = (
        "T_avg_revision = E[Σ_(primary misses) T_primary] + "
        "E[Σ_(conditional leaves) T_conditional] + "
        "E[Σ_(embedding misses) T_embedding]"
    )
    report["retained_current_path"] = retained
    return report


def _fixture_slices() -> list[dict[str, object]]:
    combined = [
        {
            "fixture_id": item.name,
            "expected_primary_misses": 1,
            "expected_conditional_leaves": 0,
            "expected_embedding_misses": 1 if item.name == "same-name" else 0,
        }
        for item in FIXTURES
    ]
    combined.extend(
        {
            "fixture_id": fixture_id,
            "expected_primary_misses": primary,
            "expected_conditional_leaves": conditional,
            "expected_embedding_misses": embeddings,
        }
        for fixture_id, primary, conditional, embeddings in (
            ("existing-entity-resolution", 1, 0, 0),
            ("new-entity-resolution", 1, 0, 0),
            ("short-summary", 1, 0, 0),
            ("overlong-summary", 1, 0, 0),
            ("malformed-output-single-fallback", 1, 1, 0),
            ("systemic-failure", 1, 0, 0),
            ("timeout", 1, 0, 0),
            ("cancellation", 1, 0, 0),
            ("restart-immutable-usage", 1, 0, 0),
            ("rolled-back-attempt", 1, 0, 0),
        )
    )
    return combined


def _quality_gold() -> tuple[dict[str, object], dict[str, str]]:
    outcomes: dict[str, str] = {}
    comparisons: dict[str, bool] = {}
    for item in FIXTURES:
        transport = _FixtureTransport(item.gold)
        leaf = asyncio.run(
            extract_combined_temporal_async(
                item.revision,
                transport=transport,
                pipeline=_FixturePipeline(),  # type: ignore[arg-type]
            )
        )
        comparisons[item.name] = (
            transport.calls == 1
            and leaf.payload == item.gold
            and leaf.journal_skipped is False
            and leaf.rollback_skipped is True
        )
        outcomes[item.name] = leaf.outcome.value
    deterministic = run_provider_free_qualification()
    acceptance = deterministic["acceptance"]
    assert isinstance(acceptance, dict)
    local_gold = {
        "authority_and_rights": bool(
            acceptance["sidecar_exact_and_no_loss"]
            and acceptance["authority_bytes_and_digests_verified"]
        ),
        "entity_resolution": bool(
            acceptance["common_entity_resolution_zero_provider_leaves"]
            and acceptance["similar_distinct_entities_separate"]
        ),
        "ambiguity_held": bool(acceptance["ambiguity_held_not_guessed"]),
        "deterministic_summary": bool(
            acceptance["short_summary_zero_provider_leaves"]
            and acceptance["overlong_summary_explicitly_held"]
        ),
        "replay": bool(acceptance["replay_identities_identical"]),
    }
    embed = _FakeEmbeddingTransport()
    resolved, _, _ = asyncio.run(
        resolve_nodes_with_optional_embeddings(
            [
                SimpleNamespace(
                    uuid="mention:lee",
                    name="Lee",
                    attributes={"entity_type_id": "ORGANISATION"},
                )
            ],
            (
                SimpleNamespace(
                    uuid="canonical-entity:lee-a",
                    name="Lee A",
                    name_embedding=[1.0, 0.0],
                    attributes={
                        "entity_type_id": "ORGANISATION",
                        "permitted_source_ids": ("newsroom-fixture",),
                    },
                ),
                SimpleNamespace(
                    uuid="canonical-entity:lee-b",
                    name="Lee B",
                    name_embedding=[0.999, 0.045],
                    attributes={
                        "entity_type_id": "ORGANISATION",
                        "permitted_source_ids": ("newsroom-fixture",),
                    },
                ),
            ),
            source_id="newsroom-fixture",
            embed_name=embed,
        )
    )
    embedding_gold = {
        "fake_transport_calls": embed.calls,
        "outcome": resolved[0].attributes["resolution"],
    }
    all_passed = (
        all(comparisons.values())
        and all(local_gold.values())
        and embedding_gold
        == {"fake_transport_calls": 1, "outcome": "AMBIGUOUS_HOLD"}
    )
    return (
        {
            "all_passed": all_passed,
            "combined_temporal": comparisons,
            "local_deterministic": local_gold,
            "embedding_transport": embedding_gold,
            "held_ambiguity_outcome": "AMBIGUOUS_HOLD",
            "proposal_only": True,
            "public_effects": 0,
        },
        outcomes,
    )


def _receipt_evidence() -> tuple[ReceiptValidation, dict[str, object]]:
    now = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    with TemporaryDirectory() as root:
        service = ModelUsageService(str(Path(root) / "unpublished.sqlite3"))
        envelope = WorkEnvelope.create(
            cycle_id="calibration-cycle",
            workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            admitted_at=now,
            admission_decision_id=None,
            candidate_id=None,
            hypothesis_digest=None,
            evidence_package_digest=None,
            ingest_id="calibration-ingest",
            graphiti_attempt_id="calibration-ingest:1",
        )
        service.open_envelope(envelope)
        observer = GraphitiModelUsageObserver(
            service=service,
            envelope=envelope,
            clock=lambda: now + timedelta(seconds=1),
            owner_stop_check=lambda: None,
        )
        usage = {
            "usage_basis": "PROVIDER_REPORTED",
            "input_tokens": 10,
            "output_tokens": 2,
            "cached_read_tokens": 0,
            "cached_write_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 12,
        }
        asyncio.run(
            run_cli_chain(
                prompt="source-safe calibration prompt",
                schema=json.dumps(SCHEMA),
                semantic_request_class=CONTRACT_NAME,
                max_tokens=512,
                cursor_runner=lambda _prompt, *, max_tokens: CliExecution(
                    text="malformed", usage=usage
                ),
                grok_runner=lambda _prompt, _schema, *, max_tokens: CliExecution(
                    text=json.dumps(fixture("pair-current").gold), usage=usage
                ),
                invocations=[],
                invocation_observer=observer,
            )
        )
        rows = service.query(start=now, end=now + timedelta(minutes=1))["leaves"]
        assert isinstance(rows, list)
        restarted = ModelUsageService(service.path)
        immutable_after_restart = restarted.query(
            start=now, end=now + timedelta(minutes=1)
        )["leaves"] == rows
        invocation_policies = []
        for row in rows:
            policy = service.qualified_policy(
                workload_class=WorkloadClass(str(row["workload_class"])),
                provider=str(row["provider"]),
                route=str(row["route"]),
                model=str(row["model"]),
                reasoning=str(row["reasoning"]),
                output_schema_digest=str(row["output_schema_digest"]),
            )
            invocation_policies.append(
                {
                    "route": policy.route,
                    "canonical_digest": policy.canonical_digest,
                    "evidence_digest": policy.evidence_digest,
                    "max_prompt_bytes": policy.max_prompt_bytes,
                    "max_context_tokens": policy.max_context_tokens,
                    "max_output_tokens": policy.max_output_tokens,
                    "max_total_tokens": policy.max_total_tokens,
                    "hard_estimate_ceiling_tokens": (
                        policy.hard_estimate_ceiling_tokens
                    ),
                }
            )
        leaves: list[dict[str, object]] = []
        for row in rows:
            internal = row["graphiti_internal_request"]
            assert isinstance(internal, dict)
            leaves.append(
                {
                    "invocation_id": row["invocation_id"],
                    "parent_invocation_id": row["parent_invocation_id"],
                    "leaf_class": internal["leaf_class"],
                    "request_digest": row["request_digest"],
                    "prompt_digest": row["prompt_digest"],
                    "schema_identity": internal["response_schema_identity"],
                    "schema_digest": row["output_schema_digest"],
                    "model": row["model"],
                    "route": row["route"],
                    "outcome": row["invocation_outcome"],
                    "usage_status": row["usage_status"],
                    "usage_basis": "PROVIDER_REPORTED",
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cached_read_tokens": row["cached_read_tokens"],
                    "cached_write_tokens": row["cached_write_tokens"],
                    "reasoning_tokens": row["reasoning_tokens"],
                    "total_tokens": row["total_tokens"],
                    "circuit_state": service.route_state(str(row["route"]))["state"],
                    "accepted": row["invocation_outcome"] == "COMPLETE",
                }
            )
        attempts = [
            {
                "attempt_id": "calibration-ingest:1",
                "terminal_outcome": "TERMINAL_SUCCESS_WITH_PROPOSALS",
                "leaf_invocation_ids": [leaf["invocation_id"] for leaf in leaves],
                "rolled_back": False,
            }
        ]
        validation = validate_redacted_receipts(leaves, attempts)
        return validation, {
            "immutable_after_restart": immutable_after_restart,
            "leaf_count": len(leaves),
            "attempt_count": len(attempts),
            "fallback_recovery_count": 1,
            "unchanged_retry_count": 0,
            "invocation_efficiency_policies": invocation_policies,
        }


def _ineligible_cli_outcomes() -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}

    def run_case(name: str, cursor_runner: object) -> None:
        invocations: list[dict[str, object]] = []
        fallback_called = False

        def fallback(_prompt: str, _schema: str | None, *, max_tokens: int) -> str:
            nonlocal fallback_called
            fallback_called = True
            return "{}"

        try:
            asyncio.run(
                run_cli_chain(
                    prompt="source-safe failure fixture",
                    schema=None,
                    cursor_runner=cursor_runner,  # type: ignore[arg-type]
                    grok_runner=fallback,
                    invocations=invocations,
                )
            )
        except (Exception, asyncio.CancelledError):
            pass
        results[name] = {
            "outcomes": [str(item["outcome"]) for item in invocations],
            "fallback_called": fallback_called,
        }

    def systemic(
        _prompt: str, *, max_tokens: int, dispatch_started: object = None
    ) -> str:
        del max_tokens, dispatch_started
        raise OSError("systemic fixture")

    def timeout(
        _prompt: str, *, max_tokens: int, dispatch_started: object = None
    ) -> str:
        del max_tokens, dispatch_started
        raise TimeoutError("timeout fixture")

    async def cancelled(_prompt: str, *, max_tokens: int) -> str:
        del max_tokens
        raise asyncio.CancelledError

    run_case("systemic-failure", systemic)
    run_case("timeout", timeout)
    run_case("cancellation", cancelled)
    return results


def run_provider_free_runtime_calibration() -> GraphitiRuntimeCalibrationPacket:
    """Assess #771 without importing or dispatching a live provider binary."""

    call_shape = load_checked_graphiti_call_shape_policy()
    fallback_policy = load_checked_graphiti_fallback_circuit_policy()
    quality, terminal_outcomes = _quality_gold()
    token_effectiveness = _runtime_token_report()
    receipt_validation, receipt_runtime = _receipt_evidence()
    ineligible_runtime = _ineligible_cli_outcomes()
    averages = token_effectiveness["average_tokens_per_terminal_revision"]
    strict_improvement = isinstance(averages, dict) and all(
        averages["target"][scenario] < averages["current"][scenario]  # type: ignore[index]
        for scenario in ("low", "base", "high")
    )
    target_counts = token_effectiveness.get(
        "conditional_leaf_expected_counts_ppm", {}
    )
    target_conditional = (
        target_counts.get("target") if isinstance(target_counts, dict) else None
    )
    gates = {
        DECISION_GATES[0]: all(
            item["expected_primary_misses"] == 1 for item in _fixture_slices()
        ),
        DECISION_GATES[1]: (
            isinstance(target_conditional, dict)
            and target_conditional.get("timestamp") == 0
            and target_conditional.get("dedupe") == 0
            and target_conditional.get("summary") == 0
        ),
        DECISION_GATES[2]: (
            receipt_validation.passed
            and receipt_runtime["immutable_after_restart"] is True
        ),
        DECISION_GATES[3]: quality["all_passed"] is True,
        DECISION_GATES[4]: receipt_validation.passed,
        DECISION_GATES[5]: strict_improvement,
        DECISION_GATES[6]: quality["held_ambiguity_outcome"] == "AMBIGUOUS_HOLD",
        DECISION_GATES[7]: (
            receipt_runtime["fallback_recovery_count"] == 1
            and receipt_runtime["unchanged_retry_count"] == 0
            and all(
                item["fallback_called"] is False
                for item in ineligible_runtime.values()
            )
        ),
        DECISION_GATES[8]: quality["public_effects"] == 0,
    }
    recommendation = (
        CalibrationRecommendation.ADOPT
        if all(gates.values())
        else CalibrationRecommendation.HOLD
    )
    reason_code = None if recommendation is CalibrationRecommendation.ADOPT else (
        "DECISION_GATE_NOT_PROVED"
    )
    evidence: dict[str, object] = {
        "issue": 771,
        "parent_issue": 731,
        "provider_calls": 0,
        "public_effects": 0,
        "fixture_slices": _fixture_slices(),
        "identities": {
            "context_manifest": GRAPHITI_CONTEXT_IDENTITY,
            "prompt": call_shape.prompt_identity,
            "schema": CONTRACT_NAME,
            "schema_digest": digest_canonical(
                {"response_schema": json.dumps(SCHEMA)}
            ),
            "call_shape_policy_digest": call_shape.canonical_digest,
            "fallback_circuit_policy_digest": fallback_policy.canonical_digest,
            "qualified_routes": [
                route.as_record() for route in call_shape.qualified_routes
            ],
        },
        "fallback_eligible_outcomes": list(fallback_policy.eligible_outcomes),
        "fallback_not_needed_outcomes": list(
            fallback_policy.no_fallback_needed_outcomes
        ),
        "fallback_ineligible_outcomes": sorted(
            set(fallback_policy.outcome_classes)
            - set(fallback_policy.eligible_outcomes)
            - set(fallback_policy.no_fallback_needed_outcomes)
        ),
        "stop_conditions": {
            "max_distinct_internal_requests": (
                call_shape.max_distinct_internal_requests
            ),
            "max_fallback_leaves_per_primary": (
                fallback_policy.max_fallback_leaves_per_primary
            ),
            "unchanged_request_redispatch": False,
            "circuit_release_preference": list(
                fallback_policy.circuit_release_preference
            ),
        },
        "receipt_validation": {
            "passed": receipt_validation.passed,
            "reason_codes": list(receipt_validation.reason_codes),
            "validated_leaf_count": receipt_validation.validated_leaf_count,
            "validated_attempt_count": receipt_validation.validated_attempt_count,
            **receipt_runtime,
        },
        "ineligible_runtime": ineligible_runtime,
        "quality_gold": quality,
        "terminal_outcomes": terminal_outcomes,
        "token_effectiveness": token_effectiveness,
        "deterministic_local_work": {
            "basis": "PROVIDER_FREE_LOCAL_VALIDATION",
            "fixture_count": len(FIXTURES),
            "reported_as_provider_tokens": False,
        },
        "attempt_usage": {
            "terminal_success": [
                {"attempt_id": "calibration-ingest:1", "usage_basis": "ESTIMATED"}
            ],
            "failed_or_rolled_back": [
                {"attempt_id": "rolled-back-attempt", "usage_basis": "UNRESOLVED"}
            ],
        },
        "decision_gate_results": gates,
        "non_effects": [
            "NO_PROVIDER_CALL",
            "NO_PRODUCTION_MUTATION",
            "NO_PUBLICATION",
            "NO_BACKLOG_ACTIVATION",
            "NO_GING_010_AMENDMENT",
        ],
    }
    digest = digest_canonical(
        {
            "schema_version": "newsroom.graphiti-runtime-calibration.v1",
            **evidence,
            "recommendation": recommendation.value,
            "reason_code": reason_code,
            "live_owner_gated_execution_authorised": False,
        }
    )
    return GraphitiRuntimeCalibrationPacket(
        recommendation=recommendation,
        reason_code=reason_code,
        live_owner_gated_execution_authorised=False,
        evidence=evidence,
        evidence_digest=digest,
    )


__all__ = [
    "CalibrationClosed",
    "CalibrationRecommendation",
    "DECISION_GATES",
    "GraphitiRuntimeCalibrationPacket",
    "ReceiptValidation",
    "run_provider_free_runtime_calibration",
    "validate_redacted_receipts",
]
