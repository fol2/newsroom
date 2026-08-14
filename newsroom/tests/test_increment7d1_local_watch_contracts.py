from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment7 import readiness
from newsroom.increment7.local_watch import (
    EVENT_SCOPED_LOCAL_WATCH,
    LOCAL_WATCH_CLOSURE,
    LOCAL_WATCH_CONVERSION_CONDITION,
    LOCAL_WATCH_EXPIRY,
    LOCAL_WATCH_VERSION,
    MAX_WATCH_DURATION_SECONDS,
    NO_PERMANENT_LOCALITY_INFERENCE,
    EventScopedLocalWatch,
    LocalWatchClosure,
    LocalWatchClosureCondition,
    LocalWatchClosureOutcome,
    LocalWatchContractError,
    LocalWatchConversionCondition,
    LocalWatchGrossBudget,
    LocalWatchPrivacyClass,
    LocalWatchSourceBinding,
    LocalWatchSourceRole,
    LocalWatchSubjectKind,
    LocalWatchTransitionKind,
    LocalWatchVersion,
    LocalWatchVersionStatus,
    validate_local_watch_closure,
    validate_local_watch_version_chain,
)

D = lambda character: "sha256:" + character * 64


def _watch() -> EventScopedLocalWatch:
    return EventScopedLocalWatch(
        watch_id="11111111-1111-4111-8111-111111111111",
        subject_kind=LocalWatchSubjectKind.EVENT_HYPOTHESIS,
        subject_id="event-hypothesis:major-flood-warning",
        subject_version_digest=D("a"),
        event_purpose="Resolve one bounded flood-warning state transition.",
        owner_identity_digest=D("b"),
        governing_policy_digests=(D("c"), D("d")),
        privacy_classification=LocalWatchPrivacyClass.PUBLIC_EVENT_SCOPE_ONLY,
        privacy_policy_digest=D("e"),
        created_at="2042-01-01T00:00:00.000000Z",
    )


def _version(
    watch: EventScopedLocalWatch | None = None,
    **changes: object,
) -> LocalWatchVersion:
    watch = watch or _watch()
    values: dict[str, object] = {
        "watch_version_id": "22222222-2222-4222-8222-222222222222",
        "watch_id": watch.watch_id,
        "version_ordinal": 1,
        "previous_version_digest": None,
        "watch_digest": watch.canonical_digest,
        "status": LocalWatchVersionStatus.OPEN,
        "locality_reference_digests": (D("1"),),
        "service_boundary_digests": (D("2"),),
        "source_bindings": (
            LocalWatchSourceBinding(
                source_version_id="source-version:authority:1",
                source_version_digest=D("3"),
                source_role=LocalWatchSourceRole.ORIGINATING_AUTHORITY,
                rights_decision_digest=D("4"),
                boundary_digest=D("1"),
            ),
            LocalWatchSourceBinding(
                source_version_id="source-version:operator:1",
                source_version_digest=D("5"),
                source_role=LocalWatchSourceRole.RESPONSIBLE_OPERATOR,
                rights_decision_digest=D("6"),
                boundary_digest=D("2"),
            ),
        ),
        "permitted_transition_kinds": (
            LocalWatchTransitionKind.CLOSE,
            LocalWatchTransitionKind.DISCOVERY_SIGNAL_REENTRY,
            LocalWatchTransitionKind.OPERATIONAL_FINDING,
            LocalWatchTransitionKind.OWNER_REVIEW,
        ),
        "gross_budget": LocalWatchGrossBudget(
            max_checks=12,
            max_results=40,
            max_fetched_bytes=2_000_000,
            max_wall_seconds=3_600,
            max_cost_microunits=0,
        ),
        "rights_basis_digests": (D("7"), D("8")),
        "operational_profile_digest": D("9"),
        "starts_at": "2042-01-02T00:00:00.000000Z",
        "review_at": "2042-01-02T12:00:00.000000Z",
        "expires_at": "2042-01-03T00:00:00.000000Z",
        "closure_conditions": (
            LocalWatchClosureCondition.BUDGET_EXHAUSTED,
            LocalWatchClosureCondition.EVENT_RESOLVED,
            LocalWatchClosureCondition.EXPIRY_REACHED,
        ),
        "conversion_conditions": (
            LocalWatchConversionCondition.PROSPECTIVE_CONTRIBUTION,
            LocalWatchConversionCondition.REVIEWED_COVERAGE_GAP,
        ),
        "change_reason": "Open one bounded fixture watch.",
        "actor_identity_digest": D("b"),
        "recorded_at": "2042-01-01T00:01:00.000000Z",
    }
    values.update(changes)
    return LocalWatchVersion(**values)  # type: ignore[arg-type]


