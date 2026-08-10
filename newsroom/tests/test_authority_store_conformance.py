from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from .authority_store_conformance import (
    CASE_INVENTORY,
    AuthorityStoreBinding,
    AuthorityStoreFixture,
    AuthorityStoreRepresentation,
    CaseId,
    ConformanceEvidence,
    CurrentUseExpectation,
    FailureCode,
    HistoricalAuthorityValue,
    LifecycleEvidence,
    LifecycleExpectation,
    TamperExpectation,
    run_conformance,
)


def _fixture() -> AuthorityStoreFixture:
    return AuthorityStoreFixture(
        representation=AuthorityStoreRepresentation(
            canonical_bytes=b'{"value":"alpha"}',
            scalar_columns={"value": "alpha", "version": 1},
            identity_columns={"record_id": "record-1", "digest": "sha256:alpha"},
            linked_rows=(
                {"child_id": "child-1", "record_id": "record-1", "ordinal": 0},
            ),
        ),
        binding=AuthorityStoreBinding(
            actor="actor-1",
            request="request-1",
            idempotency="idempotency-1",
            cas_predecessor="record-0",
        ),
        historical_values=(
            HistoricalAuthorityValue(
                identity="record-0",
                digest="sha256:previous",
                provenance="request-0",
                value={"value": "previous"},
            ),
        ),
        current_use=CurrentUseExpectation(
            upstream_heads=("authority-head-1", "policy-head-1"),
            rejected_after_head_change=True,
        ),
        tamper=TamperExpectation(
            mutation_kinds=("direct_sql", "linked_row", "self_consistent_rewrite"),
        ),
        lifecycle=LifecycleExpectation(
            competing_writers_deterministic=True,
            rollback_clean=True,
            restart_reopen=True,
            migration_reopen=True,
        ),
    )


class FixtureAdapter:
    """A tiny adapter fixture used only to test the generic kernel."""

    name = "fixture-adapter"
    supported_cases = CASE_INVENTORY

    def __init__(self, defect: str | None = None) -> None:
        self.defect = defect

    def build_fixture(self) -> AuthorityStoreFixture:
        return _fixture()

    def exercise_case(
        self, case: CaseId, fixture: AuthorityStoreFixture
    ) -> ConformanceEvidence:
        representation = fixture.representation
        binding = fixture.binding
        historical = fixture.historical_values
        current = fixture.current_use
        tamper = fixture.tamper
        lifecycle = fixture.lifecycle
        assert representation is not None
        assert binding is not None
        assert historical is not None
        assert current is not None
        assert tamper is not None
        assert lifecycle is not None

        result: dict[str, Any] = {"record_id": "record-1", "value": "alpha"}
        evidence = ConformanceEvidence(
            fresh_result=result,
            replay_result=result,
            reopened_result=result,
            representation=representation,
            binding=binding,
            lost_response_result=result,
            lost_response_integrity_validated=True,
            lost_response_used_currentness=False,
            historical_values=historical,
            current_use_checked_heads=current.upstream_heads,
            current_use_rejected_after_head_change=current.rejected_after_head_change,
            tamper_rejected={kind: True for kind in tamper.mutation_kinds},
            lifecycle=LifecycleEvidence(
                competing_writers_deterministic=(
                    lifecycle.competing_writers_deterministic
                ),
                rollback_clean=lifecycle.rollback_clean,
                restart_reopen=lifecycle.restart_reopen,
                migration_reopen=lifecycle.migration_reopen,
            ),
        )
        if self.defect == "replay" and case is CaseId.FRESH_REPLAY:
            return replace(
                evidence,
                replay_result={"record_id": "record-1", "value": "beta"},
            )
        if self.defect == "reopen" and case is CaseId.FRESH_REOPEN:
            return replace(
                evidence,
                reopened_result={"record_id": "record-1", "value": "beta"},
            )
        if self.defect == "scalar" and case is CaseId.REPRESENTATION_BINDING:
            broken = replace(
                representation,
                scalar_columns={"value": "beta", "version": 1},
            )
            return replace(evidence, representation=broken)
        if self.defect == "canonical" and case is CaseId.REPRESENTATION_BINDING:
            broken = replace(representation, canonical_bytes=b'{"value":"beta"}')
            return replace(evidence, representation=broken)
        if self.defect == "linked" and case is CaseId.REPRESENTATION_BINDING:
            broken = replace(
                representation,
                linked_rows=(
                    {"child_id": "child-1", "record_id": "record-2", "ordinal": 0},
                ),
            )
            return replace(evidence, representation=broken)
        if self.defect == "historical" and case is CaseId.HISTORICAL_READ:
            broken = replace(historical[0], digest="sha256:tampered")
            return replace(evidence, historical_values=(broken,))
        if (
            self.defect in {"actor", "request", "idempotency", "cas"}
            and case is CaseId.REQUEST_BINDING
        ):
            binding_field = "cas_predecessor" if self.defect == "cas" else self.defect
            return replace(
                evidence,
                binding=replace(binding, **{binding_field: "tampered"}),
            )
        if self.defect == "lost_integrity" and case is CaseId.LOST_RESPONSE_REPLAY:
            return replace(evidence, lost_response_integrity_validated=False)
        if self.defect == "lost_currentness" and case is CaseId.LOST_RESPONSE_REPLAY:
            return replace(evidence, lost_response_used_currentness=True)
        if self.defect == "current_heads" and case is CaseId.CURRENT_USE_REVALIDATION:
            return replace(
                evidence,
                current_use_checked_heads=current.upstream_heads[:-1],
            )
        if (
            self.defect == "current_rejection"
            and case is CaseId.CURRENT_USE_REVALIDATION
        ):
            return replace(evidence, current_use_rejected_after_head_change=False)
        if (
            self.defect in {"tamper_direct", "tamper_linked", "tamper_self_consistent"}
            and case is CaseId.TAMPER_REJECTION
        ):
            kind = {
                "tamper_direct": "direct_sql",
                "tamper_linked": "linked_row",
                "tamper_self_consistent": "self_consistent_rewrite",
            }[self.defect]
            return replace(
                evidence,
                tamper_rejected={
                    other: other != kind for other in tamper.mutation_kinds
                },
            )
        if self.defect == "competing" and case is CaseId.COMPETING_WRITERS:
            return replace(
                evidence,
                lifecycle=replace(
                    evidence.lifecycle, competing_writers_deterministic=False
                ),
            )
        if self.defect == "rollback" and case is CaseId.TRANSACTION_ROLLBACK:
            return replace(
                evidence,
                lifecycle=replace(evidence.lifecycle, rollback_clean=False),
            )
        if self.defect == "restart" and case is CaseId.RESTART_MIGRATION:
            return replace(
                evidence,
                lifecycle=replace(evidence.lifecycle, restart_reopen=False),
            )
        if self.defect == "migration" and case is CaseId.RESTART_MIGRATION:
            return replace(
                evidence,
                lifecycle=replace(evidence.lifecycle, migration_reopen=False),
            )
        return evidence


