"""Increment 9Q-10 PROSPECTIVE_RUN_AUTHORITY qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Qualification proves that a presented run_id resolves to a persisted
EvaluationEpoch → current ManifestCohort → prospective ShadowRun chain on the
real epoch contracts, fail-closed. The validator is wired into proving.assess;
a bare non-empty run_id is a namesake and cannot PASS.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.deployment import EXPECTED_EGRESS_DESTINATIONS
from newsroom.increment9.epoch import (
    EFFECTIVE_MANIFEST_IDENTITY_KEYS,
    EffectiveManifest,
    EpochAuthorityError,
    EvaluationEpoch,
    ManifestCohort,
    RunKind,
    ShadowEpochAuthority,
    ShadowRun,
    initialise_shadow_epoch_authority,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "PROSPECTIVE_RUN_AUTHORITY"
INVENTORY_NAME = "inventory.json"
EPOCH_ID = "epoch-9q10-fixture"
MANIFEST_ID = "effective-manifest-9q10-fixture"
COHORT_ID = "cohort-9q10-fixture"
RUN_ID = "run-9q10-fixture"
T0 = "2042-01-01T00:00:00.000000Z"
T1 = "2042-01-01T00:01:00.000000Z"
T2 = "2042-01-01T00:02:00.000000Z"
T3 = "2042-01-01T00:03:00.000000Z"
T9 = "2042-01-29T00:00:00.000000Z"
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_DIGEST = "sha256:" + "0" * 64

REFUSAL_CLASSES = (
    "NO_AUTHORITY",
    "MALFORMED_RUN_ID",
    "COHORT_NOT_CURRENT",
    "EPOCH_BINDING",
    "CHRONOLOGY",
    "NON_PROSPECTIVE",
    "CHAIN_BINDING",
    "MALFORMED_CHAIN",
    "ANTI_NAMESAKE",
)
PROBE_COUNTS = {
    "NO_AUTHORITY": 2,
    "MALFORMED_RUN_ID": 3,
    "COHORT_NOT_CURRENT": 1,
    "EPOCH_BINDING": 2,
    "CHRONOLOGY": 2,
    "NON_PROSPECTIVE": 2,
    "CHAIN_BINDING": 2,
    "MALFORMED_CHAIN": 3,
    "ANTI_NAMESAKE": 2,
}
PACKAGE_FIXTURES = (
    Path(__file__).parent / "fixtures" / "increment9q10_prospective_run_authority"
)
_MARKERS = {
    "NO_AUTHORITY": b"no_authority",
    "MALFORMED_RUN_ID": b"malformed_run_id",
    "COHORT_NOT_CURRENT": b"cohort_not_current",
    "EPOCH_BINDING": b"epoch_binding",
    "CHRONOLOGY": b"chronology",
    "NON_PROSPECTIVE": b"non_prospective",
    "CHAIN_BINDING": b"chain_binding",
    "MALFORMED_CHAIN": b"malformed_chain",
    "ANTI_NAMESAKE": b"anti_namesake",
}
_INVENTORY_FIELDS = frozenset({"cohort", "epoch", "manifest", "run"})
_RECORD_TYPES = {
    "epoch": EvaluationEpoch,
    "manifest": EffectiveManifest,
    "cohort": ManifestCohort,
    "run": ShadowRun,
}

Probe = Callable[[str, Path], bool]
RunAuthorityResolver = Callable[[str], "RunAuthorityPresentation | None"]


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


@dataclass(frozen=True, slots=True)
class RunAuthorityPresentation:
    epoch_bytes: bytes | None
    cohort_bytes: bytes | None
    run_bytes: bytes
    current_cohort_digest: str | None


@dataclass(frozen=True, slots=True)
class RunAuthorityVerdict:
    status: str
    reason: str
    epoch_digest: str | None = None
    cohort_digest: str | None = None
    manifest_digest: str | None = None
    exposure_contract_digest: str | None = None
    budget_rules_digest: str | None = None


@dataclass(frozen=True, slots=True)
class IsolatedRunAuthority:
    connection: sqlite3.Connection
    authority: ShadowEpochAuthority
    epoch: EvaluationEpoch
    manifest: EffectiveManifest
    cohort: ManifestCohort
    run: ShadowRun
    resolver: RunAuthorityResolver


@dataclass(frozen=True, slots=True)
class RefusalDigest:
    refusal_class: str
    before_digest: str
    after_digest: str
    engaged: bool
    count: int


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    gate_id: str
    status: str
    epoch_digest: str
    cohort_digest: str
    manifest_digest: str
    exposure_contract_digest: str
    budget_rules_digest: str
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
    evidence_digest: str


def _d(character: str) -> str:
    return "sha256:" + character * 64


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _fail(reason: str) -> RunAuthorityVerdict:
    return RunAuthorityVerdict(status="FAIL", reason=reason)


def fixture_epoch() -> EvaluationEpoch:
    return EvaluationEpoch(
        epoch_id=EPOCH_ID,
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        shadow_scope_digest=_d("1"),
        source_portfolio_digest=_d("2"),
        prospective_universe_digest=_d("3"),
        slice_rules_digest=_d("4"),
        thresholds_digest=_d("5"),
        comparator_rules_digest=_d("6"),
        reviewer_rules_digest=_d("7"),
        budget_rules_digest=_d("8"),
        rights_rules_digest=_d("9"),
        opened_at=T0,
        cutoff_at=T0,
        closes_at=T9,
    )


def fixture_manifest(character: str = "a") -> EffectiveManifest:
    digits = "0123456789abcdef"
    offset = int(character, 16)
    identities = {
        key: _d(digits[(index + offset) % 16])
        for index, key in enumerate(sorted(EFFECTIVE_MANIFEST_IDENTITY_KEYS))
    }
    suffix = "" if character == "a" else f"-{character}"
    return EffectiveManifest(
        manifest_id=f"{MANIFEST_ID}{suffix}",
        identity_digests=identities,
        observed_at=T0,
        identity_resolved=True,
    )


def fixture_cohort(
    epoch: EvaluationEpoch | None = None,
    manifest: EffectiveManifest | None = None,
    **changes: object,
) -> ManifestCohort:
    epoch = epoch or fixture_epoch()
    manifest = manifest or fixture_manifest()
    values: dict[str, object] = {
        "cohort_id": COHORT_ID,
        "epoch_id": epoch.epoch_id,
        "epoch_digest": epoch.canonical_digest,
        "manifest_digest": manifest.canonical_digest,
        "ordinal": 1,
        "previous_cohort_digest": None,
        "exposure_contract_digest": _d("b"),
        "required_slices": ("HONG_KONG", "UK"),
        "opened_at": T1,
        "decision_bearing": manifest.decision_bearing,
    }
    values.update(changes)
    return ManifestCohort(**values)  # type: ignore[arg-type]


def fixture_run(
    epoch: EvaluationEpoch | None = None,
    cohort: ManifestCohort | None = None,
    manifest: EffectiveManifest | None = None,
    *,
    run_id: str = RUN_ID,
    **changes: object,
) -> ShadowRun:
    epoch = epoch or fixture_epoch()
    manifest = manifest or fixture_manifest()
    cohort = cohort or fixture_cohort(epoch, manifest)
    values: dict[str, object] = {
        "run_id": run_id,
        "epoch_id": epoch.epoch_id,
        "epoch_digest": epoch.canonical_digest,
        "cohort_id": cohort.cohort_id,
        "cohort_digest": cohort.canonical_digest,
        "manifest_digest": manifest.canonical_digest,
        "production_snapshot_digest": _d("c"),
        "production_nonmutation_before_digest": _d("d"),
        "run_kind": RunKind.PROSPECTIVE_BASELINE,
        "started_at": T2,
        "prospective": True,
    }
    values.update(changes)
    return ShadowRun(**values)  # type: ignore[arg-type]


def fixture_inventory() -> dict[str, object]:
    """Authorised fixture chain primitives. No destination or stop_rules fields."""

    epoch = fixture_epoch()
    manifest = fixture_manifest()
    cohort = fixture_cohort(epoch, manifest)
    run = fixture_run(epoch, cohort, manifest)
    return {
        "cohort": json.loads(cohort.canonical_bytes),
        "epoch": json.loads(epoch.canonical_bytes),
        "manifest": json.loads(manifest.canonical_bytes),
        "run": json.loads(run.canonical_bytes),
    }


def bind_inventory(raw: object) -> dict[str, object]:
    """Validate a fixture chain inventory via canonical from_bytes, fail-closed."""

    if type(raw) is not dict or set(raw) != _INVENTORY_FIELDS:
        raise QualificationError("inventory is required")
    bound: dict[str, object] = {}
    for key, cls in _RECORD_TYPES.items():
        item = raw[key]
        if type(item) is not dict:
            raise QualificationError("inventory is required")
        try:
            bound[key] = cls.from_bytes(canonical_json_bytes(item))
        except (EpochAuthorityError, TypeError, ValueError) as exc:
            raise QualificationError("inventory is required") from exc
    return bound


def refuse_namesake_satisfaction(gates: tuple[str, ...] | list[str]) -> None:
    """Refuse RUNTIME_GATES list membership as this First I/O Gate."""

    if GATE_ID in gates:
        raise QualificationError(
            "RUNTIME_GATES membership cannot satisfy this First I/O Gate"
        )
    raise QualificationError(
        "PROSPECTIVE_RUN_AUTHORITY is absent from RUNTIME_GATES"
    )


def resolver_from_store(
    authority: ShadowEpochAuthority,
    connection: sqlite3.Connection,
) -> RunAuthorityResolver:
    """Resolve a run_id through the real shadow-authority read path."""

    def resolve(run_id: str) -> RunAuthorityPresentation | None:
        row = connection.execute(
            "SELECT record_bytes FROM shadow_epoch_records "
            "WHERE record_schema=? AND record_id=?",
            (ShadowRun.schema_version, run_id),
        ).fetchone()
        if row is None:
            return None
        run_bytes = bytes(row[0])
        try:
            run = ShadowRun.from_bytes(run_bytes)
        except EpochAuthorityError:
            return RunAuthorityPresentation(None, None, run_bytes, None)
        epoch_bytes: bytes | None
        cohort_bytes: bytes | None
        try:
            epoch = authority.read(run.epoch_digest)
            epoch_bytes = epoch.canonical_bytes
        except EpochAuthorityError:
            epoch_bytes = None
        try:
            cohort = authority.read(run.cohort_digest)
            cohort_bytes = cohort.canonical_bytes
        except EpochAuthorityError:
            cohort_bytes = None
        return RunAuthorityPresentation(
            epoch_bytes,
            cohort_bytes,
            run_bytes,
            _current_cohort_digest(connection, run.epoch_id),
        )

    return resolve


def persist_authorised_chain(
    *,
    run_id: str = RUN_ID,
    inventory: dict[str, object] | None = None,
) -> IsolatedRunAuthority:
    """Persist one complete fixture chain in an isolated shadow authority."""

    if inventory is None:
        epoch = fixture_epoch()
        manifest = fixture_manifest()
        cohort = fixture_cohort(epoch, manifest)
        run = fixture_run(epoch, cohort, manifest, run_id=run_id)
    else:
        bound = bind_inventory(inventory)
        epoch = bound["epoch"]
        manifest = bound["manifest"]
        cohort = bound["cohort"]
        run = bound["run"]
        if not isinstance(epoch, EvaluationEpoch):
            raise QualificationError("inventory is required")
        if not isinstance(manifest, EffectiveManifest):
            raise QualificationError("inventory is required")
        if not isinstance(cohort, ManifestCohort):
            raise QualificationError("inventory is required")
        if not isinstance(run, ShadowRun):
            raise QualificationError("inventory is required")
        if run_id != RUN_ID and run.run_id != run_id:
            run = replace(run, run_id=run_id)
    connection = sqlite3.connect(":memory:", isolation_level=None)
    authority = initialise_shadow_epoch_authority(connection)
    try:
        for record in (epoch, manifest, cohort, run):
            authority.append(record, epoch_id=epoch.epoch_id)
    except EpochAuthorityError as exc:
        raise QualificationError("inventory is required") from exc
    return IsolatedRunAuthority(
        connection,
        authority,
        epoch,
        manifest,
        cohort,
        run,
        resolver_from_store(authority, connection),
    )


def _current_cohort_digest(connection: sqlite3.Connection, epoch_id: str) -> str | None:
    rows = connection.execute(
        "SELECT record_bytes FROM shadow_epoch_records "
        "WHERE epoch_id=? AND record_schema=?",
        (epoch_id, ManifestCohort.schema_version),
    ).fetchall()
    if not rows:
        return None
    try:
        cohorts = tuple(ManifestCohort.from_bytes(bytes(row[0])) for row in rows)
    except EpochAuthorityError:
        return None
    return max(cohorts, key=lambda item: item.ordinal).canonical_digest


def _well_formed_run_id(run_id: object) -> bool:
    return type(run_id) is str and _TOKEN.fullmatch(run_id) is not None


def _constant_resolver(
    run_id: str, presentation: RunAuthorityPresentation
) -> RunAuthorityResolver:
    def resolve(presented: str) -> RunAuthorityPresentation | None:
        if presented != run_id:
            return None
        return presentation

    return resolve


def assess_run_authority(
    run_id: object,
    *,
    resolver: RunAuthorityResolver | None = None,
) -> RunAuthorityVerdict:
    """Fail-closed run-authority verdict. No wall-clock read. No network."""

    if resolver is None or not callable(resolver):
        return _fail("resolver is required")
    if not _well_formed_run_id(run_id):
        return _fail("malformed run_id")
    assert type(run_id) is str
    try:
        presented = resolver(run_id)
    except (EpochAuthorityError, QualificationError, TypeError, ValueError):
        return _fail("malformed chain record")
    if presented is None:
        return _fail("no authority presented")
    if type(presented) is not RunAuthorityPresentation:
        return _fail("malformed chain record")
    try:
        run = ShadowRun.from_bytes(presented.run_bytes)
    except EpochAuthorityError:
        return _fail("malformed chain record")
    if presented.epoch_bytes is None:
        return _fail("epoch binding mismatch")
    try:
        epoch = EvaluationEpoch.from_bytes(presented.epoch_bytes)
    except EpochAuthorityError:
        return _fail("malformed chain record")
    if presented.cohort_bytes is None:
        return _fail("chain binding mismatch")
    try:
        cohort = ManifestCohort.from_bytes(presented.cohort_bytes)
    except EpochAuthorityError:
        return _fail("malformed chain record")
    if run.epoch_digest != epoch.canonical_digest:
        return _fail("epoch binding mismatch")
    if (
        run.run_id != run_id
        or run.epoch_id != epoch.epoch_id
        or run.cohort_id != cohort.cohort_id
        or run.cohort_digest != cohort.canonical_digest
        or run.manifest_digest != cohort.manifest_digest
    ):
        return _fail("chain binding mismatch")
    if presented.current_cohort_digest != cohort.canonical_digest:
        return _fail("cohort not current")
    started = _instant(run.started_at)
    if not (_instant(epoch.cutoff_at) <= started < _instant(epoch.closes_at)):
        return _fail("chronology violation")
    if run.prospective is not True:
        return _fail("non-prospective run")
    if not EXPECTED_EGRESS_DESTINATIONS:
        return _fail("chain binding mismatch")
    return RunAuthorityVerdict(
        status="PASS",
        reason="authorised",
        epoch_digest=epoch.canonical_digest,
        cohort_digest=cohort.canonical_digest,
        manifest_digest=run.manifest_digest,
        exposure_contract_digest=cohort.exposure_contract_digest,
        budget_rules_digest=epoch.budget_rules_digest,
    )


def _reject_forbidden(inventory: Path) -> None:
    if "news_pool" in str(inventory).lower():
        raise QualificationError("inventory must not alias news_pool")


def _refusal_surfaces(inventory: Path) -> tuple[tuple[str, Path], ...]:
    if not inventory.is_dir():
        raise QualificationError("inventory is required")
    missing = [rc for rc in REFUSAL_CLASSES if not (inventory / rc).is_file()]
    if missing:
        raise QualificationError(f"missing refusal class: {missing[0]}")
    extras = sorted(
        path.name
        for path in inventory.iterdir()
        if path.name not in REFUSAL_CLASSES and path.name != INVENTORY_NAME
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _load_inventory(inventory: Path) -> dict[str, object]:
    path = inventory / INVENTORY_NAME
    if not path.is_file():
        raise QualificationError("inventory is required")
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("inventory is required") from exc
    return bind_inventory(raw)


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except (EpochAuthorityError, QualificationError):
        return True
    return False


def _verdict_fail(
    run_id: str,
    presentation: RunAuthorityPresentation | None,
    *,
    resolver: RunAuthorityResolver | None = None,
) -> bool:
    active = (
        resolver
        if resolver is not None
        else (
            _constant_resolver(run_id, presentation)
            if presentation is not None
            else (lambda _rid: None)
        )
    )
    return assess_run_authority(run_id, resolver=active).status != "PASS"


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that a run-authority refusal class engages on the real contracts."""

    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")
    if _MARKERS[refusal_class] not in path.read_bytes():
        return False
    probes = {
        "NO_AUTHORITY": _should_engage_no_authority,
        "MALFORMED_RUN_ID": _should_engage_malformed_run_id,
        "COHORT_NOT_CURRENT": _should_engage_cohort_not_current,
        "EPOCH_BINDING": _should_engage_epoch_binding,
        "CHRONOLOGY": _should_engage_chronology,
        "NON_PROSPECTIVE": _should_engage_non_prospective,
        "CHAIN_BINDING": _should_engage_chain_binding,
        "MALFORMED_CHAIN": _should_engage_malformed_chain,
        "ANTI_NAMESAKE": _should_engage_anti_namesake,
    }
    return bool(probes[refusal_class]())