def _closure(
    version: LocalWatchVersion | None = None,
    **changes: object,
) -> LocalWatchClosure:
    version = version or _version()
    values: dict[str, object] = {
        "closure_id": "33333333-3333-4333-8333-333333333333",
        "watch_id": version.watch_id,
        "watch_version_id": version.watch_version_id,
        "watch_version_digest": version.canonical_digest,
        "outcome": LocalWatchClosureOutcome.EXPIRED,
        "effective_at": version.expires_at,
        "reason": "The exact bounded window expired.",
        "evidence_reference_digests": (),
        "locality_coverage_proposal_digest": None,
        "actor_identity_digest": D("b"),
        "recorded_at": "2042-01-03T00:01:00.000000Z",
    }
    values.update(changes)
    return LocalWatchClosure(**values)  # type: ignore[arg-type]


def test_public_contract_names_match_exact_7r_allocation() -> None:
    allocation = readiness.INCREMENT_7_READINESS.allocation_by_issue[444]
    assert allocation.public_modules == ("newsroom.increment7.local_watch",)
    assert allocation.schema_ids == (
        EVENT_SCOPED_LOCAL_WATCH,
        LOCAL_WATCH_VERSION,
        LOCAL_WATCH_CLOSURE,
    )
    assert LOCAL_WATCH_EXPIRY == "EXPLICIT_DEADLINE_DEFAULTS_TO_CLOSURE"
    assert LOCAL_WATCH_CONVERSION_CONDITION.endswith("AND_DECISION_REQUIRED")
    assert NO_PERMANENT_LOCALITY_INFERENCE.startswith("ONE_OR_REPEATED_WATCHES")


def test_watch_version_and_closure_round_trip_exact_canonical_bytes() -> None:
    watch = _watch()
    version = _version(watch)
    closure = _closure(version)
    assert EventScopedLocalWatch.from_bytes(watch.canonical_bytes) == watch
    assert LocalWatchVersion.from_bytes(version.canonical_bytes) == version
    assert LocalWatchClosure.from_bytes(closure.canonical_bytes) == closure
    assert validate_local_watch_version_chain(watch, (version,)) == (version,)
    assert validate_local_watch_closure(watch, version, closure) == closure
    assert (
        watch.canonical_digest
        == EventScopedLocalWatch.from_bytes(watch.canonical_bytes).canonical_digest
    )


@pytest.mark.parametrize("kind", ("unknown", "duplicate", "noncanonical"))
def test_strict_parser_rejects_unknown_duplicate_and_noncanonical_bytes(
    kind: str,
) -> None:
    raw = _watch().canonical_bytes
    if kind == "unknown":
        value = json.loads(raw)
        value["unexpected"] = False
        raw = canonical_json_bytes(value)
    elif kind == "duplicate":
        raw = raw.replace(
            b'{"created_at":',
            b'{"created_at":"2042-01-01T00:00:00.000000Z","created_at":',
            1,
        )
    else:
        raw += b"\n"
    with pytest.raises(LocalWatchContractError):
        EventScopedLocalWatch.from_bytes(raw)


def test_scope_source_rights_profile_and_budget_are_exact_and_bounded() -> None:
    version = _version()
    with pytest.raises(LocalWatchContractError, match="locality or service"):
        replace(
            version,
            locality_reference_digests=(),
            service_boundary_digests=(),
        )
    with pytest.raises(LocalWatchContractError, match="outside exact watch scope"):
        replace(
            version,
            source_bindings=(
                replace(version.source_bindings[0], boundary_digest=D("f")),
            ),
        )
    with pytest.raises(LocalWatchContractError, match="unique and sorted"):
        replace(version, source_bindings=tuple(reversed(version.source_bindings)))
    with pytest.raises(LocalWatchContractError, match="bounded integer"):
        replace(version, gross_budget=replace(version.gross_budget, max_checks=0))
    with pytest.raises(LocalWatchContractError, match="CLOSE"):
        replace(
            version,
            permitted_transition_kinds=(
                LocalWatchTransitionKind.DISCOVERY_SIGNAL_REENTRY,
            ),
        )