def test_case_inventory_is_stable_and_complete() -> None:
    assert tuple(case.value for case in CASE_INVENTORY) == (
        "fresh_replay",
        "fresh_reopen",
        "representation_binding",
        "request_binding",
        "lost_response_replay",
        "historical_read",
        "current_use_revalidation",
        "tamper_rejection",
        "competing_writers",
        "transaction_rollback",
        "restart_migration",
    )


def test_healthy_adapter_passes_and_unsupported_cases_are_skipped() -> None:
    report = run_conformance(FixtureAdapter())
    assert report.passed
    assert report.failures == ()
    assert all(outcome.status.value == "pass" for outcome in report.outcomes)

    limited = FixtureAdapter()
    limited.supported_cases = (CaseId.FRESH_REPLAY,)
    limited_report = run_conformance(limited)
    assert limited_report.passed
    assert limited_report.outcomes[0].status.value == "pass"
    assert all(
        outcome.status.value == "skipped" for outcome in limited_report.outcomes[1:]
    )

    empty = FixtureAdapter()
    empty.supported_cases = ()
    empty_report = run_conformance(empty)
    assert not empty_report.passed
    assert empty_report.failures[0].code is FailureCode.ADAPTER_PROTOCOL


@pytest.mark.parametrize(
    ("defect", "case", "code"),
    (
        ("replay", CaseId.FRESH_REPLAY, FailureCode.REPLAY_MISMATCH),
        ("reopen", CaseId.FRESH_REOPEN, FailureCode.REOPEN_MISMATCH),
        ("scalar", CaseId.REPRESENTATION_BINDING, FailureCode.REPRESENTATION_MISMATCH),
        (
            "canonical",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        ("linked", CaseId.REPRESENTATION_BINDING, FailureCode.REPRESENTATION_MISMATCH),
        ("historical", CaseId.HISTORICAL_READ, FailureCode.HISTORICAL_INTEGRITY),
        ("actor", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        ("request", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        ("idempotency", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        ("cas", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        (
            "lost_integrity",
            CaseId.LOST_RESPONSE_REPLAY,
            FailureCode.LOST_RESPONSE_INTEGRITY,
        ),
        (
            "lost_currentness",
            CaseId.LOST_RESPONSE_REPLAY,
            FailureCode.LOST_RESPONSE_INTEGRITY,
        ),
        (
            "current_heads",
            CaseId.CURRENT_USE_REVALIDATION,
            FailureCode.CURRENT_USE_REVALIDATION,
        ),
        (
            "current_rejection",
            CaseId.CURRENT_USE_REVALIDATION,
            FailureCode.CURRENT_USE_REVALIDATION,
        ),
        ("tamper_direct", CaseId.TAMPER_REJECTION, FailureCode.TAMPER_ACCEPTED),
        ("tamper_linked", CaseId.TAMPER_REJECTION, FailureCode.TAMPER_ACCEPTED),
        (
            "tamper_self_consistent",
            CaseId.TAMPER_REJECTION,
            FailureCode.TAMPER_ACCEPTED,
        ),
        (
            "competing",
            CaseId.COMPETING_WRITERS,
            FailureCode.COMPETING_WRITERS_NONDETERMINISTIC,
        ),
        (
            "rollback",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        ("restart", CaseId.RESTART_MIGRATION, FailureCode.RESTART_MIGRATION_MISMATCH),
        ("migration", CaseId.RESTART_MIGRATION, FailureCode.RESTART_MIGRATION_MISMATCH),
    ),
)
def test_broken_adapters_fail_with_exact_family_classification(
    defect: str, case: CaseId, code: FailureCode
) -> None:
    report = run_conformance(FixtureAdapter(defect))
    assert not report.passed
    assert [(failure.case, failure.code) for failure in report.failures] == [
        (case, code)
    ]


def test_report_rendering_is_deterministic() -> None:
    first = run_conformance(FixtureAdapter("linked"))
    second = run_conformance(FixtureAdapter("linked"))
    assert first.render() == second.render()
    assert first.render()[0] == "adapter=fixture-adapter"