def _authorised_presentation() -> tuple[EvaluationEpoch, ManifestCohort, ShadowRun]:
    epoch = fixture_epoch()
    manifest = fixture_manifest()
    cohort = fixture_cohort(epoch, manifest)
    return epoch, cohort, fixture_run(epoch, cohort, manifest)


def _present(
    epoch: EvaluationEpoch,
    cohort: ManifestCohort,
    run: ShadowRun,
    *,
    current: str | None = None,
    epoch_bytes: bytes | None = None,
    cohort_bytes: bytes | None = None,
) -> RunAuthorityPresentation:
    return RunAuthorityPresentation(
        epoch.canonical_bytes if epoch_bytes is None else epoch_bytes,
        cohort.canonical_bytes if cohort_bytes is None else cohort_bytes,
        run.canonical_bytes,
        cohort.canonical_digest if current is None else current,
    )


def _should_engage_no_authority() -> bool:
    isolated = persist_authorised_chain()
    miss = assess_run_authority("ghost-run", resolver=isolated.resolver)
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    gates = proving_assess(
        run_id="ghost-run",
        kill_switch=False,
        no_emergency_stop=True,
        run_authority=isolated.resolver,
    )
    proving = next(g for g in gates if g.gate_id == GATE_ID)
    return miss.status == "FAIL" and proving.status is GateStatus.FAIL