def test_watch_has_hard_expiry_and_cannot_become_indefinite() -> None:
    version = _version()
    with pytest.raises(LocalWatchContractError, match="chronology"):
        replace(version, review_at=version.starts_at)
    too_late = (
        datetime.strptime(version.starts_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
        + timedelta(seconds=MAX_WATCH_DURATION_SECONDS + 1)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with pytest.raises(LocalWatchContractError, match="bounded maximum"):
        replace(version, expires_at=too_late)
    with pytest.raises(LocalWatchContractError, match="default to explicit closure"):
        replace(
            version,
            closure_conditions=(LocalWatchClosureCondition.EVENT_RESOLVED,),
        )


def test_extension_is_a_later_version_with_exact_predecessor() -> None:
    watch = _watch()
    first = _version(watch)
    second = _version(
        watch,
        watch_version_id="44444444-4444-4444-8444-444444444444",
        version_ordinal=2,
        previous_version_digest=first.canonical_digest,
        status=LocalWatchVersionStatus.EXTENDED,
        review_at="2042-01-03T00:00:00.000000Z",
        expires_at="2042-01-04T00:00:00.000000Z",
        change_reason="Owner-approved bounded extension.",
        recorded_at="2042-01-01T00:02:00.000000Z",
    )
    assert validate_local_watch_version_chain(watch, (first, second)) == (
        first,
        second,
    )
    with pytest.raises(LocalWatchContractError, match="predecessor"):
        validate_local_watch_version_chain(
            watch, (first, replace(second, previous_version_digest=D("0")))
        )
    with pytest.raises(LocalWatchContractError, match="later version"):
        replace(second, previous_version_digest=None)
    indefinite = replace(
        second,
        starts_at="2042-02-01T00:00:00.000000Z",
        review_at="2042-02-01T12:00:00.000000Z",
        expires_at="2042-02-02T00:00:01.000000Z",
    )
    with pytest.raises(LocalWatchContractError, match="indefinite"):
        validate_local_watch_version_chain(watch, (first, indefinite))


def test_expiry_is_exact_closure_not_signal_candidate_or_locality_selection() -> None:
    watch = _watch()
    version = _version(watch)
    closure = _closure(version)
    assert validate_local_watch_closure(watch, version, closure).outcome is (
        LocalWatchClosureOutcome.EXPIRED
    )
    with pytest.raises(LocalWatchContractError, match="exact expiry"):
        validate_local_watch_closure(
            watch,
            version,
            replace(closure, effective_at="2042-01-02T23:59:59.000000Z"),
        )
    for record in (watch, version, closure):
        assert record.creates_signal is False
        assert record.creates_lead is False
        assert record.creates_candidate is False
        assert record.authorises_locality is False
        assert record.authorises_permanent_selection is False
        assert record.production_activation_authorised is False


def test_conversion_is_multi_factor_and_only_references_separate_proposal() -> None:
    watch = _watch()
    version = _version(watch)
    with pytest.raises(LocalWatchContractError, match="one factor"):
        replace(
            version,
            conversion_conditions=(
                LocalWatchConversionCondition.REVIEWED_COVERAGE_GAP,
            ),
        )
    with pytest.raises(LocalWatchContractError, match="separate proposal"):
        _closure(version, outcome=LocalWatchClosureOutcome.CONVERSION_PROPOSED)
    conversion = _closure(
        version,
        outcome=LocalWatchClosureOutcome.CONVERSION_PROPOSED,
        effective_at="2042-01-02T18:00:00.000000Z",
        locality_coverage_proposal_digest=D("e"),
    )
    assert validate_local_watch_closure(watch, version, conversion) == conversion
    with pytest.raises(LocalWatchContractError, match="only conversion"):
        _closure(version, locality_coverage_proposal_digest=D("e"))


def test_contract_module_has_no_runtime_io_or_authority_imports() -> None:
    module_path = Path(__file__).parents[1] / "increment7" / "local_watch.py"
    tree = ast.parse(module_path.read_text())
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imports & {
        "socket",
        "subprocess",
        "urllib",
        "requests",
        "httpx",
        "sqlite3",
        "newsroom.increment6.candidates",
        "newsroom.increment6.work_items",
    }
    for record in (_watch(), _version(), _closure()):
        assert record.authorises_external_effect is False
        assert record.authorises_source_access is False
        assert record.authorises_egress is False
        assert record.authorises_spend is False
        assert record.authorises_evidence is False
        assert record.authorises_publication is False
