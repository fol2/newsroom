"""Increment 9Q-9 EFFECTIVE_MANIFEST_CURRENT qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Qualification proves bind plus drift rejection on the real epoch/controller
contracts, fail-closed. There is no parallel Effective Manifest mechanism.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.controller import (
    CONTROLLER_STAGES,
    STAGE_MANIFEST_DIMENSIONS,
    ControllerError,
    ControllerQualificationPlan,
)
from newsroom.increment9.epoch import (
    EFFECTIVE_MANIFEST_IDENTITY_KEYS,
    EffectiveManifest,
    EpochAuthorityError,
    EvaluationEpoch,
    ManifestCohort,
    RunAttempt,
    RunKind,
    ShadowRun,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "EFFECTIVE_MANIFEST_CURRENT"
INVENTORY_NAME = "inventory.json"
MANIFEST_ID = "effective-manifest-9q9-fixture"
OBSERVED_AT = "2026-08-18T12:00:00.000000Z"
IDENTITY_KEYS = tuple(sorted(EFFECTIVE_MANIFEST_IDENTITY_KEYS))

REFUSAL_CLASSES = (
    "DRIFT",
    "UNRESOLVED",
    "MALFORMED",
    "SUPERSEDED",
    "ANTI_NAMESAKE",
)
PROBE_COUNTS = {
    "DRIFT": 16,
    "UNRESOLVED": 1,
    "MALFORMED": 3,
    "SUPERSEDED": 1,
    "ANTI_NAMESAKE": 1,
}
PACKAGE_FIXTURES = (
    Path(__file__).parent / "fixtures" / "increment9q9_effective_manifest_current"
)
_MARKERS = {
    "DRIFT": b"drift",
    "UNRESOLVED": b"unresolved",
    "MALFORMED": b"malformed",
    "SUPERSEDED": b"superseded",
    "ANTI_NAMESAKE": b"anti_namesake",
}
_INVENTORY_FIELDS = frozenset(
    {"identity_digests", "identity_resolved", "manifest_id", "observed_at"}
)
_T6 = "2042-01-01T00:06:00.000000Z"
_DIGEST = "sha256:" + "0" * 64
_STACK: tuple[object, ...] | None = None

Probe = Callable[[str, Path], bool]


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


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
    manifest_digest: str
    drift_refusals: int
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
    evidence_digest: str


def _identity_digest(label: str, key: str) -> str:
    return "sha256:" + sha256(f"newsroom.increment9q9.{label}:{key}".encode()).hexdigest()


def fixture_identity_digests() -> dict[str, str]:
    """Sixteen synthetic, fixed sha256 identity digests for CI fixtures."""

    return {key: _identity_digest("identity", key) for key in IDENTITY_KEYS}


def fixture_inventory() -> dict[str, object]:
    """Authorised fixture identity inventory. No expiry field."""

    return {
        "identity_digests": fixture_identity_digests(),
        "identity_resolved": True,
        "manifest_id": MANIFEST_ID,
        "observed_at": OBSERVED_AT,
    }


def bind_inventory(raw: Mapping[str, object]) -> dict[str, object]:
    """Validate a fixture identity inventory, fail-closed."""

    if type(raw) is not dict or set(raw) != _INVENTORY_FIELDS:
        raise QualificationError("inventory is required")
    if raw.get("identity_resolved") is not True:
        raise QualificationError("inventory is required")
    identities = raw["identity_digests"]
    if type(identities) is not dict or set(identities) != set(IDENTITY_KEYS):
        raise QualificationError("inventory is required")
    bound: dict[str, str] = {}
    for key in IDENTITY_KEYS:
        try:
            bound[key] = validate_sha256_digest(
                identities[key], field=f"identity_digests.{key}"
            )
        except (CanonicalizationError, TypeError, ValueError) as exc:
            raise QualificationError("inventory is required") from exc
    manifest_id = raw["manifest_id"]
    observed_at = raw["observed_at"]
    if type(manifest_id) is not str or not manifest_id:
        raise QualificationError("inventory is required")
    if type(observed_at) is not str or not observed_at:
        raise QualificationError("inventory is required")
    return {
        "identity_digests": bound,
        "identity_resolved": True,
        "manifest_id": manifest_id,
        "observed_at": observed_at,
    }


def bind_manifest(
    inventory: Mapping[str, object],
    *,
    identity_digests: Mapping[str, str] | None = None,
    identity_resolved: bool = True,
    manifest_id: str | None = None,
) -> EffectiveManifest:
    """Bind one Effective Manifest from a fixture identity inventory."""

    bound = bind_inventory(inventory) if identity_digests is None else dict(inventory)
    identities = (
        dict(identity_digests)
        if identity_digests is not None
        else bound["identity_digests"]
    )
    return EffectiveManifest(
        manifest_id=manifest_id or str(bound["manifest_id"]),
        identity_digests=identities,
        observed_at=str(bound["observed_at"]),
        identity_resolved=identity_resolved,
    )


def refuse_namesake_satisfaction(gates: tuple[str, ...] | list[str]) -> None:
    """Refuse RUNTIME_GATES list membership as this First I/O Gate."""

    if GATE_ID in gates:
        raise QualificationError(
            "RUNTIME_GATES membership cannot satisfy this First I/O Gate"
        )
    raise QualificationError(
        "EFFECTIVE_MANIFEST_CURRENT is absent from RUNTIME_GATES"
    )


def _reject_forbidden(inventory: Path) -> None:
    lowered = str(inventory).lower()
    if "news_pool" in lowered:
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
    if type(raw) is not dict or not raw:
        raise QualificationError("inventory is required")
    return bind_inventory(raw)


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except (ControllerError, EpochAuthorityError, QualificationError):
        return True
    return False


def _epoch() -> EvaluationEpoch:
    return EvaluationEpoch(
        epoch_id="epoch-9q9-fixture",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        shadow_scope_digest="sha256:" + "1" * 64,
        source_portfolio_digest="sha256:" + "2" * 64,
        prospective_universe_digest="sha256:" + "3" * 64,
        slice_rules_digest="sha256:" + "4" * 64,
        thresholds_digest="sha256:" + "5" * 64,
        comparator_rules_digest="sha256:" + "6" * 64,
        reviewer_rules_digest="sha256:" + "7" * 64,
        budget_rules_digest="sha256:" + "8" * 64,
        rights_rules_digest="sha256:" + "9" * 64,
        opened_at="2042-01-01T00:00:00.000000Z",
        cutoff_at="2042-01-01T00:00:00.000000Z",
        closes_at="2042-01-29T00:00:00.000000Z",
    )


def _cohort(epoch: EvaluationEpoch, manifest: EffectiveManifest) -> ManifestCohort:
    return ManifestCohort(
        cohort_id="cohort-9q9-fixture",
        epoch_id=epoch.epoch_id,
        epoch_digest=epoch.canonical_digest,
        manifest_digest=manifest.canonical_digest,
        ordinal=1,
        previous_cohort_digest=None,
        exposure_contract_digest="sha256:" + "b" * 64,
        required_slices=("HONG_KONG", "UK"),
        opened_at="2042-01-01T00:01:00.000000Z",
        decision_bearing=manifest.decision_bearing,
    )


def _deployment_stack() -> tuple[object, ...]:
    """Reuse the proven 9A2/9B2 fixture constructors for controller bind."""

    global _STACK
    if _STACK is not None:
        return _STACK
    from newsroom.increment9.deployment import (
        INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
        INCREMENT9_SHADOW_SCHEMA_VERSION,
        ISOLATED_DIRECTORY_INVENTORY,
        ISOLATED_FILE_INVENTORY,
        PRODUCTION_MIGRATION_HISTORY_DIGEST,
        PRODUCTION_SCHEMA_FINGERPRINT,
        PRODUCTION_SCHEMA_VERSION,
        IsolatedDeploymentReceipt,
        qualify_deployment,
    )
    from newsroom.tests.test_increment9a2_shadow_deployment import (
        D,
        _bundle,
        _plan,
        _scope,
    )

    scope = _scope()
    deployment = _plan()
    readiness = qualify_deployment(
        deployment, _bundle(deployment), receipt_id="ready-9q9"
    )
    isolated = IsolatedDeploymentReceipt(
        receipt_id="isolated-9q9",
        deployment_plan_digest=deployment.canonical_digest,
        root_identity_digest=D("a"),
        directory_inventory=ISOLATED_DIRECTORY_INVENTORY,
        protected_file_digests={path: D("b") for path in ISOLATED_FILE_INVENTORY},
        epoch_schema_version=INCREMENT9_SHADOW_SCHEMA_VERSION,
        epoch_schema_fingerprint=INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
        epoch_backup_restore_digest=D("c"),
        production_snapshot_digest=deployment.production_snapshot_digest,
        production_snapshot_schema_version=PRODUCTION_SCHEMA_VERSION,
        production_snapshot_schema_fingerprint=PRODUCTION_SCHEMA_FINGERPRINT,
        production_snapshot_migration_history_digest=PRODUCTION_MIGRATION_HISTORY_DIGEST,
        production_snapshot_backup_restore_digest=D("d"),
        graphiti_workspace=deployment.graphiti_workspace,
        neo4j_database=deployment.neo4j_database,
        neo4j_namespace=deployment.neo4j_namespace,
        created_at="2042-01-01T00:02:30.000000Z",
    )
    epoch = replace(
        _epoch(),
        shadow_scope_digest=deployment.scope_digest,
        opened_at="2042-01-01T00:00:00.000000Z",
        cutoff_at="2042-01-01T00:00:00.000000Z",
    )
    _STACK = (scope, deployment, readiness, isolated, epoch)
    return _STACK


def _controller_kwargs(
    bound: EffectiveManifest,
    presented: EffectiveManifest | None = None,
) -> dict[str, object]:
    scope, deployment, readiness, isolated, epoch = _deployment_stack()
    presented = bound if presented is None else presented
    cohort = _cohort(epoch, bound)
    run = ShadowRun(
        run_id="run-9q9-replay",
        epoch_id=epoch.epoch_id,
        epoch_digest=epoch.canonical_digest,
        cohort_id=cohort.cohort_id,
        cohort_digest=cohort.canonical_digest,
        manifest_digest=bound.canonical_digest,
        production_snapshot_digest=deployment.production_snapshot_digest,
        production_nonmutation_before_digest="sha256:" + "e" * 64,
        run_kind=RunKind.REPLAY_QUALIFICATION,
        started_at=_T6,
        prospective=False,
    )
    attempt = RunAttempt(
        attempt_id="attempt-9q9-replay",
        run_id=run.run_id,
        run_digest=run.canonical_digest,
        ordinal=1,
        previous_attempt_digest=None,
        started_at=_T6,
        restart_reason=None,
    )
    return {
        "qualification_id": "controller-qualification-9q9",
        "scope": scope,
        "deployment_plan": deployment,
        "readiness_receipt": readiness,
        "isolated_deployment_receipt": isolated,
        "epoch": epoch,
        "effective_manifest": presented,
        "cohort": cohort,
        "run": run,
        "attempt": attempt,
        "stage_interface_digests": {
            stage: presented.identity_digests[STAGE_MANIFEST_DIMENSIONS[stage]]
            for stage in CONTROLLER_STAGES
        },
        "created_at": _T6,
        "expires_at": "2042-01-02T00:00:00.000000Z",
    }


def bind_controller(bound: EffectiveManifest) -> ControllerQualificationPlan:
    """Bind a decision-bearing cohort and replay Run to one Effective Manifest."""

    return ControllerQualificationPlan.build(**_controller_kwargs(bound))


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that an Effective Manifest refusal class engages on the real contracts.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")
    if _MARKERS[refusal_class] not in path.read_bytes():
        return False
    probes = {
        "DRIFT": _should_engage_drift,
        "UNRESOLVED": _should_engage_unresolved,
        "MALFORMED": _should_engage_malformed,
        "SUPERSEDED": _should_engage_superseded,
        "ANTI_NAMESAKE": _should_engage_anti_namesake,
    }
    return bool(probes[refusal_class]())


def _bound_manifest() -> EffectiveManifest:
    return bind_manifest(fixture_inventory())


def _should_engage_drift() -> bool:
    bound = _bound_manifest()
    kwargs = _controller_kwargs(bound)
    engaged = 0
    for key in IDENTITY_KEYS:
        drifted = dict(bound.identity_digests)
        drifted[key] = _identity_digest("drift", key)
        presented = EffectiveManifest(
            manifest_id="effective-manifest-9q9-drift",
            identity_digests=drifted,
            observed_at=bound.observed_at,
            identity_resolved=True,
        )
        if presented.canonical_digest == bound.canonical_digest:
            return False
        if _refused(
            lambda presented=presented: ControllerQualificationPlan.build(
                **{**kwargs, "effective_manifest": presented}
            )
        ):
            engaged += 1
    return engaged == 16


def _should_engage_unresolved() -> bool:
    bound = _bound_manifest()
    unresolved = EffectiveManifest(
        manifest_id=bound.manifest_id,
        identity_digests=dict(bound.identity_digests),
        observed_at=bound.observed_at,
        identity_resolved=False,
    )
    if unresolved.decision_bearing:
        return False
    return _refused(
        lambda: ControllerQualificationPlan.build(
            **_controller_kwargs(bound, unresolved)
        )
    )


def _should_engage_malformed() -> bool:
    identities = fixture_identity_digests()
    missing = dict(identities)
    del missing["candidate"]
    extra = dict(identities)
    extra["extra"] = _DIGEST
    malformed = dict(identities)
    malformed["candidate"] = "not-a-digest"
    return all(
        (
            _refused(lambda: bind_manifest(fixture_inventory(), identity_digests=missing)),
            _refused(lambda: bind_manifest(fixture_inventory(), identity_digests=extra)),
            _refused(
                lambda: bind_manifest(
                    fixture_inventory(), identity_digests=malformed
                )
            ),
        )
    )


def _should_engage_superseded() -> bool:
    bound = _bound_manifest()
    presented = EffectiveManifest(
        manifest_id="effective-manifest-9q9-superseded",
        identity_digests={
            key: _identity_digest("superseded", key) for key in IDENTITY_KEYS
        },
        observed_at=bound.observed_at,
        identity_resolved=True,
    )
    if presented.canonical_digest == bound.canonical_digest:
        return False
    return _refused(
        lambda: ControllerQualificationPlan.build(
            **_controller_kwargs(bound, presented)
        )
    )


def _should_engage_anti_namesake() -> bool:
    from scripts.increment9_shadow_campaign import RUNTIME_GATES

    namesake_closed = _refused(lambda: refuse_namesake_satisfaction(RUNTIME_GATES))
    listed = GATE_ID in RUNTIME_GATES
    authorised = not _refused(lambda: bind_controller(_bound_manifest()))
    return namesake_closed and listed and authorised


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


def _demonstrate(inventory: Mapping[str, object]) -> str:
    first = bind_manifest(inventory)
    second = bind_manifest(inventory)
    if first.canonical_digest != second.canonical_digest:
        raise QualificationError("inventory is required")
    if "expires_at" in first.primitive() or "expiry" in first.primitive():
        raise QualificationError("inventory is required")
    if first.schema_version != "newsroom.increment9.effective-manifest.v1":
        raise QualificationError("inventory is required")
    if not first.identity_resolved or not first.decision_bearing:
        raise QualificationError("inventory is required")
    plan = bind_controller(first)
    again = bind_controller(second)
    epoch = _deployment_stack()[4]
    if type(epoch) is not EvaluationEpoch:
        raise QualificationError("inventory is required")
    cohort = _cohort(epoch, first)
    if (
        plan.effective_manifest_digest != first.canonical_digest
        or again.effective_manifest_digest != first.canonical_digest
        or plan.canonical_digest != again.canonical_digest
        or cohort.manifest_digest != first.canonical_digest
        or not cohort.decision_bearing
    ):
        raise QualificationError("inventory is required")
    return first.canonical_digest


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    identity_inventory: Mapping[str, object] | None = None,
) -> QualificationEvidence:
    """Assess that Effective Manifest refusal classes engage deterministically.

    Fails closed if:
    - Inventory missing or inaccessible
    - Fixture identity inventory missing or invalid
    - Any refusal class surface missing or unexpected
    - Any digest changes without claimed engagement
    - Probe mutates any surface (fail-closed invariant)
    - Any refusal fails to engage
    """
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    if identity_inventory is None:
        bound = _load_inventory(inventory)
    else:
        bound = bind_inventory(identity_inventory)
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
    manifest_digest = _demonstrate(bound)
    payload = {
        "anti_namesake_refusals": PROBE_COUNTS["ANTI_NAMESAKE"],
        "deterministic_bind": True,
        "drift_refusals": PROBE_COUNTS["DRIFT"],
        "gate_id": GATE_ID,
        "malformed_refusals": PROBE_COUNTS["MALFORMED"],
        "manifest_digest": manifest_digest,
        "refusals": _refusal_payload(records),
        "refusals_engaged": engaged_count,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "superseded_refusals": PROBE_COUNTS["SUPERSEDED"],
        "unresolved_refusals": PROBE_COUNTS["UNRESOLVED"],
    }
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        manifest_digest=manifest_digest,
        drift_refusals=PROBE_COUNTS["DRIFT"],
        refusals_engaged=engaged_count,
        refusals=records,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""
    payload = {
        "anti_namesake_refusals": PROBE_COUNTS["ANTI_NAMESAKE"],
        "deterministic_bind": True,
        "drift_refusals": evidence.drift_refusals,
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "malformed_refusals": PROBE_COUNTS["MALFORMED"],
        "manifest_digest": evidence.manifest_digest,
        "refusals": _refusal_payload(evidence.refusals),
        "refusals_engaged": evidence.refusals_engaged,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
        "superseded_refusals": PROBE_COUNTS["SUPERSEDED"],
        "unresolved_refusals": PROBE_COUNTS["UNRESOLVED"],
    }
    return canonical_json_bytes(payload)