def _should_engage_malformed_run_id() -> bool:
    isolated = persist_authorised_chain()
    return all(
        assess_run_authority(value, resolver=isolated.resolver).status == "FAIL"
        for value in ("", "a" * 257, "run id")
    )


def _should_engage_cohort_not_current() -> bool:
    epoch = fixture_epoch()
    first_manifest = fixture_manifest("a")
    first = fixture_cohort(epoch, first_manifest)
    second_manifest = fixture_manifest("b")
    second = fixture_cohort(
        epoch,
        second_manifest,
        cohort_id="cohort-9q10-current",
        ordinal=2,
        previous_cohort_digest=first.canonical_digest,
        opened_at=T3,
    )
    stale = fixture_run(
        epoch, first, first_manifest, run_id="stale-run-9q10"
    )
    presentation = _present(epoch, first, stale, current=second.canonical_digest)
    injected = _verdict_fail(stale.run_id, presentation)
    connection = sqlite3.connect(":memory:", isolation_level=None)
    authority = initialise_shadow_epoch_authority(connection)
    for record in (epoch, first_manifest, first, second_manifest, second):
        authority.append(record, epoch_id=epoch.epoch_id)
    append_closed = _refused(
        lambda: authority.append(stale, epoch_id=epoch.epoch_id)
    )
    return injected and append_closed


def _should_engage_epoch_binding() -> bool:
    epoch, cohort, run = _authorised_presentation()
    mismatched = replace(run, epoch_digest=_d("e"))
    absent = RunAuthorityPresentation(
        None, cohort.canonical_bytes, run.canonical_bytes, cohort.canonical_digest
    )
    return _verdict_fail(
        mismatched.run_id, _present(epoch, cohort, mismatched)
    ) and _verdict_fail(run.run_id, absent)


def _should_engage_chronology() -> bool:
    epoch, cohort, run = _authorised_presentation()
    early = replace(run, started_at="2041-12-31T23:59:59.000000Z")
    late = replace(run, started_at=T9)
    return _verdict_fail(early.run_id, _present(epoch, cohort, early)) and _verdict_fail(
        late.run_id, _present(epoch, cohort, late)
    )


def _should_engage_non_prospective() -> bool:
    epoch, cohort, run = _authorised_presentation()
    decision_bearing = json.loads(run.canonical_bytes)
    decision_bearing["prospective"] = False
    constructor_closed = _refused(
        lambda: ShadowRun.from_bytes(canonical_json_bytes(decision_bearing))
    )
    replay = replace(
        run, run_kind=RunKind.REPLAY_QUALIFICATION, prospective=False
    )
    replay_closed = _verdict_fail(replay.run_id, _present(epoch, cohort, replay))
    return constructor_closed and replay_closed


def _should_engage_chain_binding() -> bool:
    epoch, cohort, run = _authorised_presentation()
    digest_drift = replace(run, manifest_digest=_DIGEST)
    identity = replace(run, epoch_id="other-epoch-9q10")
    return _verdict_fail(
        digest_drift.run_id, _present(epoch, cohort, digest_drift)
    ) and _verdict_fail(identity.run_id, _present(epoch, cohort, identity))


def _should_engage_malformed_chain() -> bool:
    epoch, cohort, run = _authorised_presentation()
    bad = b"{"
    epoch_bad = _present(epoch, cohort, run, epoch_bytes=bad)
    cohort_bad = _present(epoch, cohort, run, cohort_bytes=bad)
    run_bad = RunAuthorityPresentation(
        epoch.canonical_bytes,
        cohort.canonical_bytes,
        bad,
        cohort.canonical_digest,
    )
    return all(
        (
            _verdict_fail(run.run_id, epoch_bad),
            _verdict_fail(run.run_id, cohort_bad),
            _verdict_fail(run.run_id, run_bad),
        )
    )


def _should_engage_anti_namesake() -> bool:
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess
    from scripts.increment9_shadow_campaign import RUNTIME_GATES

    namesake_closed = _refused(lambda: refuse_namesake_satisfaction(RUNTIME_GATES))
    listed = GATE_ID in RUNTIME_GATES
    gates = proving_assess(
        run_id="r1", kill_switch=False, no_emergency_stop=True
    )
    proving = next(g for g in gates if g.gate_id == GATE_ID)
    return (
        namesake_closed
        and listed
        and proving.status is GateStatus.FAIL
        and proving.reason == "resolver is required"
    )


def _refusal_payload(
    records: tuple[RefusalDigest, ...],
) -> list[dict[str, str | bool | int]]:
    return [
        {
            "after_digest": item.after_digest,
            "before_digest": item.before_digest,
            "count": item.count,
            "engaged": item.engaged,
            "refusal_class": item.refusal_class,
        }
        for item in records
    ]


def _demonstrate(inventory: dict[str, object]) -> RunAuthorityVerdict:
    isolated = persist_authorised_chain(inventory=inventory)
    first = assess_run_authority(isolated.run.run_id, resolver=isolated.resolver)
    second = assess_run_authority(isolated.run.run_id, resolver=isolated.resolver)
    if first.status != "PASS" or first != second:
        raise QualificationError("inventory is required")
    if (
        first.epoch_digest != isolated.epoch.canonical_digest
        or first.cohort_digest != isolated.cohort.canonical_digest
        or first.manifest_digest != isolated.manifest.canonical_digest
        or first.exposure_contract_digest != isolated.cohort.exposure_contract_digest
        or first.budget_rules_digest != isolated.epoch.budget_rules_digest
    ):
        raise QualificationError("inventory is required")
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    gates = proving_assess(
        run_id=isolated.run.run_id,
        kill_switch=False,
        no_emergency_stop=True,
        run_authority=isolated.resolver,
    )
    proving = next(g for g in gates if g.gate_id == GATE_ID)
    if proving.status is not GateStatus.PASS:
        raise QualificationError("inventory is required")
    return first


def _evidence_body(
    bound: RunAuthorityVerdict,
    records: tuple[RefusalDigest, ...],
    engaged_count: int,
) -> dict[str, object]:
    return {
        "anti_namesake_refusals": PROBE_COUNTS["ANTI_NAMESAKE"],
        "budget_rules_digest": bound.budget_rules_digest,
        "chain_binding_refusals": PROBE_COUNTS["CHAIN_BINDING"],
        "chronology_refusals": PROBE_COUNTS["CHRONOLOGY"],
        "cohort_digest": bound.cohort_digest,
        "cohort_not_current_refusals": PROBE_COUNTS["COHORT_NOT_CURRENT"],
        "deterministic_pass": True,
        "epoch_binding_refusals": PROBE_COUNTS["EPOCH_BINDING"],
        "epoch_digest": bound.epoch_digest,
        "exposure_contract_digest": bound.exposure_contract_digest,
        "gate_id": GATE_ID,
        "malformed_chain_refusals": PROBE_COUNTS["MALFORMED_CHAIN"],
        "malformed_run_id_refusals": PROBE_COUNTS["MALFORMED_RUN_ID"],
        "manifest_digest": bound.manifest_digest,
        "no_authority_refusals": PROBE_COUNTS["NO_AUTHORITY"],
        "non_prospective_refusals": PROBE_COUNTS["NON_PROSPECTIVE"],
        "refusals": _refusal_payload(records),
        "refusals_engaged": engaged_count,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
    }


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    chain_inventory: dict[str, object] | None = None,
) -> QualificationEvidence:
    """Assess that run-authority refusal classes engage deterministically."""

    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    bound_inventory = (
        bind_inventory(chain_inventory)
        if chain_inventory is not None
        else _load_inventory(inventory)
    )
    writer = default_probe if probe is None else probe
    before = {rc: _digest_file(path) for rc, path in surfaces}
    engaged_count = 0
    for rc, path in surfaces:
        if writer(rc, path):
            engaged_count += 1
    after = {rc: _digest_file(path) for rc, path in surfaces}
    if any(before[rc] != after[rc] for rc in REFUSAL_CLASSES):
        raise QualificationError("refusal surface digest mutated")
    if engaged_count != len(REFUSAL_CLASSES):
        raise QualificationError(
            f"not all refusals engaged: {engaged_count}/{len(REFUSAL_CLASSES)}"
        )
    records = tuple(
        RefusalDigest(rc, before[rc], after[rc], True, PROBE_COUNTS[rc])
        for rc in REFUSAL_CLASSES
    )
    raw = {
        key: json.loads(record.canonical_bytes)
        for key, record in bound_inventory.items()
        if hasattr(record, "canonical_bytes")
    }
    bound = _demonstrate(raw)
    payload = _evidence_body(bound, records, engaged_count)
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        epoch_digest=str(bound.epoch_digest),
        cohort_digest=str(bound.cohort_digest),
        manifest_digest=str(bound.manifest_digest),
        exposure_contract_digest=str(bound.exposure_contract_digest),
        budget_rules_digest=str(bound.budget_rules_digest),
        refusals_engaged=engaged_count,
        refusals=records,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""

    records = evidence.refusals
    payload = _evidence_body(
        RunAuthorityVerdict(
            status=evidence.status,
            reason="authorised",
            epoch_digest=evidence.epoch_digest,
            cohort_digest=evidence.cohort_digest,
            manifest_digest=evidence.manifest_digest,
            exposure_contract_digest=evidence.exposure_contract_digest,
            budget_rules_digest=evidence.budget_rules_digest,
        ),
        records,
        evidence.refusals_engaged,
    )
    payload["evidence_digest"] = evidence.evidence_digest
    return canonical_json_bytes(payload)
